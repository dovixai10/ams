"""
Mobile API - KYC documents (spec section 10, 4 endpoints).
GET /employees/me/documents, POST /employees/me/documents/{documentId},
GET /employees/me/documents/{documentId}/preview, GET /documents/summary
"""
from rest_framework import serializers
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiParameter, OpenApiTypes

from .mobile_response import MobileAPIView, MobileAPIException, EnvelopeResponseSerializer
from .models import EmployeeDocument

TAG = 'Documents (KYC)'
DOCUMENT_ID_PARAM = OpenApiParameter(
    'document_id', OpenApiTypes.STR, location=OpenApiParameter.PATH,
    description='One of: 10th_marksheet, 12th_marksheet, aadhaar_front, aadhaar_back, pan_card',
)


class DocumentUploadRequestSerializer(serializers.Serializer):
    file = serializers.FileField(help_text="Must match the slot's accepted types; 10 MB cap")
    source = serializers.ChoiceField(choices=['CAMERA', 'GALLERY', 'PDF_FILE'], required=False, help_text="Audit metadata only")

# spec document id -> (model DocumentType value, display name, category, accepted MIME types)
SLOTS = [
    ('10th_marksheet', 'marksheet_10th', '10th Marksheet', 'Academic Qualification', ('application/pdf', 'image/jpeg')),
    ('12th_marksheet', 'marksheet_12th', '12th Marksheet', 'Academic Qualification', ('application/pdf', 'image/jpeg')),
    ('aadhaar_front', 'aadhar_front', 'Aadhaar Card (Front)', 'Government Identity Proof', ('image/jpeg', 'image/png')),
    ('aadhaar_back', 'aadhar_back', 'Aadhaar Card (Back)', 'Permanent Address Proof', ('image/jpeg', 'image/png')),
    ('pan_card', 'pan', 'PAN Card', 'Financial & Tax KYC', ('application/pdf', 'image/jpeg')),
]
SLOT_BY_SPEC_ID = {row[0]: row for row in SLOTS}

_STATUS_MAP = {
    EmployeeDocument.VerificationStatus.PENDING: 'PENDING',
    EmployeeDocument.VerificationStatus.SUBMITTED: 'PENDING',
    EmployeeDocument.VerificationStatus.VERIFIED: 'VERIFIED',
    EmployeeDocument.VerificationStatus.REJECTED: 'REJECTED',
}


def _serialize(spec_id, model_type, name, category, accepted_types, doc):
    if doc is None:
        return {
            "id": spec_id, "name": name, "category": category, "status": "NOT_UPLOADED",
            "acceptedTypes": list(accepted_types), "uploadedAt": None, "fileSizeBytes": None,
            "fileUrl": None, "verifiedAt": None, "verifiedBy": None, "rejectionReason": None,
        }
    return {
        "id": spec_id, "name": name, "category": category,
        "status": _STATUS_MAP.get(doc.status, 'PENDING'),
        "acceptedTypes": list(accepted_types),
        "uploadedAt": doc.uploaded_at.isoformat(),
        "fileSizeBytes": doc.file.size if doc.file else None,
        "fileUrl": doc.file.url if doc.file else None,
        "verifiedAt": doc.verified_at.isoformat() if doc.verified_at else None,
        "verifiedBy": (doc.verified_by.get_full_name() or doc.verified_by.username) if doc.verified_by else None,
        "rejectionReason": doc.rejection_reason or None,
    }


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="All five KYC slots",
    description="Always returns all five, including ones never uploaded (status NOT_UPLOADED, null file fields) - the UI renders a row for every slot regardless.",
)
class DocumentsView(MobileAPIView):
    """GET /employees/me/documents"""

    def get(self, request):
        employee = request.user.employee_profile
        existing = {
            d.document_type: d
            for d in EmployeeDocument.objects.filter(employee=employee, document_type__in=[s[1] for s in SLOTS])
        }
        documents = [
            _serialize(spec_id, model_type, name, category, accepted, existing.get(model_type))
            for spec_id, model_type, name, category, accepted in SLOTS
        ]
        verified_count = sum(1 for d in documents if d['status'] == 'VERIFIED')
        return self.ok({
            "verifiedCount": verified_count,
            "totalRequired": len(SLOTS),
            "allVerified": verified_count == len(SLOTS),
            "documents": documents,
        })


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="Upload or re-upload a document", parameters=[DOCUMENT_ID_PARAM],
    description="Any upload resets that slot to PENDING - verification is an HR back-office action, out of scope for this app. Enforces per-slot MIME types (UNSUPPORTED_FILE_TYPE) and a 10 MB cap.",
    request=DocumentUploadRequestSerializer,
)
class DocumentUploadView(MobileAPIView):
    """POST /employees/me/documents/{documentId}"""

    def post(self, request, document_id):
        row = SLOT_BY_SPEC_ID.get(document_id)
        if row is None:
            raise MobileAPIException('NOT_FOUND', f'Unknown document slot "{document_id}".', 404)
        _spec_id, model_type, name, category, accepted_types = row

        file_obj = request.FILES.get('file')
        if not file_obj:
            raise MobileAPIException('VALIDATION_ERROR', 'file is required.', 400, field='file')
        if file_obj.content_type not in accepted_types:
            raise MobileAPIException(
                'UNSUPPORTED_FILE_TYPE',
                f'{name} must be one of: {", ".join(accepted_types)}.', 415,
            )
        if file_obj.size > 10 * 1024 * 1024:
            raise MobileAPIException('FILE_TOO_LARGE', f'{name} must be 10 MB or smaller.', 413)

        employee = request.user.employee_profile
        doc, _created = EmployeeDocument.objects.update_or_create(
            employee=employee, document_type=model_type,
            defaults={
                'office': employee.office, 'branch': employee.branch,
                'file': file_obj, 'status': EmployeeDocument.VerificationStatus.SUBMITTED,
                'verified_at': None, 'verified_by': None, 'rejection_reason': '',
            },
        )
        return self.ok(
            _serialize(_spec_id, model_type, name, category, accepted_types, doc),
            message=f"{name} uploaded successfully.", status_code=201,
        )


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="Preview URL for the in-app viewer", parameters=[DOCUMENT_ID_PARAM],
    description="Media is served directly by Django, same convention as every other file URL in this app - not yet a genuinely short-lived signed URL (`expiresInSeconds` is always null). Flag if that's a hard requirement.",
)
class DocumentPreviewView(MobileAPIView):
    """GET /employees/me/documents/{documentId}/preview"""

    def get(self, request, document_id):
        row = SLOT_BY_SPEC_ID.get(document_id)
        if row is None:
            raise MobileAPIException('NOT_FOUND', f'Unknown document slot "{document_id}".', 404)
        _spec_id, model_type, name, _category, _accepted = row

        employee = request.user.employee_profile
        doc = EmployeeDocument.objects.filter(employee=employee, document_type=model_type).first()
        if doc is None or not doc.file:
            raise MobileAPIException('NOT_FOUND', f'{name} has not been uploaded yet.', 404)

        # Media is served by Django directly (see config/urls.py) rather
        # than genuinely short-lived signed URLs - same convention every
        # other file URL in this app already uses. See API docs.
        return self.ok({"previewUrl": request.build_absolute_uri(doc.file.url), "expiresInSeconds": None})


@extend_schema(responses=EnvelopeResponseSerializer, tags=[TAG], summary="Dashboard verified-count card", description="Lightweight counts for the home screen's KYC status card.")
class DocumentsSummaryView(MobileAPIView):
    """GET /documents/summary"""

    def get(self, request):
        employee = request.user.employee_profile
        docs = list(EmployeeDocument.objects.filter(employee=employee, document_type__in=[s[1] for s in SLOTS]))
        verified = sum(1 for d in docs if d.status == EmployeeDocument.VerificationStatus.VERIFIED)
        pending = sum(1 for d in docs if d.status in (EmployeeDocument.VerificationStatus.PENDING, EmployeeDocument.VerificationStatus.SUBMITTED))
        rejected = sum(1 for d in docs if d.status == EmployeeDocument.VerificationStatus.REJECTED)
        return self.ok({
            "verifiedCount": verified, "totalRequired": len(SLOTS),
            "pendingCount": pending, "rejectedCount": rejected,
        })
