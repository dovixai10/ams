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
        invoice.invoice_date = invoice_date
        invoice.due_date = due_date
        invoice.place_of_supply_state = place_of_supply_state
        invoice.payment_terms = request.POST.get('payment_terms', Invoice.PaymentTerms.DUE_ON_RECEIPT)
        invoice.sales_person_id = request.POST.get('sales_person') or None
        invoice.notes = request.POST.get('notes', '').strip()
        invoice.terms_and_conditions = request.POST.get('terms_and_conditions', '').strip()
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
        return redirect('employees:invoice_update', pk=invoice.pk)

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
        'existing_items_data': existing_items,
        'default_terms': settings_row.default_terms_and_conditions if settings_row else '',
        'default_payment_terms': settings_row.default_payment_terms if settings_row else Invoice.PaymentTerms.DUE_ON_RECEIPT,
        'office': office,
        'branch': branch,
        'today': timezone.now().date().isoformat(),
        'bank_lines': [
            line for line in [
                f'Bank: {settings_row.bank_name}' if settings_row and settings_row.bank_name else '',
                f'A/C Name: {settings_row.bank_account_name}' if settings_row and settings_row.bank_account_name else '',
                f'A/C No.: {settings_row.bank_account_number}' if settings_row and settings_row.bank_account_number else '',
                f'IFSC: {settings_row.ifsc_code}' if settings_row and settings_row.ifsc_code else '',
                f'Branch: {settings_row.bank_branch_name}' if settings_row and settings_row.bank_branch_name else '',
            ] if line
        ],
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

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=16 * mm, bottomMargin=16 * mm, leftMargin=16 * mm, rightMargin=16 * mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('InvTitle', parent=styles['Heading1'], alignment=TA_CENTER, fontSize=16, textColor=colors.HexColor('#2B2C40'))
    label_style = ParagraphStyle('InvLabel', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#8592A3'))
    normal_style = ParagraphStyle('InvNormal', parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#2B2C40'))
    section_style = ParagraphStyle('InvSection', parent=styles['Heading3'], fontSize=10, textColor=colors.HexColor('#696CFF'), spaceBefore=4, spaceAfter=4)
    right_style = ParagraphStyle('InvRight', parent=normal_style, alignment=TA_RIGHT)

    elements = []
    elements.append(Paragraph(office.name, title_style))
    elements.append(Paragraph(office.address or '', label_style))
    if office.gst_number:
        elements.append(Paragraph(f'GSTIN: {office.gst_number}', label_style))
    elements.append(Spacer(1, 6 * mm))

    type_labels = {'tax_invoice': 'TAX INVOICE', 'bill_of_supply': 'BILL OF SUPPLY', 'non_gst': 'INVOICE'}
    elements.append(Paragraph(type_labels.get(invoice.invoice_type, 'INVOICE'), title_style))
    elements.append(Spacer(1, 4 * mm))

    info_table = Table(
        [
            ['Invoice No.', invoice.invoice_number or 'DRAFT', 'Invoice Date', invoice.invoice_date.strftime('%d %b %Y')],
            ['Due Date', invoice.due_date.strftime('%d %b %Y') if invoice.due_date else '-', 'Place of Supply', invoice.place_of_supply_state],
        ],
        colWidths=[35 * mm, 55 * mm, 35 * mm, 45 * mm],
    )
    info_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'), ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#6b7280')), ('TEXTCOLOR', (2, 0), (2, -1), colors.HexColor('#6b7280')),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5), ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5e7eb')),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 5 * mm))

    elements.append(Paragraph('Bill To', section_style))
    bill_to_lines = [client.name]
    if client.contact_person:
        bill_to_lines.append(client.contact_person)
    if client.billing_address:
        bill_to_lines.append(client.billing_address)
    if client.state or client.pincode:
        bill_to_lines.append(f"{client.state} {client.pincode}".strip())
    if client.gstin:
        bill_to_lines.append(f"GSTIN: {client.gstin}")
    if client.phone:
        bill_to_lines.append(f"Phone: {client.phone}")
    if client.email:
        bill_to_lines.append(f"Email: {client.email}")
    for line in bill_to_lines:
        elements.append(Paragraph(line, normal_style))
    elements.append(Spacer(1, 4 * mm))

    meta_bits = [f"Payment Terms: {invoice.get_payment_terms_display()}"]
    if invoice.project:
        meta_bits.append(f"Project: {invoice.project.name}")
    if invoice.sales_person:
        meta_bits.append(f"Sales Person: {invoice.sales_person.full_name}")
    elements.append(Paragraph(' | '.join(meta_bits), label_style))
    elements.append(Spacer(1, 5 * mm))

    item_rows = [['#', 'Description', 'SAC', 'Qty', 'Rate', 'Disc.', 'Tax', 'Amount (₹)']]
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

    totals_rows = [
        ['Subtotal', f"₹ {invoice.subtotal:,.2f}"],
        ['Discount', f"₹ {invoice.discount_total:,.2f}"],
        ['Taxable Amount', f"₹ {invoice.taxable_amount:,.2f}"],
    ]
    if invoice.cgst_total:
        totals_rows.append(['CGST', f"₹ {invoice.cgst_total:,.2f}"])
        totals_rows.append(['SGST', f"₹ {invoice.sgst_total:,.2f}"])
    if invoice.igst_total:
        totals_rows.append(['IGST', f"₹ {invoice.igst_total:,.2f}"])
    totals_table = Table(totals_rows, colWidths=[40 * mm, 40 * mm])
    totals_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9), ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    wrapper = Table([[None, totals_table]], colWidths=[112 * mm, 80 * mm])
    wrapper.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    elements.append(wrapper)
    elements.append(Spacer(1, 2 * mm))

    grand_table = Table([['Total Amount Payable', f"₹ {invoice.grand_total:,.2f}"]], colWidths=[112 * mm, 80 * mm])
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

    if settings_row and settings_row.bank_name:
        elements.append(Paragraph('Bank Details', section_style))
        for line in [
            f"Bank Name: {settings_row.bank_name}", f"Account Name: {settings_row.bank_account_name}",
            f"Account Number: {settings_row.bank_account_number}", f"IFSC Code: {settings_row.ifsc_code}",
            f"Branch: {settings_row.bank_branch_name}",
        ]:
            if line.split(': ', 1)[1]:
                elements.append(Paragraph(line, normal_style))
        elements.append(Spacer(1, 5 * mm))

    if settings_row and settings_row.upi_vpa:
        try:
            import qrcode
            upi_link = f"upi://pay?pa={settings_row.upi_vpa}&pn={office.name}&am={invoice.grand_total}&cu=INR"
            qr_img = qrcode.make(upi_link)
            qr_buffer = BytesIO()
            qr_img.save(qr_buffer, format='PNG')
            qr_buffer.seek(0)
            elements.append(Paragraph('Scan to Pay (UPI)', section_style))
            elements.append(RLImage(qr_buffer, width=28 * mm, height=28 * mm))
            elements.append(Spacer(1, 5 * mm))
        except Exception:
            pass

    if invoice.terms_and_conditions:
        elements.append(Paragraph('Terms &amp; Conditions', section_style))
        for line in invoice.terms_and_conditions.splitlines():
            if line.strip():
                elements.append(Paragraph(line.strip(), label_style))
        elements.append(Spacer(1, 6 * mm))

    if settings_row and settings_row.signatory_name:
        if settings_row.signature_image:
            try:
                elements.append(RLImage(settings_row.signature_image.path, width=30 * mm, height=15 * mm))
            except Exception:
                pass
        elements.append(Paragraph(settings_row.signatory_name, normal_style))
        if settings_row.signatory_designation:
            elements.append(Paragraph(settings_row.signatory_designation, label_style))

    elements.append(Spacer(1, 6 * mm))
    elements.append(Paragraph('This is a computer-generated invoice.', label_style))

    doc.build(elements)
    return buffer
