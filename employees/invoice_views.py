"""Invoicing: Clients, GST invoices and per-office invoice settings.
Office-admin-side, gated on 'invoices.manage' (same mechanism as every other
module - see permissions.FEATURE_PERMISSIONS). All tax/total math lives in
invoicing_calculations.py and is never duplicated here - this module parses
input, calls that, and persists the result."""
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import ProtectedError, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from web_project import TemplateLayout
from web_project.template_helpers.theme import TemplateHelper

from .invoicing_calculations import amount_in_words, calculate_invoice_totals
from .models import Client, Employee, Invoice, InvoiceLineItem, InvoiceSettings, Project, fiscal_year_for
from .permissions import feature_required, get_request_branch, get_request_office, tenant_queryset

invoices_required = user_passes_test(feature_required('invoices.manage'))


def _financial_year_label(d: date) -> str:
    fy = fiscal_year_for(d)
    return f"{fy % 100:02d}-{(fy + 1) % 100:02d}"


def _client_json(client):
    return {
        'id': client.pk, 'name': client.name, 'contact_person': client.contact_person,
        'email': client.email, 'phone': client.phone, 'billing_address': client.billing_address,
        'state': client.state, 'pincode': client.pincode, 'gstin': client.gstin,
    }


def _company_header(office, branch):
    """The invoice header's company details: Office carries the brand
    identity (name/logo/website/GSTIN) and Branch carries the more granular
    location fields (address/city/state/pincode/phone/email) - a branch's
    own value wins when set, falling back to Office's where Branch has
    nothing (e.g. Office.contact_number)."""
    address_parts = []
    if branch and branch.address:
        address_parts.append(branch.address)
    elif office.address:
        address_parts.append(office.address)
    city_state_pin = ', '.join(p for p in [
        branch.city if branch else '', branch.state if branch else '', branch.pincode if branch else '',
    ] if p)
    if city_state_pin:
        address_parts.append(city_state_pin)

    return {
        'name': office.name,
        'logo_url': office.logo.url if office.logo else '',
        'address_lines': address_parts,
        'phone': (branch.contact_number if branch else '') or office.contact_number,
        'email': branch.email if branch else '',
        'website': office.website,
        'gstin': office.gst_number,
    }


# ---------------------------------------------------------------------------
# Invoice list
# ---------------------------------------------------------------------------

@login_required
@invoices_required
def invoice_list(request):
    qs = tenant_queryset(request, Invoice.objects.select_related('client', 'branch')).order_by('-created_at')

    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(invoice_number__icontains=q) | Q(client__name__icontains=q))

    status = request.GET.get('status', '').strip()
    if status in Invoice.Status.values:
        qs = qs.filter(status=status)

    client_id = request.GET.get('client', '').strip()
    if client_id.isdigit():
        qs = qs.filter(client_id=int(client_id))

    from django.core.paginator import Paginator
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page', '1'))

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'invoices': page_obj,
        'page_obj': page_obj,
        'clients': tenant_queryset(request, Client.objects.filter(is_active=True)).order_by('name'),
        'statuses': Invoice.Status.choices,
        'filters': {'q': q, 'status': status, 'client': client_id},
    })
    return render(request, 'employees/invoices/list.html', context)


# ---------------------------------------------------------------------------
# Create / edit (draft only) an invoice
# ---------------------------------------------------------------------------

@login_required
@invoices_required
def invoice_create(request, pk=None):
    office = get_request_office(request)
    branch = get_request_branch(request)

    invoice = None
    if pk is not None:
        invoice = get_object_or_404(tenant_queryset(request, Invoice.objects.all()), pk=pk)
        if not invoice.is_draft:
            messages.error(request, 'Only draft invoices can be edited. Generated invoices are locked.')
            return redirect('employees:invoice_list')

    if request.method == 'POST':
        action = request.POST.get('action', 'save_draft')
        client = get_object_or_404(tenant_queryset(request, Client.objects.all()), pk=request.POST.get('client'))
        project_id = request.POST.get('project') or None
        project = None
        if project_id:
            project = get_object_or_404(tenant_queryset(request, Project.objects.all()), pk=project_id)

        try:
            invoice_date = datetime.strptime(request.POST.get('invoice_date', ''), '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, 'Please provide a valid invoice date.')
            return redirect(request.path)
        due_date_raw = request.POST.get('due_date', '').strip()
        due_date = None
        if due_date_raw:
            try:
                due_date = datetime.strptime(due_date_raw, '%Y-%m-%d').date()
            except ValueError:
                pass

        invoice_type = request.POST.get('invoice_type', Invoice.InvoiceType.TAX_INVOICE)
        place_of_supply_state = request.POST.get('place_of_supply_state', '').strip()

        try:
            items = json.loads(request.POST.get('items_json', '[]'))
        except (json.JSONDecodeError, TypeError):
            items = []
        if not items:
            messages.error(request, 'Add at least one line item.')
            return redirect(request.path)

        try:
            calc = calculate_invoice_totals(
                seller_state=branch.state if branch else '', place_of_supply_state=place_of_supply_state,
                invoice_type=invoice_type, line_items=items,
            )
        except (ValueError, KeyError, InvalidOperation) as exc:
            messages.error(request, f'Could not calculate totals: {exc}')
            return redirect(request.path)

        if invoice is None:
            invoice = Invoice(office=office, branch=branch, created_by=request.user)

        invoice.client = client
        invoice.project = project
        invoice.invoice_type = invoice_type
        invoice.custom_type_label = request.POST.get('custom_type_label', '').strip() if invoice_type == Invoice.InvoiceType.CUSTOM else ''
        invoice.invoice_date = invoice_date
        invoice.due_date = due_date
        invoice.place_of_supply_state = place_of_supply_state
        invoice.sales_person_id = request.POST.get('sales_person') or None
        invoice.notes = request.POST.get('notes', '').strip()
        invoice.terms_and_conditions = request.POST.get('terms_and_conditions', '').strip()

        payment_status = request.POST.get('payment_status', Invoice.PaymentStatus.PENDING)
        invoice.payment_status = payment_status
        invoice.payment_terms = (
            '' if payment_status == Invoice.PaymentStatus.PAID
            else request.POST.get('payment_terms', Invoice.PaymentTerms.DUE_ON_RECEIPT)
        )
        if payment_status == Invoice.PaymentStatus.PAID:
            invoice.payment_method = request.POST.get('payment_method', '').strip()
            invoice.transaction_id = request.POST.get('transaction_id', '').strip()
        else:
            invoice.payment_method = ''
            invoice.transaction_id = ''
        invoice.subtotal = calc['subtotal']
        invoice.discount_total = calc['discount_total']
        invoice.taxable_amount = calc['taxable_amount']
        invoice.cgst_total = calc['cgst_total']
        invoice.sgst_total = calc['sgst_total']
        invoice.igst_total = calc['igst_total']
        invoice.grand_total = calc['grand_total']
        invoice.amount_in_words = amount_in_words(calc['grand_total'])
        invoice.save()

        invoice.items.all().delete()
        InvoiceLineItem.objects.bulk_create([
            InvoiceLineItem(
                invoice=invoice, description=line.get('description', ''),
                description_note=line.get('description_note', ''), sac_code=line.get('sac_code', ''),
                quantity=line['quantity'], unit=line.get('unit', 'Nos'),
                rate=line['rate'], discount_type=line.get('discount_type', 'fixed'),
                discount_value=line.get('discount_value', 0), tax_rate=line.get('tax_rate', 0),
                line_taxable=line['taxable'], line_tax=line['tax'], line_total=line['total'],
                display_order=idx,
            )
            for idx, line in enumerate(calc['lines'])
        ])

        if action == 'generate':
            with transaction.atomic():
                settings_row, _ = InvoiceSettings.objects.select_for_update().get_or_create(office=office)
                fy_label = _financial_year_label(invoice.invoice_date)
                invoice.invoice_number = settings_row.allocate_number(fy_label)
                invoice.status = Invoice.Status.GENERATED
                invoice.save(update_fields=['invoice_number', 'status', 'updated_at'])
            pdf_buffer = _build_invoice_pdf(invoice)
            invoice.pdf_file.save(f'invoice_{invoice.pk}.pdf', ContentFile(pdf_buffer.getvalue()), save=True)
            messages.success(request, f'Invoice {invoice.invoice_number} generated.')
            return redirect('employees:invoice_list')

        messages.success(request, 'Draft saved.')
        return redirect('employees:invoice_list')

    clients = tenant_queryset(request, Client.objects.filter(is_active=True)).order_by('name')
    projects = tenant_queryset(request, Project.objects.all()).order_by('name')
    employees = tenant_queryset(request, Employee.objects.filter(user__is_active=True)).order_by('full_name')
    settings_row = InvoiceSettings.objects.filter(office=office).first()

    existing_items = []
    if invoice is not None:
        existing_items = [
            {
                'description': i.description, 'description_note': i.description_note, 'sac_code': i.sac_code,
                'quantity': str(i.quantity), 'unit': i.unit, 'rate': str(i.rate),
                'discount_type': i.discount_type, 'discount_value': str(i.discount_value),
                'tax_rate': str(i.tax_rate),
            }
            for i in invoice.items.all()
        ]

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'invoice': invoice,
        'clients_data': [_client_json(c) for c in clients],
        'projects_data': [{'id': p.pk, 'name': p.name, 'client_id': p.client_id} for p in projects],
        'clients': clients,
        'projects': projects,
        'employees': employees,
        'invoice_types': Invoice.InvoiceType.choices,
        'payment_terms_choices': Invoice.PaymentTerms.choices,
        'payment_status_choices': Invoice.PaymentStatus.choices,
        'payment_method_choices': Invoice.PaymentMethod.choices,
        'existing_items_data': existing_items,
        'default_terms': settings_row.default_terms_and_conditions if settings_row else '',
        'default_payment_terms': settings_row.default_payment_terms if settings_row else Invoice.PaymentTerms.DUE_ON_RECEIPT,
        'office': office,
        'branch': branch,
        'settings_row': settings_row,
        'company': _company_header(office, branch),
        'today': timezone.now().date().isoformat(),
    })
    return render(request, 'employees/invoices/create.html', context)


@login_required
@invoices_required
def invoice_delete(request, pk):
    if request.method != 'POST':
        return redirect('employees:invoice_list')
    invoice = get_object_or_404(tenant_queryset(request, Invoice.objects.all()), pk=pk)
    if not invoice.is_draft:
        messages.error(request, 'Only draft invoices can be deleted. Cancel a generated invoice instead.')
    else:
        invoice.delete()
        messages.success(request, 'Draft deleted.')
    return redirect('employees:invoice_list')


@login_required
@invoices_required
def invoice_cancel(request, pk):
    if request.method != 'POST':
        return redirect('employees:invoice_list')
    invoice = get_object_or_404(tenant_queryset(request, Invoice.objects.all()), pk=pk)
    if invoice.status != Invoice.Status.GENERATED:
        messages.error(request, 'Only a generated invoice can be cancelled.')
    else:
        invoice.status = Invoice.Status.CANCELLED
        invoice.save(update_fields=['status', 'updated_at'])
        messages.success(request, f'Invoice {invoice.invoice_number} cancelled.')
    return redirect('employees:invoice_list')


@login_required
@invoices_required
def invoice_download_pdf(request, pk):
    invoice = get_object_or_404(tenant_queryset(request, Invoice.objects.all()), pk=pk)
    if not invoice.pdf_file:
        raise Http404('This invoice has no PDF yet.')
    return FileResponse(invoice.pdf_file.open('rb'), as_attachment=True, filename=f'{invoice.invoice_number or invoice.pk}.pdf')


@login_required
@invoices_required
def invoice_preview_pdf(request, pk):
    """Same PDF as the download, but served inline so a browser tab renders
    it directly instead of forcing a download - used by the 'Preview' action
    on the invoice list."""
    invoice = get_object_or_404(tenant_queryset(request, Invoice.objects.all()), pk=pk)
    if not invoice.pdf_file:
        raise Http404('This invoice has no PDF yet.')
    return FileResponse(invoice.pdf_file.open('rb'), as_attachment=False, filename=f'{invoice.invoice_number or invoice.pk}.pdf')


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

@login_required
@invoices_required
def clients_view(request):
    office = get_request_office(request)
    branch = get_request_branch(request)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'Client name is required.')
            return redirect('employees:invoice_clients')
        Client.objects.create(
            office=office, branch=branch, name=name,
            contact_person=request.POST.get('contact_person', '').strip(),
            email=request.POST.get('email', '').strip(),
            phone=request.POST.get('phone', '').strip(),
            billing_address=request.POST.get('billing_address', '').strip(),
            state=request.POST.get('state', '').strip(),
            pincode=request.POST.get('pincode', '').strip(),
            gstin=request.POST.get('gstin', '').strip(),
            created_by=request.user,
        )
        messages.success(request, f'Client "{name}" added.')
        return redirect('employees:invoice_clients')

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'clients': tenant_queryset(request, Client.objects.all()).order_by('name'),
    })
    return render(request, 'employees/invoices/clients.html', context)


@login_required
@invoices_required
def client_update(request, pk):
    if request.method != 'POST':
        return redirect('employees:invoice_clients')
    client = get_object_or_404(tenant_queryset(request, Client.objects.all()), pk=pk)
    for field in ('name', 'contact_person', 'email', 'phone', 'billing_address', 'state', 'pincode', 'gstin'):
        setattr(client, field, request.POST.get(field, '').strip())
    client.save()
    messages.success(request, f'Client "{client.name}" updated.')
    return redirect('employees:invoice_clients')


@login_required
@invoices_required
def client_toggle(request, pk):
    if request.method != 'POST':
        return redirect('employees:invoice_clients')
    client = get_object_or_404(tenant_queryset(request, Client.objects.all()), pk=pk)
    client.is_active = not client.is_active
    client.save(update_fields=['is_active', 'updated_at'])
    return redirect('employees:invoice_clients')


@login_required
@invoices_required
def client_delete(request, pk):
    if request.method != 'POST':
        return redirect('employees:invoice_clients')
    client = get_object_or_404(tenant_queryset(request, Client.objects.all()), pk=pk)
    name = client.name
    try:
        client.delete()
        messages.success(request, f'Client "{name}" deleted.')
    except ProtectedError:
        client.is_active = False
        client.save(update_fields=['is_active', 'updated_at'])
        messages.info(request, f'"{name}" has invoices on file, so it was deactivated instead of deleted.')
    return redirect('employees:invoice_clients')


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@login_required
@invoices_required
def invoice_settings(request):
    office = get_request_office(request)
    if office is None:
        messages.error(request, 'Pick an office first.')
        return redirect('employees:invoice_list')

    settings_row, _ = InvoiceSettings.objects.get_or_create(office=office)

    if request.method == 'POST':
        settings_row.number_prefix = request.POST.get('number_prefix', 'INV').strip() or 'INV'
        settings_row.default_payment_terms = request.POST.get('default_payment_terms', Invoice.PaymentTerms.DUE_ON_RECEIPT)
        settings_row.default_terms_and_conditions = request.POST.get('default_terms_and_conditions', '').strip()
        settings_row.bank_name = request.POST.get('bank_name', '').strip()
        settings_row.bank_account_name = request.POST.get('bank_account_name', '').strip()
        settings_row.bank_account_number = request.POST.get('bank_account_number', '').strip()
        settings_row.ifsc_code = request.POST.get('ifsc_code', '').strip()
        settings_row.bank_branch_name = request.POST.get('bank_branch_name', '').strip()
        settings_row.upi_vpa = request.POST.get('upi_vpa', '').strip()
        settings_row.signatory_name = request.POST.get('signatory_name', '').strip()
        settings_row.signatory_designation = request.POST.get('signatory_designation', '').strip()
        if request.FILES.get('signature_image'):
            settings_row.signature_image = request.FILES['signature_image']
        settings_row.save()
        messages.success(request, 'Invoice settings saved.')
        return redirect('employees:invoice_settings')

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'settings': settings_row,
        'payment_terms_choices': Invoice.PaymentTerms.choices,
    })
    return render(request, 'employees/invoices/settings.html', context)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def _build_invoice_pdf(invoice):
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage

    office = invoice.office
    branch = invoice.branch
    client = invoice.client
    settings_row = InvoiceSettings.objects.filter(office=office).first()
    company = _company_header(office, branch)

    PRIMARY = colors.HexColor('#696CFF')
    INK = colors.HexColor('#2B2C40')
    MUTED = colors.HexColor('#8592A3')
    LIGHT_PURPLE = colors.HexColor('#F0F0FF')
    BORDER = colors.HexColor('#E5E7EF')

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=16 * mm, bottomMargin=16 * mm, leftMargin=16 * mm, rightMargin=16 * mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('InvTitle', parent=styles['Heading1'], fontSize=18, textColor=INK, spaceAfter=0)
    label_style = ParagraphStyle('InvLabel', parent=styles['Normal'], fontSize=8, textColor=MUTED, leading=11)
    normal_style = ParagraphStyle('InvNormal', parent=styles['Normal'], fontSize=9, textColor=INK, leading=13)
    bold_style = ParagraphStyle('InvBold', parent=normal_style, fontName='Helvetica-Bold')
    section_style = ParagraphStyle('InvSection', parent=styles['Heading3'], fontSize=10, textColor=PRIMARY, spaceBefore=0, spaceAfter=3)
    right_label_style = ParagraphStyle('InvRightLabel', parent=label_style, alignment=TA_RIGHT)
    right_bold_style = ParagraphStyle('InvRightBold', parent=bold_style, alignment=TA_RIGHT)
    company_name_style = ParagraphStyle('InvCompanyName', parent=bold_style, fontSize=11, alignment=TA_RIGHT)

    content_width = A4[0] - 32 * mm
    elements = []

    # ---- Header: logo | company details ----
    # reportlab's Image flowable is lazy - it doesn't actually decode the
    # file until doc.build() runs, well outside any try/except wrapped
    # around its construction. Validate with PIL ourselves, upfront, so a
    # corrupted/unreadable logo falls back to text instead of 500ing the
    # whole invoice.
    logo_cell = Paragraph(company['name'], title_style)
    if company['logo_url']:
        try:
            from PIL import Image as PILImage
            with PILImage.open(office.logo.path) as probe:
                probe.verify()
            logo_cell = RLImage(office.logo.path, width=32 * mm, height=16 * mm, kind='proportional')
        except Exception:
            pass

    company_lines = [Paragraph(company['name'], company_name_style)]
    for line in company['address_lines']:
        company_lines.append(Paragraph(line, right_label_style))
    if company['gstin']:
        company_lines.append(Paragraph(f"GSTIN: {company['gstin']}", right_label_style))
    contact_bits = [b for b in [company['phone'], company['email'], company['website']] if b]
    if contact_bits:
        company_lines.append(Paragraph(' &nbsp;|&nbsp; '.join(contact_bits), right_label_style))

    header_table = Table([[logo_cell, company_lines]], colWidths=[content_width * 0.4, content_width * 0.6])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('LINEBELOW', (0, 0), (-1, -1), 1.2, PRIMARY), ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 5 * mm))

    # ---- Title + invoice number box ----
    type_labels = {
        'tax_invoice': 'TAX INVOICE', 'bill_of_supply': 'BILL OF SUPPLY', 'non_gst': 'INVOICE',
        'custom': (invoice.custom_type_label or 'INVOICE').upper(),
    }
    number_box = Table(
        [
            [Paragraph('Invoice No:', right_label_style), Paragraph(invoice.invoice_number or 'DRAFT', right_bold_style)],
            [Paragraph(f"Date: {invoice.invoice_date.strftime('%d %b %Y')}", right_label_style), ''],
        ],
        colWidths=[22 * mm, 30 * mm],
    )
    number_box.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.6, BORDER), ('SPAN', (0, 1), (1, 1)),
        ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    title_row = Table(
        [[Paragraph(type_labels.get(invoice.invoice_type, 'INVOICE'), title_style), number_box]],
        colWidths=[content_width * 0.6, content_width * 0.4],
    )
    title_row.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('ALIGN', (1, 0), (1, 0), 'RIGHT')]))
    elements.append(title_row)
    elements.append(Spacer(1, 5 * mm))

    # ---- Bill To (lavender) | Metadata grid ----
    bill_to_cell = [Paragraph('BILL TO', ParagraphStyle('BillToLabel', parent=section_style, fontSize=8))]
    bill_to_cell.append(Paragraph(client.name, bold_style))
    if client.contact_person:
        bill_to_cell.append(Paragraph(client.contact_person, normal_style))
    if client.billing_address:
        bill_to_cell.append(Paragraph(client.billing_address, normal_style))
    if client.state or client.pincode:
        bill_to_cell.append(Paragraph(f"{client.state} {client.pincode}".strip(), normal_style))
    if client.gstin:
        bill_to_cell.append(Paragraph(f"GSTIN: {client.gstin}", label_style))
    if client.phone:
        bill_to_cell.append(Paragraph(client.phone, label_style))
    if client.email:
        bill_to_cell.append(Paragraph(client.email, label_style))

    meta_pairs = [
        ('Project', invoice.project.name if invoice.project else ''),
        ('Invoice Date', invoice.invoice_date.strftime('%d %b %Y')),
        ('Due Date', invoice.due_date.strftime('%d %b %Y') if invoice.due_date else ''),
        ('Payment Terms', invoice.get_payment_terms_display()),
        ('Place of Supply', invoice.place_of_supply_state or ''),
        ('Sales Person', invoice.sales_person.full_name if invoice.sales_person else ''),
    ]
    meta_pairs = [(key, value) for key, value in meta_pairs if value]  # omit fields the admin left blank
    meta_rows = []
    for i in range(0, len(meta_pairs), 2):
        row = []
        for key, value in meta_pairs[i:i + 2]:
            row.append(Paragraph(f"<font color='#8592A3' size=7>{key.upper()}</font><br/><b>{value}</b>", normal_style))
        if len(row) == 1:
            row.append('')  # Table requires a rectangular grid
        meta_rows.append(row)
    meta_table = Table(meta_rows, colWidths=[(content_width * 0.55) / 2] * 2)
    meta_table.setStyle(TableStyle([
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 0), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))

    info_grid = Table([[bill_to_cell, meta_table]], colWidths=[content_width * 0.45, content_width * 0.55])
    info_grid.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), LIGHT_PURPLE), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (0, 0), 8), ('BOTTOMPADDING', (0, 0), (0, 0), 8),
        ('LEFTPADDING', (0, 0), (0, 0), 8), ('RIGHTPADDING', (0, 0), (0, 0), 8),
        ('LEFTPADDING', (1, 0), (1, 0), 10), ('TOPPADDING', (1, 0), (1, 0), 0),
    ]))
    elements.append(info_grid)
    elements.append(Spacer(1, 5 * mm))

    item_rows = [['#', 'Description', 'SAC', 'Qty', 'Rate', 'Disc.', 'Tax', 'Amount (Rs.)']]
    for idx, item in enumerate(invoice.items.all(), start=1):
        desc = item.description
        if item.description_note:
            desc += f"\n{item.description_note}"
        item_rows.append([
            str(idx), desc, item.sac_code, f"{item.quantity:g}", f"{item.rate:,.2f}",
            f"{item.discount_value:g}{'%' if item.discount_type == 'percentage' else ''}",
            f"{item.tax_rate:g}%", f"{item.line_total:,.2f}",
        ])
    items_table = Table(item_rows, colWidths=[8 * mm, 58 * mm, 18 * mm, 12 * mm, 22 * mm, 16 * mm, 14 * mm, 24 * mm])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#696CFF')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (3, 0), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#e5e7eb')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 4 * mm))

    distinct_rates = {item.tax_rate for item in invoice.items.all()}
    half_rate_label = f" ({next(iter(distinct_rates)) / 2:g}%)" if len(distinct_rates) == 1 else ''

    totals_rows = [
        ['Subtotal', f"Rs. {invoice.subtotal:,.2f}"],
        ['Discount', f"Rs. {invoice.discount_total:,.2f}"],
        ['Taxable Amount', f"Rs. {invoice.taxable_amount:,.2f}"],
    ]
    if invoice.cgst_total:
        totals_rows.append([f'CGST{half_rate_label}', f"Rs. {invoice.cgst_total:,.2f}"])
        totals_rows.append([f'SGST{half_rate_label}', f"Rs. {invoice.sgst_total:,.2f}"])
    if invoice.igst_total:
        totals_rows.append(['IGST', f"Rs. {invoice.igst_total:,.2f}"])
    # Match the live preview's layout exactly: totals occupy the right 60%
    # of the content width, left 40% empty - previously these used leftover
    # hardcoded mm widths (112+80=192mm) that didn't fit content_width
    # (~178mm on A4), overflowing past the right margin.
    totals_col_width = (content_width * 0.6) / 2
    totals_table = Table(totals_rows, colWidths=[totals_col_width, totals_col_width])
    totals_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9), ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    wrapper = Table([[None, totals_table]], colWidths=[content_width * 0.4, content_width * 0.6])
    wrapper.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    elements.append(wrapper)
    elements.append(Spacer(1, 2 * mm))

    grand_table = Table([['Total Amount', f"Rs. {invoice.grand_total:,.2f}"]], colWidths=[content_width * 0.4, content_width * 0.6])
    grand_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#696CFF')), ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'), ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(grand_table)
    elements.append(Spacer(1, 4 * mm))

    elements.append(Paragraph('Amount in Words', section_style))
    elements.append(Paragraph(invoice.amount_in_words, normal_style))
    elements.append(Spacer(1, 5 * mm))

    # ---- Payment Received (paid) | Bank Details + Payment Methods (pending) ----
    if invoice.payment_status == Invoice.PaymentStatus.PAID:
        paid_cell = [Paragraph('Payment Received', ParagraphStyle('PaidHead', parent=section_style, textColor=colors.HexColor('#3f9a1c')))]
        paid_cell.append(Paragraph(
            f"<font color='#8592A3'>Payment Method</font>: {invoice.get_payment_method_display() if invoice.payment_method else '-'}",
            normal_style,
        ))
        if invoice.transaction_id:
            paid_cell.append(Paragraph(f"<font color='#8592A3'>Transaction ID</font>: {invoice.transaction_id}", normal_style))
        paid_table = Table([[paid_cell]], colWidths=[content_width])
        paid_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#E8F8EE')),
            ('BOX', (0, 0), (-1, -1), 0.6, colors.HexColor('#71DD37')),
            ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 10), ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ]))
        elements.append(paid_table)
        elements.append(Spacer(1, 5 * mm))
    elif (settings_row and settings_row.bank_name) or (settings_row and settings_row.upi_vpa):
        bank_cell = [Paragraph('Bank Details', section_style)]
        if settings_row.bank_name:
            for label, value in [
                ('Bank Name', settings_row.bank_name), ('Account Name', settings_row.bank_account_name),
                ('Account No.', settings_row.bank_account_number), ('IFSC Code', settings_row.ifsc_code),
                ('Branch', settings_row.bank_branch_name),
            ]:
                if value:
                    bank_cell.append(Paragraph(f"<font color='#8592A3'>{label}</font>: {value}", label_style))
        else:
            bank_cell.append(Paragraph('No bank details configured.', label_style))

        payment_cell = [Paragraph('Payment Methods', section_style)]
        method_names = []
        if settings_row.bank_name:
            method_names.append('Bank Transfer')
        if settings_row.upi_vpa:
            method_names.extend(['UPI', 'GPay', 'PhonePe', 'Paytm'])
        if method_names:
            chip_table = Table(
                [[Paragraph(name, ParagraphStyle('Chip', parent=label_style, alignment=TA_CENTER, textColor=INK)) for name in method_names]],
                colWidths=[16 * mm] * len(method_names),
            )
            chip_table.setStyle(TableStyle([
                ('BOX', (0, 0), (-1, -1), 0.6, BORDER), ('INNERGRID', (0, 0), (-1, -1), 0.6, BORDER),
                ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            payment_cell.append(chip_table)
        if settings_row.upi_vpa:
            try:
                import qrcode
                upi_link = f"upi://pay?pa={settings_row.upi_vpa}&pn={office.name}&am={invoice.grand_total}&cu=INR"
                qr_img = qrcode.make(upi_link)
                qr_buffer = BytesIO()
                qr_img.save(qr_buffer, format='PNG')
                qr_buffer.seek(0)
                payment_cell.append(Spacer(1, 3 * mm))
                payment_cell.append(Paragraph('Scan to pay (UPI)', label_style))
                payment_cell.append(RLImage(qr_buffer, width=22 * mm, height=22 * mm))
            except Exception:
                pass

        bank_payment_row = Table([[bank_cell, payment_cell]], colWidths=[content_width * 0.5, content_width * 0.5])
        bank_payment_row.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (1, 0), (1, 0), 0), ('LEFTPADDING', (1, 0), (1, 0), 6),
        ]))
        elements.append(bank_payment_row)
        elements.append(Spacer(1, 5 * mm))

    # ---- Terms & Conditions | Signature ----
    terms_cell = [Paragraph('Terms &amp; Conditions', section_style)]
    term_lines = [t.strip() for t in invoice.terms_and_conditions.splitlines() if t.strip()]
    if term_lines:
        import re
        for idx, line in enumerate(term_lines, start=1):
            clean = re.sub(r'^\d+[.)]\s*', '', line)
            terms_cell.append(Paragraph(f"{idx}. {clean}", label_style))
    else:
        terms_cell.append(Paragraph('No terms added.', label_style))

    sign_cell = []
    if settings_row and settings_row.signature_image:
        try:
            from PIL import Image as PILImage
            with PILImage.open(settings_row.signature_image.path) as probe:
                probe.verify()
            sign_cell.append(RLImage(settings_row.signature_image.path, width=28 * mm, height=14 * mm, hAlign='RIGHT'))
        except Exception:
            pass
    if settings_row and settings_row.signatory_name:
        sign_cell.append(Paragraph(settings_row.signatory_name, right_bold_style))
        if settings_row.signatory_designation:
            sign_cell.append(Paragraph(settings_row.signatory_designation, right_label_style))
        sign_cell.append(Paragraph(company['name'], right_label_style))
    else:
        sign_cell.append(Paragraph('Authorized Signatory', right_label_style))

    footer_row = Table([[terms_cell, sign_cell]], colWidths=[content_width * 0.6, content_width * 0.4])
    footer_row.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'), ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0), ('LINEABOVE', (0, 0), (-1, 0), 0.6, BORDER), ('TOPPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(footer_row)

    elements.append(Spacer(1, 6 * mm))
    elements.append(Paragraph('This is a computer-generated invoice.', label_style))

    doc.build(elements)
    return buffer
