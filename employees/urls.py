from django.urls import path, include
from . import views, holiday_views, api_views, leave_views, attendance_admin_views, drf_views

app_name = 'employees'

urlpatterns = [
    # Root URL - public marketing landing page (signed-in users are bounced to their dashboard)
    path('', views.landing_page, name='home'),

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


    # office registration 
    # Office registration & approval (multi-tenant)
    path('register-office/', views.office_register, name='office_register'),
    path('office-status/', views.office_status, name='office_status'),
    path('platform/office-approvals/', views.platform_office_approvals, name='platform_office_approvals'),

    # attendance rule 

    path('attendance/rule-settings/', views.attendance_rule_settings, name='attendance_rule_settings'),
]
