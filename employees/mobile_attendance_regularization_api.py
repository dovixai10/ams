"""
Mobile API - Attendance regularization (beyond the original spec, mirrors
the web app's "forgot to check in/out" request-and-approve workflow, the
same way Face Update Requests mirror it for face re-registration).

GET/POST /attendance/regularization-requests,
DELETE /attendance/regularization-requests/{id}

Approval only happens in the web admin/HR tool (AttendanceRegularizationRequest.approve()),
not this app - once approved it writes the real Attendance record through the
same status-derivation path a live check-out uses, so salary/attendance
reports treat it as a genuine attendance mark, not a special case.
"""
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample, OpenApiParameter, OpenApiTypes

from .mobile_response import MobileAPIView, MobileAPIException, EnvelopeResponseSerializer
from .mobile_common import paginate
from .models import AttendanceRegularizationRequest

TAG = 'Attendance'


class RegularizationRequestCreateSerializer(serializers.Serializer):
    date = serializers.DateField()
    checkInTime = serializers.DateTimeField(required=False, allow_null=True, help_text="ISO 8601 - provide at least one of checkInTime/checkOutTime")
    checkOutTime = serializers.DateTimeField(required=False, allow_null=True)
    reason = serializers.CharField(required=False, allow_blank=True, help_text="Optional")


@extend_schema_view(
    get=extend_schema(
        responses=EnvelopeResponseSerializer,
        tags=[TAG], summary="Attendance regularization request history", parameters=[
            OpenApiParameter('page', OpenApiTypes.INT), OpenApiParameter('pageSize', OpenApiTypes.INT),
        ],
        description="Newest first. Includes pending, approved, rejected and cancelled requests this employee has submitted.",
    ),
    post=extend_schema(
        responses={201: EnvelopeResponseSerializer, 400: EnvelopeResponseSerializer, 422: EnvelopeResponseSerializer},
        tags=[TAG], summary="Request a missed check-in/check-out be marked",
        description=(
            "For a day the employee forgot to check in or out. At least one of checkInTime/"
            "checkOutTime is required; reason is optional. Always created PENDING - approval "
            "happens in the web admin/HR tool, not this app. On approval it writes the real "
            "Attendance record (same status-derivation path a live check-out uses), so it "
            "shows up in attendance history/summary and salary calculations exactly like a "
            "normal attendance mark."
        ),
        request=RegularizationRequestCreateSerializer,
        examples=[
            OpenApiExample('Request', value={
                "date": "2026-09-15", "checkInTime": "2026-09-15T09:30:00+05:30",
                "checkOutTime": "2026-09-15T18:15:00+05:30", "reason": "Forgot to mark attendance, was in a client meeting",
            }, request_only=True),
            OpenApiExample('201 response', value={
                "id": "reg_00012", "date": "2026-09-15",
                "checkInTime": "2026-09-15T09:30:00+05:30", "checkOutTime": "2026-09-15T18:15:00+05:30",
                "reason": "Forgot to mark attendance, was in a client meeting", "status": "PENDING",
                "appliedOn": "2026-09-18T10:05:12+05:30", "reviewedBy": None, "reviewedOn": None, "reviewComment": None,
            }, response_only=True),
        ],
    ),
)
class RegularizationRequestsView(MobileAPIView):
    """GET/POST /attendance/regularization-requests"""

    def get(self, request):
        employee = request.user.employee_profile
        qs = AttendanceRegularizationRequest.objects.filter(employee=employee).order_by('-created_at')
        items, pagination = paginate(list(qs), request.GET.get('page'), request.GET.get('pageSize'))
        return self.ok({"requests": [self._serialize(r) for r in items], "pagination": pagination})

    def post(self, request):
        employee = request.user.employee_profile
        date_str = request.data.get('date')
        check_in_str = request.data.get('checkInTime')
        check_out_str = request.data.get('checkOutTime')
        reason = (request.data.get('reason') or '').strip()

        if not date_str:
            raise MobileAPIException('VALIDATION_ERROR', 'date is required.', 400, field='date')
        if not check_in_str and not check_out_str:
            raise MobileAPIException('VALIDATION_ERROR', 'Provide at least checkInTime or checkOutTime.', 400, field='checkInTime')

        from django.utils.dateparse import parse_date
        req_date = parse_date(date_str)
        if not req_date:
            raise MobileAPIException('VALIDATION_ERROR', 'date must be YYYY-MM-DD.', 400, field='date')
        if req_date > timezone.localdate():
            raise MobileAPIException('INVALID_DATE_RANGE', 'You cannot request attendance for a future date.', 422, field='date')

        check_in = parse_datetime(check_in_str) if check_in_str else None
        check_out = parse_datetime(check_out_str) if check_out_str else None
        if check_in_str and not check_in:
            raise MobileAPIException('VALIDATION_ERROR', 'checkInTime must be ISO 8601.', 400, field='checkInTime')
        if check_out_str and not check_out:
            raise MobileAPIException('VALIDATION_ERROR', 'checkOutTime must be ISO 8601.', 400, field='checkOutTime')
        if check_in and check_out and check_out <= check_in:
            raise MobileAPIException('INVALID_DATE_RANGE', 'checkOutTime must be after checkInTime.', 422, field='checkOutTime')

        reg_request = AttendanceRegularizationRequest.objects.create(
            office=employee.office, branch=employee.branch, employee=employee,
            date=req_date, requested_check_in=check_in, requested_check_out=check_out,
            reason=reason, status=AttendanceRegularizationRequest.Status.PENDING,
        )

        from .notification_utils import create_notification
        try:
            create_notification(
                employee=employee, notification_type='attendance_regularization_pending',
                title='Attendance regularization submitted',
                message=f'Your request for {req_date} is pending review.',
            )
        except Exception:
            pass

        return self.ok(self._serialize(reg_request), message="Attendance regularization request submitted.", status_code=201)

    @staticmethod
    def _serialize(r):
        return {
            "id": f"reg_{r.id:05d}",
            "date": r.date.isoformat(),
            "checkInTime": r.requested_check_in.isoformat() if r.requested_check_in else None,
            "checkOutTime": r.requested_check_out.isoformat() if r.requested_check_out else None,
            "reason": r.reason or None,
            "status": r.status.upper(),
            "appliedOn": r.created_at.isoformat(),
            "reviewedBy": (r.reviewed_by.get_full_name() or r.reviewed_by.username) if r.reviewed_by else None,
            "reviewedOn": r.reviewed_at.isoformat() if r.reviewed_at else None,
            "reviewComment": r.admin_comment or None,
        }


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="Cancel a pending regularization request",
    description="Only permitted while the request is still PENDING - returns 409 otherwise. `id` is the numeric suffix of the `reg_NNNNN` id (e.g. 12 for \"reg_00012\").",
)
class CancelRegularizationRequestView(MobileAPIView):
    """DELETE /attendance/regularization-requests/{id}"""

    def delete(self, request, id):
        employee = request.user.employee_profile
        reg_request = AttendanceRegularizationRequest.objects.filter(employee=employee, id=id).first()
        if reg_request is None:
            raise MobileAPIException('NOT_FOUND', 'Regularization request not found.', 404)
        if reg_request.status != AttendanceRegularizationRequest.Status.PENDING:
            raise MobileAPIException('VALIDATION_ERROR', 'Only a pending request can be cancelled.', 409)

        reg_request.status = AttendanceRegularizationRequest.Status.CANCELLED
        reg_request.save(update_fields=['status', 'updated_at'])
        return self.ok(message="Regularization request cancelled.")
