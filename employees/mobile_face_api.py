"""
Mobile API - Face ID registration (spec section 6, 3 endpoints) plus Face
Update Requests (beyond the original spec - added to mirror the web app's
admin-gated re-registration workflow on mobile too).
GET/POST/DELETE /employees/me/face-id
GET/POST /face-update-requests

Reuses the same face_recognition-backed encoding/storage the existing web
face-registration flow uses (employees/views.py's register_face view,
employees/face_utils.py) rather than a second implementation.
"""
import json
from io import BytesIO

from django.core.files.base import ContentFile
from django.utils import timezone
from rest_framework import serializers
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample, OpenApiParameter, OpenApiTypes

from .mobile_response import MobileAPIView, MobileAPIException, EnvelopeResponseSerializer
from .mobile_common import paginate
from .face_utils import is_encoding_unique
from .models import FaceUpdateRequest

TAG = 'Face ID'
UPDATE_REQUEST_TAG = 'Face Update Requests'


class FaceUpdateRequestCreateSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, help_text="Optional - why you need to re-register (e.g. 'grew a beard', 'glasses changed').")


def _serialize_update_request(r):
    return {
        "id": f"fur_{r.id:05d}",
        "status": r.status.upper(),
        "reason": r.reason or None,
        "adminComment": r.admin_comment or None,
        "requestedAt": r.requested_at.isoformat(),
        "reviewedAt": r.reviewed_at.isoformat() if r.reviewed_at else None,
        "reviewedBy": (r.reviewed_by.get_full_name() or r.reviewed_by.username) if r.reviewed_by else None,
        "completedAt": r.completed_at.isoformat() if r.completed_at else None,
    }


class FaceEnrollRequestSerializer(serializers.Serializer):
    photo = serializers.ImageField(help_text="Front-camera selfie, JPEG, 5 MB cap")
    capturedAt = serializers.DateTimeField(required=False, help_text="Device capture time - audit only, never trusted for business logic")


def _detect_faces(image_bytes):
    """Returns (face_locations, image_array) using the same HOG detector
    and upsample-retry the kiosk check-in flow already uses (views.py)."""
    import numpy as np
    from PIL import Image
    import face_recognition

    image = Image.open(BytesIO(image_bytes))
    if image.mode != 'RGB':
        image = image.convert('RGB')
    image_array = np.array(image)

    face_locations = face_recognition.face_locations(image_array, model='hog')
    if not face_locations:
        face_locations = face_recognition.face_locations(image_array, number_of_times_to_upsample=2, model='hog')
    return face_locations, image_array


@extend_schema_view(
    get=extend_schema(
        responses=EnvelopeResponseSerializer, tags=[TAG], summary="Enrolment status",
        description="Drives the Face ID status card and gates the check-in button.",
        examples=[
            OpenApiExample('200 response - registered', value={
                "faceIdRegistered": True, "registeredAt": "2026-09-14T09:12:04+05:30",
                "referenceImageUrl": "/media/profile_pics/kamal.jpg",
            }, response_only=True),
            OpenApiExample('200 response - not yet registered', value={
                "faceIdRegistered": False, "registeredAt": None, "referenceImageUrl": None,
            }, response_only=True),
        ],
    ),
    post=extend_schema(
        responses={
            201: EnvelopeResponseSerializer, 409: EnvelopeResponseSerializer, 422: EnvelopeResponseSerializer,
        },
        tags=[TAG], summary="Enrol or re-enrol",
        description=(
            "First-time enrolment is always allowed. Re-enrolment (a face already on file) "
            "requires an admin-approved Face Update Request first - see POST "
            "/face-update-requests - and returns 409 otherwise. Exactly one active reference "
            "per employee; re-enrolment replaces it but keeps the prior version in an audit log "
            "(actor + timestamp), and fulfils (marks COMPLETED) the approved request that "
            "allowed it. Rejects NO_FACE_DETECTED / MULTIPLE_FACES, and rejects a face that "
            "already matches a different employee."
        ),
        request=FaceEnrollRequestSerializer,
        examples=[
            OpenApiExample('201 response', value={
                "faceIdRegistered": True, "registeredAt": "2026-09-14T09:12:04+05:30",
                "referenceImageUrl": "/media/profile_pics/kamal.jpg",
                "quality": {"score": None, "acceptable": True},
            }, response_only=True),
            OpenApiExample('409 re-enrolment needs approval', value={
                "success": False, "data": None,
                "message": "Re-registering your face requires admin approval. Please submit a face update request first.",
                "error": {"code": "VALIDATION_ERROR", "field": None, "details": None},
            }, response_only=True, status_codes=['409']),
            OpenApiExample('409 request still pending', value={
                "success": False, "data": None,
                "message": "Your face update request is still pending approval.",
                "error": {"code": "VALIDATION_ERROR", "field": None, "details": None},
            }, response_only=True, status_codes=['409']),
            OpenApiExample('422 no face detected', value={
                "success": False, "data": None,
                "message": "No face was detected in the photo. Please retake it.",
                "error": {"code": "NO_FACE_DETECTED", "field": None, "details": None},
            }, response_only=True, status_codes=['422']),
            OpenApiExample('422 multiple faces', value={
                "success": False, "data": None,
                "message": "More than one face was detected in the photo.",
                "error": {"code": "MULTIPLE_FACES", "field": None, "details": None},
            }, response_only=True, status_codes=['422']),
            OpenApiExample('422 already registered to someone else', value={
                "success": False, "data": None,
                "message": 'This face appears to already be registered to another employee ("Lokendra Singh").',
                "error": {"code": "VALIDATION_ERROR", "field": "photo", "details": None},
            }, response_only=True, status_codes=['422']),
        ],
    ),
    delete=extend_schema(
        responses=EnvelopeResponseSerializer, tags=[TAG], summary="Clear enrolment",
        description="Audit-logged. Consider restricting this to HR rather than the employee themself.",
        examples=[OpenApiExample('200 response', value={
            "success": True, "data": None, "message": "Face ID enrolment cleared.", "error": None,
        }, response_only=True)],
    ),
)
class FaceIdView(MobileAPIView):
    """GET/POST/DELETE /employees/me/face-id"""

    def get(self, request):
        employee = request.user.employee_profile
        return self.ok({
            "faceIdRegistered": bool(employee.has_registered_face),
            "registeredAt": employee.face_registered_at.isoformat() if employee.face_registered_at else None,
            "referenceImageUrl": employee.profile_picture.url if employee.profile_picture else None,
        })

    def post(self, request):
        employee = request.user.employee_profile

        # Same gate the web app enforces: first-time registration is
        # always allowed, but once a face is on file, re-registering
        # requires an admin-approved Face Update Request first - this
        # endpoint used to skip that check entirely, unlike the web flow.
        if not employee.can_access_face_registration:
            latest = employee.latest_face_update_request
            if latest and latest.status == FaceUpdateRequest.Status.PENDING:
                raise MobileAPIException(
                    'VALIDATION_ERROR',
                    'Your face update request is still pending approval.', 409,
                )
            raise MobileAPIException(
                'VALIDATION_ERROR',
                'Re-registering your face requires admin approval. Please submit a face update request first.', 409,
            )

        photo = request.FILES.get('photo')
        if not photo:
            raise MobileAPIException('VALIDATION_ERROR', 'photo is required.', 400, field='photo')
        if photo.content_type != 'image/jpeg':
            raise MobileAPIException('UNSUPPORTED_FILE_TYPE', 'Face reference must be a JPEG.', 415)
        if photo.size > 5 * 1024 * 1024:
            raise MobileAPIException('FILE_TOO_LARGE', 'Face reference must be 5 MB or smaller.', 413)

        image_bytes = photo.read()

        try:
            import face_recognition  # noqa: F401 - import check only
        except ImportError:
            raise MobileAPIException('SERVER_ERROR', 'Face recognition is not available on this server.', 500)

        face_locations, image_array = _detect_faces(image_bytes)
        if len(face_locations) == 0:
            raise MobileAPIException('NO_FACE_DETECTED', 'No face was detected in the photo. Please retake it.', 422)
        if len(face_locations) > 1:
            raise MobileAPIException('MULTIPLE_FACES', 'More than one face was detected in the photo.', 422)

        import face_recognition
        encodings = face_recognition.face_encodings(image_array, face_locations)
        if not encodings:
            raise MobileAPIException('NO_FACE_DETECTED', 'Could not extract a usable face from the photo.', 422)
        encoding = encodings[0]

        is_unique, conflict_emp, _distance = is_encoding_unique(encoding, exclude_employee_id=employee.pk)
        if not is_unique:
            raise MobileAPIException(
                'VALIDATION_ERROR',
                f'This face appears to already be registered to another employee ("{conflict_emp.full_name}").',
                422, field='photo',
            )

        was_registered = employee.has_registered_face
        file_name = f'face_{employee.id}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.jpg'

        # Mirrors the existing web registration flow exactly: the captured
        # face photo becomes the profile picture too (has_registered_face
        # requires both to be set - see Employee.has_registered_face).
        employee.profile_picture.save(file_name, ContentFile(image_bytes), save=False)
        employee.face_encoding = json.dumps(encoding.tolist())
        employee.face_registered = True
        employee.face_registered_at = timezone.now()
        employee.save(update_fields=['profile_picture', 'face_registered', 'face_registered_at', 'face_encoding'])

        from .models import FaceEnrollmentLog
        log = FaceEnrollmentLog.objects.create(
            employee=employee,
            action=FaceEnrollmentLog.Action.RE_ENROLLED if was_registered else FaceEnrollmentLog.Action.ENROLLED,
            actor=request.user,
            quality_score=None,
        )
        log.reference_image.save(file_name, ContentFile(image_bytes), save=True)

        # The approval this re-registration used up is now fulfilled.
        for pending in employee.face_update_requests.filter(status=FaceUpdateRequest.Status.APPROVED):
            pending.mark_completed()

        return self.ok({
            "faceIdRegistered": True,
            "registeredAt": employee.face_registered_at.isoformat(),
            "referenceImageUrl": employee.profile_picture.url,
            "quality": {"score": None, "acceptable": True},
        }, message="Face ID registered successfully.", status_code=201)

    def delete(self, request):
        employee = request.user.employee_profile
        employee.set_face_encoding(None)
        employee.profile_picture = None
        employee.save(update_fields=['face_encoding', 'face_registered', 'face_registered_at', 'profile_picture'])

        from .models import FaceEnrollmentLog
        FaceEnrollmentLog.objects.create(
            employee=employee, action=FaceEnrollmentLog.Action.CLEARED, actor=request.user,
        )

        return self.ok(message="Face ID enrolment cleared.")


@extend_schema_view(
    get=extend_schema(
        responses=EnvelopeResponseSerializer,
        tags=[UPDATE_REQUEST_TAG], summary="My face update request history",
        parameters=[OpenApiParameter('page', OpenApiTypes.INT), OpenApiParameter('pageSize', OpenApiTypes.INT)],
        description="Newest first. Check this (or just the first item) to see whether a request is still PENDING, "
                     "was REJECTED, or is APPROVED and ready to act on via POST /employees/me/face-id.",
        examples=[OpenApiExample('200 response', value={
            "requests": [{
                "id": "fur_00003", "status": "APPROVED", "reason": "Grew a beard",
                "adminComment": "Approved - go ahead", "requestedAt": "2026-09-14T10:00:00+05:30",
                "reviewedAt": "2026-09-14T15:00:00+05:30", "reviewedBy": "Priya Sharma", "completedAt": None,
            }],
            "pagination": {"page": 1, "pageSize": 20, "totalItems": 1, "totalPages": 1},
        }, response_only=True)],
    ),
    post=extend_schema(
        responses={201: EnvelopeResponseSerializer, 409: EnvelopeResponseSerializer},
        tags=[UPDATE_REQUEST_TAG], summary="Request permission to re-register your face",
        description=(
            "Once a face is on file, POST /employees/me/face-id refuses re-enrolment until an "
            "admin approves a request made here (409 VALIDATION_ERROR otherwise - see that "
            "endpoint). Rejects with 409 if you have no face registered yet, or already have a "
            "PENDING or APPROVED request outstanding."
        ),
        request=FaceUpdateRequestCreateSerializer,
        examples=[
            OpenApiExample('Request', value={"reason": "Grew a beard"}, request_only=True),
            OpenApiExample('201 response', value={
                "id": "fur_00003", "status": "PENDING", "reason": "Grew a beard",
                "adminComment": None, "requestedAt": "2026-09-15T10:00:00+05:30",
                "reviewedAt": None, "reviewedBy": None, "completedAt": None,
            }, response_only=True),
            OpenApiExample('409 no face registered yet', value={
                "success": False, "data": None,
                "message": "Please register your face before requesting an update.",
                "error": {"code": "VALIDATION_ERROR", "field": None, "details": None},
            }, response_only=True, status_codes=['409']),
            OpenApiExample('409 request already outstanding', value={
                "success": False, "data": None,
                "message": "You already have a face update request awaiting processing.",
                "error": {"code": "VALIDATION_ERROR", "field": None, "details": None},
            }, response_only=True, status_codes=['409']),
        ],
    ),
)
class FaceUpdateRequestsView(MobileAPIView):
    """GET/POST /face-update-requests"""

    def get(self, request):
        employee = request.user.employee_profile
        qs = FaceUpdateRequest.objects.filter(employee=employee).order_by('-requested_at')
        items, pagination = paginate(list(qs), request.GET.get('page'), request.GET.get('pageSize'))
        return self.ok({
            "requests": [_serialize_update_request(r) for r in items],
            "pagination": pagination,
        })

    def post(self, request):
        employee = request.user.employee_profile

        if not employee.has_registered_face:
            raise MobileAPIException('VALIDATION_ERROR', 'Please register your face before requesting an update.', 409)

        active_exists = employee.face_update_requests.filter(
            status__in=[FaceUpdateRequest.Status.PENDING, FaceUpdateRequest.Status.APPROVED]
        ).exists()
        if active_exists:
            raise MobileAPIException('VALIDATION_ERROR', 'You already have a face update request awaiting processing.', 409)

        reason = (request.data.get('reason') or '').strip()
        update_request = FaceUpdateRequest.objects.create(
            office=employee.office, branch=employee.branch, employee=employee, reason=reason,
        )

        return self.ok(
            _serialize_update_request(update_request),
            message="Face update request submitted. An administrator will review it shortly.",
            status_code=201,
        )
