"""
Shared helpers for the mobile attendance app API (employees/mobile_*.py).
Built against DOVIX_AI_Attendance_Backend_API_Spec.pdf v1.0 (14 Sep 2026).
"""
import re
from django.utils import timezone


def employee_code(employee):
    """The employeeId shown to the mobile client, e.g. 'KI00014'. Same
    format already used by /api/v1/profile/ (EmployeeProfileSerializer) -
    kept identical rather than inventing a second numbering scheme."""
    return f"KI{employee.id:05d}"


_CODE_RE = re.compile(r'^KI0*(\d+)$', re.IGNORECASE)


def resolve_employee_by_identifier(identifier, office=None):
    """POST /auth/login's `identifier` is 'Employee ID or work email' in one
    field; the server resolves which. Returns an Employee or None."""
    from .models import Employee

    identifier = (identifier or '').strip()
    if not identifier:
        return None

    qs = Employee.objects.select_related('user', 'office', 'branch')
    if office is not None:
        qs = qs.filter(office=office)

    m = _CODE_RE.match(identifier)
    if m:
        return qs.filter(id=int(m.group(1))).first()

    return qs.filter(email__iexact=identifier).first()


# --- Attendance status -----------------------------------------------------

# Employee.branch/office are enough to look up Holiday/LeaveRequest; this
# maps Attendance.final_status (an internal, hours-based outcome) onto the
# spec's AttendanceStatus enum (section 3.1). LATE isn't one of final_status's
# values in this codebase (attendance here is graded by hours worked, not
# arrival time) - it's computed separately at check-in time (see
# mobile_attendance_api.py) and stored nowhere else, so a past day that was
# late but otherwise a full day still reports PRESENT here, same as the
# existing web app already does.
FINAL_STATUS_TO_SPEC = {
    'present': 'PRESENT',
    'absent': 'ABSENT',
    'half_day': 'HALF_DAY',
    'late_penalty': 'HALF_DAY',
    'sandwich_leave': 'ABSENT',
    'checked_in': 'PENDING',
}


def spec_day_status(employee, day, *, attendance=None, holiday_dates=None, leave_dates=None, half_leave_dates=None):
    """Returns one AttendanceStatus value (section 3.1) for a single
    calendar day for this employee. Callers doing a whole month should
    precompute holiday_dates/leave_dates (sets of date) once and pass them
    in - see mobile_attendance_api.py for the batched version."""
    today = timezone.localdate()
    if day > today:
        return None  # future date - caller decides whether to omit or null it

    if holiday_dates is not None and day in holiday_dates:
        return 'HOLIDAY'
    if leave_dates is not None and day in leave_dates:
        return 'PAID_LEAVE'

    if attendance is not None:
        if attendance.check_in_time and not attendance.check_out_time and day == today:
            return 'PENDING'
        return FINAL_STATUS_TO_SPEC.get(attendance.final_status, 'PRESENT')

    # Half a day of approved leave and no punch: the leave covers one half.
    if half_leave_dates is not None and day in half_leave_dates and day.weekday() != 6:
        return 'HALF_DAY'

    # No record and not a holiday/leave day - was it actually a working day?
    # There's no per-shift working-days field in this codebase yet (see
    # GET /employees/me/shift's own note on this); Sunday-off is the
    # existing app's convention elsewhere, so it's reused here too.
    if day.weekday() == 6:  # Sunday
        return 'HOLIDAY'
    return 'ABSENT'


def approved_leave_weights(employee, first, last):
    """{date: weight} for every day in [first, last] covered by an approved
    leave: 1 for a full day, 0.5 for a first/second-half leave (both halves
    of one date add up to a full day)."""
    from datetime import timedelta
    from .models import LeaveRequest

    weights = {}
    for leave in LeaveRequest.objects.filter(
        employee=employee, status=LeaveRequest.Status.APPROVED,
        start_date__lte=last, end_date__gte=first,
    ):
        per_day = 0.5 if leave.is_half_day else 1.0
        day = max(leave.start_date, first)
        stop = min(leave.end_date, last)
        while day <= stop:
            weights[day] = min(weights.get(day, 0.0) + per_day, 1.0)
            day += timedelta(days=1)
    return weights


def count_absent_days(employee, records, first, last, holiday_dates, leave_weights):
    """Absent days in [first, last], counting a working day the employee never
    punched in on (no Attendance row at all) as well as rows marked
    absent/sandwich_leave - a day with no row is the common case, and
    counting only existing rows silently reported 0.

    Working day = not a Sunday, not a holiday, on/after the joining date, not
    a full day of approved leave. A half-day leave covers half of that day, so
    only the other half can count as absent. Future days are never counted."""
    from datetime import timedelta

    end = min(last, timezone.localdate())
    start = max(first, employee.joining_date) if getattr(employee, 'joining_date', None) else first
    by_date = {r.date: r for r in records}

    absent = 0.0
    day = start
    while day <= end:
        weight = leave_weights.get(day, 0.0)
        if day.weekday() != 6 and day not in holiday_dates and weight < 1.0:
            record = by_date.get(day)
            if record is None or record.final_status in ('absent', 'sandwich_leave'):
                absent += 1.0 - weight
        day += timedelta(days=1)
    return int(absent) if absent == int(absent) else absent


def count_leave_days(leave_weights, holiday_dates):
    """Leave days taken, in days (a half-day leave is 0.5) - Sundays and
    holidays inside a leave range aren't leave days."""
    total = sum(w for d, w in leave_weights.items() if d.weekday() != 6 and d not in holiday_dates)
    return int(total) if total == int(total) else total


def duration_payload(total_seconds):
    """{"seconds": N, "display": "8h 59m"} - the spec's duration shape
    (section 2.5)."""
    total_seconds = int(total_seconds or 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    return {"seconds": total_seconds, "display": f"{hours}h {minutes:02d}m"}


def paginate(queryset_or_list, page, page_size):
    """Applies the spec's pagination convention (section 2.6) to a list or
    queryset already ordered by the caller. Returns (page_items, pagination_dict)."""
    try:
        page = max(int(page or 1), 1)
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = min(max(int(page_size or 20), 1), 100)
    except (TypeError, ValueError):
        page_size = 20

    # NB: a plain list also has a .count() method (with a different
    # signature - counts occurrences of a value, takes no args when you
    # call it right but breaks hasattr-based duck typing), so check for
    # an actual QuerySet explicitly rather than hasattr(..., 'count').
    from django.db.models import QuerySet
    total_items = queryset_or_list.count() if isinstance(queryset_or_list, QuerySet) else len(queryset_or_list)
    total_pages = max((total_items + page_size - 1) // page_size, 1)
    start = (page - 1) * page_size
    end = start + page_size
    items = queryset_or_list[start:end]

    pagination = {
        "page": page, "pageSize": page_size,
        "totalItems": total_items, "totalPages": total_pages,
    }
    return items, pagination
