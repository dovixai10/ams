"""
Mobile API - Employee profile (spec section 5, 4 endpoints).
GET/PATCH /employees/me/profile, POST /employees/me/avatar, GET /employees/me
"""
from django.utils import timezone
from rest_framework import serializers
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample

from .mobile_response import MobileAPIView, MobileAPIException, EnvelopeResponseSerializer
from .mobile_common import employee_code
from .models import Attendance

TAG = 'Employee Profile'


class ProfilePatchRequestSerializer(serializers.Serializer):
    personalEmail = serializers.EmailField(required=False, help_text="Self-editable - unlike the work email")
    phoneNumber = serializers.CharField(required=False, help_text="E.164 or Indian 10-digit, optional +91")


class AvatarUploadRequestSerializer(serializers.Serializer):
    file = serializers.FileField(help_text="JPEG or PNG, 5 MB cap")


def _work_location(employee):
    office = employee.office
    branch = employee.branch
    if office and branch:
        return f"{office.name} {branch.name}"
    return office.name if office else None


def _office_location(employee):
    branch = employee.branch
    if branch and (branch.city or branch.state):
        parts = [p for p in [branch.city, branch.state] if p]
        return ", ".join(parts + ["India"]) if parts else None
    if employee.office and employee.office.address:
        return employee.office.address
    return None


def _online_status(employee):
    today_attendance = Attendance.objects.filter(employee=employee, date=timezone.localdate()).first()
    if today_attendance and today_attendance.check_in_time and not today_attendance.check_out_time:
        return "ONLINE"
    return "OFFLINE"


def _profile_payload(employee):
    manager = employee.reporting_manager
    return {
        "employeeId": employee_code(employee),
        "name": employee.full_name or employee.name,
        "avatarUrl": employee.profile_picture.url if employee.profile_picture else None,
        "department": employee.department or None,
        "designation": employee.designation or None,
        "workEmail": employee.email,
        "personalEmail": employee.personal_email or None,
        "phoneNumber": employee.contact or None,
        "officeLocation": _office_location(employee),
        "workLocation": _work_location(employee),
        "joiningDate": employee.joining_date.isoformat() if employee.joining_date else None,
        "employeeType": employee.employee_type,
        "reportingManager": (
            {"employeeId": employee_code(manager), "name": manager.full_name or manager.name}
            if manager else None
        ),
        "onlineStatus": _online_status(employee),
        "faceIdRegistered": bool(employee.has_registered_face),
    }


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="Dashboard header summary",
    description="Lightweight subset (5 fields) used on every app launch, kept separate from the full profile so cold start stays fast.",
)
class MeSummaryView(MobileAPIView):
    """GET /employees/me - lightweight dashboard header summary."""

    def get(self, request):
        employee = request.user.employee_profile
        return self.ok({
            "employeeId": employee_code(employee),
            "name": employee.full_name or employee.name,
            "avatarUrl": employee.profile_picture.url if employee.profile_picture else None,
            "designation": employee.designation or None,
            "officeLocation": _office_location(employee),
        })


@extend_schema_view(
    get=extend_schema(
        responses=EnvelopeResponseSerializer,
        tags=[TAG], summary="Get full profile",
        description="Every field the profile screen renders - personal, employment, and HR-managed details.",
        examples=[OpenApiExample('200 response', value={
            "employeeId": "KI00014", "name": "Kamal", "avatarUrl": None,
            "department": None, "designation": None, "workEmail": "kamal@dovixai.com",
            "personalEmail": None, "phoneNumber": "9998887766",
            "officeLocation": "Jaipur, Rajasthan, India", "workLocation": "Dovix AI Head Office",
            "joiningDate": "2026-07-07", "employeeType": "FULL_TIME", "reportingManager": None,
            "onlineStatus": "OFFLINE", "faceIdRegistered": True,
        }, response_only=True)],
    ),
    patch=extend_schema(
        responses=EnvelopeResponseSerializer,
        tags=[TAG], summary="Edit self-service fields",
        description="Only `personalEmail` and `phoneNumber` are editable here - anything else (name, department, designation, manager, joining date, employee type) is HR-managed and returns 403 FORBIDDEN.",
        request=ProfilePatchRequestSerializer,
    ),
)
class ProfileView(MobileAPIView):
    """GET/PATCH /employees/me/profile"""

    EDITABLE_FIELDS = {'personalEmail': 'personal_email', 'phoneNumber': 'contact'}

    def get(self, request):
        return self.ok(_profile_payload(request.user.employee_profile))

    def patch(self, request):
        employee = request.user.employee_profile

        # Reject any attempt to touch an HR-managed field, per spec.
        blocked = set(request.data.keys()) - set(self.EDITABLE_FIELDS.keys())
        if blocked:
            raise MobileAPIException(
                'FORBIDDEN',
                f"These fields are HR-managed and cannot be edited here: {', '.join(sorted(blocked))}",
                403,
            )

        if 'personalEmail' in request.data:
            value = (request.data.get('personalEmail') or '').strip()
            from django.core.validators import validate_email
            from django.core.exceptions import ValidationError as DjangoValidationError
            if value:
                try:
                    validate_email(value)
                except DjangoValidationError:
                    raise MobileAPIException('VALIDATION_ERROR', 'Enter a valid email address.', 400, field='personalEmail')
            employee.personal_email = value

        if 'phoneNumber' in request.data:
            import re
            value = (request.data.get('phoneNumber') or '').strip()
            if value and not re.match(r'^(\+91)?[6-9]\d{9}$', value.replace(' ', '')):
                raise MobileAPIException(
                    'VALIDATION_ERROR',
                    'Enter a valid E.164 or Indian 10-digit number (optionally prefixed +91).',
                    400, field='phoneNumber',
                )
            employee.contact = value

        employee.save(update_fields=[self.EDITABLE_FIELDS[k] for k in request.data.keys() if k in self.EDITABLE_FIELDS])
        return self.ok(_profile_payload(employee), message="Profile updated successfully.")


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="Upload profile photo",
    description="multipart/form-data, single `file` part. Server generates a square thumbnail.",
    request=AvatarUploadRequestSerializer,
)
class AvatarUploadView(MobileAPIView):
    """POST /employees/me/avatar"""

    def post(self, request):
        file_obj = request.FILES.get('file')
        if not file_obj:
            raise MobileAPIException('VALIDATION_ERROR', 'file is required.', 400, field='file')
        if file_obj.content_type not in ('image/jpeg', 'image/png'):
            raise MobileAPIException('UNSUPPORTED_FILE_TYPE', 'Avatar must be JPEG or PNG.', 415)
        if file_obj.size > 5 * 1024 * 1024:
            raise MobileAPIException('FILE_TOO_LARGE', 'Avatar must be 5 MB or smaller.', 413)

        employee = request.user.employee_profile
        employee.profile_picture.save(file_obj.name, file_obj, save=True)
        return self.ok(
            {"avatarUrl": employee.profile_picture.url},
            message="Avatar updated successfully.",
            status_code=201,
        )
