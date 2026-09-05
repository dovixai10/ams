"""Payroll run computation and payslip rendering."""

from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from .models import Attendance, Employee, EmployeeSalary, LeaveRequest, PayrollRun, PayrollRunLine, SalarySlip


def _month_bounds(period_month: date):
    year, month = period_month.year, period_month.month
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _active_salary(employee, period_month: date):
    return (
        EmployeeSalary.objects.filter(
            employee=employee,
            is_active=True,
            effective_from__lte=period_month,
        )
        .order_by('-effective_from')
        .first()
    )


def _paid_and_lop_days(employee, period_start, period_end):
    working_days = monthrange(period_start.year, period_start.month)[1]
    approved_lop = LeaveRequest.objects.filter(
        employee=employee,
        status=LeaveRequest.Status.APPROVED,
        start_date__lte=period_end,
        end_date__gte=period_start,
    ).count()
    lop_days = Decimal(str(min(approved_lop, working_days)))
    paid_days = Decimal(str(working_days)) - lop_days
    present = Attendance.objects.filter(
        employee=employee,
        date__gte=period_start,
        date__lte=period_end,
        check_in_time__isnull=False,
    ).count()
    if present == 0 and paid_days > 0:
        return paid_days, lop_days, working_days, ['no_attendance']
    return paid_days, lop_days, working_days, []


def _prorate(amount, paid_days, working_days):
    if not amount or working_days <= 0:
        return Decimal('0')
    return (Decimal(amount) * paid_days / Decimal(working_days)).quantize(Decimal('0.01'), ROUND_HALF_UP)


def compute_payroll_run(run: PayrollRun):
    """Compute all employee lines for a payroll run (skeleton engine)."""
    if run.is_locked:
        raise ValueError('Cannot recompute a closed or paid payroll run.')

    period_start, period_end = _month_bounds(run.period_month)
    employees = Employee.objects.filter(office=run.office, user__is_active=True)

    prior_run = (
        PayrollRun.objects.filter(
            office=run.office,
            period_month__lt=run.period_month,
            status__in=[PayrollRun.Status.COMPUTED, PayrollRun.Status.APPROVED, PayrollRun.Status.PAID, PayrollRun.Status.CLOSED],
        )
        .order_by('-period_month')
        .first()
    )
    prior_lines = {}
    if prior_run:
        prior_lines = {ln.employee_id: ln for ln in prior_run.lines.all()}

    exceptions = []
    with transaction.atomic():
        run.lines.all().delete()
        for employee in employees:
            salary = _active_salary(employee, run.period_month)
            flags = []
            if not salary:
                flags.append('no_salary_structure')
                PayrollRunLine.objects.create(
                    run=run,
                    employee=employee,
                    exception_flags=flags,
                    notes='No salary structure found.',
                )
                exceptions.append(employee)
                continue

            paid_days, lop_days, working_days, att_flags = _paid_and_lop_days(
                employee, period_start, period_end
            )
            flags.extend(att_flags)

            earnings = {
                'basic': _prorate(salary.basic_salary, paid_days, working_days),
                'hra': _prorate(salary.hra, paid_days, working_days),
                'conveyance': _prorate(salary.conveyance_allowance, paid_days, working_days),
                'medical': _prorate(salary.medical_allowance, paid_days, working_days),
                'special_allowance': _prorate(salary.special_allowance, paid_days, working_days),
                'bonus': _prorate(salary.bonus, paid_days, working_days),
                'overtime': Decimal('0'),
            }
            earnings = {k: v for k, v in earnings.items() if v > 0}
            gross = sum(earnings.values(), Decimal('0'))

            pf_base = min(earnings.get('basic', Decimal('0')), Decimal('15000'))
            pf_employee = (pf_base * Decimal('0.12')).quantize(Decimal('0.01'), ROUND_HALF_UP)

            deductions = {
                'pf_employee': pf_employee,
                'esi': _prorate(salary.esi, paid_days, working_days),
                'professional_tax': _prorate(salary.professional_tax, paid_days, working_days),
                'tds': _prorate(salary.tds, paid_days, working_days),
            }
            if lop_days > 0 and working_days > 0:
                lop_amount = (gross * lop_days / Decimal(working_days)).quantize(Decimal('0.01'), ROUND_HALF_UP)
                if lop_amount > 0:
                    deductions['lop'] = lop_amount

            deductions = {k: v for k, v in deductions.items() if v > 0}
            total_deductions = sum(deductions.values(), Decimal('0'))
            net = gross - total_deductions

            if net < 0:
                flags.append('negative_net_pay')

            prior = prior_lines.get(employee.id)
            prior_net = prior.net_pay if prior else None
            if prior_net and prior_net > 0:
                var_pct = abs((net - prior_net) / prior_net * 100)
                if var_pct > Decimal('25'):
                    flags.append('variance_threshold')

            employer = {
                'pf_employer': pf_employee,
                'esi_employer': _prorate(salary.esi, paid_days, working_days),
                'gratuity': Decimal('0'),
            }
            employer = {k: v for k, v in employer.items() if v > 0}

            PayrollRunLine.objects.create(
                run=run,
                employee=employee,
                paid_days=paid_days,
                lop_days=lop_days,
                working_days=working_days,
                gross_earnings=gross,
                total_deductions=total_deductions,
                net_pay=net,
                prior_net_pay=prior_net,
                earnings_json={k: str(v) for k, v in earnings.items()},
                deductions_json={k: str(v) for k, v in deductions.items()},
                employer_contrib_json={k: str(v) for k, v in employer.items()},
                exception_flags=flags,
            )

        run.status = PayrollRun.Status.COMPUTED
        run.computed_at = timezone.now()
        run.save(update_fields=['status', 'computed_at', 'updated_at'])

    return run


def publish_payslips_from_run(run: PayrollRun):
    """Create/update SalarySlip rows from computed payroll lines."""
    for line in run.lines.select_related('employee'):
        if line.exception_flags and 'no_salary_structure' in line.exception_flags:
            continue
        SalarySlip.objects.update_or_create(
            office=run.office,
            employee=line.employee,
            month=run.period_month,
            defaults={
                'payroll_run': run,
                'basic_salary': Decimal(line.earnings_json.get('basic', '0')),
                'deductions': line.total_deductions,
                'net_salary': line.net_pay,
                'paid_days': line.paid_days,
                'lop_days': line.lop_days,
                'working_days': line.working_days,
                'gross_earnings': line.gross_earnings,
                'earnings_json': line.earnings_json,
                'deductions_json': line.deductions_json,
                'employer_contrib_json': line.employer_contrib_json,
            },
        )


def amount_in_words_inr(amount) -> str:
    """Minimal Indian rupee amount in words (skeleton)."""
    try:
        val = int(Decimal(amount))
    except Exception:
        return ''
    if val == 0:
        return 'Zero rupees only'
    return f'{val:,} rupees only'
