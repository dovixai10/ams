"""Employee Performance report: one page pulling together task throughput
(Task/TaskUpdate), hours worked (Attendance), and team/sprint context
(Team/Sprint) into a single filterable dashboard, plus a CSV export of the
same data. No new models - everything here is read-only, computed on the fly
from data the rest of the app already writes.
"""
import calendar
import csv
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Avg, Case, CharField, Count, Q, Sum, Value, When
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from web_project import TemplateLayout
from web_project.template_helpers.theme import TemplateHelper

from .integrations.attendance_report import WORKED_STATUSES
from .models import Attendance, Employee, Task, Team
from .permissions import feature_required, get_request_branch, get_request_office, tenant_queryset
from .sprint_utils import current_sprint, ensure_upcoming_sprints

view_required = user_passes_test(feature_required('reports.view'))

RANGE_CHOICES = [
    ('week', 'This Week'),
    ('month', 'This Month'),
    ('sprint', 'This Sprint'),
    ('custom', 'Custom Range'),
]
STATUS_BANDS = [  # (minimum completion %, label, badge color)
    (95, 'Excellent', 'success'),
    (80, 'Good', 'info'),
    (60, 'Average', 'warning'),
    (0, 'Needs Attention', 'danger'),
]


def _display_name(employee):
    return (employee.full_name or employee.name or employee.email).strip()


def _week_range(today):
    start = today - timedelta(days=today.weekday())  # Monday
    return start, start + timedelta(days=6)


def _month_range(today):
    start = today.replace(day=1)
    last_day = calendar.monthrange(today.year, today.month)[1]
    return start, today.replace(day=last_day)


def _previous_period(start, end):
    """An equal-length window immediately before [start, end] - for sprints
    (fixed-length, back-to-back by construction) this lands exactly on the
    previous sprint, without needing sprint-specific handling."""
    span = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    return prev_end - timedelta(days=span - 1), prev_end


def _resolve_period(request, branch):
    """(start, end, mode, label, notice) for the report's main date filter."""
    today = timezone.localdate()
    mode = request.GET.get('range', 'week')
    if mode not in dict(RANGE_CHOICES):
        mode = 'week'
    notice = ''

    if mode == 'month':
        start, end = _month_range(today)
        label = today.strftime('%B %Y')
    elif mode == 'sprint':
        if branch:
            ensure_upcoming_sprints(branch)
        sprint = current_sprint(branch) if branch else None
        if sprint is None:
            start, end = _week_range(today)
            mode = 'week'
            notice = 'No active sprint for this branch (or none selected) - showing this week instead.'
            label = f"{start:%b %d} - {end:%b %d, %Y}"
        else:
            start, end = sprint.start_date, sprint.end_date
            label = f"{sprint.name} ({start:%b %d} - {end:%b %d, %Y})"
    elif mode == 'custom':
        start = _parse_date(request.GET.get('start'))
        end = _parse_date(request.GET.get('end'))
        if not start or not end or start > end:
            start, end = _week_range(today)
            mode = 'week'
            notice = 'Enter a valid start and end date - showing this week instead.'
            label = f"{start:%b %d} - {end:%b %d, %Y}"
        else:
            label = f"{start:%b %d, %Y} - {end:%b %d, %Y}"
    else:
        mode = 'week'
        start, end = _week_range(today)
        label = f"{start:%b %d} - {end:%b %d, %Y}"

    return start, end, mode, label, notice


def _parse_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _delta(current, previous):
    """(direction, percent) change vs. the previous period - '' direction if
    there's nothing to compare against (avoids a misleading '+100%' the very
    first time a metric has any data)."""
    if not previous:
        return '', None
    change = (current - previous) / previous * 100
    return ('up' if change >= 0 else 'down'), abs(round(change))


def _scope_employees(request, branch, team, employee_id):
    qs = tenant_queryset(request, Employee.objects.filter(user__is_active=True)).select_related('designation')
    if team is not None:
        qs = qs.filter(teams=team)
    if employee_id:
        qs = qs.filter(pk=employee_id)
    return list(qs.order_by('full_name', 'name'))


def _attendance_stats(request, emp_ids, start, end):
    """(avg_hours_per_day, on_time_pct, active_employee_count, hours_by_employee)."""
    if not emp_ids:
        return 0, 0, 0, {}
    qs = tenant_queryset(request, Attendance.objects.filter(employee_id__in=emp_ids, date__range=(start, end)))
    avg_hours = qs.aggregate(a=Avg('total_work_hours'))['a'] or 0
    present = qs.filter(final_status__in=WORKED_STATUSES)
    present_count = present.count()
    on_time_pct = round(present.filter(is_late=False).count() * 100 / present_count) if present_count else 0
    active_count = present.values('employee_id').distinct().count()
    hours_by_employee = dict(qs.values('employee_id').annotate(total=Sum('total_work_hours')).values_list('employee_id', 'total'))
    return float(avg_hours), on_time_pct, active_count, hours_by_employee


def _completed_counts(request, emp_ids, start, end):
    """(count_by_employee, hours_by_employee, total_count) for tasks each
    employee completed within the period. 'hours' sums the task's own Hours
    field (Task.estimated_hours) for those same completed tasks - not
    attendance - so the Tasks and Hours columns always describe the same
    set of work."""
    if not emp_ids:
        return {}, {}, 0
    qs = tenant_queryset(request, Task.objects.filter(
        assigned_to_id__in=emp_ids, status=Task.Status.COMPLETED, status_updated_at__date__range=(start, end),
    ))
    rows = list(qs.values('assigned_to_id').annotate(n=Count('id'), hrs=Sum('estimated_hours')))
    count_by_employee = {row['assigned_to_id']: row['n'] for row in rows}
    hours_by_employee = {row['assigned_to_id']: float(row['hrs'] or 0) for row in rows}
    return count_by_employee, hours_by_employee, sum(count_by_employee.values())


def _relevant_tasks(request, emp_ids, start, end):
    """Tasks 'relevant' to [start, end]: completed within it, or still open
    and already assigned by its end. Backs both the completion-rate % and
    the 'Tasks & Working Hours' list, so they always agree with each other
    and with the page's date filter - picking Oct 1-2 only shows tasks that
    were actually live in that window, not every task ever created."""
    if not emp_ids:
        return Task.objects.none()
    return tenant_queryset(request, Task.objects.filter(assigned_to_id__in=emp_ids, created_at__date__lte=end)).filter(
        Q(status=Task.Status.COMPLETED, status_updated_at__date__range=(start, end)) | ~Q(status=Task.Status.COMPLETED)
    )


def _completion_rates(request, emp_ids, start, end, completed_by_employee):
    """Per-employee completion % for the period: of the tasks relevant to
    them this period, how many did they finish?"""
    if not emp_ids:
        return {}
    relevant = _relevant_tasks(request, emp_ids, start, end)
    denominators = dict(relevant.values('assigned_to_id').annotate(n=Count('id')).values_list('assigned_to_id', 'n'))
    rates = {}
    for emp_id, total in denominators.items():
        completed = completed_by_employee.get(emp_id, 0)
        rates[emp_id] = round(completed * 100 / total) if total else 0
    return rates


def _status_band(rate, has_data):
    if not has_data:
        return 'No Data', 'secondary'
    for minimum, label, color in STATUS_BANDS:
        if rate >= minimum:
            return label, color
    return STATUS_BANDS[-1][1], STATUS_BANDS[-1][2]


def _task_donut(request, emp_ids):
    """Current snapshot (not period-bound - a backlog's health is 'right
    now', not a slice of the calendar) of every task assigned to the scoped
    employees, bucketed the same way Task.is_overdue defines overdue."""
    empty = {'completed': 0, 'overdue': 0, 'in_progress': 0, 'blocked': 0, 'pending': 0}
    if not emp_ids:
        return empty, 0
    today = timezone.localdate()
    bucketed = (
        tenant_queryset(request, Task.objects.filter(assigned_to_id__in=emp_ids))
        .annotate(bucket=Case(
            When(status=Task.Status.COMPLETED, then=Value('completed')),
            When(due_date__lt=today, then=Value('overdue')),
            When(status=Task.Status.IN_PROGRESS, then=Value('in_progress')),
            When(status=Task.Status.BLOCKED, then=Value('blocked')),
            default=Value('pending'), output_field=CharField(),
        ))
        .values('bucket').annotate(n=Count('id'))
    )
    counts = dict(empty)
    for row in bucketed:
        counts[row['bucket']] = row['n']
    return counts, sum(counts.values())


def _chart_buckets_for_period(start, end):
    """Split [start, end] into a sensible number of points for the line
    chart - daily up to 2 weeks, weekly up to ~10 weeks, monthly beyond that
    - so the chart automatically fits whichever period the page's own date
    filter is set to, instead of needing a selector of its own."""
    span_days = (end - start).days + 1
    if span_days <= 14:
        return [((start + timedelta(days=i)).strftime('%a %d'), start + timedelta(days=i), start + timedelta(days=i)) for i in range(span_days)]
    if span_days <= 70:
        buckets, cursor = [], start
        while cursor <= end:
            bucket_end = min(cursor + timedelta(days=6), end)
            buckets.append((f'{cursor:%d %b}', cursor, bucket_end))
            cursor = bucket_end + timedelta(days=1)
        return buckets
    buckets, cursor = [], start.replace(day=1)
    while cursor <= end:
        last_day = calendar.monthrange(cursor.year, cursor.month)[1]
        bucket_end = min(date(cursor.year, cursor.month, last_day), end)
        bucket_start = max(cursor, start)
        buckets.append((cursor.strftime('%b %Y'), bucket_start, bucket_end))
        cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
    return buckets[:24]  # safety cap for an unusually long custom range


def _chart_series(request, emp_ids, start, end):
    labels, completed, hours = [], [], []
    for label, b_start, b_end in _chart_buckets_for_period(start, end):
        labels.append(label)
        if emp_ids:
            completed.append(tenant_queryset(request, Task.objects.filter(
                assigned_to_id__in=emp_ids, status=Task.Status.COMPLETED, status_updated_at__date__range=(b_start, b_end),
            )).count())
            avg = tenant_queryset(request, Attendance.objects.filter(
                employee_id__in=emp_ids, date__range=(b_start, b_end),
            )).aggregate(a=Avg('total_work_hours'))['a']
            hours.append(round(float(avg or 0), 1))
        else:
            completed.append(0)
            hours.append(0)
    return {'labels': labels, 'completed': completed, 'hours': hours}


def _task_list(request, emp_ids, start, end, limit=60):
    """Tasks relevant to [start, end] (see _relevant_tasks) for the 'Tasks &
    Working Hours' panel's All/Completed/Overdue tabs - same scope as the
    completion-rate %, so the list actually respects the date filter."""
    if not emp_ids:
        return []
    rows = (
        _relevant_tasks(request, emp_ids, start, end)
        .select_related('project', 'assigned_to')
        .order_by('-status_updated_at', '-created_at')[:limit]
    )
    return [{
        'id': t.id, 'title': t.title, 'project': t.project.name if t.project_id else '-',
        'assignee': _display_name(t.assigned_to) if t.assigned_to_id else 'Unassigned',
        'hours': t.estimated_hours_display or '-', 'status': t.status, 'status_display': t.get_status_display(),
        'status_color': t.status_badge, 'overdue': t.is_overdue,
    } for t in rows]


def _build_report(request):
    """Everything both the page and the CSV export need, in one place so
    they can never drift apart on what a filter means."""
    office = get_request_office(request)
    if office is None:
        return None
    branch = get_request_branch(request)

    teams = list(tenant_queryset(request, Team.objects.all()).order_by('name'))
    team_id = request.GET.get('team')
    team = next((t for t in teams if str(t.id) == team_id), None) if team_id else None

    scoped_for_dropdown = _scope_employees(request, branch, team, None)
    employee_id = request.GET.get('employee')
    employee_filter = next((e for e in scoped_for_dropdown if str(e.id) == employee_id), None) if employee_id else None

    start, end, mode, period_label, notice = _resolve_period(request, branch)
    prev_start, prev_end = _previous_period(start, end)

    employees = scoped_for_dropdown if employee_filter is None else [employee_filter]
    emp_ids = [e.id for e in employees]

    avg_hours, on_time_pct, active_count, _attendance_hours_by_employee = _attendance_stats(request, emp_ids, start, end)
    prev_avg_hours, prev_on_time_pct, prev_active_count, _ = _attendance_stats(request, emp_ids, prev_start, prev_end)

    completed_by_employee, task_hours_by_employee, tasks_completed = _completed_counts(request, emp_ids, start, end)
    _, _, prev_tasks_completed = _completed_counts(request, emp_ids, prev_start, prev_end)
    rates_by_employee = _completion_rates(request, emp_ids, start, end, completed_by_employee)

    prev_completed_for_rate, _, _ = _completed_counts(request, emp_ids, prev_start, prev_end)
    prev_rates = _completion_rates(request, emp_ids, prev_start, prev_end, prev_completed_for_rate)
    avg_rate = round(sum(rates_by_employee.values()) / len(rates_by_employee)) if rates_by_employee else 0
    prev_avg_rate = round(sum(prev_rates.values()) / len(prev_rates)) if prev_rates else 0

    total_employees = len(employees)

    table = []
    for emp in employees:
        rate = rates_by_employee.get(emp.id, 0)
        has_data = emp.id in rates_by_employee  # they had at least one task relevant to this period
        label, color = _status_band(rate, has_data)
        table.append({
            'employee': emp,
            'name': _display_name(emp),
            'role': emp.designation.name if emp.designation_id else '-',
            'tasks': completed_by_employee.get(emp.id, 0),
            'hours': round(task_hours_by_employee.get(emp.id, 0), 1),
            'rate': rate,
            'status_label': label,
            'status_color': color,
        })
    table.sort(key=lambda r: (r['rate'], r['tasks'], r['hours']), reverse=True)
    leaderboard = table[:5]

    donut_counts, donut_total = _task_donut(request, emp_ids)
    donut = {
        key: {'count': count, 'pct': round(count * 100 / donut_total) if donut_total else 0}
        for key, count in donut_counts.items()
    }

    chart = _chart_series(request, emp_ids, start, end)
    task_list = _task_list(request, emp_ids, start, end)

    best = leaderboard[0] if leaderboard and leaderboard[0]['tasks'] else None
    most_hours = max(table, key=lambda r: r['hours'], default=None)
    overdue_count = donut_counts.get('overdue', 0)

    tiles = [
        {'key': 'total', 'icon': 'bx-group', 'label': 'Total Employees', 'value': total_employees, 'direction': '', 'delta': None},
        {'key': 'active', 'icon': 'bx-user-check', 'label': 'Active Employees', 'value': active_count,
         'direction': _delta(active_count, prev_active_count)[0], 'delta': _delta(active_count, prev_active_count)[1]},
        {'key': 'completed', 'icon': 'bx-check-square', 'label': 'Tasks Completed', 'value': tasks_completed,
         'direction': _delta(tasks_completed, prev_tasks_completed)[0], 'delta': _delta(tasks_completed, prev_tasks_completed)[1]},
        {'key': 'hours', 'icon': 'bx-time-five', 'label': 'Avg Working Hours', 'value': f'{avg_hours:.1f} hrs',
         'direction': _delta(avg_hours, prev_avg_hours)[0], 'delta': _delta(avg_hours, prev_avg_hours)[1]},
    ]

    insights = []
    if best:
        insights.append({'icon': 'bx-crown', 'title': f"{best['name']} is the top performer this period",
                          'body': f"Completed {best['tasks']} task{'s' if best['tasks'] != 1 else ''} ({best['hours']}h of task work)."})
    rate_dir, rate_delta = _delta(avg_rate, prev_avg_rate)
    if rate_delta is not None:
        insights.append({'icon': 'bx-trending-up' if rate_dir == 'up' else 'bx-trending-down',
                          'title': f"Completion rate {'increased' if rate_dir == 'up' else 'decreased'} by {rate_delta}%",
                          'body': f"Compared to the previous period ({prev_avg_rate}% -> {avg_rate}%)."})
    if most_hours and most_hours['hours']:
        insights.append({'icon': 'bx-bar-chart-alt-2', 'title': 'Most task hours logged',
                          'body': f"{most_hours['name']} logged {most_hours['hours']}h of completed task work this period."})
    insights.append({'icon': 'bx-error-circle' if overdue_count else 'bx-check-circle',
                      'title': f"{overdue_count} task{'s' if overdue_count != 1 else ''} overdue" if overdue_count else 'No overdue tasks',
                      'body': 'Focus on the pending work below.' if overdue_count else 'Everything is on track.'})
    ontime_dir, ontime_delta = _delta(on_time_pct, prev_on_time_pct)
    insights.append({'icon': 'bx-calendar-check', 'title': f'Team attendance is {on_time_pct}%',
                      'body': (f"{'Improved' if ontime_dir == 'up' else 'Dropped'} by {ontime_delta}% from the previous period."
                               if ontime_delta is not None else 'No data for the previous period to compare.')})

    return {
        'office': office, 'branch': branch, 'teams': teams, 'team': team,
        'employees_for_filter': scoped_for_dropdown, 'employee_filter': employee_filter,
        'mode': mode, 'period_label': period_label, 'notice': notice,
        'start': start, 'end': end, 'custom_start': request.GET.get('start', ''), 'custom_end': request.GET.get('end', ''),
        'tiles': tiles, 'table': table, 'leaderboard': leaderboard,
        'donut': donut, 'donut_total': donut_total, 'chart': chart, 'insights': insights, 'task_list': task_list,
    }


@login_required
@view_required
def employee_performance_report(request):
    data = _build_report(request)
    if data is None:
        messages.error(request, 'Your account is not linked to an approved office.')
        return redirect('employees:employee_dashboard')

    if data['notice']:
        messages.info(request, data['notice'])

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'range_choices': RANGE_CHOICES,
        **data,
    })
    return render(request, 'employees/reports/employee_performance.html', context)


@login_required
@view_required
def employee_performance_export(request):
    data = _build_report(request)
    if data is None:
        messages.error(request, 'Your account is not linked to an approved office.')
        return redirect('employees:employee_dashboard')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="employee_performance_{data["start"]}_{data["end"]}.csv"'
    writer = csv.writer(response)
    writer.writerow(['Period', data['period_label']])
    writer.writerow([])
    writer.writerow(['Employee', 'Role', 'Tasks Completed', 'Hours Worked', 'Completion %', 'Status'])
    for row in data['table']:
        writer.writerow([row['name'], row['role'], row['tasks'], row['hours'], row['rate'], row['status_label']])
    return response
