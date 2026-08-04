"""
Document Upload API URLs
URL patterns for document upload endpoints
"""

from django.urls import path
from . import document_views, document_upload_api

app_name = 'document_api'

urlpatterns = [
    # NEW API ENDPOINTS - Document Status & Upload
    path('api/documents/status/', document_upload_api.get_document_status, name='document_status'),
    path('api/upload/<str:doc_type>/', document_upload_api.upload_document, name='upload_document_api'),
    
    # Employee document upload (legacy)
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
