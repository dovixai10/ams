"""
Mobile API - Leave management (spec section 9, 4 endpoints).
GET /leave/balances, GET/POST /leave/requests, DELETE /leave/requests/{id}

Per your call: exposes your real, admin-configurable LeaveType list per
office/branch rather than the spec's fixed CASUAL/SICK/EARNED/PRIVILEGE/PAID
enum, since this system already supports arbitrary leave types that vary by
office. `type` in the API is a LeaveType's `code` (e.g. "CL"), not one of
those five fixed strings - see the shared API docs for how the Flutter
dropdown should be built from GET /leave/balances instead of a hardcoded list.
"""
from django.utils import timezone
from rest_framework import serializers
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample, OpenApiParameter, OpenApiTypes

from .mobile_response import MobileAPIView, MobileAPIException, EnvelopeResponseSerializer
from .mobile_common import paginate

TAG = 'Leave'


class LeaveRequestCreateSerializer(serializers.Serializer):
    type = serializers.CharField(help_text="A LeaveType `code` from GET /leave/balances, e.g. \"CL\" - not a fixed enum, see module docstring")
    startDate = serializers.DateField()
    endDate = serializers.DateField()
    reason = serializers.CharField()
from .models import LeaveType, EmployeeLeaveBalance, LeaveRequest, Holiday


def _working_days_between(office, branch, start, end):
    """Authoritative day count excluding Sundays and holidays - the business
    rule the spec explicitly calls for (client's naive count includes both)."""
    holiday_dates = set(
        Holiday.objects.filter(office=office, branch=branch, date__gte=start, date__lte=end)
        .values_list('date', flat=True)
    )
    days = 0
    d = start
    while d <= end:
        if d.weekday() != 6 and d not in holiday_dates:
            days += 1
        d += timezone.timedelta(days=1)
    return days


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="Leave balances",
    description="One entry per active leave type configured for this employee's office/branch - build the apply-leave dropdown from this list's `type`/`label`, not a hardcoded enum.",
    examples=[OpenApiExample('200 response', value={
        "financialYear": "2026-27",
        "balances": [{"type": "CL", "label": "Casual Leave", "available": 8.0, "total": 12.0}],
    }, response_only=True)],
)
class BalancesView(MobileAPIView):
    """GET /leave/balances"""

    def get(self, request):
        employee = request.user.employee_profile
        # LeaveType.branch=NULL means "office-wide"; only office-wide types
        # plus this employee's own branch's types apply to them.
        types = [
            t for t in LeaveType.objects.filter(office=employee.office, is_active=True).order_by('name')
            if t.branch_id is None or t.branch_id == employee.branch_id
        ]

        balances = []
        for t in types:
            bal = EmployeeLeaveBalance.objects.filter(employee=employee, leave_type=t).first()
            available = float(bal.balance) if bal else 0.0
            total = float(t.annual_limit) if t.annual_limit is not None else (
                float(bal.total_credited_this_year) if bal else available
            )
            balances.append({
                "type": t.code, "label": t.name,
                "available": available, "total": total,
            })

        today = timezone.localdate()
        fy_start_year = today.year if today.month >= 4 else today.year - 1
        return self.ok({
            "financialYear": f"{fy_start_year}-{str(fy_start_year + 1)[-2:]}",
            "balances": balances,
        })


@extend_schema_view(
    get=extend_schema(
        responses=EnvelopeResponseSerializer,
        tags=[TAG], summary="Request history", parameters=[
            OpenApiParameter('page', OpenApiTypes.INT), OpenApiParameter('pageSize', OpenApiTypes.INT),
        ],
        description="Newest first.",
    ),
    post=extend_schema(
        responses={201: EnvelopeResponseSerializer, 400: EnvelopeResponseSerializer, 422: EnvelopeResponseSerializer},
        tags=[TAG], summary="Apply for leave",
        description=(
            "`days` is recomputed server-side excluding Sundays and holidays (the naive "
            "client-side count including weekends is never trusted). Always created PENDING - "
            "approval happens in the web admin/HR tool, not this app."
        ),
        request=LeaveRequestCreateSerializer,
        examples=[
            OpenApiExample('Request', value={"type": "CL", "startDate": "2026-12-21", "endDate": "2026-12-22", "reason": "Family function at home town"}, request_only=True),
            OpenApiExample('201 response', value={
                "id": "lv_00007", "type": "CL", "label": "Casual Leave",
                "startDate": "2026-12-21", "endDate": "2026-12-22", "days": 2,
                "reason": "Family function at home town", "status": "PENDING",
                "appliedOn": "2026-09-14T14:17:36+05:30", "reviewedBy": None, "reviewedOn": None, "reviewComment": None,
            }, response_only=True),
            OpenApiExample('422 insufficient balance', value={
                "success": False, "data": None,
                "message": "You requested 2 day(s) but only have 0.0 available for Casual Leave.",
                "error": {"code": "INSUFFICIENT_LEAVE_BALANCE", "field": None,
                          "details": {"requested": 2, "available": 0.0}},
            }, response_only=True, status_codes=['422']),
        ],
    ),
)
class LeaveRequestsView(MobileAPIView):
    """GET/POST /leave/requests"""

    def get(self, request):
        employee = request.user.employee_profile
        qs = LeaveRequest.objects.filter(employee=employee).select_related('leave_type_ref').order_by('-created_at')
        items, pagination = paginate(list(qs), request.GET.get('page'), request.GET.get('pageSize'))
        return self.ok({"requests": [self._serialize(r) for r in items], "pagination": pagination})

    def post(self, request):
        employee = request.user.employee_profile
        type_code = (request.data.get('type') or '').strip()
        start_str = request.data.get('startDate')
        end_str = request.data.get('endDate')
        reason = (request.data.get('reason') or '').strip()

        missing = [f for f, v in [('type', type_code), ('startDate', start_str), ('endDate', end_str), ('reason', reason)] if not v]
        if missing:
            raise MobileAPIException('VALIDATION_ERROR', 'Please select dates, a leave type, and enter a reason.', 400, field=missing[0])

        from django.utils.dateparse import parse_date
        start_date, end_date = parse_date(start_str), parse_date(end_str)
        if not start_date or not end_date:
            raise MobileAPIException('VALIDATION_ERROR', 'Dates must be YYYY-MM-DD.', 400, field='startDate')
        if end_date < start_date:
            raise MobileAPIException('INVALID_DATE_RANGE', 'End date cannot be before start date.', 422, field='endDate')
        if start_date < timezone.localdate():
            raise MobileAPIException('INVALID_DATE_RANGE', 'Leave cannot be requested for a past date.', 422, field='startDate')

        leave_type = LeaveType.objects.filter(office=employee.office, code__iexact=type_code, is_active=True).first()
        if leave_type is None or (leave_type.branch_id is not None and leave_type.branch_id != employee.branch_id):
            raise MobileAPIException('VALIDATION_ERROR', f'Unknown leave type "{type_code}".', 400, field='type')

        days = _working_days_between(employee.office, employee.branch, start_date, end_date)
        if days <= 0:
            raise MobileAPIException('INVALID_DATE_RANGE', 'Selected range has no working days.', 422, field='endDate')

        overlap = LeaveRequest.objects.filter(
            employee=employee, status__in=[LeaveRequest.Status.PENDING, LeaveRequest.Status.APPROVED],
            start_date__lte=end_date, end_date__gte=start_date,
        ).exists()
        if overlap:
            raise MobileAPIException('OVERLAPPING_LEAVE', 'This range overlaps an existing pending or approved request.', 422)

        if leave_type.category == LeaveType.Category.PAID:
            bal = EmployeeLeaveBalance.objects.filter(employee=employee, leave_type=leave_type).first()
            available = float(bal.balance) if bal else 0.0
            if days > available:
                raise MobileAPIException(
                    'INSUFFICIENT_LEAVE_BALANCE',
                    f'You requested {days} day(s) but only have {available} available for {leave_type.name}.',
                    422, details={"requested": days, "available": available},
                )

        leave_request = LeaveRequest.objects.create(
            office=employee.office, branch=employee.branch, employee=employee,
            leave_type_ref=leave_type,
            leave_category=(LeaveRequest.LeaveCategory.PAID if leave_type.category == LeaveType.Category.PAID
                             else LeaveRequest.LeaveCategory.LWP),
            leave_type=LeaveRequest.LeaveType.FULL_DAY,
            start_date=start_date, end_date=end_date, reason=reason,
            status=LeaveRequest.Status.PENDING,
        )

        from .notification_utils import create_notification
        try:
            create_notification(
                employee=employee, notification_type='leave_pending',
                title='Leave request submitted',
                message=f'Your {leave_type.name} request ({start_date} to {end_date}) is pending review.',
            )
        except Exception:
            pass

        return self.ok(self._serialize(leave_request), message="Leave request submitted.", status_code=201)

    @staticmethod
    def _serialize(r):
        return {
            "id": f"lv_{r.id:05d}",
            "type": r.leave_type_ref.code if r.leave_type_ref else None,
            "label": r.leave_type_ref.name if r.leave_type_ref else r.get_leave_category_display(),
            "startDate": r.start_date.isoformat(),
            "endDate": r.end_date.isoformat(),
            "days": r.total_days,
            "reason": r.reason,
            "status": r.status.upper(),
            "appliedOn": r.created_at.isoformat(),
            "reviewedBy": r.reviewed_by.get_full_name() or r.reviewed_by.username if r.reviewed_by else None,
            "reviewedOn": r.reviewed_at.isoformat() if r.reviewed_at else None,
            "reviewComment": r.admin_comment or None,
        }


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="Cancel a pending request",
    description="Only permitted while the request is still PENDING - returns 409 otherwise. `id` is the numeric suffix of the `lv_NNNNN` id (e.g. 7 for \"lv_00007\").",
)
class CancelLeaveRequestView(MobileAPIView):
    """DELETE /leave/requests/{id} - id is the numeric suffix of the lv_NNNNN
    ids this API hands out, e.g. DELETE /leave/requests/184 for "lv_00184"."""

    def delete(self, request, id):
        employee = request.user.employee_profile
        leave_request = LeaveRequest.objects.filter(employee=employee, id=id).first()
        if leave_request is None:
            raise MobileAPIException('NOT_FOUND', 'Leave request not found.', 404)
        if leave_request.status != LeaveRequest.Status.PENDING:
            raise MobileAPIException(
                'VALIDATION_ERROR',
                'Only a pending request can be cancelled.', 409,
            )

        leave_request.status = LeaveRequest.Status.CANCELLED
        leave_request.save(update_fields=['status', 'updated_at'])
        # Nothing to restore: this app only deducts a leave balance on
        # admin approval, not on submission - a still-pending request
        # never reserved any balance in the first place.
        return self.ok(message="Leave request cancelled.")
