"""Recruitment - office-admin-side. 'recruitment.manage' holders get full
access (dashboard, jobs, pipeline, every application, settings). Plain
'recruitment.recruiter' holders get My Candidates (their own assigned
applications) PLUS the detail page for any application they're personally
assigned to (so they can update status/schedule interviews/add notes on
their own candidates) - but not reassigning recruiters or deleting, which
stay manager-only. Mirrors crm_views.py's structure and conventions
throughout - same tenant_queryset scoping, same CSV import/export shape,
same action= POST-dispatch style for a detail page with several small edits.
"""
import csv
import io
import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from web_project import TemplateLayout
from web_project.template_helpers.theme import TemplateHelper

from .forms import JobForm
from .models import (
    Employee, Job, JobApplication, JobApplicationActivity, JobApplicationRecruiter,
    RecruitmentCareersPage,
)
from .notification_utils import create_notification
from .permissions import (
    employees_holding_permission, feature_required, get_request_branch, get_request_office,
    has_permission, tenant_queryset,
)

recruitment_required = user_passes_test(feature_required('recruitment.manage'))
recruitment_recruiter_or_manage_required = user_passes_test(
    lambda u: has_permission(u, 'recruitment.manage') or has_permission(u, 'recruitment.recruiter')
)

PIPELINE_STAGES = [
    JobApplication.Status.APPLIED,
    JobApplication.Status.SCREENING,
    JobApplication.Status.SHORTLISTED,
    JobApplication.Status.INTERVIEW,
    JobApplication.Status.TECHNICAL,
    JobApplication.Status.OFFER,
    JobApplication.Status.HIRED,
]

INTERVIEW_SCHEDULED_MARKER = 'Interview scheduled'

REQUIRED_CSV_COLUMNS = {'full_name', 'email', 'phone'}
ALL_CSV_COLUMNS = ['full_name', 'email', 'phone', 'current_location', 'current_company', 'current_ctc', 'expected_ctc', 'job_title', 'message']


def _recruiter_queryset(request):
    """Employees assignable as a recruiter - holds recruitment.manage OR
    recruitment.recruiter, tenant-scoped."""
    manage_ids = employees_holding_permission(request, 'recruitment.manage').values_list('pk', flat=True)
    recruiter_ids = employees_holding_permission(request, 'recruitment.recruiter').values_list('pk', flat=True)
    return Employee.objects.filter(pk__in=set(manage_ids) | set(recruiter_ids)).select_related('user').order_by('full_name', 'email')


def _safe_decimal(raw):
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@login_required
@recruitment_required
def recruitment_dashboard(request):
    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_month_end = month_start - timedelta(seconds=1)
    prev_month_start = prev_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    jobs = tenant_queryset(request, Job.objects.all())
    applications = tenant_queryset(request, JobApplication.objects.all())
    activities = tenant_queryset(request, JobApplicationActivity.objects.all())

    def pct_change(this_count, last_count):
        if last_count == 0:
            return None
        return round((this_count - last_count) / last_count * 100, 1)

    open_jobs = jobs.filter(status=Job.Status.OPEN).count()
    open_jobs_this_month = jobs.filter(status=Job.Status.OPEN, created_at__gte=month_start).count()
    open_jobs_last_month = jobs.filter(status=Job.Status.OPEN, created_at__gte=prev_month_start, created_at__lte=prev_month_end).count()

    total_apps_this_month = applications.filter(created_at__gte=month_start).count()
    total_apps_last_month = applications.filter(created_at__gte=prev_month_start, created_at__lte=prev_month_end).count()

    shortlisted_count = applications.filter(status=JobApplication.Status.SHORTLISTED).count()
    shortlisted_this_month = activities.filter(new_status=JobApplication.Status.SHORTLISTED, created_at__gte=month_start).count()
    shortlisted_last_month = activities.filter(new_status=JobApplication.Status.SHORTLISTED, created_at__gte=prev_month_start, created_at__lte=prev_month_end).count()

    interviews_upcoming = applications.filter(interview_scheduled_at__gte=now).count()
    interview_logs = activities.filter(description__startswith=INTERVIEW_SCHEDULED_MARKER)
    interviews_this_month = interview_logs.filter(created_at__gte=month_start).count()
    interviews_last_month = interview_logs.filter(created_at__gte=prev_month_start, created_at__lte=prev_month_end).count()

    pipeline_counts = {row['status']: row['count'] for row in applications.values('status').annotate(count=Count('id'))}
    pipeline_data = [{'label': JobApplication.Status(s).label, 'count': pipeline_counts.get(s, 0)} for s in PIPELINE_STAGES]

    source_counts = {row['source']: row['count'] for row in applications.values('source').annotate(count=Count('id'))}
    others = source_counts.get(JobApplication.Source.MANUAL, 0) + source_counts.get(JobApplication.Source.CSV, 0)
    source_data = [
        {'label': 'Website', 'count': source_counts.get(JobApplication.Source.WEBSITE, 0)},
        {'label': 'LinkedIn', 'count': source_counts.get(JobApplication.Source.LINKEDIN, 0)},
        {'label': 'Referral', 'count': source_counts.get(JobApplication.Source.REFERRAL, 0)},
        {'label': 'WhatsApp', 'count': source_counts.get(JobApplication.Source.WHATSAPP, 0)},
        {'label': 'Job Board', 'count': source_counts.get(JobApplication.Source.JOB_BOARD, 0)},
        {'label': 'Others', 'count': others},
    ]

    recent_applications = applications.select_related('job').order_by('-created_at')[:10]

    top_jobs_qs = list(jobs.annotate(applicant_count=Count('applications')).order_by('-applicant_count')[:5])
    max_applicants = max((j.applicant_count for j in top_jobs_qs), default=0)
    top_jobs = [{'job': j, 'pct': (j.applicant_count / max_applicants * 100) if max_applicants else 0} for j in top_jobs_qs]

    upcoming_interviews = applications.filter(interview_scheduled_at__gte=now).select_related('job').order_by('interview_scheduled_at')[:5]
    recent_activities = activities.select_related('application').order_by('-created_at')[:10]

    office = get_request_office(request)
    careers_url = ''
    if office:
        careers_page, _ = RecruitmentCareersPage.objects.get_or_create(office=office)
        careers_url = request.build_absolute_uri(f'/careers/{careers_page.slug}/')

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'open_jobs': open_jobs,
        'open_jobs_trend': pct_change(open_jobs_this_month, open_jobs_last_month),
        'total_applications': applications.count(),
        'total_applications_trend': pct_change(total_apps_this_month, total_apps_last_month),
        'shortlisted_count': shortlisted_count,
        'shortlisted_trend': pct_change(shortlisted_this_month, shortlisted_last_month),
        'interviews_upcoming': interviews_upcoming,
        'interviews_trend': pct_change(interviews_this_month, interviews_last_month),
        'pipeline_data': pipeline_data,
        'source_data': source_data,
        'recent_applications': recent_applications,
        'top_jobs': top_jobs,
        'upcoming_interviews': upcoming_interviews,
        'recent_activities': recent_activities,
        'careers_url': careers_url,
    })
    return render(request, 'employees/recruitment/dashboard.html', context)


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

@login_required
@recruitment_required
def recruitment_job_list(request):
    jobs = tenant_queryset(request, Job.objects.select_related('department', 'designation', 'branch'))

    status = request.GET.get('status', '').strip()
    if status in Job.Status.values:
        jobs = jobs.filter(status=status)

    jobs = jobs.annotate(applicant_count=Count('applications')).order_by('-created_at')

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'jobs': jobs,
        'status_choices': Job.Status.choices,
        'status_filter': status,
    })
    return render(request, 'employees/recruitment/job_list.html', context)


@login_required
@recruitment_required
def recruitment_job_create(request):
    if request.method == 'POST':
        form = JobForm(request.POST, request=request, created_by=request.user)
        if form.is_valid():
            job = form.save()
            messages.success(request, f'Job "{job.title}" created.')
            return redirect('employees:recruitment_job_list')
        messages.error(request, 'Please correct the errors below.')
    else:
        form = JobForm(request=request)

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'form': form,
        'title': 'Create Job',
    })
    return render(request, 'employees/recruitment/job_form.html', context)


@login_required
@recruitment_required
def recruitment_job_update(request, pk):
    job = get_object_or_404(tenant_queryset(request, Job.objects.all()), pk=pk)
    if request.method == 'POST':
        form = JobForm(request.POST, instance=job, request=request)
        if form.is_valid():
            form.save()
            messages.success(request, f'Job "{job.title}" updated.')
            return redirect('employees:recruitment_job_list')
        messages.error(request, 'Please correct the errors below.')
    else:
        form = JobForm(instance=job, request=request)

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'form': form,
        'title': f'Edit "{job.title}"',
        'job': job,
    })
    return render(request, 'employees/recruitment/job_form.html', context)


@login_required
@recruitment_required
@require_http_methods(['POST'])
def recruitment_job_delete(request, pk):
    job = get_object_or_404(tenant_queryset(request, Job.objects.all()), pk=pk)
    title = job.title
    job.delete()  # JobApplication.job is SET_NULL - existing applications just become "manual entry", not deleted
    messages.success(request, f'Job "{title}" deleted. Any applications it had are kept, just unlinked from it.')
    return redirect('employees:recruitment_job_list')


@login_required
@recruitment_required
def recruitment_job_detail(request, pk):
    job = get_object_or_404(
        tenant_queryset(request, Job.objects.select_related('department', 'designation', 'employment_type', 'branch')), pk=pk,
    )
    applications = job.applications.all().order_by('-created_at')

    status = request.GET.get('status', '').strip()
    if status in JobApplication.Status.values:
        applications = applications.filter(status=status)
    source = request.GET.get('source', '').strip()
    if source in JobApplication.Source.values:
        applications = applications.filter(source=source)

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'job': job,
        'applications': applications,
        'status_choices': JobApplication.Status.choices,
        'source_choices': JobApplication.Source.choices,
        'status_filter': status,
        'source_filter': source,
    })
    return render(request, 'employees/recruitment/job_detail.html', context)


# ---------------------------------------------------------------------------
# Pipeline board
# ---------------------------------------------------------------------------

@login_required
@recruitment_required
def recruitment_pipeline(request):
    applications = tenant_queryset(request, JobApplication.objects.select_related('job')).exclude(
        status=JobApplication.Status.REJECTED,
    )

    job_id = request.GET.get('job', '').strip()
    if job_id.isdigit():
        applications = applications.filter(job_id=int(job_id))

    columns = []
    for stage in PIPELINE_STAGES:
        columns.append({
            'key': stage,
            'label': JobApplication.Status(stage).label,
            'applications': [a for a in applications if a.status == stage],
        })

    jobs = tenant_queryset(request, Job.objects.all()).order_by('title')

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'columns': columns,
        'jobs': jobs,
        'job_filter': job_id,
        'status_choices': JobApplication.Status.choices,
    })
    return render(request, 'employees/recruitment/pipeline_board.html', context)


@login_required
@recruitment_required
@require_http_methods(['POST'])
def recruitment_pipeline_move(request, pk):
    application = get_object_or_404(tenant_queryset(request, JobApplication.objects.all()), pk=pk)

    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        payload = request.POST

    new_status = payload.get('status')
    if new_status not in JobApplication.Status.values:
        return JsonResponse({'success': False, 'error': 'Invalid status.'}, status=400)

    if new_status != application.status:
        application.status = new_status
        application.save(update_fields=['status', 'updated_at'])
        application.log_activity(
            f'Status changed to {JobApplication.Status(new_status).label}', user=request.user, new_status=new_status,
        )

    return JsonResponse({'success': True, 'status': application.status})


# ---------------------------------------------------------------------------
# Application detail
# ---------------------------------------------------------------------------

@login_required
@recruitment_recruiter_or_manage_required
def recruitment_application_detail(request, pk):
    application = get_object_or_404(
        tenant_queryset(request, JobApplication.objects.select_related('job', 'department', 'designation', 'employment_type')),
        pk=pk,
    )

    is_manager = has_permission(request.user, 'recruitment.manage')
    employee = getattr(request.user, 'employee_profile', None)
    is_assigned = employee is not None and application.assigned_recruiters.filter(pk=employee.pk).exists()
    if not (is_manager or is_assigned):
        raise PermissionDenied("You're not assigned to this application.")

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'assign_recruiters' and not is_manager:
            raise PermissionDenied('Only recruitment managers can reassign recruiters.')

        if action == 'update_status':
            new_status = request.POST.get('status')
            if new_status in JobApplication.Status.values and new_status != application.status:
                application.status = new_status
                application.save(update_fields=['status', 'updated_at'])
                application.log_activity(
                    f'Status changed to {JobApplication.Status(new_status).label}', user=request.user, new_status=new_status,
                )
                messages.success(request, 'Status updated.')

        elif action == 'assign_recruiters':
            allowed_ids = set(_recruiter_queryset(request).values_list('pk', flat=True))
            submitted_ids = {int(i) for i in request.POST.getlist('recruiters') if i.isdigit()}
            new_ids = submitted_ids & allowed_ids

            existing_ids = set(application.recruiter_assignments.values_list('recruiter_id', flat=True))
            to_add = new_ids - existing_ids
            to_remove = existing_ids - new_ids

            if to_remove:
                application.recruiter_assignments.filter(recruiter_id__in=to_remove).delete()
            for recruiter_id in to_add:
                JobApplicationRecruiter.objects.create(application=application, recruiter_id=recruiter_id, assigned_by=request.user)

            if to_add or to_remove:
                added_names = list(Employee.objects.filter(pk__in=to_add).values_list('full_name', flat=True))
                application.log_activity(
                    f'Recruiters updated ({", ".join(added_names) or "removed"})' if added_names else 'Recruiter unassigned',
                    user=request.user,
                )
                for recruiter in Employee.objects.filter(pk__in=to_add):
                    create_notification(
                        employee=recruiter, notification_type='recruiter_assigned',
                        title='Assigned as Recruiter',
                        message=f'You were assigned to {application.full_name}\'s application' + (f' for {application.job.title}' if application.job else '') + '.',
                        action_url=f'/recruitment/applications/{application.pk}/',
                    )
                messages.success(request, 'Recruiters updated.')

        elif action == 'schedule_interview':
            scheduled_at = request.POST.get('interview_scheduled_at', '').strip()
            mode = request.POST.get('interview_mode', '').strip()
            title = request.POST.get('interview_title', '').strip()
            if scheduled_at:
                from django.utils.dateparse import parse_datetime
                parsed = parse_datetime(scheduled_at)
                if parsed:
                    if timezone.is_naive(parsed):
                        parsed = timezone.make_aware(parsed)
                    application.interview_scheduled_at = parsed
                    application.interview_mode = mode if mode in JobApplication.InterviewMode.values else ''
                    application.interview_title = title
                    application.save(update_fields=['interview_scheduled_at', 'interview_mode', 'interview_title', 'updated_at'])

                    interviewer_ids = {int(i) for i in request.POST.getlist('interviewers') if i.isdigit()}
                    interviewers = tenant_queryset(request, Employee.objects.filter(pk__in=interviewer_ids))
                    application.interviewers.set(interviewers)

                    names = ', '.join(interviewers.values_list('full_name', flat=True)) or 'none assigned'
                    label = f'{title} - ' if title else ''
                    application.log_activity(
                        f'{INTERVIEW_SCHEDULED_MARKER}: {label}{parsed.strftime("%d %b %Y, %I:%M %p")} - Interviewer(s): {names}',
                        user=request.user,
                    )
                    notify_employees = set(application.assigned_recruiters.all()) | set(interviewers)
                    for employee in notify_employees:
                        create_notification(
                            employee=employee, notification_type='interview_scheduled',
                            title='Interview Scheduled',
                            message=f'{label}interview scheduled for {application.full_name} on {parsed.strftime("%d %b %Y, %I:%M %p")}.',
                            action_url=f'/recruitment/applications/{application.pk}/',
                        )
                    messages.success(request, 'Interview scheduled.')
                else:
                    messages.error(request, 'Please provide a valid date/time.')

        elif action == 'add_note':
            note = request.POST.get('note', '').strip()
            if note:
                application.log_activity(note, user=request.user)
                messages.success(request, 'Note added.')

        return redirect('employees:recruitment_application_detail', pk=application.pk)

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'application': application,
        'status_choices': JobApplication.Status.choices,
        'interview_mode_choices': JobApplication.InterviewMode.choices,
        'activities': application.activities.select_related('created_by').order_by('-created_at'),
        'assigned_recruiter_ids': set(application.assigned_recruiters.values_list('pk', flat=True)),
        'recruiter_options': _recruiter_queryset(request),
        'assigned_interviewer_ids': set(application.interviewers.values_list('pk', flat=True)),
        'interviewer_options': tenant_queryset(request, Employee.objects.select_related('user')).order_by('full_name', 'email'),
        'is_manager': is_manager,
    })
    return render(request, 'employees/recruitment/application_detail.html', context)


@login_required
@recruitment_required
@require_http_methods(['POST'])
def recruitment_application_delete(request, pk):
    application = get_object_or_404(tenant_queryset(request, JobApplication.objects.all()), pk=pk)
    name = application.full_name
    application.delete()
    messages.success(request, f'Application from "{name}" deleted.')
    return redirect('employees:recruitment_job_list')


# ---------------------------------------------------------------------------
# My Candidates (recruiter-or-manage)
# ---------------------------------------------------------------------------

@login_required
@recruitment_recruiter_or_manage_required
def recruitment_my_candidates(request):
    employee = getattr(request.user, 'employee_profile', None)
    applications = (
        tenant_queryset(request, JobApplication.objects.select_related('job')).filter(assigned_recruiters=employee)
        if employee else JobApplication.objects.none()
    )

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'applications': applications.order_by('-created_at'),
        'has_employee_profile': employee is not None,
    })
    return render(request, 'employees/recruitment/my_candidates.html', context)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@login_required
@recruitment_required
def recruitment_settings(request):
    office = get_request_office(request)
    if office is None:
        messages.error(request, 'Pick an office first.')
        return redirect('employees:recruitment_dashboard')

    page, _ = RecruitmentCareersPage.objects.get_or_create(office=office)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'toggle_page':
            page.is_active = not page.is_active
            page.save(update_fields=['is_active'])
            messages.success(request, f"Careers page is now {'active' if page.is_active else 'inactive'}.")
        elif action == 'update_intro':
            page.intro_text = request.POST.get('intro_text', '').strip()
            page.save(update_fields=['intro_text'])
            messages.success(request, 'Intro text updated.')
        elif action == 'regenerate_slug':
            page.slug = ''
            page.save()
            messages.success(request, 'Careers page link regenerated. The old link stops working immediately.')
        return redirect('employees:recruitment_settings')

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'page': page,
        'careers_url': request.build_absolute_uri(f'/careers/{page.slug}/'),
    })
    return render(request, 'employees/recruitment/settings.html', context)


# ---------------------------------------------------------------------------
# CSV export / import
# ---------------------------------------------------------------------------

@login_required
@recruitment_required
def recruitment_application_export(request):
    scope = request.GET.get('scope', 'all')
    if scope == 'selected':
        ids = [int(i) for i in request.GET.get('ids', '').split(',') if i.isdigit()]
        qs = tenant_queryset(request, JobApplication.objects.filter(pk__in=ids))
    else:
        qs = tenant_queryset(request, JobApplication.objects.all())

    response = HttpResponse(content_type='text/csv')
    stamp = timezone.now().strftime('%Y%m%d_%H%M')
    response['Content-Disposition'] = f'attachment; filename="job_applications_{stamp}.csv"'
    writer = csv.writer(response)
    writer.writerow([
        'Full Name', 'Phone', 'Email', 'Current Location', 'Current Company', 'Current CTC', 'Expected CTC',
        'Department', 'Designation', 'Employment Type', 'Job Title', 'Source', 'Status', 'Assigned Recruiters',
        'Message', 'Applied At',
    ])
    for app in qs.select_related('job', 'department', 'designation', 'employment_type').prefetch_related('assigned_recruiters').order_by('-created_at'):
        writer.writerow([
            app.full_name, app.phone, app.email, app.current_location, app.current_company,
            app.current_ctc or '', app.expected_ctc or '',
            app.department.name if app.department else '', app.designation.name if app.designation else '',
            app.employment_type.name if app.employment_type else '',
            app.job.title if app.job else '', app.get_source_display(), app.get_status_display(),
            ', '.join(r.full_name for r in app.assigned_recruiters.all()),
            app.message, app.created_at.strftime('%Y-%m-%d %H:%M'),
        ])
    return response


@login_required
@recruitment_required
def recruitment_application_import_sample(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="job_applications_sample.csv"'
    writer = csv.writer(response)
    writer.writerow(ALL_CSV_COLUMNS)
    writer.writerow(['Rahul Sharma', 'rahul@example.com', '+919876543210', 'Jaipur', 'Acme Pvt Ltd', '600000', '800000', 'Backend Developer', 'Referred by a current employee'])
    return response


@login_required
@recruitment_required
def recruitment_application_import(request):
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

    jobs_by_title = {j.title.strip().lower(): j for j in tenant_queryset(request, Job.objects.all())}
    existing_emails = set(tenant_queryset(request, JobApplication.objects.all()).values_list('email', flat=True))

    imported, skipped, failed = 0, 0, 0
    errors = []

    for row_num, row in enumerate(reader, start=2):
        row = {(k or '').strip().lower(): (v or '').strip() for k, v in row.items()}
        full_name = row.get('full_name', '')
        email = row.get('email', '')
        phone = row.get('phone', '')
        if not (full_name and email and phone):
            failed += 1
            errors.append(f'Row {row_num}: full_name, email and phone are required.')
            continue
        if email in existing_emails:
            skipped += 1
            continue

        job = jobs_by_title.get(row.get('job_title', '').strip().lower())

        application = JobApplication.objects.create(
            job=job, office=office, branch=branch,
            full_name=full_name, email=email, phone=phone,
            current_location=row.get('current_location', ''), current_company=row.get('current_company', ''),
            current_ctc=_safe_decimal(row.get('current_ctc')), expected_ctc=_safe_decimal(row.get('expected_ctc')),
            department=job.department if job else None, designation=job.designation if job else None,
            employment_type=job.employment_type if job else None,
            message=row.get('message', ''), source=JobApplication.Source.CSV, created_by=request.user,
        )
        application.log_activity('Imported from CSV', user=request.user)
        existing_emails.add(email)
        imported += 1

    return JsonResponse({'success': True, 'imported': imported, 'skipped': skipped, 'failed': failed, 'errors': errors[:20]})
