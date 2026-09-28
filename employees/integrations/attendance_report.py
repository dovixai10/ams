"""Builds the daily attendance report that gets sent over WhatsApp, and renders
it into the two message shapes the WhatsApp client can send.

An employee is:
  * Present   - has marked attendance today (checked in) by the time the report runs
  * On leave  - hasn't, but has a full day of approved leave today (not "absent")
  * Absent    - hasn't marked attendance and isn't on approved leave
Employees whose branch has a public/company holiday today are left out entirely
(when the schedule skips holidays), so a holiday doesn't read as everyone absent.
"""
import re

from django.utils import timezone

from ..models import Attendance, Employee, Holiday, LeaveRequest

# A row counts as "marked attendance" if the employee really checked in, or an
# admin/regularization recorded a working status for the day. Leave/absent
# placeholders written by leave approval or the daily absent job don't count.
WORKED_STATUSES = ('present', 'half_day', 'late_penalty', 'checked_in')

# Meta rejects template variables containing newlines/tabs or 4+ spaces, and
# long values - so lists are flattened to one line and capped.
TEMPLATE_LIST_LIMIT = 700
TEXT_LIST_LIMIT = 1400


def _has_marked_attendance(attendance):
    return (
        bool(list(attendance.sessions.all()))
        or bool(attendance.check_in_photo)
        or attendance.final_status in WORKED_STATUSES
    )


def _display_name(employee):
    return (employee.full_name or employee.name or employee.email).strip()


def build_attendance_report(office, branch=None, when=None, skip_holidays=True):
    """Returns a dict describing today's attendance for the office (or one
    branch), as of `when` (default: now, local time). If everyone is on a
    holiday the dict has a 'skipped_reason' instead of names."""
    when = timezone.localtime(when) if when else timezone.localtime()
    today = when.date()

    employees = Employee.objects.filter(office=office, user__is_active=True).select_related('branch')
    if branch is not None:
        employees = employees.filter(branch=branch)
    employees = list(employees)

    scope_label = office.name if office else 'Office'
    if branch is not None:
        scope_label = f'{scope_label} - {branch.name}'

    report = {
        'date': today,
        'when': when,
        'scope_label': scope_label,
        'present': [], 'absent': [], 'on_leave': [],
        'skipped_reason': '',
    }

    if skip_holidays:
        holidays = list(Holiday.objects.filter(office=office, date=today).exclude(type='optional'))
        if holidays:
            office_wide = next((h for h in holidays if h.branch_id is None), None)
            holiday_branch_ids = {h.branch_id for h in holidays if h.branch_id is not None}
            remaining = []
            for emp in employees:
                if office_wide is None and emp.branch_id not in holiday_branch_ids:
                    remaining.append(emp)
            if not remaining and employees:
                first = office_wide or holidays[0]
                report['skipped_reason'] = f'Holiday today: {first.name}'
                return report
            employees = remaining

    attendance_by_employee = {
        a.employee_id: a
        for a in Attendance.objects.filter(employee__in=employees, date=today).prefetch_related('sessions')
    }
    on_leave_ids = set(
        LeaveRequest.objects.filter(
            employee__in=employees, status=LeaveRequest.Status.APPROVED,
            leave_type=LeaveRequest.LeaveType.FULL_DAY,
            start_date__lte=today, end_date__gte=today,
        ).values_list('employee_id', flat=True)
    )

    for emp in employees:
        attendance = attendance_by_employee.get(emp.id)
        name = _display_name(emp)
        if attendance is not None and _has_marked_attendance(attendance):
            report['present'].append(name)
        elif emp.id in on_leave_ids:
            report['on_leave'].append(name)
        else:
            report['absent'].append(name)

    for key in ('present', 'absent', 'on_leave'):
        report[key].sort(key=str.lower)
    report['total'] = len(report['present']) + len(report['absent']) + len(report['on_leave'])
    return report


def _join_names(names, limit):
    """Comma-join names, cutting off with '+N more' if the text would exceed `limit`."""
    if not names:
        return '-'
    out, used = [], 0
    for index, name in enumerate(names):
        extra = len(name) + (2 if out else 0)
        if used + extra > limit:
            out.append(f'+{len(names) - index} more')
            break
        out.append(name)
        used += extra
    return ', '.join(out)


def _flat(value):
    """One line, no runs of spaces - what a template variable is allowed to be."""
    return re.sub(r'\s+', ' ', str(value)).strip()


def _when_label(report):
    return f"{report['date']:%a, %d %b %Y} {report['when']:%I:%M %p}".replace(' 0', ' ')


def render_text(report):
    """Multi-line message for free-form (24-hour window) sending."""
    lines = [
        f"*Attendance report* - {report['scope_label']}",
        _when_label(report),
        '',
        f"Present ({len(report['present'])}/{report['total']}): {_join_names(report['present'], TEXT_LIST_LIMIT)}",
        f"Absent ({len(report['absent'])}): {_join_names(report['absent'], TEXT_LIST_LIMIT)}",
    ]
    if report['on_leave']:
        lines.append(f"On leave ({len(report['on_leave'])}): {_join_names(report['on_leave'], TEXT_LIST_LIMIT)}")
    return '\n'.join(lines)


def template_params(report):
    """The 8 body variables of the standard attendance-report template:

        Attendance report for {{1}} as of {{2}}. Present ({{3}}): {{4}}.
        Absent ({{5}}): {{6}}. On leave ({{7}}): {{8}}.
    """
    return [
        _flat(report['scope_label']),
        _flat(_when_label(report)),
        str(len(report['present'])),
        _flat(_join_names(report['present'], TEMPLATE_LIST_LIMIT)),
        str(len(report['absent'])),
        _flat(_join_names(report['absent'], TEMPLATE_LIST_LIMIT)),
        str(len(report['on_leave'])),
        _flat(_join_names(report['on_leave'], TEMPLATE_LIST_LIMIT)),
    ]


SUGGESTED_TEMPLATE_TEXT = (
    'Attendance report for {{1}} as of {{2}}. Present ({{3}}): {{4}}. '
    'Absent ({{5}}): {{6}}. On leave ({{7}}): {{8}}.'
)
