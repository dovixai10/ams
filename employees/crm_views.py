"""CRM - Leads. Office-admin-side (gated on 'crm.manage', the same way as
every other module - see permissions.FEATURE_PERMISSIONS). Platform admin
has no CRM screens of its own; its only lever is whether a plan includes
'crm.manage' at all.

Three ways a Lead gets created here:
  - Manual: crm_lead_create, from the "Add Lead" card.
  - CSV: crm_lead_import, a bulk upload.
  - Website: crm_public_lead_page, a public (no-login) per-office page at
    /l/<slug>/, submitted by whoever fills the form.
A fourth source, WhatsApp, is created by the periodic Celery poll in
integrations/crm_whatsapp.py, not by any view here - crm_settings just lets
the office admin point that poll at their WhatsApp marketing service.
"""
import csv
import io
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from web_project import TemplateLayout
from web_project.template_helpers.theme import TemplateHelper

from .models import CrmWebsiteLeadPage, CrmWhatsAppLeadSource, Employee, Lead
from .permissions import feature_required, get_request_branch, get_request_office, tenant_queryset

crm_required = user_passes_test(feature_required('crm.manage'))

PIPELINE_STAGES = [
    Lead.Status.NEW,
    Lead.Status.CONTACTED,
    Lead.Status.INTERESTED,
    Lead.Status.PROPOSAL_SENT,
    Lead.Status.FOLLOW_UP,
    Lead.Status.CONVERTED,
]

SOURCE_COLORS = {
    Lead.Source.WEBSITE: '#03C3EC',
    Lead.Source.WHATSAPP: '#71DD37',
    Lead.Source.CSV: '#696CFF',
    Lead.Source.MANUAL: '#8592A3',
}


# ---------------------------------------------------------------------------
# Shared filtering
# ---------------------------------------------------------------------------

def _filtered_leads(request):
    """The office/branch-scoped, GET-param-filtered Lead queryset - shared by
    the list page and the CSV export so "Download Filtered Leads" always
    matches what's on screen."""
    qs = tenant_queryset(request, Lead.objects.select_related('assigned_to', 'branch'))

    q = request.GET.get('q', '').strip()
    if q:
        from django.db.models import Q
        qs = qs.filter(
            Q(name__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q) | Q(company__icontains=q)
        )

    source = request.GET.get('source', '').strip()
    if source in Lead.Source.values:
        qs = qs.filter(source=source)

    status = request.GET.get('status', '').strip()
    if status in Lead.Status.values:
        qs = qs.filter(status=status)

    assignee = request.GET.get('assignee', '').strip()
    if assignee == 'unassigned':
        qs = qs.filter(assigned_to__isnull=True)
    elif assignee.isdigit():
        qs = qs.filter(assigned_to_id=int(assignee))

    date_from = request.GET.get('date_from', '').strip()
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    date_to = request.GET.get('date_to', '').strip()
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    return qs


def _activity_style(description):
    """Small heuristic to pick an icon/color for an activity line, since we
    don't store a separate category per row - just enough to match the
    Recent Activities card's colored icons."""
    text = description.lower()
    if 'whatsapp' in text:
        return 'bx bxl-whatsapp', '#71DD37'
    if 'imported' in text or 'csv' in text:
        return 'bx bx-upload', '#696CFF'
    if 'assigned' in text or 'reassigned' in text:
        return 'bx bx-user-check', '#FFAB00'
    if 'status' in text:
        return 'bx bx-refresh', '#03C3EC'
    if 'website' in text or 'form' in text:
        return 'bx bx-globe', '#03C3EC'
    return 'bx bx-info-circle', '#8592A3'


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------

@login_required
@crm_required
def crm_leads(request):
    office = get_request_office(request)
    all_leads = tenant_queryset(request, Lead.objects.all())
    filtered = _filtered_leads(request).order_by('-created_at')

    total_count = all_leads.count()

    def _kpi(qs):
        now = timezone.now()
        this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_end = this_month_start - timezone.timedelta(seconds=1)
        last_month_start = last_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        this_month = qs.filter(created_at__gte=this_month_start).count()
        last_month = qs.filter(created_at__gte=last_month_start, created_at__lte=last_month_end).count()
        if last_month:
            change = round((this_month - last_month) / last_month * 100)
        else:
            change = 100 if this_month else 0
        return {'count': qs.count(), 'change': change}

    kpis = {
        'total': _kpi(all_leads),
        'whatsapp': _kpi(all_leads.filter(source=Lead.Source.WHATSAPP)),
        'website': _kpi(all_leads.filter(source=Lead.Source.WEBSITE)),
        'csv': _kpi(all_leads.filter(source=Lead.Source.CSV)),
        'converted': _kpi(all_leads.filter(status=Lead.Status.CONVERTED)),
    }

    pipeline = []
    for status in PIPELINE_STAGES:
        count = all_leads.filter(status=status).count()
        pipeline.append({
            'key': status.value,
            'label': status.label,
            'count': count,
            'pct': round(count / total_count * 100) if total_count else 0,
        })

    donut = []
    for source in Lead.Source:
        count = all_leads.filter(source=source).count()
        if count:
            donut.append({
                'label': source.label,
                'count': count,
                'pct': round(count / total_count * 100) if total_count else 0,
                'color': SOURCE_COLORS[source],
            })

    employees = tenant_queryset(request, Employee.objects.filter(user__is_active=True)).order_by('full_name')

    per_page = request.GET.get('per_page', '10')
    per_page = int(per_page) if per_page.isdigit() and int(per_page) in (10, 25, 50, 100) else 10

    from django.core.paginator import Paginator
    paginator = Paginator(filtered, per_page)
    page_number = request.GET.get('page', '1')
    page_obj = paginator.get_page(page_number)
    page_range = list(paginator.get_elided_page_range(page_obj.number, on_each_side=2, on_ends=1))

    from .models import LeadActivity
    recent_activities = [
        {'activity': a, 'icon': _activity_style(a.description)[0], 'color': _activity_style(a.description)[1]}
        for a in tenant_queryset(request, LeadActivity.objects.select_related('lead')).order_by('-created_at')[:6]
    ]

    website_page = CrmWebsiteLeadPage.objects.filter(office=office).first() if office else None
    whatsapp_source = CrmWhatsAppLeadSource.objects.filter(office=office).first() if office else None

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'kpis': kpis,
        'pipeline': pipeline,
        'donut': donut,
        'total_count': total_count,
        'leads': page_obj,
        'page_obj': page_obj,
        'page_range': page_range,
        'per_page': per_page,
        'employees': employees,
        'recent_activities': recent_activities,
        'statuses': Lead.Status.choices,
        'sources': Lead.Source.choices,
        'website_page': website_page,
        'whatsapp_source': whatsapp_source,
        'filters': {
            'q': request.GET.get('q', ''),
            'source': request.GET.get('source', ''),
            'status': request.GET.get('status', ''),
            'assignee': request.GET.get('assignee', ''),
            'date_from': request.GET.get('date_from', ''),
            'date_to': request.GET.get('date_to', ''),
        },
    })
    return render(request, 'employees/crm/leads.html', context)


# ---------------------------------------------------------------------------
# Lead mutations (plain POST + redirect + Django messages, like the rest
# of this app's admin CRUD pages)
# ---------------------------------------------------------------------------

def _redirect_to_list(request):
    from django.urls import reverse
    url = reverse('employees:crm_leads')
    qs = request.POST.get('next_qs', '')
    return redirect(f'{url}?{qs}' if qs else url)


@login_required
@crm_required
def crm_lead_create(request):
    if request.method != 'POST':
        return redirect('employees:crm_leads')

    office = get_request_office(request)
    branch = get_request_branch(request)
    name = request.POST.get('name', '').strip()
    phone = request.POST.get('phone', '').strip()
    if not name or not phone:
        messages.error(request, 'Name and phone number are required.')
        return _redirect_to_list(request)

    lead = Lead.objects.create(
        office=office,
        branch=branch,
        name=name,
        phone=phone,
        email=request.POST.get('email', '').strip(),
        source=Lead.Source.MANUAL,
        assigned_to_id=request.POST.get('assigned_to') or None,
        created_by=request.user,
    )
    lead.log_activity('Lead created manually', user=request.user)
    messages.success(request, f'Lead "{lead.name}" added.')
    return _redirect_to_list(request)


@login_required
@crm_required
def crm_lead_update(request, pk):
    if request.method != 'POST':
        return redirect('employees:crm_leads')

    lead = get_object_or_404(tenant_queryset(request, Lead.objects.all()), pk=pk)
    changes = []

    for field in ('name', 'phone', 'email', 'company', 'message'):
        if field in request.POST:
            new_value = request.POST.get(field, '').strip()
            if new_value != getattr(lead, field):
                setattr(lead, field, new_value)
                changes.append(field)

    if 'status' in request.POST:
        new_status = request.POST.get('status')
        if new_status in Lead.Status.values and new_status != lead.status:
            lead.status = new_status
            changes.append('status')
            lead.log_activity(f'Status changed to {Lead.Status(new_status).label}', user=request.user)

    if 'assigned_to' in request.POST:
        new_assignee = request.POST.get('assigned_to') or None
        new_assignee_id = int(new_assignee) if new_assignee else None
        if new_assignee_id != lead.assigned_to_id:
            lead.assigned_to_id = new_assignee_id
            changes.append('assigned_to')
            if new_assignee_id:
                employee = Employee.objects.filter(pk=new_assignee_id).first()
                lead.log_activity(f'Assigned to {employee.full_name if employee else "an employee"}', user=request.user)
            else:
                lead.log_activity('Unassigned', user=request.user)

    if changes:
        lead.save()
        messages.success(request, f'Lead "{lead.name or lead.phone}" updated.')
    return _redirect_to_list(request)


@login_required
@crm_required
def crm_lead_delete(request, pk):
    if request.method != 'POST':
        return redirect('employees:crm_leads')
    lead = get_object_or_404(tenant_queryset(request, Lead.objects.all()), pk=pk)
    name = lead.name or lead.phone
    lead.delete()
    messages.success(request, f'Lead "{name}" deleted.')
    return _redirect_to_list(request)


@login_required
@crm_required
def crm_lead_bulk_delete(request):
    if request.method != 'POST':
        return redirect('employees:crm_leads')
    ids = [int(i) for i in request.POST.get('ids', '').split(',') if i.isdigit()]
    qs = tenant_queryset(request, Lead.objects.filter(pk__in=ids))
    count = qs.count()
    qs.delete()
    if count:
        messages.success(request, f'Deleted {count} lead(s).')
    else:
        messages.error(request, 'No leads were selected.')
    return _redirect_to_list(request)


# ---------------------------------------------------------------------------
# CSV import / export
# ---------------------------------------------------------------------------

REQUIRED_CSV_COLUMNS = {'name', 'phone'}
ALL_CSV_COLUMNS = ['name', 'phone', 'email', 'company', 'message']


@login_required
@crm_required
def crm_lead_import_sample(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="crm_leads_sample.csv"'
    writer = csv.writer(response)
    writer.writerow(ALL_CSV_COLUMNS)
    writer.writerow(['Rahul Sharma', '+919876543210', 'rahul@example.com', 'Sharma Enterprises', 'Interested in the Growth plan'])
    return response


@login_required
@crm_required
def crm_lead_import(request):
    """AJAX file upload - returns a JSON summary so the page can show
    imported/skipped/failed counts without a full reload."""
    if request.method != 'POST' or 'file' not in request.FILES:
        return JsonResponse({'success': False, 'error': 'No file uploaded.'}, status=400)

    upload = request.FILES['file']
    if not upload.name.lower().endswith('.csv'):
        return JsonResponse({'success': False, 'error': 'Please upload a .csv file.'}, status=400)
    if upload.size > 5 * 1024 * 1024:
        return JsonResponse({'success': False, 'error': 'File is too large (max 5 MB).'}, status=400)

    office = get_request_office(request)
    branch = get_request_branch(request)

    try:
        decoded = upload.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        return JsonResponse({'success': False, 'error': 'Could not read the file - please save it as UTF-8 CSV.'}, status=400)

    reader = csv.DictReader(io.StringIO(decoded))
    headers = {(h or '').strip().lower() for h in (reader.fieldnames or [])}
    missing = REQUIRED_CSV_COLUMNS - headers
    if missing:
        return JsonResponse({
            'success': False,
            'error': f"Missing required column(s): {', '.join(sorted(missing))}. Expected columns: {', '.join(ALL_CSV_COLUMNS)}.",
        }, status=400)

    imported, skipped, failed = 0, 0, 0
    errors = []
    existing_phones = set(
        tenant_queryset(request, Lead.objects.all()).values_list('phone', flat=True)
    )

    for row_num, row in enumerate(reader, start=2):
        row = {(k or '').strip().lower(): (v or '').strip() for k, v in row.items()}
        name = row.get('name', '')
        phone = row.get('phone', '')
        if not name or not phone:
            failed += 1
            errors.append(f'Row {row_num}: name and phone are required.')
            continue
        if phone in existing_phones:
            skipped += 1
            continue

        lead = Lead.objects.create(
            office=office,
            branch=branch,
            name=name,
            phone=phone,
            email=row.get('email', ''),
            company=row.get('company', ''),
            message=row.get('message', ''),
            source=Lead.Source.CSV,
            created_by=request.user,
        )
        lead.log_activity('Imported from CSV', user=request.user)
        existing_phones.add(phone)
        imported += 1

    return JsonResponse({
        'success': True,
        'imported': imported,
        'skipped': skipped,
        'failed': failed,
        'errors': errors[:20],
    })


@login_required
@crm_required
def crm_lead_export(request):
    scope = request.GET.get('scope', 'filtered')
    if scope == 'selected':
        ids = [int(i) for i in request.GET.get('ids', '').split(',') if i.isdigit()]
        qs = tenant_queryset(request, Lead.objects.filter(pk__in=ids))
    elif scope == 'all':
        qs = tenant_queryset(request, Lead.objects.all())
    else:
        qs = _filtered_leads(request)

    response = HttpResponse(content_type='text/csv')
    stamp = timezone.now().strftime('%Y%m%d_%H%M')
    response['Content-Disposition'] = f'attachment; filename="crm_leads_{stamp}.csv"'
    writer = csv.writer(response)
    writer.writerow(['Name', 'Phone', 'Email', 'Company', 'Source', 'Status', 'Assigned To', 'Message', 'Created At'])
    for lead in qs.select_related('assigned_to').order_by('-created_at'):
        writer.writerow([
            lead.name, lead.phone, lead.email, lead.company,
            lead.get_source_display(), lead.get_status_display(),
            lead.assigned_to.full_name if lead.assigned_to else '',
            lead.message, lead.created_at.strftime('%Y-%m-%d %H:%M'),
        ])
    return response


# ---------------------------------------------------------------------------
# Settings: website lead page + WhatsApp lead source
# ---------------------------------------------------------------------------

@login_required
@crm_required
def crm_settings(request):
    office = get_request_office(request)
    if office is None:
        messages.error(request, 'Pick an office first.')
        return redirect('employees:crm_leads')

    website_page, _ = CrmWebsiteLeadPage.objects.get_or_create(office=office)
    whatsapp_source = CrmWhatsAppLeadSource.objects.filter(office=office).first()

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'toggle_website_page':
            website_page.is_active = not website_page.is_active
            website_page.save(update_fields=['is_active'])
            messages.success(request, f"Website lead page is now {'active' if website_page.is_active else 'inactive'}.")

        elif action == 'save_whatsapp_source':
            url = request.POST.get('source_url', '').strip()
            token = request.POST.get('access_token', '').strip()
            reengage_raw = request.POST.get('reengage_after_days', '').strip()
            if not url:
                messages.error(request, 'Please enter the WhatsApp source URL.')
            elif reengage_raw and not reengage_raw.isdigit():
                messages.error(request, 'Re-engage after (days) must be a whole number.')
            else:
                whatsapp_source = whatsapp_source or CrmWhatsAppLeadSource(office=office, created_by=request.user)
                whatsapp_source.source_url = url
                whatsapp_source.reengage_after_days = int(reengage_raw) if reengage_raw else None
                if token:
                    whatsapp_source.set_access_token(token)
                whatsapp_source.is_active = True
                whatsapp_source.save()
                messages.success(request, 'WhatsApp lead source saved.')

        elif action == 'disable_whatsapp_source' and whatsapp_source:
            whatsapp_source.is_active = False
            whatsapp_source.save(update_fields=['is_active'])
            messages.success(request, 'WhatsApp lead source disabled.')

        elif action == 'test_whatsapp_source' and whatsapp_source:
            from .integrations.crm_whatsapp import poll_source
            created = poll_source(whatsapp_source)
            whatsapp_source.refresh_from_db()
            if whatsapp_source.last_poll_ok:
                messages.success(request, f'Connected successfully. {created} new lead(s) imported.')
            else:
                messages.error(request, f'Could not reach the source: {whatsapp_source.last_poll_error}')

        return redirect('employees:crm_settings')

    website_url = request.build_absolute_uri(f'/l/{website_page.slug}/')

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'website_page': website_page,
        'website_url': website_url,
        'whatsapp_source': whatsapp_source,
    })
    return render(request, 'employees/crm/settings.html', context)


# ---------------------------------------------------------------------------
# Public sample website lead-capture page - no login required
# ---------------------------------------------------------------------------

def crm_public_lead_page(request, slug):
    page = get_object_or_404(CrmWebsiteLeadPage.objects.select_related('office'), slug=slug, is_active=True)
    office = page.office
    submitted = False

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        phone = request.POST.get('phone', '').strip()
        email = request.POST.get('email', '').strip()
        message = request.POST.get('message', '').strip()

        if name and phone:
            lead = Lead.objects.create(
                office=office,
                name=name,
                phone=phone,
                email=email,
                message=message,
                source=Lead.Source.WEBSITE,
            )
            lead.log_activity('Submitted the website contact form')
            submitted = True
        else:
            messages.error(request, 'Please enter your name and phone number.')

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_blank.html', context),
        'hide_mobile_nav': True,
        'show_mobile_nav': False,
        'office': office,
        'submitted': submitted,
    })
    return render(request, 'employees/crm/public_lead_page.html', context)
