"""
Mobile API - Face ID registration (spec section 6, 3 endpoints).
GET/POST/DELETE /employees/me/face-id

Reuses the same face_recognition-backed encoding/storage the existing web
face-registration flow uses (employees/views.py's register_face view,
employees/face_utils.py) rather than a second implementation.
"""
import json
from io import BytesIO

from django.core.files.base import ContentFile
from django.utils import timezone
from rest_framework import serializers
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample

from .mobile_response import MobileAPIView, MobileAPIException, EnvelopeResponseSerializer
from .face_utils import is_encoding_unique

TAG = 'Face ID'


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
    get=extend_schema(responses=EnvelopeResponseSerializer, tags=[TAG], summary="Enrolment status", description="Drives the Face ID status card and gates the check-in button."),
    post=extend_schema(
        responses=EnvelopeResponseSerializer,
        tags=[TAG], summary="Enrol or re-enrol",
        description=(
            "Exactly one active reference per employee; re-enrolment replaces it but keeps the "
            "prior version in an audit log (actor + timestamp). Rejects NO_FACE_DETECTED / "
            "MULTIPLE_FACES, and rejects a face that already matches a different employee."
        ),
        request=FaceEnrollRequestSerializer,
        examples=[OpenApiExample('201 response', value={
            "faceIdRegistered": True, "registeredAt": "2026-09-14T09:12:04+05:30",
            "referenceImageUrl": "/media/profile_pics/kamal.jpg",
            "quality": {"score": None, "acceptable": True},
        }, response_only=True)],
    ),
    delete=extend_schema(responses=EnvelopeResponseSerializer, tags=[TAG], summary="Clear enrolment", description="Audit-logged. Consider restricting this to HR rather than the employee themself."),
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
