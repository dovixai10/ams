"""
Core logic for crediting leave-type balances (accrual) and handling
year-end carry-forward. Called by management commands (cron) and can
also be called directly from views/shell for testing.
"""
from datetime import date
from decimal import Decimal

from .models import Employee, LeaveType, EmployeeLeaveBalance, LeaveCreditLog


def get_or_create_leave_balance(employee, leave_type):
    """Return the EmployeeLeaveBalance row for this employee+type, creating it if needed."""
    balance, _ = EmployeeLeaveBalance.objects.get_or_create(
        employee=employee,
        leave_type=leave_type,
        defaults={'credit_year': date.today().year}
    )
    return balance


def _already_credited_this_period(balance, leave_type, run_date):
    """Idempotency check so the same monthly/yearly/one-time credit never fires twice."""
    if not balance.last_credited_date:
        return False

    if leave_type.accrual_frequency == LeaveType.AccrualFrequency.MONTHLY:
        return (
            balance.last_credited_date.year == run_date.year
            and balance.last_credited_date.month == run_date.month
        )
    if leave_type.accrual_frequency == LeaveType.AccrualFrequency.YEARLY:
        return balance.last_credited_date.year == run_date.year
    if leave_type.accrual_frequency == LeaveType.AccrualFrequency.ONE_TIME:
        # Once credited, never again — regardless of balance/deductions since.
        return LeaveCreditLog.objects.filter(
            employee=balance.employee,
            leave_type=leave_type,
            credit_type=LeaveCreditLog.CreditType.INITIAL_ALLOCATION,
        ).exists() or LeaveCreditLog.objects.filter(
            employee=balance.employee,
            leave_type=leave_type,
            credit_type=LeaveCreditLog.CreditType.AUTO_ACCRUAL,
        ).exists()
    return False


def run_accrual_for_leave_type(leave_type, run_date=None):
    """Credit every eligible, active employee for one leave type. Safe to run
    daily via cron — employees who were already credited this period are skipped."""
    run_date = run_date or date.today()

    if leave_type.accrual_frequency == LeaveType.AccrualFrequency.NONE:
        return 0

    employees = Employee.objects.filter(user__is_active=True)
    credited_count = 0

    for employee in employees:
        if not leave_type.is_applicable_for(employee):
            continue

        balance = get_or_create_leave_balance(employee, leave_type)

        if _already_credited_this_period(balance, leave_type, run_date):
            continue

        credit_type = (
            LeaveCreditLog.CreditType.INITIAL_ALLOCATION
            if leave_type.accrual_frequency == LeaveType.AccrualFrequency.ONE_TIME
            else LeaveCreditLog.CreditType.AUTO_ACCRUAL
        )

        result = balance.credit(
            leave_type.accrual_amount,
            credit_type=credit_type,
            note=f'Accrual for {run_date.strftime("%b %Y")}',
        )
        if result is not None:
            credited_count += 1

    return credited_count


def run_all_accruals(run_date=None):
    """Run accrual for every active leave type. This is what the daily cron calls."""
    run_date = run_date or date.today()
    total = 0
    leave_types = LeaveType.objects.filter(is_active=True).exclude(
        accrual_frequency=LeaveType.AccrualFrequency.NONE
    )
    for leave_type in leave_types:
        total += run_accrual_for_leave_type(leave_type, run_date)
    return total


def run_year_end_carry_forward(new_year=None):
    """Run once at year boundary (e.g. Jan 1 via cron). For each employee balance:
    - If carry forward is NOT allowed: balance is zeroed out, with an audit log.
    - If carry forward IS allowed but capped: balance is trimmed to the cap.
    - Either way, the yearly credit counter resets for the new annual_limit tracking.
    """
    new_year = new_year or date.today().year
    processed = 0

    for leave_type in LeaveType.objects.all():
        balances = EmployeeLeaveBalance.objects.filter(leave_type=leave_type)

        for balance in balances:
            if not leave_type.allow_carry_forward:
                if balance.balance > 0:
                    lost = balance.balance
                    balance.balance = Decimal('0.0')
                    LeaveCreditLog.objects.create(
                        employee=balance.employee,
                        leave_type=leave_type,
                        amount=-lost,
                        balance_after=Decimal('0.0'),
                        credit_type=LeaveCreditLog.CreditType.DEDUCTION,
                        note=f'Balance expired at year end (carry forward not allowed) — {new_year}',
                    )
            elif leave_type.carry_forward_cap is not None and balance.balance > leave_type.carry_forward_cap:
                lost = balance.balance - leave_type.carry_forward_cap
                balance.balance = leave_type.carry_forward_cap
                LeaveCreditLog.objects.create(
                    employee=balance.employee,
                    leave_type=leave_type,
                    amount=-lost,
                    balance_after=balance.balance,
                    credit_type=LeaveCreditLog.CreditType.CARRY_FORWARD,
                    note=f'Capped at carry-forward limit ({leave_type.carry_forward_cap}) for {new_year}',
                )

            balance.total_credited_this_year = Decimal('0.0')
            balance.credit_year = new_year
            balance.save(update_fields=['balance', 'total_credited_this_year', 'credit_year', 'updated_at'])
            processed += 1

    return processed