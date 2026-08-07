"""
Document Upload and Verification Views
Handles employee document uploads and admin verification
"""

from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse, FileResponse
from django.utils import timezone
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import os
import logging
from datetime import datetime

from .models import Employee, EmployeeDocument
from .permissions import is_office_admin
logger = logging.getLogger(__name__)

# Allowed file extensions
ALLOWED_EXTENSIONS = {
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'csv',
    'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp',
    'txt', 'zip', 'rar'
}

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


def validate_file(file_obj):
    """Validate uploaded file"""
    if not file_obj:
        return False, "No file provided"
    
    # Check file size
    if file_obj.size > MAX_FILE_SIZE:
        return False, f"File size exceeds {MAX_FILE_SIZE / (1024*1024):.0f}MB limit"
    
    # Check file extension
    ext = file_obj.name.split('.')[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"File type .{ext} not allowed. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
    
    return True, "Valid"


@login_required
@require_http_methods(["POST"])
def upload_document(request):
    """
    API endpoint for employee document upload
    POST /employee/upload-document/
    
    Expects:
        - document_type: Type of document (marksheet_10th, aadhar_front, etc.)
        - file: File to upload
    
    Returns JSON response
    """
    try:
        # Get employee profile
        employee = request.user.employee_profile
        
        # Get document type
        document_type = request.POST.get('document_type')
        if not document_type:
            return JsonResponse({
                'success': False,
                'error': 'Document type is required'
            }, status=400)
        
        # Validate document type
        valid_types = [choice[0] for choice in EmployeeDocument.DocumentType.choices]
        if document_type not in valid_types:
            return JsonResponse({
                'success': False,
                'error': f'Invalid document type: {document_type}'
            }, status=400)
        
        # Get uploaded file
        if 'file' not in request.FILES:
            return JsonResponse({
                'success': False,
                'error': 'No file provided'
            }, status=400)
        
        file_obj = request.FILES['file']
        
        # Validate file
        is_valid, message = validate_file(file_obj)
        if not is_valid:
            return JsonResponse({
                'success': False,
                'error': message
            }, status=400)
        
        # Create or update document record
        document, created = EmployeeDocument.objects.update_or_create(
            employee=employee,
            document_type=document_type,
            defaults={
                'file': file_obj,
                'status': EmployeeDocument.VerificationStatus.SUBMITTED,
                'uploaded_at': timezone.now(),
            }
        )

        if not created:
            document.file = file_obj
            document.status = EmployeeDocument.VerificationStatus.SUBMITTED
            document.uploaded_at = timezone.now()

        document.needs_resubmission = False
        document.resubmit_requested_at = None
        document.resubmit_reason = ''
        document.save()
        
        logger.info(f"Document uploaded: {document.id} by {employee.name}")
        
        return JsonResponse({
            'success': True,
            'message': 'Document uploaded successfully!',
            'document_id': document.id,
            'status': document.status,
            'needs_resubmission': document.needs_resubmission,
            'file_name': file_obj.name,
            'file_size': f"{file_obj.size / (1024*1024):.2f} MB",
        })
    
    except Exception as e:
        logger.error(f"Error uploading document: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'Server error during upload'
        }, status=500)


@login_required
@require_http_methods(["GET"])
def get_employee_documents(request, employee_id=None):
    """
    Get all documents for an employee
    GET /employee/documents/ or /employee/<id>/documents/
    
    Returns JSON list of documents
    """
    try:
        # If no employee_id provided, get current user's documents
        if employee_id is None:
            employee = request.user.employee_profile
        else:
            # Admin can view any employee's documents
            if not is_office_admin(request.user):
                return JsonResponse({
                    'success': False,
                    'error': 'Permission denied'
                }, status=403)
            employee = get_object_or_404(Employee, id=employee_id)
        
        documents = EmployeeDocument.objects.filter(employee=employee).order_by('-uploaded_at')
        
        docs_data = []
        for doc in documents:
            docs_data.append({
                'id': doc.id,
                'document_type': doc.document_type,
                'document_type_display': doc.get_document_type_display(),
                'status': doc.status,
                'status_display': doc.get_status_display(),
                'needs_resubmission': doc.needs_resubmission,
                'resubmit_reason': doc.resubmit_reason,
                'resubmit_requested_at': doc.resubmit_requested_at.isoformat() if doc.resubmit_requested_at else None,
                'file_name': doc.file.name.split('/')[-1],
                'file_url': doc.file.url if doc.file else None,
                'file_size': f"{doc.file_size_mb} MB",
                'uploaded_at': doc.uploaded_at.isoformat(),
                'verified_at': doc.verified_at.isoformat() if doc.verified_at else None,
                'verified_by': doc.verified_by.get_full_name() if doc.verified_by else None,
                'rejection_reason': doc.rejection_reason,
            })
        
        return JsonResponse({
            'success': True,
            'documents': docs_data,
            'count': len(docs_data)
        })
    
    except Exception as e:
        logger.error(f"Error fetching documents: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'Server error'
        }, status=500)


@login_required
@require_http_methods(["PATCH", "POST"])
def verify_document(request, pk):
    """
    Admin endpoint to verify a document
    POST /api/documents/<pk>/verify/
    
    Returns JSON response with document details
    """
    try:
        # Check if user is admin/staff
        if not request.user.is_staff:
            return JsonResponse({
                'success': False,
                'error': 'Permission denied. Admin access required.'
            }, status=403)
        
        # Get document
        document = get_object_or_404(EmployeeDocument, id=pk)
        
        # Prevent re-verification (idempotent)
        if document.status == EmployeeDocument.VerificationStatus.VERIFIED:
            return JsonResponse({
                'success': True,
                'message': 'Document already verified',
                'id': document.id,
                'status': document.status,
                'verified_at': document.verified_at.isoformat() if document.verified_at else None,
                'verified_by': {
                    'id': document.verified_by.id,
                    'username': document.verified_by.username,
                    'email': document.verified_by.email
                } if document.verified_by else None
            })
        
        # Verify document
        document.status = EmployeeDocument.VerificationStatus.VERIFIED
        document.verified_at = timezone.now()
        document.verified_by = request.user
        document.rejection_reason = ''
        document.needs_resubmission = False
        document.resubmit_requested_at = None
        document.resubmit_reason = ''
        document.save()
        
        logger.info(f"Document verified: {document.id} by {request.user.username}")
        
        return JsonResponse({
            'success': True,
            'message': 'Document verified successfully!',
            'id': document.id,
            'status': document.status,
            'verified_at': document.verified_at.isoformat(),
            'needs_resubmission': document.needs_resubmission,
            'verified_by': {
                'id': request.user.id,
                'username': request.user.username,
                'email': request.user.email
            }
        })
    
    except Exception as e:
        logger.error(f"Error verifying document: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'Server error'
        }, status=500)


@login_required
@require_http_methods(["PATCH", "POST"])
def verify_document_legacy(request):
    """
    Legacy admin endpoint to verify/reject a document (backward compatibility)
    POST /admin/verify-document/
    """
    try:
        import json
        try:
            data = json.loads(request.body)
        except:
            data = request.POST
        
        document_id = data.get('document_id')
        action = data.get('action')
        
        if not document_id:
            return JsonResponse({
                'success': False,
                'error': 'Missing document_id'
            }, status=400)
        
        # Redirect to new endpoint format
        return verify_document(request, document_id)
    
    except Exception as e:
        logger.error(f"Error in legacy verify: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'Server error'
        }, status=500)


@login_required
@require_http_methods(["DELETE", "POST"])
def delete_document(request, document_id):
    """
    Delete a document (employee can only delete their own)
    DELETE /employee/document/<id>/delete/
    """
    try:
        document = get_object_or_404(EmployeeDocument, id=document_id)
        
        # Check permission
        if document.employee != request.user.employee_profile and not is_office_admin(request.user):
            return JsonResponse({
                'success': False,
                'error': 'Permission denied'
            }, status=403)
        
        # Delete file
        if document.file:
            document.file.delete()
        
        # Delete record
        document.delete()
        
        logger.info(f"Document deleted: {document_id}")
        
        return JsonResponse({
            'success': True,
            'message': 'Document deleted successfully'
        })
    
    except Exception as e:
        logger.error(f"Error deleting document: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'Server error'
        }, status=500)


@login_required
@user_passes_test(is_office_admin)
@require_http_methods(["POST"])
def request_document_resubmission(request, pk):
    """Allow admins to request that an employee re-upload a document."""
    document = get_object_or_404(EmployeeDocument, id=pk)
    reason = (request.POST.get('reason') or '').strip()
    document.status = EmployeeDocument.VerificationStatus.REJECTED
    document.needs_resubmission = True
    document.resubmit_requested_at = timezone.now()
    document.resubmit_reason = reason
    document.save(update_fields=[
        'status',
        'needs_resubmission',
        'resubmit_requested_at',
        'resubmit_reason',
    ])

    logger.info(f"Resubmission requested for document {document.id} by {request.user.username}")

    return JsonResponse({
        'success': True,
        'message': 'Employee asked to re-upload this document.',
        'needs_resubmission': True,
        'reason': reason,
    })


@login_required
@require_http_methods(["GET"])
def view_document(request, document_id):
    """
    View/download a document
    GET /employee/document/<id>/view/
    
    Returns the document file or JSON response with file URL
    """
    try:
        document = get_object_or_404(EmployeeDocument, id=document_id)
        
        # Check permission - employee can only view their own, admin can view all
        if document.employee != request.user.employee_profile and not is_office_admin(request.user):
            return JsonResponse({
                'success': False,
                'error': 'Permission denied'
            }, status=403)
        
        # If file exists, return it
        if document.file:
            try:
                return FileResponse(document.file.open('rb'), as_attachment=False)
            except Exception as e:
                logger.error(f"Error opening document file: {str(e)}")
                return JsonResponse({
                    'success': False,
                    'error': 'Could not open file'
                }, status=500)
        else:
            return JsonResponse({
                'success': False,
                'error': 'Document file not found'
            }, status=404)
    
    except Exception as e:
        logger.error(f"Error viewing document: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'Server error'
        }, status=500)
