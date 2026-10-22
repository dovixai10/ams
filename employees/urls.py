from django.urls import path, include
from . import views, holiday_views, api_views, leave_views, attendance_admin_views, drf_views, integration_views, reports_views, subscription_views, crm_views, invoice_views, crm_lead_api, recruitment_views, recruitment_public_views

app_name = 'employees'

urlpatterns = [
    # Root URL - public marketing landing page (signed-in users are bounced to their dashboard)
    path('', views.landing_page, name='home'),
    path("privacy-policy/", views.privacy_policy, name="privacy_policy"),
    path("terms-of-service/", views.terms_of_service, name="terms_of_service"),

    #open attendence
    path("attendance-kiosk/<uuid:token>/", views.attendance_kiosk, name="attendance_kiosk"),

    # Authentication URLs
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Dashboard URLs
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('employee-dashboard/', views.employee_dashboard, name='employee_dashboard'),
    path('dashboard/', views.modern_dashboard, name='modern_dashboard'),
    path('mobile-dashboard/', views.mobile_dashboard, name='mobile_dashboard'),
    path('points/manage/', views.admin_points_management, name='admin_points_management'),

    # Employee CRUD URLs (Admin only)
    path('employees/', views.EmployeeListView.as_view(), name='employee_list'),
    path('employees/live-search/', views.employee_live_search, name='employee_live_search'),
    path('employees/create/', views.EmployeeCreateView.as_view(), name='employee_create'),
    path('employees/<int:pk>/', views.employee_detail, name='employee_detail'),
    path('employees/<int:pk>/toggle-status/', views.employee_toggle_status, name='employee_toggle_status'),
    path('employees/<int:pk>/update/', views.EmployeeUpdateView.as_view(), name='employee_update'),
    path('employees/<int:pk>/delete/', views.EmployeeDeleteView.as_view(), name='employee_delete'),
    path('employees/<int:pk>/logs/', views.employee_attendance_logs, name='employee_logs'),

    # Employee Profile URL (Employee only)
    path('profile/', views.employee_profile, name='employee_profile'),
    path('profile/documents/', views.employee_documents, name='employee_documents'),
    path('profile/view/', views.employee_profile_mobile, name='employee_profile_mobile'),

    # SuperAdmin Profile URLs (SuperAdmin only)
    path('admin-profile/', views.superadmin_profile, name='superadmin_profile'),
    path('admin-profile/edit/', views.superadmin_profile_edit, name='superadmin_profile_edit'),
    path('office-profile/edit/', views.office_profile_edit, name='office_profile_edit'),
    path('admin-profile/change-password/', views.superadmin_change_password, name='superadmin_change_password'),
    # path('checkin-dashboard/', views.checkin_dashboard, name='checkin_dashboard'),

    # Check-in URLs (Employee only)
    # Route directly to the main check-in/check-out page (templates/employees/check_in.html)
    path('check-in/', views.check_in, name='check_in'),
    # Short mobile-friendly link. The check_in view requires an employee login,
    # then requests location and camera access and processes the attendance.
    # path('mark-attendance/', views.check_in, name='mark_attendance'),
    path(
    "mark-attendance/<uuid:token>/",
    views.mark_attendance,
    name="mark_attendance",
),
    path('check-out/', views.check_out, name='check_out'),
    path('api/check-in-status/', views.check_in_status, name='check_in_status'),
    # path('holidays/', views.holiday_calendar, name='holiday_calendar'),
    # Break Management URLs
    path('breaks/', views.employee_breaks, name='employee_breaks'),
    path('breaks/start/', views.start_break, name='start_break'),
    path('breaks/end/', views.end_break, name='end_break'),
    path('breaks/admin/', views.admin_breaks_dashboard, name='admin_breaks'),

    # Leave Management URLs
    path('leave/requests/', views.employee_leave_requests, name='employee_leave_requests'),
    path('leave/manage/', views.admin_leave_requests, name='admin_leave_requests'),

    # Attendance Regularization URLs
    path('attendance/regularization/', views.employee_attendance_regularization_requests, name='employee_attendance_regularization_requests'),
    path('attendance/regularization/<int:pk>/cancel/', views.cancel_attendance_regularization_request, name='cancel_attendance_regularization_request'),
    path('attendance/regularization/manage/', views.admin_attendance_regularization_requests, name='admin_attendance_regularization_requests'),

    # Attendance URLs
    path('attendance/', views.AttendanceListView.as_view(), name='attendance_list'),  # Admin only
    path('my-attendance/', views.my_attendance_logs, name='my_attendance_logs'),  # Employee only
    path('attendance-logs/', views.admin_attendance_logs, name='admin_attendance_logs'),  # Admin only - All activity logs
    path('attendance-logs/export/', views.admin_attendance_logs_excel, name='admin_attendance_logs_excel'),

    path('attendance/calendar/', views.employee_attendance_calendar, name='attendance_calendar'),  # Employee - Calendar view
    path('attendance/admin-calendar/', views.admin_attendance_calendar, name='admin_attendance_calendar'),  # Admin - Calendar view
    path('attendance/comments/', views.attendance_day_comments, name='attendance_comments_list'),
    path('attendance/comments/create/', views.create_attendance_day_comment, name='attendance_comments_create'),
    path('attendance/comments/<int:comment_id>/delete/', views.delete_attendance_day_comment, name='attendance_comments_delete'),
    path('attendance/comment-threads/', views.attendance_day_comment_threads, name='attendance_comments_threads'),
    path('attendance/details/<str:date>/', views.attendance_details_api, name='attendance_details'),  # API - Get attendance details for a date
    path('api/attendance/', views.attendance_detail_api, name='attendance_detail_api'),  # API - Get attendance details for a date
    path('admin/attendance/<int:attendance_id>/detail/', views.admin_attendance_detail, name='admin_attendance_detail'),  # Admin - View attendance details

    # Face Recognition URLs
    path('face/register/', views.face_registration, name='face_register'),
    path('face/attendance/', views.mark_attendance, name='face_attendance'),
    path('face/update-request/', views.request_face_update, name='request_face_update'),
    path('management/face-update-requests/', views.admin_face_update_requests, name='admin_face_update_requests'),
    
    # Ticket System URLs
    path('support-tickets/', views.support_tickets, name='support_tickets'),  # Employee - Unified support tickets (request + history)
    path('tickets/', views.employee_tickets, name='employee_tickets'),  # Employee - My tickets (redirect to support_tickets)
    path('tickets/create/', views.create_ticket, name='create_ticket'),  # Employee - Create ticket (redirect to support_tickets)
    path('tickets/<int:pk>/', views.ticket_detail, name='ticket_detail'),  # Employee - View ticket
    path('tickets/<int:pk>/comment/', views.add_ticket_comment, name='add_ticket_comment'),  # Add comment
    path('tickets/manage/', views.admin_tickets, name='admin_tickets'),  # Admin - All tickets
    path('tickets/manage/<int:pk>/update/', views.admin_update_ticket, name='admin_update_ticket'),  # Admin - Update ticket

    # Project Management URLs
    path('projects/', views.admin_projects, name='admin_projects'),  # Admin - Projects list + create
    path('projects/<int:pk>/', views.admin_project_detail, name='admin_project_detail'),  # Admin - Project detail
    path('projects/<int:pk>/add-task/', views.admin_project_add_task, name='admin_project_add_task'),
    path('projects/<int:pk>/upload-attachment/', views.admin_project_upload_attachment, name='admin_project_upload_attachment'),
    path('projects/<int:pk>/attachments/<int:attachment_id>/delete/', views.admin_project_delete_attachment, name='admin_project_delete_attachment'),
    path('projects/<int:pk>/delete/', views.admin_project_delete, name='admin_project_delete'),

    # Task Management URLs
    path('tasks/manage/', views.admin_tasks, name='admin_tasks'),  # Admin - Task dashboard
    path('tasks/manage/<int:pk>/', views.admin_task_detail, name='admin_task_detail'),  # Admin - Task detail
    path('tasks/<int:pk>/update-status/', views.update_task_status, name='update_task_status'),  # Shared update
    path('tasks/', views.employee_tasks, name='employee_tasks'),  # Employee - My tasks
    path('tasks/manage/export/', views.admin_tasks_excel, name='admin_tasks_excel'),

    # Teams & team task board URLs
    path('my-teams/', views.employee_my_teams, name='employee_my_teams'),  # Employee - which teams am I on
    path('teams/', views.admin_teams, name='admin_teams'),  # Admin - create/edit teams
    path('teams/<int:team_id>/board/', views.team_board, name='team_board'),  # Kanban board for one team
    path('teams/<int:team_id>/board/add-task/', views.team_board_add_task, name='team_board_add_task'),
    path('tasks/<int:pk>/board-move/', views.team_board_move_task, name='team_board_move_task'),  # AJAX drag/reassign
    path('tasks/<int:pk>/board-comment/', views.team_board_add_comment, name='team_board_add_comment'),  # AJAX comment
    path('tasks/<int:pk>/board-attachment/', views.team_board_add_task_attachment, name='team_board_add_task_attachment'),  # AJAX task-level attachment

    # Password Reset URLs
    path('password-reset/', views.EmployeePasswordResetView.as_view(), name='password_reset'),
    path('password-reset/request/', views.password_reset_request, name='password_reset_request'),
    path('password-reset/done/', views.EmployeePasswordResetDoneView.as_view(), name='password_reset_done'),
    path('password-reset/<uidb64>/<token>/', views.EmployeePasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('password-reset/complete/', views.EmployeePasswordResetCompleteView.as_view(), name='password_reset_complete'),

    # Admin Password Management URLs
    path('password-requests/', views.password_reset_requests_list, name='password_reset_requests'),
    path('password-requests/<int:request_id>/process/', views.process_password_reset_request, name='process_password_reset'),
    path('employee/<int:employee_id>/change-password/', views.employee_change_password, name='employee_change_password'),

    # Document Upload API URLs
    path('', include(('employees.document_upload_urls', 'document_api'))),
    
    # Holiday Management URLs
    path('holidays/', holiday_views.holidays_calendar, name='holidays_calendar'),
    path('', include('employees.holiday_urls')),
    
    # Leave receipt upload
    path('api/leaves/<int:leave_id>/upload-receipt/', leave_views.upload_leave_receipt, name='upload_leave_receipt'),
    path('leaves/<int:leave_id>/documents/', leave_views.leave_verification_documents, name='leave_documents'),
    
    # Branch Management
    path('branches/', views.admin_branches, name='admin_branches'),
    path('branches/switch/', views.switch_branch, name='switch_branch'),

    # Roles & Permissions
    path('roles/', views.admin_roles, name='admin_roles'),

    # Rules & Regulations
    path('rules/', views.company_rules, name='company_rules'),
    path('rules/manage/', views.admin_rules, name='admin_rules'),
    path('rules-and-regulations/', views.rules_and_regulations, name='rules_and_regulations'),

    # Loans & Advance
    path('loans/request/', views.loan_request, name='loan_request'),
    path('loans/my-loans/', views.my_loans, name='my_loans'),
    path('loans/manage/', views.admin_loans, name='admin_loans'),
    
    # Reimbursements
    path('reimbursements/request/', views.reimbursement_request, name='reimbursement_request'),
    path('reimbursements/my-reimbursements/', views.my_reimbursements, name='my_reimbursements'),
    path('reimbursements/manage/', views.admin_reimbursements, name='admin_reimbursements'),

    path('asset-management/', views.asset_management, name='asset_management'),

    # Services
    path('services/leave-verification/', views.leave_verification_portal, name='leave_verification'),
    path('services/assets/', views.employee_assets, name='employee_assets'),
    path('api/asset/<int:asset_id>/update-status/', views.update_asset_status, name='update_asset_status'),
    path('api/asset/<int:asset_id>/verify/', views.verify_asset_status, name='verify_asset_status'),

    # generate attendance report
    path(
    "attendance/excel/",
    views.attendance_excel_report,
    name="attendance_excel_report",
),
    # Salary Slip URLs
    path('employees/employee-salary/', views.employee_salary, name='employee_salary'),
    path('employees/employee-salary/report/', views.employee_salary_excel_report, name='employee_salary_excel_report'),

    path('salary-slips/', views.salary_slips, name='salary_slips'),
    path('salary-slips/manage/', views.admin_salary_slips, name='admin_salary_slips'),
    path('api/salary-slip-preview/', views.salary_slip_preview_api, name='salary_slip_preview_api'),
    path('salary-slips/<int:pk>/download/', views.download_salary_slip, name='download_salary_slip'),
    path("shift/", views.admin_shifts, name="admin_shifts"),
    path("shift-assignment/", views.shift_assignment, name="shift_assignment"),
    path("shift/update/", views.update_employee_shift, name="update_employee_shift"),
    path("shift/bulk-assign/", views.bulk_assign_shift, name="bulk_assign_shift"),
    path("shift/remove/", views.remove_employee_shift, name="remove_employee_shift"),
    path("shift/employees-data/", views.get_employee_shifts_data, name="get_employee_shifts_data"),
    # Employee ID Card URLs
    path('id-card/', views.view_id_card, name='view_id_card'),
    path('id-card/download-pdf/', views.download_id_card_pdf, name='download_id_card_pdf'),
    path('id-card/manage/', views.admin_id_cards, name='admin_id_cards'),
    path('id-card/<int:pk>/download/', views.download_id_card, name='download_id_card'),
    # ID Card Management (dynamic generator UI)
    # Named "dynamic_id_card_generator" to match existing template references
    path('id-card/generator/', views.admin_idcard_generator, name='dynamic_id_card_generator'),
    path('api/get-employee-data/', views.get_employee_data_api, name='get_employee_data_api'),

    # DRF API (token-authenticated, for external platforms)
    path('api/v1/token-auth/', drf_views.TokenAuthView.as_view(), name='api_token_auth'),
    path('api/v1/profile/', drf_views.EmployeeProfileAPIView.as_view(), name='employee_profile_api'),
    path('api/v1/salary-slips/', drf_views.SalarySlipListAPIView.as_view(), name='salary_slips_api'),
    path('api/v1/leads/capture/<str:api_key>/', crm_lead_api.CaptureLeadView.as_view(), name='crm_capture_lead_api'),

    # Dashboard API
    path('api/dashboard/', api_views.dashboard_api, name='dashboard_api'),
    path('api/checkin-dashboard/', api_views.checkin_dashboard_api, name='checkin_dashboard_api'),
    path('api/dashboard-ui-state/', api_views.dashboard_ui_state_api, name='dashboard_ui_state_api'),
    
    # Notification URLs
    path('notifications/', views.notification_center, name='notification_center'),
    path('api/notifications/list/', api_views.notifications_list_api, name='notifications_list_api'),
    path('api/notifications/count/', api_views.notification_count_api, name='notification_count_api'),
    path('api/notifications/<int:notification_id>/mark-read/', api_views.mark_notification_as_read, name='mark_notification_read'),
    path('api/notifications/mark-all-read/', api_views.mark_all_notifications_as_read, name='mark_all_notifications_read'),
    path('api/notifications/<int:notification_id>/delete/', api_views.delete_notification, name='delete_notification'),
    
    # API Endpoints
    path('api/get-employee-data/', views.get_employee_data, name='get_employee_data'),
    path('api/attendance/<int:employee_id>/<str:date_str>/details/', getattr(views, 'attendance_details_api', lambda *a, **k: None), name='attendance_details_api'),
    path('api/attendance/<int:employee_id>/<str:date_str>/comment/', getattr(views, 'attendance_comment_api', lambda *a, **k: None), name='attendance_comment_api'),
    path('api/attendance/<int:employee_id>/month/', api_views.attendance_month_api, name='attendance_month_api'),
    path('api/attendance/<int:employee_id>/<str:date_str>/', api_views.attendance_detail_api_v2, name='attendance_detail_api_v2'),
    path('api/attendance/<int:employee_id>/<str:date_str>/comments/', api_views.attendance_comment_api_v2, name='attendance_comment_api_v2'),
    path('api/employees/<int:employee_id>/paid_leave_balance/', api_views.paid_leave_balance_api, name='paid_leave_balance_api'),
    path('api/attendance/calendar/', api_views.attendance_calendar_ajax, name='attendance_calendar_ajax'),
    path('api/attendance/calendar/unified/', api_views.attendance_calendar_api, name='attendance_calendar_api'),
    path('api/attendance/<int:employee_id>/holidays/', api_views.holidays_api, name='holidays_api'),
    # MANUAL ATTENDANCE MARKING
    # MANUAL ATTENDANCE MARKING
    # Note: anything under 'admin/...' gets shadowed by Django's own admin
    # site catch-all (path("admin/", admin.site.urls) in config/urls.py is
    # registered first and swallows unmatched sub-paths, redirecting to
    # Django's own /admin/login/) - so these live at the unprefixed paths
    # below instead, which is also what {% url %} actually resolves to
    # (Django picks the LAST-registered pattern for a given name).
    path('admin/manual-attendance/', views.manual_attendance, name='manual_attendance'),

    # Manual Attendance URLs
    # "Adjust Paid Leave" (admin_adjust_paid_leave / adjust_paid_leave / manual_leave_adjustment)
    # removed - salary now auto-calculates from leave/paid-leave directly, a
    # separate manual balance-adjustment page just fights that calculation.
    path('manual-attendance/', views.manual_attendance, name='manual_attendance'),
    path('manual-attendance/lookup/', views.manual_attendance_lookup, name='manual_attendance_lookup'),
    path('api/employee-details/', attendance_admin_views.get_employee_details, name='get_employee_details'),
    path('api/leave-balance/', attendance_admin_views.get_leave_balance, name='get_leave_balance'),
    path('api/checkin-dashboard-state/', attendance_admin_views.checkin_dashboard_state, name='checkin_dashboard_state'),
    path('api/attendance-calendar-data/', attendance_admin_views.attendance_calendar_data, name='attendance_calendar_data'),
    path('api/attendance/status/', api_views.attendance_status_api, name='attendance_status_api'),

    # Leave Type Management (admin)
    path('leave-types/', views.admin_leave_types, name='admin_leave_types'),
    path('leave-types/<int:pk>/update/', views.admin_leave_type_update, name='admin_leave_type_update'),
    path('leave-types/<int:pk>/toggle/', views.admin_leave_type_toggle, name='admin_leave_type_toggle'),
    path('leave-types/<int:pk>/delete/', views.admin_leave_type_delete, name='admin_leave_type_delete'),

    path('leave/balances/', views.employee_leave_balances, name='employee_leave_balances'),

    # Document Type Management (admin) + approvals
    path('document-types/', views.admin_document_types, name='admin_document_types'),
    path('document-types/<int:pk>/update/', views.admin_document_type_update, name='admin_document_type_update'),
    path('document-types/<int:pk>/toggle/', views.admin_document_type_toggle, name='admin_document_type_toggle'),
    path('document-types/<int:pk>/delete/', views.admin_document_type_delete, name='admin_document_type_delete'),

    # Integrations - WhatsApp (accounts / recipients / report schedules / message log)
    path('integrations/whatsapp/', integration_views.whatsapp_home, name='whatsapp_home'),
    path('integrations/whatsapp/groups/create/', integration_views.whatsapp_group_create, name='whatsapp_group_create'),
    path('integrations/whatsapp/groups/sync/', integration_views.whatsapp_group_sync, name='whatsapp_group_sync'),
    path('integrations/whatsapp/recipients/<int:pk>/invite-link/', integration_views.whatsapp_group_invite_link, name='whatsapp_group_invite_link'),
    path('integrations/whatsapp/phones/<int:pk>/link/', integration_views.whatsapp_web_link, name='whatsapp_web_link'),
    path('integrations/whatsapp/phones/<int:pk>/api/<str:action>/', integration_views.whatsapp_web_api, name='whatsapp_web_api'),
    path('integrations/whatsapp/logs/', integration_views.whatsapp_logs, name='whatsapp_logs'),
    path('integrations/whatsapp/schedules/<int:pk>/send-now/', integration_views.whatsapp_schedule_send_now, name='whatsapp_schedule_send_now'),
    path('integrations/whatsapp/recipients/<int:pk>/test/', integration_views.whatsapp_recipient_test, name='whatsapp_recipient_test'),
    path('integrations/whatsapp/<str:kind>/', integration_views.whatsapp_manage, name='whatsapp_manage'),
    path('integrations/whatsapp/<str:kind>/<int:pk>/update/', integration_views.whatsapp_update, name='whatsapp_update'),
    path('integrations/whatsapp/<str:kind>/<int:pk>/toggle/', integration_views.whatsapp_toggle, name='whatsapp_toggle'),
    path('integrations/whatsapp/<str:kind>/<int:pk>/delete/', integration_views.whatsapp_delete, name='whatsapp_delete'),

    # Reports
    path('reports/employee-performance/', reports_views.employee_performance_report, name='employee_performance_report'),
    path('reports/employee-performance/export/', reports_views.employee_performance_export, name='employee_performance_export'),

    # CRM - Leads
    path('crm/leads/', crm_views.crm_leads, name='crm_leads'),
    path('crm/leads/add/', crm_views.crm_lead_create, name='crm_lead_create'),
    path('crm/leads/import/', crm_views.crm_lead_import, name='crm_lead_import'),
    path('crm/leads/import/sample/', crm_views.crm_lead_import_sample, name='crm_lead_import_sample'),
    path('crm/leads/export/', crm_views.crm_lead_export, name='crm_lead_export'),
    path('crm/leads/<int:pk>/update/', crm_views.crm_lead_update, name='crm_lead_update'),
    path('crm/leads/<int:pk>/delete/', crm_views.crm_lead_delete, name='crm_lead_delete'),
    path('crm/leads/bulk-delete/', crm_views.crm_lead_bulk_delete, name='crm_lead_bulk_delete'),
    path('crm/settings/', crm_views.crm_settings, name='crm_settings'),
    # Public sample lead-capture page for one office - no login required.
    path('l/<slug:slug>/', crm_views.crm_public_lead_page, name='crm_public_lead_page'),

    # Recruitment
    path('recruitment/dashboard/', recruitment_views.recruitment_dashboard, name='recruitment_dashboard'),
    path('recruitment/jobs/', recruitment_views.recruitment_job_list, name='recruitment_job_list'),
    path('recruitment/jobs/export/', recruitment_views.recruitment_job_export, name='recruitment_job_export'),
    path('recruitment/jobs/bulk-delete/', recruitment_views.recruitment_job_bulk_delete, name='recruitment_job_bulk_delete'),
    path('recruitment/jobs/create/', recruitment_views.recruitment_job_create, name='recruitment_job_create'),
    path('recruitment/jobs/<int:pk>/', recruitment_views.recruitment_job_detail, name='recruitment_job_detail'),
    path('recruitment/jobs/<int:pk>/update/', recruitment_views.recruitment_job_update, name='recruitment_job_update'),
    path('recruitment/jobs/<int:pk>/delete/', recruitment_views.recruitment_job_delete, name='recruitment_job_delete'),
    path('recruitment/pipeline/', recruitment_views.recruitment_pipeline, name='recruitment_pipeline'),
    path('recruitment/pipeline/<int:pk>/move/', recruitment_views.recruitment_pipeline_move, name='recruitment_pipeline_move'),
    path('recruitment/applications/<int:pk>/', recruitment_views.recruitment_application_detail, name='recruitment_application_detail'),
    path('recruitment/applications/<int:pk>/delete/', recruitment_views.recruitment_application_delete, name='recruitment_application_delete'),
    path('recruitment/applications/export/', recruitment_views.recruitment_application_export, name='recruitment_application_export'),
    path('recruitment/applications/import/', recruitment_views.recruitment_application_import, name='recruitment_application_import'),
    path('recruitment/applications/import/sample/', recruitment_views.recruitment_application_import_sample, name='recruitment_application_import_sample'),
    path('recruitment/my-candidates/', recruitment_views.recruitment_my_candidates, name='recruitment_my_candidates'),
    path('recruitment/settings/', recruitment_views.recruitment_settings, name='recruitment_settings'),
    # Public careers page for one office - no login required.
    path('careers/<slug:slug>/', recruitment_public_views.recruitment_public_careers_page, name='recruitment_public_careers_page'),

    # Invoicing
    path('invoices/', invoice_views.invoice_list, name='invoice_list'),
    path('invoices/create/', invoice_views.invoice_create, name='invoice_create'),
    path('invoices/<int:pk>/edit/', invoice_views.invoice_create, name='invoice_update'),
    path('invoices/<int:pk>/delete/', invoice_views.invoice_delete, name='invoice_delete'),
    path('invoices/<int:pk>/cancel/', invoice_views.invoice_cancel, name='invoice_cancel'),
    path('invoices/<int:pk>/download/', invoice_views.invoice_download_pdf, name='invoice_download_pdf'),
    path('invoices/<int:pk>/preview/', invoice_views.invoice_preview_pdf, name='invoice_preview_pdf'),
    path('invoices/clients/', invoice_views.clients_view, name='invoice_clients'),
    path('invoices/clients/<int:pk>/update/', invoice_views.client_update, name='invoice_client_update'),
    path('invoices/clients/<int:pk>/toggle/', invoice_views.client_toggle, name='invoice_client_toggle'),
    path('invoices/clients/<int:pk>/delete/', invoice_views.client_delete, name='invoice_client_delete'),
    path('invoices/settings/', invoice_views.invoice_settings, name='invoice_settings'),

    # Employee attribute types (Designation / Department / Employment Type)
    path('employee-settings/<str:kind>/', views.admin_employee_attribute_types, name='admin_employee_attribute_types'),
    path('employee-settings/<str:kind>/<int:pk>/update/', views.admin_employee_attribute_type_update, name='admin_employee_attribute_type_update'),
    path('employee-settings/<str:kind>/<int:pk>/toggle/', views.admin_employee_attribute_type_toggle, name='admin_employee_attribute_type_toggle'),
    path('employee-settings/<str:kind>/<int:pk>/delete/', views.admin_employee_attribute_type_delete, name='admin_employee_attribute_type_delete'),
    path('document-approvals/', views.document_approvals, name='document_approvals'),


    # office registration 
    # Office registration & approval (multi-tenant)
    path('register-office/', views.office_register, name='office_register'),
    path('office-status/', views.office_status, name='office_status'),
    path('platform/office-approvals/', views.platform_office_approvals, name='platform_office_approvals'),
    path('platform/offices/<int:pk>/', views.platform_office_detail, name='platform_office_detail'),
    path('platform/document-types/', views.platform_document_types, name='platform_document_types'),
    path('platform/document-types/<int:pk>/update/', views.platform_document_type_update, name='platform_document_type_update'),
    path('platform/document-types/<int:pk>/toggle/', views.platform_document_type_toggle, name='platform_document_type_toggle'),
    path('platform/document-types/<int:pk>/delete/', views.platform_document_type_delete, name='platform_document_type_delete'),
    path('platform/dashboard/', views.platform_dashboard, name='platform_dashboard'),
    path('platform/profile/', views.platform_profile, name='platform_profile'),
    path('platform/plans/', subscription_views.platform_plans, name='platform_plans'),
    path('platform/plans/<int:pk>/update/', subscription_views.platform_plan_update, name='platform_plan_update'),
    path('platform/plans/<int:pk>/toggle/', subscription_views.platform_plan_toggle, name='platform_plan_toggle'),
    path('platform/plans/<int:pk>/delete/', subscription_views.platform_plan_delete, name='platform_plan_delete'),
    path('platform/offices/<int:pk>/set-plan/', subscription_views.platform_office_set_plan, name='platform_office_set_plan'),
    path('subscription/choose-plan/', subscription_views.choose_plan, name='choose_plan'),
    path('api/plans/', subscription_views.public_plans_api, name='public_plans_api'),

    # attendance rule 

    path('attendance/rule-settings/', views.attendance_rule_settings, name='attendance_rule_settings'),
]
