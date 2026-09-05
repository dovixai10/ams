"""Payroll run and payslip views (#43–44)."""

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.files.base import ContentFile
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone

from employees.permissions import get_request_office, office_admin_required
from web_project import TemplateLayout
from web_project.template_helpers.theme import TemplateHelper

from .models import Employee, PayrollRun, PayrollRunLine, SalarySlip
from .payroll_service import amount_in_words_inr, compute_payroll_run, publish_payslips_from_run
from .views import tenant_object_or_404, tenant_queryset


def _layout(request, extra=None):
    ctx = TemplateLayout.init(request, context={})
    ctx.update({'layout_path': TemplateHelper.set_layout('layout_vertical.html', ctx)})
    if extra:
        ctx.update(extra)
    return ctx


@login_required
@user_passes_test(office_admin_required)
def payroll_run_list(request):
    office = get_request_office(request)
    runs = PayrollRun.objects.filter(office=office).order_by('-period_month') if office else PayrollRun.objects.none()
    if request.method == 'POST':
        month_str = request.POST.get('period_month')
        if month_str and office:
            from datetime import datetime
            period = datetime.strptime(month_str, '%Y-%m').date().replace(day=1)
            run, created = PayrollRun.objects.get_or_create(
                office=office,
                period_month=period,
                defaults={'created_by': request.user},
            )
            if created:
                messages.success(request, f'Payroll run created for {period:%B %Y}.')
            else:
                messages.info(request, 'A run for that month already exists.')
            return redirect('employees:payroll_run_detail', pk=run.pk)
    return render(request, 'employees/payroll/run_list.html', _layout(request, {
        'runs': runs,
        'page_title': 'Payroll processing',
    }))


@login_required
@user_passes_test(office_admin_required)
def payroll_run_detail(request, pk):
    run = get_object_or_404(tenant_queryset(request, PayrollRun.objects.all()), pk=pk)
    lines = run.lines.select_related('employee').order_by('employee__full_name')
    exceptions = [ln for ln in lines if ln.exception_flags]

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'compute' and run.status == PayrollRun.Status.DRAFT:
            compute_payroll_run(run)
            messages.success(request, 'Payroll computed for all active employees.')
        elif action == 'review' and run.status == PayrollRun.Status.COMPUTED:
            run.status = PayrollRun.Status.UNDER_REVIEW
            run.save(update_fields=['status', 'updated_at'])
            messages.success(request, 'Moved to under review.')
        elif action == 'approve' and run.status == PayrollRun.Status.UNDER_REVIEW:
            run.status = PayrollRun.Status.APPROVED
            run.approved_at = timezone.now()
            run.save(update_fields=['status', 'approved_at', 'updated_at'])
            publish_payslips_from_run(run)
            messages.success(request, 'Approved and payslips published.')
        elif action == 'close' and run.status == PayrollRun.Status.APPROVED:
            run.status = PayrollRun.Status.CLOSED
            run.closed_at = timezone.now()
            run.save(update_fields=['status', 'closed_at', 'updated_at'])
            messages.success(request, 'Payroll run closed (immutable).')
        return redirect('employees:payroll_run_detail', pk=run.pk)

    return render(request, 'employees/payroll/run_detail.html', _layout(request, {
        'run': run,
        'lines': lines,
        'exceptions': exceptions,
        'page_title': f'Payroll {run.period_month:%B %Y}',
    }))


def build_payslip_context(salary_slip: SalarySlip):
    employee = salary_slip.employee
    office = employee.office
    earnings = {k: Decimal(v) for k, v in (salary_slip.earnings_json or {}).items()}
    deductions = {k: Decimal(v) for k, v in (salary_slip.deductions_json or {}).items()}
    employer = {k: Decimal(v) for k, v in (salary_slip.employer_contrib_json or {}).items()}
    gross = salary_slip.gross_earnings or sum(earnings.values(), Decimal('0'))
    total_ded = salary_slip.deductions or sum(deductions.values(), Decimal('0'))
    return {
        'slip': salary_slip,
        'employee': employee,
        'office': office,
        'earnings': earnings,
        'deductions': deductions,
        'employer': employer,
        'gross': gross,
        'total_deductions': total_ded,
        'net': salary_slip.net_salary,
        'net_words': salary_slip.net_pay_words or amount_in_words_inr(salary_slip.net_salary),
        'month_label': salary_slip.month.strftime('%B %Y'),
    }


def render_payslip_pdf(salary_slip, request=None):
    import io
    html = render_to_string('employees/payroll/payslip_pdf.html', build_payslip_context(salary_slip), request=request)
    buffer = io.BytesIO()
    from xhtml2pdf import pisa
    pisa.CreatePDF(html, dest=buffer, encoding='utf-8')
    buffer.seek(0)
    return buffer


@login_required
def payslip_preview(request, pk):
    salary_slip = get_object_or_404(
        tenant_queryset(request, SalarySlip.objects.select_related('employee', 'employee__office')),
        pk=pk,
    )
    is_owner = hasattr(request.user, 'employee_profile') and request.user.employee_profile == salary_slip.employee
    if not (office_admin_required(request.user) or is_owner):
        messages.error(request, 'Access denied.')
        return redirect('employees:employee_dashboard')
    return render(request, 'employees/payroll/payslip_preview.html', _layout(request, {
        **build_payslip_context(salary_slip),
        'page_title': f'Payslip {salary_slip.month:%B %Y}',
    }))


@login_required
def payslip_download_pdf(request, pk):
    salary_slip = get_object_or_404(
        tenant_queryset(request, SalarySlip.objects.select_related('employee')),
        pk=pk,
    )
    is_owner = hasattr(request.user, 'employee_profile') and request.user.employee_profile == salary_slip.employee
    if not (office_admin_required(request.user) or is_owner):
        messages.error(request, 'Access denied.')
        return redirect('employees:employee_dashboard')
    pdf = render_payslip_pdf(salary_slip, request)
    filename = f"payslip_{salary_slip.employee_id}_{salary_slip.month:%Y_%m}.pdf"
    return HttpResponse(pdf.getvalue(), content_type='application/pdf', headers={
        'Content-Disposition': f'attachment; filename="{filename}"',
    })
