"""
Document Upload API Views
Handles file uploads for employee documents with validation and storage
"""

import os
import json
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.conf import settings
from django.utils.text import slugify
import mimetypes

# Document type mapping
DOCUMENT_TYPES = {
    '10th': 'marksheet_10th',
    '12th': 'marksheet_12th',
    'aadhaar': 'aadhaar_front',
    'aadhaar-back': 'aadhaar_back',
    'pan': 'pan_document',
    'bank': 'bank_passbook_document',
    'education': 'educational_qualifications',
}

# Allowed file types
ALLOWED_EXTENSIONS = ['pdf', 'jpg', 'jpeg', 'png']
ALLOWED_MIMETYPES = ['application/pdf', 'image/jpeg', 'image/png', 'image/jpg']
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


def validate_file(file):
    """
    Validate uploaded file
    Returns: (is_valid, error_message)
    """
    if not file:
        return False, "No file provided"

    # Check file size
    if file.size > MAX_FILE_SIZE:
        return False, f"File size must be less than {MAX_FILE_SIZE / (1024 * 1024):.0f}MB"

    # Check file type by extension (primary validation)
    ext = os.path.splitext(file.name)[1].lower().lstrip('.')
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"Only {', '.join(ALLOWED_EXTENSIONS).upper()} files are allowed"

    # Check MIME type (secondary validation - be lenient)
    # Some browsers may report different MIME types, so we check by extension primarily
    if file.content_type:
        # Map extensions to acceptable MIME types (be flexible)
        mime_map = {
            'pdf': ['application/pdf'],
            'jpg': ['image/jpeg', 'image/jpg'],
            'jpeg': ['image/jpeg', 'image/jpg'],
            'png': ['image/png']
        }
        
        acceptable_mimes = mime_map.get(ext, [])
        # If we have acceptable MIME types for this extension, check against them
        if acceptable_mimes and file.content_type not in acceptable_mimes:
            # Log warning but don't fail - extension is the primary validator
            import logging
            logging.warning(f"Unexpected MIME type {file.content_type} for .{ext} file, but allowing based on extension")

    return True, None


def get_upload_path(doc_type, filename):
    """
    Generate upload path for document
    Format: media/documents/{doc_type}/{timestamp}_{filename}
    """
    from datetime import datetime
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    ext = os.path.splitext(filename)[1]
    safe_filename = f"{timestamp}_{slugify(os.path.splitext(filename)[0])}{ext}"
    return f"documents/{doc_type}/{safe_filename}"


@login_required
@require_http_methods(["POST"])
def upload_document(request, doc_type):
    """
    Handle document upload with verification lock check
    POST /api/upload/{doc_type}/
    
    Expected form data:
    - file: File object
    
    Returns JSON:
    {
        "status": "success|error|locked",
        "message": "Document uploaded successfully",
        "file_url": "/media/documents/..."
    }
    """
    try:
        # Validate document type
        if doc_type not in DOCUMENT_TYPES:
            return JsonResponse({
                "status": "error",
                "message": f"Invalid document type: {doc_type}"
            }, status=400)

        # Get uploaded file
        if 'file' not in request.FILES:
            return JsonResponse({
                "status": "error",
                "message": "No file provided"
            }, status=400)

        file = request.FILES['file']

        # Validate file
        is_valid, error_msg = validate_file(file)
        if not is_valid:
            return JsonResponse({
                "status": "error",
                "message": error_msg
            }, status=400)

        # CHECK FOR VERIFICATION LOCK
        try:
            from employees.models import Employee, EmployeeDocument
            employee = Employee.objects.get(user=request.user)
            
            # Map document type to EmployeeDocument type
            doc_type_mapping = {
                '10th': 'marksheet_10th',
                '12th': 'marksheet_12th',
                'aadhaar': 'aadhar_front',
                'aadhaar-back': 'aadhar_back',
                'pan': 'pan',
                'bank': 'bank_proof',
                'education': 'education_proof'
            }
            
            mapped_doc_type = doc_type_mapping.get(doc_type)
            if mapped_doc_type:
                # Check if there's a verified document of this type
                verified_doc = EmployeeDocument.objects.filter(
                    employee=employee,
                    document_type=mapped_doc_type,
                    status='verified'
                ).first()
                
                if verified_doc:
                    return JsonResponse({
                        "status": "locked",
                        "message": "This document has been verified and cannot be re-uploaded. Please contact admin if you need to make changes.",
                        "verified_at": verified_doc.verified_at.isoformat() if verified_doc.verified_at else None,
                        "verified_by": verified_doc.verified_by.get_full_name() if verified_doc.verified_by else None
                    }, status=403)
                    
        except Exception as e:
            print(f"Warning: Could not check verification status: {str(e)}")
            # Continue with upload if verification check fails

        # Generate upload path
        upload_path = get_upload_path(doc_type, file.name)

        # Save file
        file_url = default_storage.save(upload_path, ContentFile(file.read()))

        # Get full URL
        full_url = default_storage.url(file_url)

        # Create/update EmployeeDocument record
        try:
            from employees.models import Employee, EmployeeDocument
            employee = Employee.objects.get(user=request.user)
            
            # Map document type to EmployeeDocument type
            doc_type_mapping = {
                '10th': 'marksheet_10th',
                '12th': 'marksheet_12th',
                'aadhaar': 'aadhar_front',
                'aadhaar-back': 'aadhar_back',
                'pan': 'pan',
                'bank': 'bank_proof',
                'education': 'education_proof'
            }
            
            mapped_doc_type = doc_type_mapping.get(doc_type)
            if mapped_doc_type:
                # Deactivate any existing documents of this type
                EmployeeDocument.objects.filter(
                    employee=employee,
                    document_type=mapped_doc_type
                ).update(status='submitted')
                
                # Create new document record
                EmployeeDocument.objects.create(
                    employee=employee,
                    office=employee.office,
                    branch=employee.branch,
                    document_type=mapped_doc_type,
                    file=file_url,
                    status='submitted'
                )
                
        except Exception as e:
            print(f"Warning: Could not update EmployeeDocument record: {str(e)}")
            # Continue anyway - file was saved successfully

        return JsonResponse({
            "status": "success",
            "message": "Document uploaded successfully",
            "file_url": full_url
        })

    except Exception as e:
        print(f"Upload error: {str(e)}")
        return JsonResponse({
            "status": "error",
            "message": "An error occurred during upload. Please try again."
        }, status=500)


@login_required
@require_http_methods(["GET"])
def get_document_status(request):
    """
    Get upload status for all documents including verification lock
    GET /api/documents/status/
    
    Returns JSON:
    {
        "documents": {
            "10th": {"uploaded": true, "url": "...", "is_locked": false, "verified_at": null},
            "12th": {"uploaded": false, "is_locked": false},
            ...
        }
    }
    """
    try:
        from employees.models import Employee, EmployeeDocument
        employee = Employee.objects.get(user=request.user)
        
        # Map document types to EmployeeDocument types
        doc_type_mapping = {
            '10th': 'marksheet_10th',
            '12th': 'marksheet_12th',
            'aadhaar': 'aadhar_front',
            'aadhaar-back': 'aadhar_back',
            'pan': 'pan',
            'bank': 'bank_proof',
            'education': 'education_proof'
        }
        
        documents = {}
        for doc_type in DOCUMENT_TYPES.keys():
            mapped_doc_type = doc_type_mapping.get(doc_type)
            
            # Check EmployeeDocument records
            doc_record = None
            if mapped_doc_type:
                doc_record = EmployeeDocument.objects.filter(
                    employee=employee,
                    document_type=mapped_doc_type
                ).order_by('-uploaded_at').first()
            
            if doc_record:
                documents[doc_type] = {
                    "uploaded": True,
                    "url": doc_record.file.url if doc_record.file else None,
                    "status": doc_record.status,
                    "is_locked": doc_record.status == 'verified',
                    "verified_at": doc_record.verified_at.isoformat() if doc_record.verified_at else None,
                    "verified_by": doc_record.verified_by.get_full_name() if doc_record.verified_by else None,
                    "uploaded_at": doc_record.uploaded_at.isoformat()
                }
            else:
                # Fallback to old employee field system
                field_name = DOCUMENT_TYPES.get(doc_type)
                if field_name and hasattr(employee, field_name):
                    file_field = getattr(employee, field_name)
                    if file_field:
                        documents[doc_type] = {
                            "uploaded": True,
                            "url": file_field.url if hasattr(file_field, 'url') else str(file_field),
                            "status": "submitted",
                            "is_locked": False,
                            "verified_at": None,
                            "verified_by": None,
                            "uploaded_at": None
                        }
                    else:
                        documents[doc_type] = {
                            "uploaded": False,
                            "is_locked": False
                        }
                else:
                    documents[doc_type] = {
                        "uploaded": False,
                        "is_locked": False
                    }

        return JsonResponse({
            "status": "success",
            "documents": documents
        })

    except Exception as e:
        print(f"Status check error: {str(e)}")
        return JsonResponse({
            "status": "error",
            "message": "Could not retrieve document status"
        }, status=500)
