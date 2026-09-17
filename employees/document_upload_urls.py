"""
Document Upload API URLs
URL patterns for document upload endpoints
"""

from django.urls import path
from . import document_views

app_name = 'document_api'

urlpatterns = [
    # Document status (dynamic, keyed by DocumentType id) & upload
    path('api/documents/status/', document_views.get_document_status, name='document_status'),
    path('employee/upload-document/', document_views.upload_document, name='upload_document'),
    
    # Get employee documents
    path('employee/documents/', document_views.get_employee_documents, name='get_documents'),
    path('employee/<int:employee_id>/documents/', document_views.get_employee_documents, name='get_employee_documents'),
    
    # Admin verification - new endpoint format
    path('api/documents/<int:pk>/verify/', document_views.verify_document, name='verify_document'),
    # Legacy endpoint for backward compatibility
    path('admin/verify-document/', document_views.verify_document_legacy, name='verify_document_legacy'),
    path('api/documents/<int:pk>/request-resubmit/', document_views.request_document_resubmission, name='request_document_resubmission'),
    
    # View/Download document
    path('employee/document/<int:document_id>/view/', document_views.view_document, name='view_document'),
    
    # Delete document
    path('employee/document/<int:document_id>/delete/', document_views.delete_document, name='delete_document'),
]
