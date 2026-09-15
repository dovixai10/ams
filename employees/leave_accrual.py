"""
Leave accrual + carry-forward engine — reads LeaveType's own config and
credits EmployeeLeaveBalance accordingly. Everything here is LAZY: there
is no cron job. Instead, every function is safe to call repeatedly and
only acts when something is actually due (idempotent), so simply calling
get_employee_leave_type_balances() whenever an employee opens their leave
page is enough to keep balances correct.
"""
from datetime import date
from decimal import Decimal
from .models import Employee, LeaveType, EmployeeLeaveBalance, LeaveCreditLog, fiscal_year_for


def initialize_balances_for_new_type(leave_type: LeaveType, credited_by=None):
    """
    Called right after a LeaveType is created. Creates an EmployeeLeaveBalance
    row for every eligible, active employee and credits their first cycle
    immediately, instead of waiting for someone to visit the leave page.

    Returns the number of employees actually credited.
    """
    if not leave_type.is_active:
        return 0

    employees = Employee.objects.filter(user__is_active=True, office=leave_type.office)
    credited_count = 0
    today = date.today()

    for employee in employees:
        # branch=NULL means "office-wide"; a branch-tagged leave type only
        # applies to employees in that same branch.
        if leave_type.branch_id is not None and leave_type.branch_id != employee.branch_id:
            continue
        if not leave_type.is_applicable_for(employee):
            continue

        balance_obj, _ = EmployeeLeaveBalance.objects.get_or_create(
            employee=employee,
            leave_type=leave_type,
            defaults={'balance': 0, 'credit_year': fiscal_year_for(today), 'branch': employee.branch},
        )

        if leave_type.accrual_frequency == LeaveType.AccrualFrequency.NONE:
            continue  # manual-only type — admin credits by hand later

        result = balance_obj.credit(
            leave_type.accrual_amount,
            credit_type='initial_allocation',
            note=f"Initial allocation on {leave_type.name} creation",
            credited_by=credited_by,
        )
        if result:
            credited_count += 1

    return credited_count


def _months_elapsed(start: date, end: date) -> int:
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def _years_elapsed(start: date, end: date) -> int:
    years = end.year - start.year
    if (end.month, end.day) < (start.month, start.day):
        years -= 1
    return max(years, 0)


def apply_year_end_carry_forward_if_due(balance_obj: EmployeeLeaveBalance, today: date = None):
    """
    LAZY fiscal-year rollover (April -> March). Runs whenever an employee's
    balance is looked up. If balance_obj.credit_year is behind the current
    fiscal year, settles last FY's leftover balance right now:

      - allow_carry_forward = False           -> whole balance forfeited to 0
      - allow_carry_forward = True + cap set  -> anything above cap forfeited
      - allow_carry_forward = True + no cap   -> balance carries over untouched

    No-op once credit_year already matches the current fiscal year.
    """
    today = today or date.today()
    current_fy = fiscal_year_for(today)

    if balance_obj.credit_year >= current_fy:
        return

    lt = balance_obj.leave_type
    forfeited = Decimal('0.0')

    if not lt.allow_carry_forward:
        forfeited = balance_obj.balance
        balance_obj.balance = Decimal('0.0')
    elif lt.carry_forward_cap is not None and balance_obj.balance > lt.carry_forward_cap:
        forfeited = balance_obj.balance - lt.carry_forward_cap
        balance_obj.balance = lt.carry_forward_cap
    # else: allow_carry_forward=True, no cap -> balance carries fully, untouched

    balance_obj.total_credited_this_year = Decimal('0.0')
    balance_obj.credit_year = current_fy
    balance_obj.save(update_fields=[
        'balance', 'total_credited_this_year', 'credit_year', 'updated_at'
    ])

    if forfeited > 0:
        LeaveCreditLog.objects.create(
            employee=balance_obj.employee, leave_type=lt,
            branch=balance_obj.employee.branch,
            amount=-forfeited, balance_after=balance_obj.balance,
            credit_type='deduction',
            note=f"Forfeited {forfeited} day(s) not carried forward into FY {current_fy}-{current_fy + 1}",
        )
    else:
        LeaveCreditLog.objects.create(
            employee=balance_obj.employee, leave_type=lt,
            branch=balance_obj.employee.branch,
            amount=Decimal('0.0'), balance_after=balance_obj.balance,
            credit_type='carry_forward',
            note=f"Balance carried forward into FY {current_fy}-{current_fy + 1}",
        )


def ensure_accrual(employee, balance_obj: EmployeeLeaveBalance, today: date = None):
    """
    Catch up any missed accrual cycles for this specific balance.
    Uses joining_date as the baseline for the very first credit, then
    last_credited_date for every credit after that.
    """
    lt = balance_obj.leave_type
    today = today or date.today()

    if lt.accrual_frequency == LeaveType.AccrualFrequency.NONE:
        return

    base_date = balance_obj.last_credited_date or employee.joining_date or balance_obj.created_at.date()

    if lt.accrual_frequency == LeaveType.AccrualFrequency.MONTHLY:
        cycles_due = _months_elapsed(base_date, today)
    elif lt.accrual_frequency == LeaveType.AccrualFrequency.YEARLY:
        cycles_due = _years_elapsed(base_date, today)
    elif lt.accrual_frequency == LeaveType.AccrualFrequency.ONE_TIME:
        cycles_due = 1 if balance_obj.last_credited_date is None else 0
    else:
        cycles_due = 0

    for _ in range(cycles_due):
        balance_obj.credit(
            lt.accrual_amount,
            credit_type='auto_accrual',
            note=f"Auto accrual ({lt.get_accrual_frequency_display()})",
        )
        balance_obj.refresh_from_db()


def get_employee_leave_type_balances(employee):
    """
    Returns [{'leave_type': LeaveType, 'balance': Decimal}, ...] for every
    active, applicable LeaveType.

    Call order matters:
      1. Get-or-create the balance row.
      2. Settle any pending year-end carry-forward FIRST (using last
         FY's numbers, before anything new gets added).
      3. THEN run this FY's accrual catch-up.

    This single function is your entire "automation" — no cron needed.
    """
    leave_types = LeaveType.objects.filter(office=employee.office, is_active=True).order_by('display_order', 'name')
    result = []
    today = date.today()

    for lt in leave_types:
        # branch=NULL means "office-wide"; a branch-tagged leave type only
        # applies to employees in that same branch.
        if lt.branch_id is not None and lt.branch_id != employee.branch_id:
            continue
        if not lt.is_applicable_for(employee):
            continue

        balance_obj, _ = EmployeeLeaveBalance.objects.get_or_create(
            employee=employee,
            leave_type=lt,
            defaults={'balance': 0, 'credit_year': fiscal_year_for(today), 'branch': employee.branch},
        )
        if balance_obj.branch_id != employee.branch_id:
            # Employee was reassigned to a different branch since this balance
            # row was created — keep it in sync (lookup above is intentionally
            # employee+leave_type only, matching the DB's unique_together).
            balance_obj.branch = employee.branch
            balance_obj.save(update_fields=['branch'])

        apply_year_end_carry_forward_if_due(balance_obj, today)  # settle last FY first
        balance_obj.refresh_from_db()

        ensure_accrual(employee, balance_obj, today)             # then credit due cycles

        result.append({
            'leave_type': lt,
            'balance': balance_obj.balance,
        })

    return result


def resync_balances_for_type_change(leave_type: LeaveType, old_amount, admin_user=None):
    """
    Call this right after an admin edits an existing LeaveType's
    accrual_amount. Adjusts every employee's current balance by the
    difference between what they *would* have been credited so far under
    the new amount vs. the old amount — but only for cycles that were
    already auto-credited (auto_accrual / initial_allocation), never
    touching manual adjustments or deductions.

    Returns the number of employees whose balance actually changed.
    """
    old_amount = Decimal(str(old_amount))
    new_amount = leave_type.accrual_amount
    diff_per_cycle = new_amount - old_amount

    if diff_per_cycle == 0:
        return 0

    updated = 0
    for balance_obj in EmployeeLeaveBalance.objects.filter(leave_type=leave_type).select_related('employee'):
        cycles_credited = balance_obj.employee.leave_credit_logs.filter(
            leave_type=leave_type,
            credit_type__in=['auto_accrual', 'initial_allocation'],
        ).count()
        if cycles_credited == 0:
            continue

        adjustment = diff_per_cycle * cycles_credited
        new_balance = balance_obj.balance + adjustment

        if leave_type.max_balance_cap is not None:
            new_balance = min(new_balance, leave_type.max_balance_cap)
        new_balance = max(new_balance, Decimal('0.0'))

        actual_change = new_balance - balance_obj.balance
        if actual_change == 0:
            continue

        balance_obj.balance = new_balance
        balance_obj.save(update_fields=['balance', 'updated_at'])

        LeaveCreditLog.objects.create(
            employee=balance_obj.employee,
            branch=balance_obj.employee.branch,
            leave_type=leave_type,
            amount=actual_change,
            balance_after=balance_obj.balance,
            credit_type='manual_adjustment',
            note=f"Auto-resync: accrual amount changed {old_amount} → {new_amount}",
            credited_by=admin_user,
        )
        updated += 1

    return updated