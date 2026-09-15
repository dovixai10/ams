"""
URL routing for the mobile attendance app API, matching
DOVIX_AI_Attendance_Backend_API_Spec.pdf v1.0 section 15 exactly (path,
method, and the 45-endpoint count). Mounted at the project root so paths
resolve to exactly /api/v1/... as the spec requires - see config/urls.py.
"""
from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

from . import mobile_auth_api as auth
from . import mobile_profile_api as profile
from . import mobile_face_api as face
from . import mobile_attendance_api as attendance
from . import mobile_leave_api as leave
from . import mobile_documents_api as documents
from . import mobile_notifications_api as notifications
from . import mobile_payroll_api as payroll
from . import mobile_reports_api as reports
from . import mobile_misc_api as misc
from . import mobile_tasks_api as tasks

app_name = 'mobile_api'

urlpatterns = [
    # OpenAPI schema + interactive docs (self-hosted, not a third-party page)
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='mobile_api:schema'), name='swagger_ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='mobile_api:schema'), name='redoc'),

    # 4. Authentication (5)
    path('api/v1/auth/login', auth.LoginView.as_view(), name='auth_login'),
    path('api/v1/auth/refresh', auth.RefreshView.as_view(), name='auth_refresh'),
    path('api/v1/auth/logout', auth.LogoutView.as_view(), name='auth_logout'),
    path('api/v1/auth/forgot-password', auth.ForgotPasswordView.as_view(), name='auth_forgot_password'),
    path('api/v1/auth/reset-password', auth.ResetPasswordView.as_view(), name='auth_reset_password'),

    # 5. Employee profile (4)
    path('api/v1/employees/me', profile.MeSummaryView.as_view(), name='me_summary'),
    path('api/v1/employees/me/profile', profile.ProfileView.as_view(), name='me_profile'),
    path('api/v1/employees/me/avatar', profile.AvatarUploadView.as_view(), name='me_avatar'),

    # 6. Face ID (3)
    path('api/v1/employees/me/face-id', face.FaceIdView.as_view(), name='me_face_id'),

    # 6b. Face Update Requests (2) - beyond the original spec, mirrors the
    # web app's admin-gated re-registration workflow on mobile too.
    path('api/v1/face-update-requests', face.FaceUpdateRequestsView.as_view(), name='face_update_requests'),

    # 7. Attendance check-in/out (3)
    path('api/v1/attendance/today', attendance.TodayView.as_view(), name='attendance_today'),
    path('api/v1/attendance/check-in', attendance.CheckInView.as_view(), name='attendance_check_in'),
    path('api/v1/attendance/check-out', attendance.CheckOutView.as_view(), name='attendance_check_out'),

    # 8. Attendance calendar/history/stats (4)
    path('api/v1/attendance/summary', attendance.SummaryView.as_view(), name='attendance_summary'),
    path('api/v1/attendance/calendar', attendance.CalendarView.as_view(), name='attendance_calendar'),
    path('api/v1/attendance/day/<str:date>', attendance.DayDetailView.as_view(), name='attendance_day'),
    path('api/v1/attendance/history', attendance.HistoryView.as_view(), name='attendance_history'),

    # 9. Leave management (4)
    path('api/v1/leave/balances', leave.BalancesView.as_view(), name='leave_balances'),
    path('api/v1/leave/requests', leave.LeaveRequestsView.as_view(), name='leave_requests'),
    path('api/v1/leave/requests/<int:id>', leave.CancelLeaveRequestView.as_view(), name='leave_request_cancel'),

    # 10. Document verification / KYC (4)
    path('api/v1/employees/me/documents', documents.DocumentsView.as_view(), name='me_documents'),
    path('api/v1/employees/me/documents/<str:document_id>', documents.DocumentUploadView.as_view(), name='me_document_upload'),
    path('api/v1/employees/me/documents/<str:document_id>/preview', documents.DocumentPreviewView.as_view(), name='me_document_preview'),
    path('api/v1/documents/summary', documents.DocumentsSummaryView.as_view(), name='documents_summary'),

    # 11. Notifications (5)
    path('api/v1/notifications', notifications.NotificationsListView.as_view(), name='notifications_list'),
    path('api/v1/notifications/<int:id>/read', notifications.MarkNotificationReadView.as_view(), name='notification_mark_read'),
    path('api/v1/notifications/mark-all-read', notifications.MarkAllNotificationsReadView.as_view(), name='notifications_mark_all_read'),
    path('api/v1/notifications/unread-count', notifications.UnreadCountView.as_view(), name='notifications_unread_count'),
    path('api/v1/notifications/register-device', notifications.RegisterDeviceView.as_view(), name='notifications_register_device'),

    # 12. Payroll and salary slips (5)
    path('api/v1/payroll/available-months', payroll.AvailableMonthsView.as_view(), name='payroll_available_months'),
    path('api/v1/payroll/slips/<str:year_month>', payroll.SlipDetailView.as_view(), name='payroll_slip_detail'),
    path('api/v1/payroll/slips', payroll.SlipListView.as_view(), name='payroll_slip_list'),
    path('api/v1/payroll/slips/<str:year_month>/pdf', payroll.SlipPdfView.as_view(), name='payroll_slip_pdf'),
    path('api/v1/payroll/slips/<str:year_month>/email', payroll.SlipEmailView.as_view(), name='payroll_slip_email'),

    # 13. Reports and analytics (1)
    path('api/v1/reports/monthly-summary', reports.MonthlySummaryView.as_view(), name='reports_monthly_summary'),

    # 14. Shift, holidays, employee services (7)
    path('api/v1/employees/me/shift', misc.ShiftView.as_view(), name='me_shift'),
    path('api/v1/employees/me/achievements', misc.AchievementsView.as_view(), name='me_achievements'),
    path('api/v1/holidays', misc.HolidaysView.as_view(), name='holidays'),
    path('api/v1/shift-swap-requests', misc.ShiftSwapRequestView.as_view(), name='shift_swap_requests'),
    path('api/v1/expense-claims', misc.ExpenseClaimView.as_view(), name='expense_claims'),
    path('api/v1/hr-tickets', misc.HRTicketView.as_view(), name='hr_tickets'),
    path('api/v1/company-policies', misc.CompanyPoliciesView.as_view(), name='company_policies'),

    # 16. Tasks & Projects (5) - beyond the original spec, mirrors the web
    # app's employee task board (view/self-create tasks, post status
    # updates, browse projects you're a team member or manager of).
    path('api/v1/tasks', tasks.TasksView.as_view(), name='tasks_list'),
    path('api/v1/tasks/<int:id>', tasks.TaskDetailView.as_view(), name='task_detail'),
    path('api/v1/tasks/<int:id>/updates', tasks.TaskStatusUpdateView.as_view(), name='task_status_update'),
    path('api/v1/projects', tasks.MyProjectsView.as_view(), name='my_projects'),
]
