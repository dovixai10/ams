"""
Mobile API - Reports and analytics (spec section 13, 1 endpoint).
GET /reports/monthly-summary?month=YYYY-MM
"""
import calendar
from datetime import date as date_cls

from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from .mobile_response import MobileAPIView, MobileAPIException, EnvelopeResponseSerializer
from .mobile_common import duration_payload
from .models import Attendance, Holiday, LeaveRequest

DAY_NAMES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
TAG = 'Reports'


def _month_bounds(year, month):
    first = date_cls(year, month, 1)
    last = date_cls(year, month, calendar.monthrange(year, month)[1])
    return first, last


def _metrics_for_range(employee, first, last):
    records = list(Attendance.objects.filter(employee=employee, date__gte=first, date__lte=last))
    present = sum(1 for r in records if r.final_status == 'present')
    half = sum(1 for r in records if r.final_status in ('half_day', 'late_penalty'))
    absent = sum(1 for r in records if r.final_status in ('absent', 'sandwich_leave'))
    leave_days = LeaveRequest.objects.filter(
        employee=employee, status=LeaveRequest.Status.APPROVED,
        start_date__lte=last, end_date__gte=first,
    ).count()
    working_seconds = sum(int(float(r.total_work_hours or 0) * 3600) for r in records)
    holiday_count = Holiday.objects.filter(office=employee.office, branch=employee.branch, date__gte=first, date__lte=last).count()
    total_days = (last - first).days + 1

    return {
        "present": present, "half": half, "absent": absent, "leave_days": leave_days,
        "working_seconds": working_seconds, "holiday_count": holiday_count, "total_days": total_days,
        "records": records,
    }


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="Everything the reports screen needs, in one call",
    parameters=[OpenApiParameter('month', OpenApiTypes.STR, required=True, description='YYYY-MM')],
    description="All aggregates computed server-side from the canonical attendance records - a single source of truth, so this never disagrees with /attendance/summary or /attendance/calendar. `metrics.lateMarks` currently always reports 0 (see the docs' Decisions section on arrival-time lateness).",
)
class MonthlySummaryView(MobileAPIView):
    """GET /reports/monthly-summary?month=YYYY-MM"""

    def get(self, request):
        employee = request.user.employee_profile
        month_str = request.GET.get('month')
        if not month_str:
            raise MobileAPIException('VALIDATION_ERROR', 'month is required, format YYYY-MM.', 400, field='month')
        try:
            year, month = (int(p) for p in month_str.split('-'))
        except ValueError:
            raise MobileAPIException('VALIDATION_ERROR', 'month must be in YYYY-MM format.', 400, field='month')

        first, last = _month_bounds(year, month)
        today = timezone.localdate()
        m = _metrics_for_range(employee, first, min(last, today))

        prev_month_date = (first.replace(day=1) - timezone.timedelta(days=1))
        prev_first, prev_last = _month_bounds(prev_month_date.year, prev_month_date.month)
        prev_m = _metrics_for_range(employee, prev_first, prev_last)

        def percent(part, whole):
            return round(part / whole * 100) if whole else 0

        current_percent = percent(m['present'] + m['half'] * 0.5, m['total_days'])
        previous_percent = percent(prev_m['present'] + prev_m['half'] * 0.5, prev_m['total_days'])
        rating = "Excellent" if current_percent >= 90 else "Good" if current_percent >= 75 else "Needs Improvement"

        days_distribution = [
            {"status": "PRESENT", "count": m['present'], "percent": percent(m['present'], m['total_days'])},
            {"status": "HALF_DAY", "count": m['half'], "percent": percent(m['half'], m['total_days'])},
            {"status": "ABSENT", "count": m['absent'], "percent": percent(m['absent'], m['total_days'])},
            {"status": "HOLIDAY", "count": m['holiday_count'], "percent": percent(m['holiday_count'], m['total_days'])},
            {"status": "PAID_LEAVE", "count": m['leave_days'], "percent": percent(m['leave_days'], m['total_days'])},
        ]

        by_weekday = {i: {"seconds": 0, "count": 0, "present": 0} for i in range(7)}
        for r in m['records']:
            wd = r.date.weekday()
            seconds = int(float(r.total_work_hours or 0) * 3600)
            by_weekday[wd]["seconds"] += seconds
            by_weekday[wd]["count"] += 1
            if r.final_status == 'present':
                by_weekday[wd]["present"] += 1
        weekly_overview = []
        for i, name in enumerate(DAY_NAMES):
            bucket = by_weekday[i]
            rate = percent(bucket["present"], bucket["count"]) if bucket["count"] else 0
            weekly_overview.append({
                "day": name, "ratePercent": rate,
                "workingHours": duration_payload(bucket["seconds"]),
            })

        avg_seconds = int(m['working_seconds'] / len(m['records'])) if m['records'] else 0
        prev_avg_seconds = int(prev_m['working_seconds'] / len(prev_m['records'])) if prev_m['records'] else 0
        delta_seconds = avg_seconds - prev_avg_seconds
        best_day = max((b["present"] for b in by_weekday.values()), default=0)
        best_day_rate = max((percent(b["present"], b["count"]) for b in by_weekday.values() if b["count"]), default=0)

        return self.ok({
            "month": f"{year:04d}-{month:02d}",
            "metrics": {
                "totalPresentDays": m['present'], "totalAbsentDays": m['absent'],
                "leaveDays": m['leave_days'], "lateMarks": 0,  # arrival-time lateness isn't persisted per-record - see API docs
                "totalWorkingHours": duration_payload(m['working_seconds']),
            },
            "attendanceRate": {
                "percent": current_percent, "previousMonthPercent": previous_percent,
                "deltaPercent": current_percent - previous_percent, "ratingLabel": rating,
            },
            "daysDistribution": days_distribution,
            "weeklyOverview": weekly_overview,
            "insights": {
                "averageHoursPerDay": duration_payload(avg_seconds),
                "averageHoursDeltaVsPrevious": {
                    "seconds": delta_seconds,
                    "display": ("+" if delta_seconds >= 0 else "-") + duration_payload(abs(delta_seconds))["display"],
                },
                "bestDayRatePercent": best_day_rate,
                "bestDayCount": best_day,
            },
        })
