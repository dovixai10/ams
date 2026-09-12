"""
Leave management views - separated to avoid large views.py file
"""
import logging
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.utils import timezone
from django.contrib import messages

from .models import LeaveRequest, LeaveVerificationDocument
from web_project import TemplateLayout
from web_project.template_helpers.theme import TemplateHelper

from .leave_accrual import get_employee_leave_type_balances
from .permissions import office_admin_required, is_platform_admin

logger = logging.getLogger(__name__)


# def is_superadmin(user):
#     """Check if user is superadmin"""
#     return user.is_superuser


@login_required
@user_passes_test(office_admin_required)
@require_http_methods(["GET"])
def leave_verification_documents(request, leave_id):
    """Return verification documents for a leave (admin use).
    
    Always returns JSON for consistency with frontend expectations.
    """
    try:
        leave = get_object_or_404(LeaveRequest, id=leave_id)

        if not is_platform_admin(request.user):
            if leave.employee.office_id != request.user.office_admin_profile.office_id:
                return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
      
        # Build documents list with all required fields
        documents = []
        for doc in leave.verification_documents.order_by('-uploaded_at'):
            try:
                doc_data = {
                    'id': doc.id,
                    'name': doc.file.name.split('/')[-1] if doc.file else 'Unknown',
                    'url': request.build_absolute_uri(doc.file.url) if doc.file else None,
                    'file_size': doc.file.size if doc.file else 0,
                    'uploaded_at': timezone.localtime(doc.uploaded_at).strftime('%b %d, %Y %I:%M %p'),
                    'is_active': doc.is_active,
                }
                documents.append(doc_data)
            except Exception as doc_error:
                logger.warning(f"Error processing document {doc.id}: {str(doc_error)}")
                continue
        
        # Always return JSON
        return JsonResponse({
            'success': True,
            'leave': {
                'id': leave.id,
                'employee': leave.employee.full_name,
                'dates': f"{leave.start_date.strftime('%b %d, %Y')} – {leave.end_date.strftime('%b %d, %Y')}",
                'status': leave.get_verification_status_display(),
            },
            'documents': documents,
        }, status=200)
        
    except LeaveRequest.DoesNotExist:
        logger.warning(f"Leave request {leave_id} not found")
        return JsonResponse({
            'success': False,
            'error': 'Leave request not found',
        }, status=404)
        
    except Exception as e:
        logger.error(f"Error in leave_verification_documents for leave {leave_id}: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'Internal server error',
            'detail': str(e) if request.user.is_superuser else 'An error occurred while fetching documents'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def upload_leave_receipt(request, leave_id):
    """Upload receipt/document for leave verification"""
    leave = get_object_or_404(LeaveRequest, id=leave_id)
    
    # Permission check: employee can only upload for own leaves
    if not is_platform_admin(request.user):
        is_owner = hasattr(request.user, 'employee_profile') and request.user.employee_profile == leave.employee
        is_this_offices_admin = (
            hasattr(request.user, 'office_admin_profile')
            and leave.employee.office_id == request.user.office_admin_profile.office_id
        )
        if not (is_owner or is_this_offices_admin):
            return JsonResponse({'error': 'Permission denied'}, status=403)
    
    if 'file' not in request.FILES:
        return JsonResponse({'error': 'No file provided'}, status=400)
    
    file = request.FILES['file']
    
    # Validate file size (max 5MB)
    if file.size > 5 * 1024 * 1024:
        return JsonResponse({'error': 'File size exceeds 5MB limit'}, status=400)
    
    try:
        doc = LeaveVerificationDocument.objects.create(
            leave=leave,
            office=leave.office,
            branch=leave.branch,
            file=file,
            uploaded_by=request.user
        )
        
        return JsonResponse({
            'success': True,
            'document': {
                'id': doc.id,
                'name': doc.file.name.split('/')[-1],
                'url': doc.file.url,
                'uploaded_at': timezone.localtime(doc.uploaded_at).strftime('%b %d, %Y %I:%M %p'),
            }
        }, status=201)
    
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
