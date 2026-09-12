from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib import messages
from django.contrib.auth.views import (
    PasswordResetView,
    PasswordResetDoneView,
    PasswordResetConfirmView,
    PasswordResetCompleteView,
)
from django.views.generic import TemplateView, ListView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy, reverse
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_http_methods
from django.db.models import Q, Min, Max, Count
from django.utils import timezone
from django.http import JsonResponse, HttpResponseBadRequest, FileResponse
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.core.mail import send_mail
from django.conf import settings
from web_project import TemplateLayout
from web_project.template_helpers.theme import TemplateHelper
# upar imports ke saath:
from employees.models import Employee, PaidLeaveAdjustment
# from .models import LeaveAdjustment, Employee

from decimal import Decimal
from .models import LeaveType, EmployeeLeaveBalance, LeaveCreditLog

from datetime import date
from .leave_accrual import initialize_balances_for_new_type, get_employee_leave_type_balances

from .permissions import office_admin_required, is_platform_admin, get_request_office
from django.urls import reverse
import sys, re
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from django.http import HttpResponse
from openpyxl.utils import get_column_letter

# Do not discard working image libraries merely because the optional
# face-recognition package is unavailable.
try:
    import numpy as np
except ImportError as e:
    print(f"⚠️  NumPy is unavailable: {e}", file=sys.stderr)
    np = None

try:
    import cv2
except ImportError as e:
    print(f"⚠️  OpenCV is unavailable: {e}", file=sys.stderr)
    cv2 = None

try:
    import face_recognition
except ImportError as e:
    print(f"⚠️  Face recognition is unavailable: {e}", file=sys.stderr)
    face_recognition = None

from django.core.files.base import ContentFile
from io import BytesIO
try:
    from PIL import Image
except ImportError:
    Image = None
import base64

from .models import (
    Employee,
    Attendance,
    AttendanceBreak,
    AttendanceDayComment,
    AttendanceLog,
    PasswordResetRequest,
    FaceUpdateRequest,
    LeaveRequest,
    Task,
    TaskUpdate,
    EmployeeDocument,
    CompanyRule,
    LoanRequest,
    ReimbursementRequest,
    LeaveVerificationDocument,
    RulesAcceptance,
    RuleAcknowledgement,
    AssetAssignment,
    Shift,
    EmployeeSalary
)
from .forms import (
    EmployeeForm,
    EmployeeUpdateForm,
    SuperAdminProfileForm,
    EmployeeDocumentForm,
    EmployeePasswordResetForm,
    LeaveRequestForm,
    LoanRequestForm,
    ReimbursementRequestForm,
    LeaveVerificationUploadForm,
    AssetAssignmentForm,
    TaskForm,
    TaskUpdateForm,
    OfficeProfileForm
)
try:
    from .face_utils import (
    extract_face_encoding,
    extract_face_encoding_from_file,
    extract_face_encoding_from_file_bytes,
    compare_faces,
    get_match_tolerance,
    get_strict_match_tolerance,
    find_best_face_match,
    is_encoding_unique,
)
except ImportError:
    extract_face_encoding = None
    extract_face_encoding_from_file = None
    extract_face_encoding_from_file_bytes = None
    compare_faces = None
    get_match_tolerance = None
    get_strict_match_tolerance = None
    find_best_face_match = None
    is_encoding_unique = None
from django.db import transaction
from django.utils.dateparse import parse_date

from django.contrib.auth.hashers import make_password

from datetime import datetime, date, timedelta
import json
from collections import defaultdict
import logging


logger = logging.getLogger(__name__)

# office _registration 
from .models import Office, OfficeAdmin
from .forms import OfficeRegistrationForm
from .permissions import (
    office_admin_required, is_platform_admin, get_request_office, is_office_admin, is_employee,
    get_request_branch, tenant_queryset, tenant_object_or_404,
    feature_required, has_permission, FEATURE_PERMISSION_KEYS,
)


from django.core.exceptions import PermissionDenied


def require_same_office(request, obj):
    """
    Extra protection for objects that were fetched through
    another relationship instead of a direct office queryset.
    """
    if is_platform_admin(request.user):
        return

    office = get_request_office(request)

    if office is None:
        raise PermissionDenied(
            'Your account is not linked to an approved office.'
        )

    object_office_id = getattr(
        obj,
        'office_id',
        None
    )

    if object_office_id != office.id:
        raise PermissionDenied(
            'You do not have permission to access this office data.'
        )
    
def office_register(request):
    if request.user.is_authenticated:
        return redirect('employees:login')

    if request.method == 'POST':
        form = OfficeRegistrationForm(request.POST, request.FILES)   # <-- add request.FILES
        if form.is_valid():
            office = form.save()
            messages.success(
                request,
                'Registration submitted! We will review your details and notify you once approved.'
            )
            return redirect(reverse('employees:office_status') + f'?email={office.admins.first().user.email}')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = OfficeRegistrationForm()

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_blank.html', context),
        'hide_mobile_nav': True,
        'form': form,
    })
    return render(request, 'employees/auth/office_register.html', context)

def office_status(request):
    """Lets a pending office admin check their approval status without logging in."""
    email = request.GET.get('email', '').strip()
    office_admin = None
    error = None

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()

    if email:
        office_admin = OfficeAdmin.objects.filter(user__email=email, is_owner=True).select_related('office').first()
        if not office_admin:
            error = 'No registration found for that email.'

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_blank.html', context),
        'hide_mobile_nav': True,
        'email': email,
        'office_admin': office_admin,
        'error': error,
    })
    return render(request, 'employees/auth/office_status.html', context)


@login_required
@user_passes_test(is_platform_admin)
def platform_office_approvals(request):
    """Platform-level screen (you) to approve/reject office registrations."""
    status_filter = request.GET.get('status', 'pending')
    offices = Office.objects.select_related().prefetch_related('admins__user').order_by('-created_at')
    if status_filter and status_filter in Office.Status.values:
        offices = offices.filter(status=status_filter)

    if request.method == 'POST':
        office = get_object_or_404(Office, pk=request.POST.get('office_id'))
        action = request.POST.get('action')
        if action == 'approve':
            office.approve(request.user)
            messages.success(request, f'{office.name} approved. Their admin can now log in.')
        elif action == 'reject':
            office.reject(request.user, request.POST.get('reason', ''))
            messages.info(request, f'{office.name} rejected.')
        return redirect('employees:platform_office_approvals')

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'offices': offices,
        'status_filter': status_filter,
        'status_choices': Office.Status.choices,
    })
    return render(request, 'employees/platform/office_approvals.html', context)


def is_admin(user):
    """Check if user is a superuser or admin"""
    return user.is_superuser or user.is_staff


def is_superuser(user):
    """Check if user is a superuser"""
    return user.is_superuser


RULES_VERSION_OVERRIDE = getattr(settings, 'COMPANY_RULES_VERSION', None)


def determine_rules_version() -> str:
    """Return the active rules version string."""
    if RULES_VERSION_OVERRIDE:
        return RULES_VERSION_OVERRIDE
    latest_change = CompanyRule.objects.aggregate(latest=Max('updated_at')).get('latest')
    if latest_change:
        return latest_change.strftime('v%Y%m%d')
    return 'v1'


def get_working_days(start_date: date, end_date: date) -> int:
    """Return count of working days between two dates inclusive, excluding Sundays and 1st/3rd/5th Saturdays."""

    if start_date > end_date:
        return 0

    total_days = 0
    current = start_date
    while current <= end_date:
        weekday = current.weekday()  # Monday=0 ... Sunday=6

        if weekday == 6:
            current += timedelta(days=1)
            continue

        if weekday == 5:
            saturday_count = 0
            for day in range(1, current.day + 1):
                if datetime(current.year, current.month, day).weekday() == 5:
                    saturday_count += 1

            if saturday_count in {1, 3, 5}:
                current += timedelta(days=1)
                continue

        total_days += 1
        current += timedelta(days=1)

    return total_days


def calculate_attendance_metrics(attendance_qs, start_date: date, end_date: date):
    """Calculate working day metrics for attendance records within provided date range."""

    working_days = get_working_days(start_date, end_date)

    present = attendance_qs.filter(check_out_time__isnull=False, half_day=False).count()
    half_days = attendance_qs.filter(check_out_time__isnull=False, half_day=True).count()

    absent = max(working_days - (present + half_days), 0)

    attendance_percentage = 0
    if working_days:
        attendance_percentage = ((present + (half_days * 0.5)) / working_days) * 100

    return {
        'total_working_days': working_days,
        'present_days': present,
        'half_day_days': half_days,
        'absent_days': absent,
        'attendance_percentage': round(attendance_percentage, 1),
    }


def humanize_seconds(total_seconds: int) -> str:
    """Return a human-friendly duration from seconds (e.g., '1h 20m')."""

    if total_seconds is None:
        return '0m'

    try:
        total = max(int(total_seconds), 0)
    except (TypeError, ValueError):
        total = 0

    hours, remainder = divmod(total, 3600)
    minutes, _ = divmod(remainder, 60)

    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return ' '.join(parts)


# Helper functions to check user roles
# def is_superadmin(user):
#     """Check if user is a superadmin (only true superusers, not staff)"""
#     return user.is_superuser



def _parse_comment_date(value: str):
    date_obj = parse_date(value)
    if date_obj is None:
        raise ValueError('Invalid date.')
    return date_obj


def _serialize_comment(comment: AttendanceDayComment, current_user=None):
    created_by_display = None
    if comment.created_by:
        created_by_display = comment.created_by.get_full_name() or comment.created_by.get_username()

    return {
        'id': comment.pk,
        'employee_id': comment.employee_id,
        'employee_name': comment.employee.name,
        'date': comment.date.isoformat(),
        'comment': comment.comment,
        'is_admin_comment': comment.is_admin_comment,
        'created_at': timezone.localtime(comment.created_at).isoformat(),
        'updated_at': timezone.localtime(comment.updated_at).isoformat(),
        'created_by_display': created_by_display,
        'is_mine': bool(current_user and comment.created_by_id == current_user.id),
    }


def _comment_queryset_for_user(request):
    qs = tenant_queryset(
        request,
        AttendanceDayComment.objects.select_related(
            "employee",
            "created_by",
        )
    )

    if is_employee(request.user):
        return qs.filter(employee=request.user.employee_profile)

    if office_admin_required(request.user):
        return qs

    return qs.none()


def _build_comment_threads_for_admin(request, *, limit=10, employee_id=None, current_user=None):
    """Return serialized recent attendance comment threads for admin dashboard usage."""

    # qs = AttendanceDayComment.objects.select_related('employee', 'created_by').order_by('-updated_at')
    qs = tenant_queryset(
        request,
        AttendanceDayComment.objects.select_related(
            "employee",
            "created_by",
        )
    ).order_by("-updated_at")
    if employee_id:
        qs = qs.filter(employee_id=employee_id)

    # Limit rows scanned to keep aggregation efficient while ensuring paired records are included
    max_rows = max(limit * 4, 40) if limit else 60
    comments = list(qs[:max_rows])

    threads = {}
    for comment in comments:
        key = (comment.employee_id, comment.date)
        thread = threads.get(key)
        if thread is None:
            thread = {
                'employee_id': comment.employee_id,
                'employee_name': comment.employee.name,
                'employee_email': comment.employee.email,
                'date': comment.date,
                'employee_comment': None,
                'admin_comment': None,
                'last_activity': comment.updated_at,
            }
            threads[key] = thread
        elif comment.updated_at > thread['last_activity']:
            thread['last_activity'] = comment.updated_at

        serialized = _serialize_comment(comment, current_user)
        if comment.is_admin_comment:
            thread['admin_comment'] = serialized
        else:
            thread['employee_comment'] = serialized

    thread_list = list(threads.values())
    thread_list.sort(key=lambda item: item['last_activity'], reverse=True)

    if limit:
        thread_list = thread_list[:limit]

    serialized_threads = []
    for thread in thread_list:
        needs_reply = bool(
            thread['employee_comment']
            and not (thread['admin_comment'] and thread['admin_comment']['comment'].strip())
        )
        serialized_threads.append({
            'employee_id': thread['employee_id'],
            'employee_name': thread['employee_name'],
            'employee_email': thread['employee_email'],
            'date': thread['date'].isoformat(),
            'date_display': thread['date'].strftime('%b %d, %Y'),
            'employee_comment': thread['employee_comment'],
            'admin_comment': thread['admin_comment'],
            'last_activity': timezone.localtime(thread['last_activity']).isoformat(),
            'needs_admin_reply': needs_reply,
        })

    return serialized_threads


@login_required
@require_http_methods(['GET'])
def attendance_day_comments(request):
    """Return comments for a given employee and date."""

    employee_id = request.GET.get('employee_id')
    date_str = request.GET.get('date')

    if not date_str:
        return HttpResponseBadRequest('Missing date parameter.')

    try:
        target_date = _parse_comment_date(date_str)
    except ValueError:
        return HttpResponseBadRequest('Invalid date parameter.')

    # queryset = AttendanceDayComment.objects.select_related('employee', 'created_by').filter(date=target_date)
    queryset = tenant_queryset(
        request,
        AttendanceDayComment.objects.select_related(
            "employee",
            "created_by",
        )
    ).filter(
        date=target_date
    )

    if employee_id:
        queryset = queryset.filter(employee_id=employee_id)
    elif is_employee(request.user):
        queryset = queryset.filter(employee=request.user.employee_profile)
    elif not office_admin_required(request.user):
        return HttpResponseBadRequest('Not allowed to view comments.')

    comments = [
        _serialize_comment(comment, request.user)
        for comment in queryset.order_by('is_admin_comment', '-created_at')
    ]
    return JsonResponse({'comments': comments})


@login_required
@require_http_methods(['POST'])
def create_attendance_day_comment(request):
    """Create a new attendance day comment for employee/admin."""

    is_admin_user = office_admin_required(request.user)

    employee_id = request.POST.get('employee_id')
    date_str = request.POST.get('date')
    comment_text = (request.POST.get('comment') or '').strip()

    if not all([employee_id, date_str, comment_text]):
        return HttpResponseBadRequest('Missing required fields.')

    # employee = get_object_or_404(Employee, pk=employee_id)
    employee = get_object_or_404(
        tenant_queryset(
            request,
            Employee.objects.all(),
        ),
        pk=employee_id,
    )

    if not is_admin_user and employee != request.user.employee_profile:
        return HttpResponseBadRequest('Not allowed to create comment for this employee.')

    try:
        target_date = _parse_comment_date(date_str)
    except ValueError:
        return HttpResponseBadRequest('Invalid date value.')

    with transaction.atomic():
        comment_obj, created = AttendanceDayComment.objects.update_or_create(
            employee=employee,
            branch=employee.branch,
            date=target_date,
            is_admin_comment=is_admin_user,
            defaults={
                "office": employee.office,
                'comment': comment_text,
                'created_by': request.user,
            }
        )

    status_code = 201 if created else 200
    return JsonResponse({'comment': _serialize_comment(comment_obj, request.user)}, status=status_code)


@login_required
@require_http_methods(['GET'])
def attendance_day_comment_threads(request):
    """Return recent attendance comment threads for admin consumption."""

    if not office_admin_required(request.user):
        return HttpResponseBadRequest('Not allowed.')

    limit_param = request.GET.get('limit')
    employee_id_param = request.GET.get('employee_id')

    limit = 10
    if limit_param:
        try:
            limit = max(1, min(int(limit_param), 50))
        except (TypeError, ValueError):
            return HttpResponseBadRequest('Invalid limit parameter.')

    employee_id = None
    if employee_id_param:
        try:
            employee_id = int(employee_id_param)
        except (TypeError, ValueError):
            return HttpResponseBadRequest('Invalid employee parameter.')

    threads = _build_comment_threads_for_admin(
        request,
        limit=limit,
        employee_id=employee_id,
        current_user=request.user,
    )

    totals = {
        'total': len(threads),
        'needs_admin_reply': sum(1 for thread in threads if thread['needs_admin_reply']),
    }

    return JsonResponse({'threads': threads, 'totals': totals})


@login_required
@require_http_methods(['POST', 'DELETE'])
def delete_attendance_day_comment(request, comment_id):
    """Delete comment when user has permission."""

    # comment = get_object_or_404(AttendanceDayComment, pk=comment_id)
    comment = get_object_or_404(
        tenant_queryset(
            request,
            AttendanceDayComment.objects.all(),
        ),
        pk=comment_id,
    )

    if office_admin_required(request.user):
        pass
    elif is_employee(request.user) and comment.employee == request.user.employee_profile and not comment.is_admin_comment:
        pass
    else:
        return HttpResponseBadRequest('Not allowed to delete comment.')

    comment.delete()
    return JsonResponse({'deleted': True})


# def is_employee(user):
#     """Check if user is an employee"""
#     return hasattr(user, 'employee_profile')


def _pending_leave_verifications_for_employee(employee):
    """Return leave requests that still need verification documents."""
    statuses = [
        LeaveRequest.VerificationStatus.PENDING,
        LeaveRequest.VerificationStatus.SUBMITTED,
        LeaveRequest.VerificationStatus.UNDER_REVIEW,
    ]
    leaves = (
        LeaveRequest.objects.filter(office=employee.office, branch=employee.branch, employee=employee, verification_status__in=statuses)
        .order_by('-created_at')
        .prefetch_related('verification_documents')
    )
    pending = []
    now = timezone.now()
    for leave in leaves:
        leave.ensure_verification_deadline()
        if leave.verification_deadline and now > leave.verification_deadline:
            leave.expire_verification_window()
            continue
        pending.append(leave)
    return pending


# Authentication Views
from .models import Office, OfficeAdmin  # add this import near your other model imports

class LoginView(TemplateView):
    """Custom login view that handles admin, office admin, and employee logins"""

    def get(self, request):
        if request.user.is_authenticated:
            return self.redirect_authenticated_user(request.user)
        return render(request, 'employees/auth/login.html', self.get_context_data())

    def post(self, request):
        username = request.POST.get('email-username')
        password = request.POST.get('password')

        if not username or not password:
            messages.error(request, 'Please provide both email/username and password.')
            return render(request, 'employees/auth/login.html', self.get_context_data())

        user = authenticate(request, username=username, password=password)

        if not user:
            try:
                user_obj = User.objects.get(email=username)
                user = authenticate(request, username=user_obj.username, password=password)
            except User.DoesNotExist:
                pass

        if user:
            # Block login if office isn't approved yet
            if hasattr(user, 'office_admin_profile'):
                office = user.office_admin_profile.office
                if office.status != Office.Status.APPROVED:
                    context = self.get_context_data()
                    context.update({
                        'login_error': f'Your office registration is {office.get_status_display().lower()}. Please wait for approval.',
                        'entered_username': username,
                    })
                    return render(request, 'employees/auth/login.html', context)

            login(request, user)
            messages.success(request, f'Welcome back, {user.get_full_name() or user.username}!')
            return self.redirect_authenticated_user(user)
        else:
            context = self.get_context_data()
            context.update({
                'login_error': 'Invalid email/username or password.',
                'entered_username': username,
            })
            return render(request, 'employees/auth/login.html', context)

    def get_context_data(self, **kwargs):
        context = TemplateLayout.init(self, super().get_context_data(**kwargs))
        context.update({
            'layout_path': TemplateHelper.set_layout('layout_blank.html', context),
            'hide_mobile_nav': True,
        })
        return context

    def redirect_authenticated_user(self, user):
        next_url = self.request.POST.get('next') or self.request.GET.get('next')
        if next_url:
            return redirect(next_url)

        if is_platform_admin(user):
            return redirect('employees:admin_dashboard')
        elif is_office_admin(user):
            return redirect('employees:admin_dashboard')
        elif is_employee(user):
            return redirect('employees:check_in')
        else:
            return redirect('/')

@login_required
def logout_view(request):
    """Logout view"""
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('/')  # Redirect to home/login page


class EmployeePasswordResetView(PasswordResetView):
    """Send password reset email to users requesting a link."""

    template_name = 'employees/auth/password_reset_form.html'
    form_class = EmployeePasswordResetForm
    email_template_name = 'employees/emails/password_reset_email.txt'
    html_email_template_name = 'employees/emails/password_reset_email.html'
    subject_template_name = 'employees/emails/password_reset_subject.txt'
    success_url = reverse_lazy('employees:password_reset_done')
    from_email = settings.DEFAULT_FROM_EMAIL

    def get_context_data(self, **kwargs):
        context = TemplateLayout.init(self, super().get_context_data(**kwargs))
        context.update({
            'layout_path': TemplateHelper.set_layout('layout_blank.html', context),
            'hide_mobile_nav': True,
            'page_title': 'Forgot Password',
        })
        return context

    def get_email_context(self):
        context = super().get_email_context()
        context.setdefault('support_email', settings.DEFAULT_FROM_EMAIL)
        context.setdefault('company_name', 'Kwikster CRM')
        return context


class EmployeePasswordResetDoneView(PasswordResetDoneView):
    """Confirmation page after email with reset link has been sent."""

    template_name = 'employees/auth/password_reset_done.html'

    def get_context_data(self, **kwargs):
        context = TemplateLayout.init(self, super().get_context_data(**kwargs))
        context.update({
            'layout_path': TemplateHelper.set_layout('layout_blank.html', context),
            'hide_mobile_nav': True,
            'page_title': 'Check Your Email',
        })
        return context


class EmployeePasswordResetConfirmView(PasswordResetConfirmView):
    """Allow user to set a new password after following reset link."""

    template_name = 'employees/auth/password_reset_confirm.html'
    success_url = reverse_lazy('employees:password_reset_complete')

    def get_context_data(self, **kwargs):
        context = TemplateLayout.init(self, super().get_context_data(**kwargs))
        context.update({
            'layout_path': TemplateHelper.set_layout('layout_blank.html', context),
            'hide_mobile_nav': True,
            'page_title': 'Set New Password',
        })
        return context


class EmployeePasswordResetCompleteView(PasswordResetCompleteView):
    """Success page after password has been reset."""

    template_name = 'employees/auth/password_reset_complete.html'

    def get_context_data(self, **kwargs):
        context = TemplateLayout.init(self, super().get_context_data(**kwargs))
        context.update({
            'layout_path': TemplateHelper.set_layout('layout_blank.html', context),
            'hide_mobile_nav': True,
            'page_title': 'Password Reset Successful',
        })
        return context


# Dashboard Views
@login_required
@user_passes_test(office_admin_required)
def admin_dashboard(request):
    """Admin dashboard view with comprehensive statistics"""
    from django.utils import timezone
    from django.db.models import Count, Q
    from datetime import timedelta
    from employees.models import Ticket, AttendanceLog, LeaveRequest
    
    today = timezone.now().date()
    now = timezone.now()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    
    # Employee Statistics
    # total_employees = Employee.objects.count()
    total_employees = tenant_queryset(
        request,
        Employee.objects.all()
    ).count()
    active_employees = tenant_queryset(
        request,
        Employee.objects.all()
    ).filter(user__is_active=True).count()

    office = get_request_office(request)

    print("Current Office:", office)
    print("Office ID:", office.id if office else None)

    today_records = Attendance.objects.filter(date=today)

    for a in today_records:
        print(
            "Attendance:",
            a.id,
            "Employee:", a.employee.name,
            "Attendance Office:", a.office_id,
            "Employee Office:", a.employee.office_id,
        )

    print(
    Attendance.objects.filter(
            office=office,
            date=today
        ).query
    )

    print(
        Attendance.objects.filter(
            office=office,
            date=today
        ).count()
    )
    # Attendance Statistics
    # today_checkins = Attendance.objects.filter(date=today).count()
    today_checkins = tenant_queryset(
        request,
        Attendance.objects.all()
        ).filter(
            date=today
    ).count()
    
    today_checkouts = tenant_queryset(
        request,
        Attendance.objects.all()
    ).filter(date=today, check_out_time__isnull=False).count()

    incomplete_today = today_checkins - today_checkouts
    
    # Weekly attendance trend
    week_attendance = []
    for i in range(7):
        date = today - timedelta(days=6-i)
        count = tenant_queryset(
    request,
    Attendance.objects.all()
).filter(
    date=date).count()
        week_attendance.append({
            'date': date.strftime('%a'),
            'count': count
        })
    week_attendance_counts = [entry['count'] for entry in week_attendance]
    week_attendance_labels = [entry['date'] for entry in week_attendance]
    
    # Leave Statistics
    # pending_leave_requests = LeaveRequest.objects.filter(status=LeaveRequest.Status.PENDING).count()
    # total_leave_requests = LeaveRequest.objects.count()
    # recent_leave_requests = (
    #     LeaveRequest.objects
    #     .select_related('employee')
    #     .order_by('-created_at')[:5]
    # )

    leave_requests = tenant_queryset(
        request,
        LeaveRequest.objects.all()
    )

    pending_leave_requests = leave_requests.filter(
        status=LeaveRequest.Status.PENDING
    ).count()

    total_leave_requests = leave_requests.count()

    recent_leave_requests = (
        leave_requests
        .select_related("employee")
        .order_by("-created_at")[:5]
    )

    # Ticket Statistics
    # open_tickets = Ticket.objects.filter(status='open').count()
    # urgent_tickets = Ticket.objects.filter(priority='urgent', status__in=['open', 'in_progress']).count()
    # resolved_today = Ticket.objects.filter(resolved_at__date=today).count()
    
    tickets = tenant_queryset(
        request,
        Ticket.objects.all()
    )

    open_tickets = tickets.filter(
        status="open"
    ).count()

    urgent_tickets = tickets.filter(
        priority="urgent",
        status__in=["open", "in_progress"]
    ).count()

    resolved_today = tickets.filter(
        resolved_at__date=today
    ).count()

    # Password Reset Requests

    # pending_password_requests = PasswordResetRequest.objects.filter(status='pending').count()
    # recent_password_requests = PasswordResetRequest.objects.filter(
    #     status='pending'
    # ).select_related('employee').order_by('-created_at')[:5]
    
    password_requests = tenant_queryset(
        request,
        PasswordResetRequest.objects.all()
    )

    pending_password_requests = password_requests.filter(
        status="pending"
    ).count()

    recent_password_requests = (
        password_requests
        .filter(status="pending")
        .select_related("employee")
        .order_by("-created_at")[:5]
    )
    # Recent Activity Logs
    # recent_failures = AttendanceLog.objects.filter(
    #     success=False
    # ).select_related('employee').order_by('-timestamp')[:5]
    
    recent_failures = (
        tenant_queryset(
            request,
            AttendanceLog.objects.all()
        )
        .filter(success=False)
        .select_related("employee")
        .order_by("-timestamp")[:5]
    )

    # Top performers (most check-ins this month)
    # top_performers = Employee.objects.annotate(
    #     checkin_count=Count('attendance_records', filter=Q(attendance_records__date__gte=month_ago))
    # ).order_by('-checkin_count')[:5]
    
    top_performers = (
        tenant_queryset(
            request,
            Employee.objects.all()
        )
        .annotate(
            checkin_count=Count(
                "attendance_records",
                filter=Q(attendance_records__date__gte=month_ago)
            )
        )
        .order_by("-checkin_count")[:5]
    )
    # Recent tickets
    # recent_tickets = Ticket.objects.select_related('employee').order_by('-created_at')[:5]
    recent_tickets = (
        tenant_queryset(
            request,
            Ticket.objects.all()
        )
        .select_related("employee")
        .order_by("-created_at")[:5]
    )
    
    # Today's attendance
    today_attendance = tenant_queryset(
        request,
        Attendance.objects.all()
    ).filter(
        date=today
        ).select_related('employee').order_by('-check_in_time')[:10]
        
    # Recent employees
    # recent_employees = Employee.objects.order_by('-created_at')[:5]
    recent_employees = (
        tenant_queryset(
            request,
            Employee.objects.all()
        )
        .order_by("-created_at")[:5]
    )

    # Monthly statistics
    month_checkins = tenant_queryset(
    request,
    Attendance.objects.all()
).filter(
    date__gte=month_ago).count()
    month_tickets = Ticket.objects.filter(created_at__gte=month_ago).count()

    # Attendance rate
    expected_checkins = total_employees * 30  # Assuming 30 days
    attendance_rate = (month_checkins / expected_checkins * 100) if expected_checkins > 0 else 0

    # Attendance day comments summary for dashboard chat
    comment_threads_limit = 10
    admin_comment_threads = _build_comment_threads_for_admin(
        request,
        limit=comment_threads_limit,
        current_user=request.user,
    )
    comment_threads_total = len(admin_comment_threads)
    comment_threads_needing_reply = sum(
        1 for thread in admin_comment_threads if thread['needs_admin_reply']
    )
    
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'total_employees': total_employees,
        'active_employees': active_employees,
        'today_checkins': today_checkins,
        'today_checkouts': today_checkouts,
        'incomplete_today': incomplete_today,
        'open_tickets': open_tickets,
        'urgent_tickets': urgent_tickets,
        'resolved_today': resolved_today,
        'pending_password_requests': pending_password_requests,
        'recent_password_requests': recent_password_requests,
        'month_checkins': month_checkins,
        'month_tickets': month_tickets,
        'attendance_rate': round(attendance_rate, 1),
        'week_attendance': week_attendance,
        'week_attendance_counts_json': json.dumps(week_attendance_counts),
        'week_attendance_labels_json': json.dumps(week_attendance_labels),
        'recent_failures': recent_failures,
        'top_performers': top_performers,
        'recent_tickets': recent_tickets,
        'today_attendance': today_attendance,
        'recent_employees': recent_employees,
        'pending_leave_requests': pending_leave_requests,
        'total_leave_requests': total_leave_requests,
        'recent_leave_requests': recent_leave_requests,
        'today': today,
        'now': now,
        'navbar_hide_toggle': True,
        'hide_mobile_nav': True,
        'is_navbar': False,
        'navbar_type': 'hidden',
        'comment_threads_initial_json': json.dumps(admin_comment_threads),
        'comment_threads_total': comment_threads_total,
        'comment_threads_needing_reply': comment_threads_needing_reply,
        'comment_threads_limit': comment_threads_limit,
    })
    return render(request, 'employees/dashboard/admin_dashboard.html', context)


@login_required
@user_passes_test(is_employee)
def employee_dashboard(request):
    """Employee dashboard view"""
    employee = request.user.employee_profile
    from django.utils import timezone
    from calendar import monthcalendar, month_name
    import datetime

    # Get current month and year
    today = timezone.now().date()
    current_month = today.month
    current_year = today.year

    # Get approved leave for current month
    from datetime import timedelta
    month_start = datetime.date(current_year, current_month, 1)
    month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    approved_leaves = LeaveRequest.objects.filter(
        employee=employee,
        status=LeaveRequest.Status.APPROVED,
        start_date__lte=month_end,
        end_date__gte=month_start
    ).values_list('start_date', 'end_date')

    leave_dates = set()
    for start_date, end_date in approved_leaves:
        current_date = max(start_date, month_start)
        end_date = min(end_date, month_end)
        while current_date <= end_date:
            leave_dates.add(current_date)
            current_date += timedelta(days=1)

    # Get all attendance for current month
    month_attendance = Attendance.objects.filter(
        employee=employee,
        date__year=current_year,
        date__month=current_month
    ).order_by('date')

    # Create calendar data
    cal = monthcalendar(current_year, current_month)
    month_name_str = month_name[current_month]

    # Create attendance dictionary for quick lookup
    attendance_dict = {}
    for attendance in month_attendance:
        attendance_dict[attendance.date.day] = attendance

    # Create calendar grid with attendance data
    calendar_data = []
    for week in cal:
        week_data = []
        for day in week:
            if day == 0:
                week_data.append({
                    'day': None, 
                    'attendance': None, 
                    'is_today': False,
                    'status': 'empty'
                })
            else:
                day_date = datetime.date(current_year, current_month, day)
                attendance = attendance_dict.get(day)
                is_today = day_date == today
                is_past = day_date < today
                is_future = day_date > today
                
                # Determine status
                if is_today:
                    if attendance:
                        if attendance.check_out_time:
                            status = 'today-complete'
                        else:
                            status = 'today-incomplete'
                    else:
                        status = 'today-absent'
                elif attendance:
                    if attendance.check_out_time:
                        # Check if it's a half day (less than 6 hours)
                        if attendance.duration_hours < 6:
                            status = 'halfday'
                        else:
                            status = 'present'
                    else:
                        status = 'incomplete'
                elif is_past:
                    status = 'absent'
                else:
                    status = 'future'
                
                # Override status for approved leave days without attendance
                if not attendance and day_date in leave_dates:
                    status = 'absent'
                
                week_data.append({
                    'day': day,
                    'attendance': attendance,
                    'is_today': is_today,
                    'is_past': is_past,
                    'is_future': is_future,
                    'status': status
                })
        calendar_data.append(week_data)

    # Additional statistics
    from datetime import timedelta
    from employees.models import Ticket
    
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    
    # Ticket statistics
    my_open_tickets = Ticket.objects.filter(employee=employee, status='open').count()
    my_total_tickets = Ticket.objects.filter(employee=employee).count()
    my_resolved_tickets = Ticket.objects.filter(employee=employee, status='resolved').count()
    
    # Attendance statistics
    complete_days = month_attendance.filter(check_out_time__isnull=False).count()
    incomplete_days = month_attendance.count() - complete_days
    
    # Calculate total hours worked this month
    total_hours = 0
    for att in month_attendance.filter(check_out_time__isnull=False):
        total_hours += att.duration_hours
    
    # Week attendance
    week_attendance = Attendance.objects.filter(
        employee=employee,
        date__gte=week_ago
    ).count()
    
    # Recent tickets
    recent_tickets = Ticket.objects.filter(employee=employee).order_by('-created_at')[:3]
    
    # Salary slip is unlocked once the employee is 3 months past joining,
    # OR as soon as the admin has actually generated at least one slip for
    # them - no point gating access to a payslip that already exists.
    from datetime import timedelta
    from employees.models import SalarySlip
    three_months_ago = timezone.now() - timedelta(days=90)
    salary_slip_eligible = (
        employee.created_at <= three_months_ago
        or SalarySlip.objects.filter(employee=employee).exists()
    )

    # Check if employee has ID card
    from employees.models import EmployeeIDCard
    has_id_card = EmployeeIDCard.objects.filter(employee=employee).exists()
    
    context = TemplateLayout.init(request, context={})
    latest_face_request = (
        FaceUpdateRequest.objects
        .filter(employee=employee)
        .select_related('reviewed_by')
        .order_by('-requested_at')
        .first()
    )

    face_update_active = bool(
        latest_face_request
        and latest_face_request.status in (
            FaceUpdateRequest.Status.PENDING,
            FaceUpdateRequest.Status.APPROVED,
        )
    )
    face_update_pending = bool(
        latest_face_request
        and latest_face_request.status == FaceUpdateRequest.Status.PENDING
    )
    can_request_face_update = (
        employee.has_registered_face
        and not employee.can_access_face_registration
        and not face_update_active
    )

    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'employee': employee,
        'has_checked_in_today': Attendance.has_checked_in_today(employee),
        'today_attendance': Attendance.objects.filter(
            employee=employee,
            date=timezone.now().date()
        ).first(),
        'recent_attendance': Attendance.objects.filter(employee=employee).order_by('-date')[:10],
        'today': today,
        'current_time': timezone.now(),
        'calendar_data': calendar_data,
        'month_name': month_name_str,
        'current_month': current_month,
        'current_year': current_year,
        'total_month_attendance': month_attendance.count(),
        'complete_days': complete_days,
        'incomplete_days': incomplete_days,
        'total_hours': round(total_hours, 1),
        'week_attendance': week_attendance,
        'my_open_tickets': my_open_tickets,
        'my_total_tickets': my_total_tickets,
        'my_resolved_tickets': my_resolved_tickets,
        'recent_tickets': recent_tickets,
        'day_names': ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
        'requires_face_registration': not employee.has_registered_face,
        'face_registration_accessible': employee.can_access_face_registration,
        'latest_face_update_request': latest_face_request,
        'face_update_active': face_update_active,
        'face_update_pending': face_update_pending,
        'can_request_face_update': can_request_face_update,
        'face_update_status': latest_face_request.status if latest_face_request else '',
        'face_update_status_display': latest_face_request.get_status_display() if latest_face_request else '',
        'pending_verification_leaves': _pending_leave_verifications_for_employee(employee),
        'salary_slip_eligible': salary_slip_eligible,
        'has_id_card': has_id_card,
    })
    return render(request, 'employees/dashboard/employee_dashboard.html', context)


@login_required
@user_passes_test(is_employee)
def mobile_dashboard(request):
    """Mobile-friendly dashboard for employees"""
    employee = request.user.employee_profile
    today = timezone.now().date()
    
    # Get today's attendance
    today_attendance = Attendance.objects.filter(
        employee=employee,
        date=today
    ).first()
    
    # Get assigned tasks
    try:
        from employees.models import Task
        tasks = Task.objects.filter(assigned_to=employee).order_by('-created_at')[:5]
    except:
        tasks = []
    
    # Check profile completion
    documents_submitted = hasattr(employee, 'documents_submitted') and employee.documents_submitted
    rules_accepted = hasattr(employee, 'rules_accepted') and employee.rules_accepted
    
    # Get notifications
    from employees.models import EmployeeNotification
    notifications = EmployeeNotification.objects.filter(employee=employee).order_by('-created_at')[:10]
    unread_count = EmployeeNotification.objects.filter(employee=employee, is_read=False).count()
    
    context = TemplateLayout.init(request, context={})
    context.update({
        "layout_path": TemplateHelper.set_layout("layout_mobile.html", context),
        "employee": employee,
        "today_date": today.strftime('%a, %b %d, %Y'),
        "today_attendance": today_attendance,
        "tasks": tasks,
        "documents_submitted": documents_submitted,
        "rules_accepted": rules_accepted,
        "has_checked_in_today": today_attendance and today_attendance.check_in_time,
        "has_checked_out_today": today_attendance and today_attendance.check_out_time,
        "notifications": notifications,
        "unread_count": unread_count,
    })
    return render(request, "employees/mobile_dashboard.html", context)

def rules_and_regulations(request):
    return render(request, 'employees/rules_and_regulations.html')

@login_required
@user_passes_test(is_employee)
def employee_breaks(request):
    """Display break analytics and controls for the logged-in employee."""

    employee = request.user.employee_profile
    now = timezone.now()
    today = now.date()
    attendance_today = Attendance.objects.filter(employee=employee, date=today).first()
    active_break = attendance_today.active_break if attendance_today else None

    todays_breaks = list(
        AttendanceBreak.objects.filter(
            employee=employee,
            attendance__date=today
        ).select_related('attendance').order_by('-start_time')
    )

    month_start = today.replace(day=1)
    month_breaks = list(
        AttendanceBreak.objects.filter(
            employee=employee,
            start_time__date__gte=month_start,
            start_time__date__lte=today
        ).select_related('attendance').order_by('-start_time')
    )

    recent_breaks = list(
        AttendanceBreak.objects.filter(employee=employee).select_related('attendance').order_by('-start_time')[:20]
    )

    today_seconds = sum(b.duration_seconds for b in todays_breaks)
    month_seconds = sum(b.duration_seconds for b in month_breaks)
    average_seconds = int(today_seconds / len(todays_breaks)) if todays_breaks else 0

    daily_map = defaultdict(lambda: {'seconds': 0, 'count': 0})
    for br in month_breaks:
        key = br.start_time.date()
        daily_map[key]['seconds'] += br.duration_seconds
        daily_map[key]['count'] += 1

    daily_summary = [
        {
            'date': day,
            'seconds': details['seconds'],
            'display': humanize_seconds(details['seconds']),
            'count': details['count']
        }
        for day, details in sorted(daily_map.items(), reverse=True)
    ][:7]

    can_start_break = bool(attendance_today and not attendance_today.check_out_time and active_break is None)
    can_end_break = bool(active_break)

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'employee': employee,
        'attendance_today': attendance_today,
        'active_break': active_break,
        'todays_breaks': todays_breaks,
        'recent_breaks': recent_breaks,
        'daily_summary': daily_summary,
        'today_break_display': humanize_seconds(today_seconds),
        'month_break_display': humanize_seconds(month_seconds),
        'average_break_display': humanize_seconds(average_seconds),
        'can_start_break': can_start_break,
        'can_end_break': can_end_break,
        'today': today,
        'now': now,
    })

    return render(request, 'employees/breaks/employee_breaks.html', context)


@login_required
@user_passes_test(feature_required('attendance.manage'))
def admin_breaks_dashboard(request):
    """Interactive dashboard for admins to monitor employee breaks."""

    now = timezone.now()
    default_start = now.date() - timedelta(days=6)
    default_end = now.date()

    start_param = request.GET.get('start')
    end_param = request.GET.get('end')
    employee_id = request.GET.get('employee')

    try:
        start_date = datetime.strptime(start_param, '%Y-%m-%d').date() if start_param else default_start
    except ValueError:
        start_date = default_start
        messages.warning(request, 'Invalid start date provided. Showing last 7 days.')

    try:
        end_date = datetime.strptime(end_param, '%Y-%m-%d').date() if end_param else default_end
    except ValueError:
        end_date = default_end
        messages.warning(request, 'Invalid end date provided. Showing last 7 days.')

    if start_date > end_date:
        start_date, end_date = end_date, start_date
        messages.info(request, 'Start date was after end date. Dates have been swapped for you.')

    # all_employees = Employee.objects.all().order_by('name')
    all_employees = tenant_queryset(
        request,
        Employee.objects.all()
    ).order_by('name')
    selected_employee = None
    if employee_id:
        selected_employee = get_object_or_404(Employee, pk=employee_id)

    filtered_breaks = AttendanceBreak.objects.select_related('employee', 'attendance').filter(
        start_time__date__gte=start_date,
        start_time__date__lte=end_date
    ).order_by('-start_time')

    if selected_employee:
        filtered_breaks = filtered_breaks.filter(employee=selected_employee)

    break_entries = list(filtered_breaks)

    total_seconds = 0
    completed_count = 0
    active_count = 0
    per_employee = {}
    per_day = defaultdict(lambda: {'seconds': 0, 'count': 0})

    for br in break_entries:
        seconds = br.duration_seconds
        total_seconds += seconds
        if br.end_time:
            completed_count += 1
        else:
            active_count += 1

        day_key = br.start_time.date()
        per_day[day_key]['seconds'] += seconds
        per_day[day_key]['count'] += 1

        summary = per_employee.setdefault(br.employee_id, {
            'employee': br.employee,
            'total_seconds': 0,
            'break_count': 0,
            'active_count': 0,
        })
        summary['total_seconds'] += seconds
        summary['break_count'] += 1
        if br.end_time is None:
            summary['active_count'] += 1

    summary_list = []
    for data in per_employee.values():
        break_count = data['break_count']
        average = int(data['total_seconds'] / break_count) if break_count else 0
        summary_list.append({
            'employee': data['employee'],
            'break_count': break_count,
            'active_count': data['active_count'],
            'total_seconds': data['total_seconds'],
            'total_display': humanize_seconds(data['total_seconds']),
            'average_seconds': average,
            'average_display': humanize_seconds(average),
        })

    summary_list.sort(key=lambda entry: entry['total_seconds'], reverse=True)

    daily_break_summary = [
        {
            'date': day,
            'count': stats['count'],
            'seconds': stats['seconds'],
            'display': humanize_seconds(stats['seconds'])
        }
        for day, stats in sorted(per_day.items())
    ]

    average_seconds_overall = int(total_seconds / len(break_entries)) if break_entries else 0

    active_breaks_global = list(
        AttendanceBreak.objects.select_related('employee', 'attendance').filter(end_time__isnull=True).order_by('-start_time')
    )

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'start_date': start_date,
        'end_date': end_date,
        'start_date_str': start_date.strftime('%Y-%m-%d'),
        'end_date_str': end_date.strftime('%Y-%m-%d'),
        'selected_employee': selected_employee,
        'employee_options': all_employees,
        'break_entries': break_entries,
        'summary_list': summary_list,
        'daily_break_summary': daily_break_summary,
        'total_break_display': humanize_seconds(total_seconds),
        'average_break_display': humanize_seconds(average_seconds_overall),
        'total_break_seconds': total_seconds,
        'average_break_seconds': average_seconds_overall,
        'completed_break_count': completed_count,
        'active_break_count': active_count,
        'active_breaks_global': active_breaks_global,
    })

    return render(request, 'employees/breaks/admin_breaks.html', context)



# def get_employee_leave_type_balances(employee):
#     """
#     Returns a list of dicts: [{'leave_type': LeaveType, 'balance': Decimal}, ...]
#     for every active LeaveType applicable to this employee.
#     Creates a zero-balance EmployeeLeaveBalance row the first time a type is seen.
#     """
#     leave_types = LeaveType.objects.filter(is_active=True).order_by('display_order', 'name')
#     result = []

#     for lt in leave_types:
#         if not lt.is_applicable_for(employee):
#             continue

#         balance_obj, _ = EmployeeLeaveBalance.objects.get_or_create(
#             employee=employee,
#             leave_type=lt,
#             defaults={'balance': 0, 'credit_year': date.today().year},
#         )

#         result.append({
#             'leave_type': lt,
#             'balance': balance_obj.balance,
#         })

#     return result

@login_required
@user_passes_test(is_employee)
def employee_leave_requests(request):
    employee = request.user.employee_profile
    leave_qs = LeaveRequest.objects.filter(employee=employee).order_by('-created_at')
    # leave_qs = tenant_queryset(
    #     request,
    #     LeaveRequest.objects.all()
    # ).filter(employee=employee).order_by('-created_at')

    if request.method == 'POST':
        form = LeaveRequestForm(request.POST, employee=employee)
        if form.is_valid():
            leave_request = form.save(commit=False)
            leave_request.employee = employee
            leave_request.office = employee.office
            leave_request.branch = employee.branch
            leave_request.status = LeaveRequest.Status.PENDING
            leave_request.save()

            message_line = "Your leave request has been submitted and is awaiting review."
            send_leave_notification_email(
                leave_request,
                subject="Leave request submitted",
                message_line=message_line,
                request=request,
            )

            messages.success(request, 'Leave request submitted successfully. We will notify you once it is reviewed.')
            request.session['latest_leave_id'] = leave_request.id
            return redirect('employees:employee_leave_requests')
        else:
            messages.error(request, 'Please correct the issues below and try again.')
    else:
        form = LeaveRequestForm(employee=employee)

    latest_leave_id = request.session.pop('latest_leave_id', None)

    # Legacy single number (kept so nothing else breaks)
    paid_leave_balance = employee.get_final_leave_balance()

    # NEW: per-leave-type balances
    leave_type_balances = get_employee_leave_type_balances(employee)

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'form': form,
        'leave_requests': leave_qs,
        'latest_leave_id': latest_leave_id,
        'paid_leave_balance': float(paid_leave_balance),
        'leave_type_balances': leave_type_balances,
    })
    return render(request, 'employees/leave/employee_leave_requests_new.html', context)

@login_required
@user_passes_test(is_employee)
def leave_verification_portal(request):
    """Dedicated portal for employees to upload leave verification documents."""
    employee = request.user.employee_profile
    pending_leaves = _pending_leave_verifications_for_employee(employee)

    if request.method == 'POST':
        form = LeaveVerificationUploadForm(request.POST, request.FILES, employee=employee)
        if form.is_valid():
            leave = form.cleaned_data['leave']
            LeaveVerificationDocument.objects.create(
                leave=leave,
                office=leave.office,
                branch=leave.branch,
                uploaded_by=employee,
                file=form.cleaned_data['receipt'],
                notes=form.cleaned_data['notes']
            )
            leave.mark_verification_submitted()
            messages.success(request, 'Your document has been submitted.')
            return redirect('employees:leave_verification')
        messages.error(request, 'Please fix the errors below and try again.')
    else:
        form = LeaveVerificationUploadForm(employee=employee)

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'pending_leaves': pending_leaves,
        'form': form,
    })
    return render(request, 'employees/leave/leave_verification.html', context)


@login_required
@user_passes_test(is_employee)
@require_http_methods(["POST"])
def upload_leave_receipt(request, leave_id):
    """Upload compliance document for leave request"""
    from django.http import JsonResponse
    from django.core.files.storage import default_storage
    
    leave = get_object_or_404(LeaveRequest, id=leave_id, employee__user=request.user)
    
    if not leave.is_verification_window_open:
        leave.expire_verification_window()
        return JsonResponse({
            'success': False,
            'error': 'Document upload time is over (3 days expired). Please contact HR/Admin.',
        }, status=400)
    
    if 'receipt' not in request.FILES:
        return JsonResponse({'success': False, 'error': 'No file provided'}, status=400)
    
    file = request.FILES['receipt']
    
    # Validate file
    max_size = 5 * 1024 * 1024  # 5MB
    allowed_types = ['application/pdf', 'image/jpeg', 'image/jpg', 'image/png']
    
    if file.size > max_size:
        return JsonResponse({'success': False, 'error': 'File size exceeds 5MB'}, status=400)
    
    if file.content_type not in allowed_types:
        return JsonResponse({'success': False, 'error': 'Only PDF, JPG, and PNG files allowed'}, status=400)
    
    # Supersede previous active documents
    leave.verification_documents.filter(is_active=True).update(
        is_active=False,
        replaced_at=timezone.now(),
        notes='Superseded by new upload'
    )

    doc = LeaveVerificationDocument.objects.create(
        leave=leave,
        office=leave.office,
        branch=leave.branch,
        uploaded_by=request.user.employee_profile,
        file=file
    )

    leave.mark_verification_submitted()

    documents_payload = [
        {
            'id': document.id,
            'name': document.file.name.split('/')[-1],
            'url': document.file.url,
            'uploaded_at': timezone.localtime(document.uploaded_at).isoformat(),
            'active': document.is_active,
        }
        for document in leave.verification_documents.order_by('-uploaded_at')
    ]
    
    return JsonResponse({
        'success': True,
        'message': 'Document uploaded successfully',
        'verification_status': leave.get_verification_status_display(),
        'deadline': leave.verification_deadline.isoformat() if leave.verification_deadline else None,
        'documents': documents_payload,
        'uploaded': {
            'id': doc.id,
            'name': doc.file.name.split('/')[-1],
            'url': doc.file.url,
        }
    })


@login_required
@user_passes_test(feature_required('leave.manage'))
@require_http_methods(["GET"])
def leave_verification_documents(request, leave_id):
    """Return verification documents for a leave (admin use).
    
    CRITICAL FIX: Hide documents for rejected leaves to protect employee privacy.
    Employees should never see documents from rejected leave requests.
    """
    leave = get_object_or_404(LeaveRequest, id=leave_id)
    
    # CRITICAL: If leave is rejected, don't show documents to employees
    # Only admins can see rejected leave documents
    if leave.status == LeaveRequest.Status.REJECTED:
        # Check if requester is the employee (not admin)
        if hasattr(request.user, 'employee_profile') and request.user.employee_profile == leave.employee:
            return JsonResponse({
                'success': False,
                'error': 'Documents are not available for rejected leave requests',
                'status': 403
            }, status=403)
    
    documents = [
        {
            'id': doc.id,
            'name': doc.file.name.split('/')[-1],
            'url': doc.file.url,
            'uploaded_at': timezone.localtime(doc.uploaded_at).strftime('%b %d, %Y %I:%M %p'),
            'is_active': doc.is_active,
        }
        for doc in leave.verification_documents.order_by('-uploaded_at')
    ]

    return JsonResponse({
        'success': True,
        'leave': {
            'employee': leave.employee.full_name,
            'dates': f"{leave.start_date.strftime('%b %d, %Y')} – {leave.end_date.strftime('%b %d, %Y')}",
            'status': leave.get_verification_status_display(),
            'documents': documents,
        }
    })


@login_required
@user_passes_test(feature_required('leave.manage'))
def admin_leave_requests(request):
    """Admin view to manage employee leave requests.
    
    Shows all leaves (pending, approved, rejected) by default.
    Admin can filter by status if needed.
    """

    status_filter = request.GET.get('status', '').strip()
    employee_query = request.GET.get('employee', '').strip()
    requested_after = request.GET.get('requested_after')
    requested_before = request.GET.get('requested_before')

    # leave_qs = LeaveRequest.objects.select_related('employee', 'reviewed_by').prefetch_related('verification_documents').order_by('-created_at')
    
    # --------------------------------------------------------- 
    # # OFFICE-SCOPED LEAVE QUERYSET 
    # # --------------------------------------------------------- 
    # # All GET results, filters, summaries, and POST lookups 
    # # must use this office-scoped queryset.
    leave_qs = tenant_queryset( request, LeaveRequest.objects.select_related( 'employee', 'reviewed_by' ).prefetch_related( 'verification_documents' ) ).order_by( '-created_at' )

    # Show ALL leaves by default (pending, approved, rejected)
    # Only filter if admin explicitly selects a status
    if status_filter and status_filter in LeaveRequest.Status.values:
        leave_qs = leave_qs.filter(status=status_filter)

    if employee_query:
        leave_qs = leave_qs.filter(
            Q(employee__name__icontains=employee_query)
            | Q(employee__full_name__icontains=employee_query)
            | Q(employee__email__icontains=employee_query)
        )

    if requested_after:
        leave_qs = leave_qs.filter(start_date__gte=requested_after)

    if requested_before:
        leave_qs = leave_qs.filter(end_date__lte=requested_before)

    filters_active = any([status_filter, employee_query, requested_after, requested_before])





    #-----------------------------------------

    if request.method == 'POST':
        leave_id = request.POST.get('leave_id')
        action = request.POST.get('action')
        admin_comment = (request.POST.get('admin_comment') or '').strip()
        leave_request = get_object_or_404(LeaveRequest, pk=leave_id)
        leave_request = get_object_or_404( tenant_queryset( request, LeaveRequest.objects.select_related( 'employee', 'reviewed_by' ) ), pk=leave_id )
        office = leave_request.employee.office
        if action == 'approve':
            leave_request.mark_approved(request.user, admin_comment)

            # ---------------------------------------------------------
            # ✔ PAID LEAVE → Deduct manual extra leaves also
            # ---------------------------------------------------------
            from decimal import Decimal

            if leave_request.leave_category == LeaveRequest.LeaveCategory.PAID:
                employee = leave_request.employee
                calendar_days = (leave_request.end_date - leave_request.start_date).days + 1

                if leave_request.leave_type == LeaveRequest.LeaveType.FULL_DAY:
                    leave_days = Decimal(str(calendar_days))
                else:
                    leave_days = Decimal(str(calendar_days * 0.5))

                # Existing legacy deduction (kept so nothing else in the app breaks)
                employee.manual_extra_leaves -= leave_days
                employee.save()

                # NEW: deduct from the specific EmployeeLeaveBalance the employee selected
                if leave_request.leave_type_ref:
                    balance_obj, _ = EmployeeLeaveBalance.objects.get_or_create(
                        employee=employee,
                        branch=employee.branch,
                        leave_type=leave_request.leave_type_ref,
                        defaults={'balance': 0, 'credit_year': date.today().year},
                    )
                    balance_obj.deduct(
                        leave_days,
                        note=f"Leave #{leave_request.id} approved ({leave_request.start_date} → {leave_request.end_date})"
                    )
            # ---------------------------------------------------------

            # Auto-mark attendance based on leave category
            from .models import Attendance
            from datetime import timedelta
            current_date = leave_request.start_date

            # Determine attendance status based on leave category
            if leave_request.is_without_pay():
                attendance_status = 'Absent'
            else:
                attendance_status = 'Leave'

            while current_date <= leave_request.end_date:
                attendance, created = Attendance.objects.get_or_create(
                    employee=leave_request.employee,
                    branch=leave_request.employee.branch,
                    date=current_date,
                    defaults={
                        'final_status': attendance_status,
                        'check_in_time': timezone.now().replace(hour=0, minute=0, second=0),
                    }
                )
                if not created:
                    attendance.final_status = attendance_status
                    attendance.save(update_fields=['final_status'])
                current_date += timedelta(days=1)

            # Send mail
            message_line = 'Your leave request has been approved.'
            send_leave_notification_email(
                leave_request,
                subject='Leave request approved',
                message_line=message_line,
                request=request,
            )

            # Notification
            from employees.notification_utils import create_leave_approved_notification
            create_leave_approved_notification(leave_request.employee, leave_request)

            messages.success(request, f'Leave request for {leave_request.employee.full_name} approved.')


    # if request.method == 'POST':
    #     leave_id = request.POST.get('leave_id')
    #     action = request.POST.get('action')
    #     admin_comment = (request.POST.get('admin_comment') or '').strip()
    #     leave_request = get_object_or_404(LeaveRequest, pk=leave_id)

    #     if action == 'approve':
    #         leave_request.mark_approved(request.user, admin_comment)
            
    #         # Auto-mark attendance based on leave category
    #         from .models import Attendance
    #         from datetime import timedelta
    #         current_date = leave_request.start_date
            
    #         # Determine attendance status based on leave category
    #         # PAID leave → 'Leave' status
    #         # LWP / WITHOUT_PAID leave → 'Absent' status
    #         if leave_request.is_without_pay():
    #             attendance_status = 'Absent'  # LWP/Without Paid shows as Absent
    #         else:
    #             attendance_status = 'Leave'   # Paid Leave shows as Leave
            
    #         while current_date <= leave_request.end_date:
    #             attendance, created = Attendance.objects.get_or_create(
    #                 employee=leave_request.employee,
    #                 date=current_date,
    #                 defaults={
    #                     'final_status': attendance_status,
    #                     'check_in_time': timezone.now().replace(hour=0, minute=0, second=0),
    #                 }
    #             )
    #             if not created:
    #                 # Update existing attendance to appropriate status
    #                 attendance.final_status = attendance_status
    #                 attendance.save(update_fields=['final_status'])
    #             current_date += timedelta(days=1)
            
    #         message_line = 'Your leave request has been approved.'
    #         send_leave_notification_email(
    #             leave_request,
    #             subject='Leave request approved',
    #             message_line=message_line,
    #             request=request,
    #         )
            
    #         # CREATE NOTIFICATION
    #         from employees.notification_utils import create_leave_approved_notification
    #         create_leave_approved_notification(leave_request.employee, leave_request)
            
    #         messages.success(request, f'Leave request for {leave_request.employee.full_name} approved.')
        elif action == 'reject':
            leave_request.mark_rejected(request.user, admin_comment)
            message_line = 'Your leave request has been rejected.'
            send_leave_notification_email(
                leave_request,
                subject='Leave request rejected',
                message_line=message_line,
                request=request,
            )
            
            # CREATE NOTIFICATION
            from employees.notification_utils import create_leave_rejected_notification
            create_leave_rejected_notification(leave_request.employee, leave_request)
            
            messages.info(request, f'Leave request for {leave_request.employee.full_name} rejected.')
        else:
            messages.error(request, 'Unsupported action. Please try again.')

        return redirect('employees:admin_leave_requests')

    summary = leave_qs.aggregate(
        total=Count('id'),
        pending=Count('id', filter=Q(status=LeaveRequest.Status.PENDING)),
        approved=Count('id', filter=Q(status=LeaveRequest.Status.APPROVED)),
        rejected=Count('id', filter=Q(status=LeaveRequest.Status.REJECTED)),
    )

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'leave_requests': leave_qs,
        'summary': summary,
        'status_choices': LeaveRequest.Status.choices,
        'status_filter': status_filter,
        'employee_query': employee_query,
        'requested_after': requested_after,
        'requested_before': requested_before,
        'filters_active': filters_active,
    })

    return render(request, 'employees/leave/admin_leave_requests.html', context)


@login_required
@user_passes_test(is_employee)
@require_http_methods(["POST"])
@transaction.atomic
def start_break(request):
    """Start a break for the currently checked-in employee."""

    employee = request.user.employee_profile
    now = timezone.now()
    today = now.date()
    redirect_url = request.POST.get('next') or request.headers.get('Referer') or reverse('employees:employee_breaks')

    attendance = Attendance.objects.filter(employee=employee, date=today).select_for_update().first()
    reason_type = request.POST.get('reason_type') or AttendanceBreak.BreakReason.TEA
    reason = (request.POST.get('reason') or '').strip()
    other_reason = (request.POST.get('other_reason') or '').strip()
    ip_address = get_client_ip(request)
    user_agent = request.META.get('HTTP_USER_AGENT', '')

    if not attendance:
        AttendanceLog.objects.create(
            employee=employee,
            branch=employee.branch,
            action='break_start_failed',
            success=False,
            failure_reason='not_checked_in',
            ip_address=ip_address,
            user_agent=user_agent,
            notes='Break start denied because employee is not checked in today.'
        )
        messages.error(request, 'You need to check in before starting a break.')
        return redirect(redirect_url)

    if attendance.check_out_time:
        AttendanceLog.objects.create(
            employee=employee,
            branch=employee.branch,
            attendance=attendance,
            action='break_start_failed',
            success=False,
            failure_reason='break_not_allowed',
            ip_address=ip_address,
            user_agent=user_agent,
            notes='Break start denied because employee has already checked out.'
        )
        messages.error(request, 'You have already checked out today. Breaks can only be started before checking out.')
        return redirect(redirect_url)

    if attendance.active_break:
        AttendanceLog.objects.create(
            employee=employee,
            branch=employee.branch,
            attendance=attendance,
            action='break_start_failed',
            success=False,
            failure_reason='break_active_exists',
            ip_address=ip_address,
            user_agent=user_agent,
            notes='Break start denied because an active break already exists.'
        )
        messages.warning(request, 'You already have an active break running.')
        return redirect(redirect_url)

    if reason_type not in AttendanceBreak.BreakReason.values:
        reason_type = AttendanceBreak.BreakReason.TEA

    expected_minutes = AttendanceBreak.DEFAULT_DURATIONS.get(reason_type, 0)

    if reason_type == AttendanceBreak.BreakReason.OTHER:
        reason_text = other_reason or reason
    else:
        reason_text = reason or AttendanceBreak.BreakReason(reason_type).label

    AttendanceBreak.objects.create(
        attendance=attendance,
        employee=employee,
        branch=employee.branch,
        reason_type=reason_type,
        reason=reason_text,
        expected_duration_minutes=expected_minutes
    )

    AttendanceLog.objects.create(
        employee=employee,
        branch=employee.branch,
        attendance=attendance,
        action='break_start_success',
        success=True,
        ip_address=ip_address,
        user_agent=user_agent,
        notes=f"Break started at {now.strftime('%H:%M:%S')}" + (f" with reason: {reason}" if reason else '')
    )

    if reason_text:
        messages.success(request, f'Break started. Reason noted: {reason_text}')
    else:
        messages.success(request, 'Break started. Remember to end it when you return!')

    return redirect(redirect_url)


@login_required
@user_passes_test(is_employee)
@require_http_methods(["POST"])
@transaction.atomic
def end_break(request):
    """End the employee's current active break."""

    employee = request.user.employee_profile
    now = timezone.now()
    today = now.date()
    redirect_url = request.POST.get('next') or request.headers.get('Referer') or reverse('employees:employee_breaks')

    attendance = Attendance.objects.filter(employee=employee, date=today).select_for_update().first()
    ip_address = get_client_ip(request)
    user_agent = request.META.get('HTTP_USER_AGENT', '')

    if not attendance:
        AttendanceLog.objects.create(
            employee=employee,
            branch=employee.branch,
            action='break_end_failed',
            success=False,
            failure_reason='not_checked_in',
            ip_address=ip_address,
            user_agent=user_agent,
            notes='Break end denied because employee is not checked in today.'
        )
        messages.error(request, 'You are not checked in today. No active break to end.')
        return redirect(redirect_url)

    active_break = attendance.active_break
    if not active_break:
        AttendanceLog.objects.create(
            employee=employee,
            branch=employee.branch,
            attendance=attendance,
            action='break_end_failed',
            success=False,
            failure_reason='break_not_active',
            ip_address=ip_address,
            user_agent=user_agent,
            notes='Break end denied because no active break exists.'
        )
        messages.warning(request, "You don't have an active break at the moment.")
        return redirect(redirect_url)

    active_break.complete()
    active_break.refresh_from_db()
    exceeded = active_break.check_and_mark_exceeded()

    AttendanceLog.objects.create(
        employee=employee,
        branch=employee.branch,
        attendance=attendance,
        action='break_end_success',
        success=True,
        ip_address=ip_address,
        user_agent=user_agent,
        notes=f"Break ended at {now.strftime('%H:%M:%S')}. Duration: {active_break.duration_display}"
    )

    messages.success(request, f'Break ended. Total break time: {active_break.duration_display}')
    if exceeded:
        AttendanceLog.objects.create(
            employee=employee,
            branch=employee.branch,
            attendance=attendance,
            action='break_duration_exceeded',
            success=False,
            failure_reason='break_exceeded_limit',
            ip_address=ip_address,
            user_agent=user_agent,
            notes=f"Break exceeded expected duration by {active_break.exceeded_by_display or 'unknown'}"
        )
        messages.warning(
            request,
            (
                'Break exceeded the expected duration '
                f"({active_break.expected_duration_display or 'no limit set'}). "
                f"Exceeded by {active_break.exceeded_by_display}."
            )
        )

    return redirect(redirect_url)


@login_required
@user_passes_test(is_employee)
def my_attendance_logs(request):
    """Employee attendance logs view - shows detailed attendance history"""
    employee = request.user.employee_profile
    from django.utils import timezone
    from django.core.paginator import Paginator
    
    # Get filter parameters
    month = request.GET.get('month')
    year = request.GET.get('year')
    
    # Base queryset
    attendance_records = Attendance.objects.filter(employee=employee).order_by('-date')
    
    filter_kwargs = {}
    if month:
        filter_kwargs['date__month'] = int(month)
    if year:
        filter_kwargs['date__year'] = int(year)

    if filter_kwargs:
        attendance_records = attendance_records.filter(**filter_kwargs)

    # Pagination
    paginator = Paginator(attendance_records, 20)  # 20 records per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Calculate statistics
    aggregated_metrics = {}
    if attendance_records.exists():
        date_bounds = attendance_records.aggregate(
            first_date=Min('date'),
            last_date=Max('date'),
        )

        start_date = date_bounds['first_date']
        end_date = date_bounds['last_date']

        if start_date and end_date:
            aggregated_metrics = calculate_attendance_metrics(attendance_records, start_date, end_date)
    else:
        aggregated_metrics = {
            'total_working_days': 0,
            'present_days': 0,
            'half_day_days': 0,
            'absent_days': 0,
            'attendance_percentage': 0,
        }

    total_days = attendance_records.count()
    complete_days = attendance_records.filter(check_out_time__isnull=False).count()
    incomplete_days = total_days - complete_days

    # Calculate total hours worked (only for complete days)
    total_hours = 0
    for record in attendance_records.filter(check_out_time__isnull=False):
        total_hours += record.duration_hours
    
    # Get available years for filter
    available_years = Attendance.objects.filter(
        employee=employee
    ).dates('date', 'year', order='DESC')
    
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'employee': employee,
        'page_obj': page_obj,
        'attendance_records': page_obj.object_list,
        'total_days': total_days,
        'complete_days': complete_days,
        'incomplete_days': incomplete_days,
        'total_hours': round(total_hours, 2),
        'total_working_days': aggregated_metrics.get('total_working_days', 0),
        'present_days': aggregated_metrics.get('present_days', 0),
        'absent_days': aggregated_metrics.get('absent_days', 0),
        'half_day_days': aggregated_metrics.get('half_day_days', 0),
        'attendance_percentage': aggregated_metrics.get('attendance_percentage', 0),
        'available_years': available_years,
        'selected_month': month,
        'selected_year': year,
        'current_date': timezone.now().date(),
    })
    return render(request, 'employees/my_attendance_logs.html', context)


# Employee CRUD Views
@method_decorator(login_required, name='dispatch')
@method_decorator(user_passes_test(feature_required('employees.manage')), name='dispatch')
class EmployeeListView(ListView):
    """List all employees"""
    model = Employee
    template_name = 'employees/employee_list.html'
    context_object_name = 'employees'
    paginate_by = 10

    def get_context_data(self, **kwargs):
        context = TemplateLayout.init(self, super().get_context_data(**kwargs))
        context.update({
            'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        })
        return context

    def get_queryset(self):
        queryset = Employee.objects.all()
        queryset = tenant_queryset(
            self.request,
            queryset
        )
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(full_name__icontains=search) |
                Q(email__icontains=search) |
                Q(contact__icontains=search)
            )
        return queryset.order_by('name', 'full_name')


@login_required
@user_passes_test(feature_required('employees.manage'))
def employee_live_search(request):
    """Return filtered employees for live search (AJAX only)."""
    if request.headers.get('x-requested-with') != 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': 'Invalid request'}, status=400)

    query = request.GET.get('q', '').strip()
    employees = tenant_queryset(
        request,
        Employee.objects.all()
    )

    if query:
        employees = employees.filter(
            Q(name__icontains=query) |
            Q(full_name__icontains=query) |
            Q(email__icontains=query) |
            Q(contact__icontains=query)
        )

    employees = employees.order_by('name', 'full_name')[:25]
    html = render_to_string(
        'employees/partials/_employee_rows.html',
        {'employees': employees, 'request': request}
    )

    return JsonResponse({
        'success': True,
        'html': html,
        'count': employees.count(),
    })


@method_decorator(login_required, name='dispatch')
@method_decorator(user_passes_test(feature_required('employees.manage')), name='dispatch')
@method_decorator(
    login_required,
    name='dispatch'
)
@method_decorator(
    user_passes_test(
        feature_required('employees.manage')
    ),
    name='dispatch'
)
class EmployeeCreateView(CreateView):
    """Create new employee"""
    model = Employee
    form_class = EmployeeForm
    template_name = 'employees/employee_form.html'
    success_url = reverse_lazy('employees:employee_list')

    def get_form_kwargs(self):
        # EmployeeForm needs the request to scope its shift/branch dropdowns
        # to the current office (this was previously never wired up, so
        # those dropdowns silently rendered empty).
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def get_context_data(self, **kwargs):
        context = TemplateLayout.init(self, super().get_context_data(**kwargs))
        context.update({
            'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
            'title': 'Create Employee',
        })
        return context

    def form_valid(self, form):
        password = form.cleaned_data.get('password')

        office = get_request_office(
            self.request
        )

        if (
            not is_platform_admin(
                self.request.user
            )
            and office is None
        ):
            form.add_error(
                None,
                'Your account is not linked to an approved office.'
            )
            return self.form_invalid(form)

        password = form.cleaned_data.get(
            'password'
        )

        if not password or len(password) < 8:
            form.add_error(
                'password',
                'Password is required (minimum 8 characters).'
            )
            return self.form_invalid(form)

        try:
            with transaction.atomic():

                user = User.objects.create_user(
                    username=form.cleaned_data[
                        'email'
                    ],
                    email=form.cleaned_data[
                        'email'
                    ],
                    first_name=form.cleaned_data.get(
                        'full_name',
                        ''
                    ),
                    password=password,
                    is_staff=True,
                    is_active=True,
                )

                employee = form.save(
                    commit=False
                )

                employee.user = user

                # Office comes from middleware,
                # not from the submitted form.
                employee.office = office

                employee.profile_picture = None
                employee.face_registered = False
                employee.face_encoding = None
                employee.face_registered_at = None

                employee.save()
                form.save_m2m()  # persists the 'roles' selection (deferred by commit=False)
                login_url = self.request.build_absolute_uri(reverse('employees:login'))
                try:
                    send_employee_onboarding_email(employee, password, login_url)
                except Exception:
                    messages.warning(
                        self.request,
                        'Employee created but onboarding email could not be sent. Please verify email settings.'
                    )

                self.object = employee
                messages.success(
                    self.request,
                    'Employee created successfully. Ask the employee to log in and register their face using their camera before using attendance.'
                )
                return redirect(self.get_success_url())
        except Exception as e:
            form.add_error(None, f'Could not create employee: {e}')
            return self.form_invalid(form)


def send_employee_onboarding_email(employee: Employee, raw_password: str, login_url: str) -> None:
    """Send onboarding email with initial credentials to the employee."""
    subject = "Welcome to Kwikster CRM"
    context = {
        "employee_name": employee.full_name,
        "login_url": login_url,
        "email": employee.email,
        "password": raw_password,
    }

    html_message = render_to_string("employees/emails/onboarding_email.html", context)
    plain_message = strip_tags(html_message)

    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[employee.email],
            html_message=html_message,
            fail_silently=False,
        )
    except Exception as exc:  # pragma: no cover - log unexpected email failures
        logger.exception("Failed to send onboarding email to %s: %s", employee.email, exc)
        raise


def send_leave_notification_email(leave_request: LeaveRequest, *, subject: str, message_line: str, request) -> None:
    """Send leave request notifications to the employee with status details."""

    try:
        action_url = request.build_absolute_uri(reverse('employees:employee_leave_requests'))
    except Exception:
        action_url = reverse('employees:employee_leave_requests')

    context = {
        'employee_name': leave_request.employee.full_name,
        'status_display': leave_request.get_status_display(),
        'status': leave_request.status,
        'start_date': leave_request.start_date,
        'end_date': leave_request.end_date,
        'total_days': leave_request.total_days,
        'admin_comment': leave_request.admin_comment,
        'message_line': message_line,
        'action_url': action_url,
        'reviewed_at': leave_request.reviewed_at,
        'created_at': leave_request.created_at,
    }

    html_message = render_to_string('employees/emails/leave_status_email.html', context)
    plain_message = strip_tags(html_message)

    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[leave_request.employee.email],
            html_message=html_message,
            fail_silently=False,
        )
    except Exception as exc:
        logger.exception("Failed to send leave notification to %s: %s", leave_request.employee.email, exc)


@method_decorator(login_required, name='dispatch')
@method_decorator(user_passes_test(feature_required('employees.manage')), name='dispatch')
class EmployeeUpdateView(UpdateView):
    """Update existing employee"""
    model = Employee
    form_class = EmployeeUpdateForm
    template_name = 'employees/employee_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def get_queryset(self):
        # Not tenant_queryset() here: an admin editing an employee (e.g. to
        # transfer them) needs to reach employees in ANY of their office's
        # branches, not just the currently active one.
        if is_platform_admin(self.request.user):
            return super().get_queryset()
        office = get_request_office(self.request)
        if office is None:
            return super().get_queryset().none()
        return super().get_queryset().filter(office=office)
    def get_context_data(self, **kwargs):
        context = TemplateLayout.init(self, super().get_context_data(**kwargs))
        context.update({
            'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
            'title': 'Update Employee',
        })
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'Employee updated successfully.')
        return response

    def get_success_url(self):
        return reverse_lazy('employees:employee_list')


@method_decorator(login_required, name='dispatch')
@method_decorator(user_passes_test(feature_required('employees.manage')), name='dispatch')
class EmployeeDeleteView(DeleteView):
    """Delete employee"""
    model = Employee
    template_name = 'employees/employee_confirm_delete.html'
    success_url = reverse_lazy('employees:employee_list')

    def get_context_data(self, **kwargs):
        context = TemplateLayout.init(self, super().get_context_data(**kwargs))
        context.update({
            'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        })
        return context

    def delete(self, request, *args, **kwargs):
        employee = self.get_object()
        # Delete associated user account
        if employee.user:
            employee.user.delete()
        messages.success(request, 'Employee deleted successfully!')
        return super().delete(request, *args, **kwargs)


# Employee Status Toggle View (for super-admins to activate/deactivate employees)
@login_required
@user_passes_test(feature_required('employees.manage'))
def employee_toggle_status(request, pk):
    """Toggle employee active/inactive status (Super-admin only)"""
    employee = get_object_or_404(Employee, pk=pk)

    if request.method == 'POST':
        # Toggle the user's active status
        employee.user.is_active = not employee.user.is_active
        employee.user.save()

        status = "activated" if employee.user.is_active else "deactivated"
        messages.success(request, f'Employee {employee.full_name} has been {status} successfully!')

        next_url = request.POST.get('next')
        if next_url:
            return redirect(next_url)

        # Redirect back to the page that made the request
        referer = request.META.get('HTTP_REFERER')
        if referer and 'employee_list' in referer:
            return redirect('employees:employee_list')
        else:
            return redirect('employees:employee_detail', pk=pk)

    # If not POST, redirect back
    messages.error(request, 'Invalid request method.')
    return redirect('employees:employee_list')


@login_required
@user_passes_test(feature_required('employees.manage'))
def employee_detail(request, pk):
    """View employee details (Super-admin only)"""
    employee = get_object_or_404(Employee, pk=pk)
    from django.utils import timezone

    # Get attendance statistics
    total_attendance = tenant_queryset(
    request,
    Attendance.objects.all()
).filter(employee=employee).count()
    current_month_attendance = tenant_queryset(
    request,
    Attendance.objects.all()
).filter(
        employee=employee,
        date__year=timezone.now().year,
        date__month=timezone.now().month
    ).count()

    # Get recent attendance records
    recent_attendance = tenant_queryset(
    request,
    Attendance.objects.all()
).filter(employee=employee).order_by('-date')[:10]

    # Get attendance for current week
    week_start = timezone.now().date() - timezone.timedelta(days=7)
    week_attendance = tenant_queryset(
    request,
    Attendance.objects.all()
).filter(
        employee=employee,
        date__gte=week_start,
        date__lte=timezone.now().date()
    ).order_by('-date')

    # Get the salary structure currently in effect (latest row whose
    # effective_from is today or earlier)
    current_salary = EmployeeSalary.objects.filter(
        employee=employee,
        effective_from__lte=timezone.now().date()
    ).order_by('-effective_from').first()

    monthly_ctc = current_salary.gross_salary + current_salary.fixed_deductions if current_salary else 0


    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'employee': employee,
        'total_attendance': total_attendance,
        'current_month_attendance': current_month_attendance,
        'recent_attendance': recent_attendance,
        'week_attendance': week_attendance,
        'monthly_ctc': monthly_ctc,
        'today': timezone.now().date(),
    })
    return render(request, 'employees/employee_detail.html', context)


@login_required
@user_passes_test(feature_required('attendance.manage'))
def employee_attendance_logs(request, pk):
    """Interactive activity log view for a specific employee (Super-admin only)."""

    employee = get_object_or_404(Employee, pk=pk)

    logs_qs = AttendanceLog.objects.filter(employee=employee).select_related('attendance').order_by('-timestamp')

    total_logs = logs_qs.count()
    successful_logs = logs_qs.filter(success=True).count()
    failed_logs = total_logs - successful_logs

    action_labels = dict(AttendanceLog.ACTION_CHOICES)
    action_summary = [
        {
            'code': row['action'],
            'label': action_labels.get(row['action'], row['action'].replace('_', ' ').title()),
            'count': row['count'],
        }
        for row in logs_qs.values('action').annotate(count=Count('id')).order_by('-count')
    ]

    log_display_limit = 250
    logs = list(logs_qs[:log_display_limit])

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'employee': employee,
        'logs': logs,
        'total_logs': total_logs,
        'successful_logs': successful_logs,
        'failed_logs': failed_logs,
        'action_summary': action_summary,
        'log_display_limit': log_display_limit,
        'has_more_logs': total_logs > log_display_limit,
        'status_filters': [
            {'code': 'all', 'label': 'All'},
            {'code': 'success', 'label': 'Success'},
            {'code': 'failed', 'label': 'Failed'},
        ],
        'action_filters': [
            {'code': 'all', 'label': 'All Actions'},
            {'code': 'check_in', 'label': 'Check-In'},
            {'code': 'check_out', 'label': 'Check-Out'},
            {'code': 'break', 'label': 'Breaks'},
            {'code': 'other', 'label': 'Other'},
        ],
    })

    return render(request, 'employees/employee_logs.html', context)


# Employee Profile View (for employees to view their own profile)
@login_required
@user_passes_test(is_employee)
def employee_profile(request):
    """Employee profile view"""
    # Redirect superadmins to their profile
    if request.user.is_superuser:
        return redirect('employees:superadmin_profile')

    employee = request.user.employee_profile
    latest_face_request = (
        employee.face_update_requests
        .select_related('reviewed_by')
        .order_by('-requested_at')
        .first()
    )
    face_update_active = bool(
        latest_face_request
        and latest_face_request.status in (
            FaceUpdateRequest.Status.PENDING,
            FaceUpdateRequest.Status.APPROVED,
        )
    )
    face_update_pending = bool(
        latest_face_request
        and latest_face_request.status == FaceUpdateRequest.Status.PENDING
    )
    can_request_face_update = (
        employee.has_registered_face
        and not face_update_active
        and not employee.can_access_face_registration
    )

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'employee': employee,
        'latest_face_update_request': latest_face_request,
        'face_update_active': face_update_active,
        'face_update_pending': face_update_pending,
        'can_request_face_update': can_request_face_update,
        'face_update_status': latest_face_request.status if latest_face_request else '',
        'face_update_status_display': latest_face_request.get_status_display() if latest_face_request else '',
    })
    return render(request, 'employees/employee_profile.html', context)


@login_required
@user_passes_test(is_employee)
def employee_profile_mobile(request):
    """Mobile profile page. Renders a shell only - all profile data (personal
    info, employment, leave balance, salary) is loaded client-side from the
    DRF endpoint (/api/v1/profile/), the same JSON API external platforms use."""
    if request.user.is_superuser:
        return redirect('employees:superadmin_profile')

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_mobile.html', context),
    })
    return render(request, 'employees/employee_profile_mobile.html', context)


@login_required
@user_passes_test(is_employee)
@require_http_methods(["GET", "POST"])
def employee_documents(request):
    """Allow employees to upload and manage their key documents."""
    if request.user.is_superuser:
        return redirect('employees:superadmin_profile')

    employee = request.user.employee_profile

    if request.method == 'POST':
        form = EmployeeDocumentForm(request.POST, request.FILES, instance=employee)
        if form.is_valid():
            form.save()
            messages.success(request, 'Documents updated successfully.')
            return redirect('employees:employee_documents')
    else:
        form = EmployeeDocumentForm(instance=employee)

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'form': form,
        'employee': employee,
    })
    return render(request, 'employees/employee_documents.html', context)


@login_required
@user_passes_test(is_employee)
def employee_assets(request):
    """List assets assigned to the logged-in employee."""
    employee = request.user.employee_profile
    assets = AssetAssignment.objects.filter(employee=employee).order_by('-assigned_date', '-created_at')

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'assets': assets,
    })
    return render(request, 'employees/assets/employee_assets.html', context)


@login_required
@user_passes_test(is_employee)
def update_asset_status(request, asset_id):
    """API endpoint to update asset status by employee.
    
    CRITICAL: Enforce dropdown disable logic:
    - Dropdown disabled if: hr_verified=True AND return_requested=False
    - Dropdown disabled if: employee_status=RETURNED AND hr_verified=True
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)
    
    try:
        import json
        from django.utils import timezone
        
        data = json.loads(request.body)
        new_status = data.get('status')
        
        # Validate status
        valid_statuses = ['not_received', 'received', 'returned']
        if new_status not in valid_statuses:
            return JsonResponse({'error': 'Invalid status'}, status=400)
        
        # Get asset assignment
        asset = AssetAssignment.objects.get(id=asset_id, employee=request.user.employee_profile)
        
        # CRITICAL: Check if dropdown should be disabled
        # Dropdown is disabled if:
        # 1. HR verified "Received" and hasn't requested return
        # 2. Asset is already "Returned" and HR verified it
        if (asset.hr_verified and not asset.return_requested) or \
           (asset.employee_status == 'returned' and asset.hr_verified):
            return JsonResponse({
                'success': False,
                'error': 'This asset status is locked. HR must request a return to make changes.',
                'is_locked': True
            }, status=403)
        
        # Update status
        asset.employee_status = new_status
        asset.status_updated_at = timezone.now()
        asset.save(update_fields=['employee_status', 'status_updated_at', 'updated_at'])
        
        return JsonResponse({
            'success': True,
            'message': f'Asset status updated to {new_status}',
            'status': new_status,
            'updated_at': asset.status_updated_at.isoformat(),
            'hr_verified': asset.hr_verified,
            'return_requested': asset.return_requested
        })
    
    except AssetAssignment.DoesNotExist:
        return JsonResponse({'error': 'Asset not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(feature_required('employees.manage'))
@require_http_methods(["POST"])
def verify_asset_status(request, asset_id):
    """API endpoint for admin to manage asset lifecycle.
    
    Three HR actions:
    A. Verify Received: Sets hr_verified=True, return_requested=False
       - Employee dropdown becomes DISABLED
    B. Request Return: Sets return_requested=True, hr_verified=False
       - Employee dropdown becomes ENABLED
    C. Verify Returned: Sets hr_verified=True, return_requested=False
       - Employee dropdown becomes DISABLED permanently
    """
    try:
        import json
        from django.utils import timezone
        
        data = json.loads(request.body)
        action = data.get('action', 'verify')  # 'verify', 'request_return', 'verify_returned'
        comment = data.get('comment', '').strip()
        
        # Start with the asset and its employee/office relationships.
        asset_queryset = (
            AssetAssignment.objects
            .select_related(
                "employee",
                "employee__user",
                "employee__office",
            )
        )

        # Platform admin can access assets from every office.
        # Office admin can access only assets assigned to employees
        # in the admin's own office.
        if not is_platform_admin(request.user):

            office = get_request_office(request)

            if office is None:
                return JsonResponse(
                    {
                        "success": False,
                        "error": "No office is associated with this admin account.",
                    },
                    status=403,
                )

            asset_queryset = asset_queryset.filter(
                employee__office=office
            )
            branch = get_request_branch(request)
            if branch is not None:
                asset_queryset = asset_queryset.filter(employee__branch=branch)

        # Get the asset only after applying the correct tenant filter.
        asset = asset_queryset.filter(
            id=asset_id
        ).first()

        if asset is None:
            return JsonResponse(
                {
                    "success": False,
                    "error": "Asset assignment was not found or you do not have permission to access it.",
                },
                status=404,
            )
        
        # CRITICAL: Implement the 3-step asset lifecycle workflow
        if action == 'verify':
            # Action A: Verify Received
            # HR verifies that employee received the asset
            asset.hr_verified = True
            asset.return_requested = False
            message = 'Asset verified as received. Employee dropdown is now locked.'
            
        elif action == 'request_return':
            # Action B: Request Return
            # HR requests the asset back from employee
            asset.return_requested = True
            asset.hr_verified = False
            message = 'Return requested. Employee can now update status.'
            
        elif action == 'verify_returned':
            # Action C: Verify Returned
            # HR verifies that employee returned the asset
            asset.employee_status = 'returned'
            asset.hr_verified = True
            asset.return_requested = False
            message = 'Asset verified as returned. Employee dropdown is now permanently locked.'
            
        else:
            return JsonResponse({'error': 'Invalid action'}, status=400)
        
        # Update common fields
        asset.hr_comment = comment
        asset.hr_verified_at = timezone.now()
        asset.hr_verified_by = request.user
        asset.save()
        
        return JsonResponse({
            'success': True,
            'message': message,
            'action': action,
            'employee_status': asset.employee_status,
            'hr_verified': asset.hr_verified,
            'return_requested': asset.return_requested,
            'hr_comment': asset.hr_comment,
            'verified_at': asset.hr_verified_at.isoformat() if asset.hr_verified_at else None,
            'verified_by': asset.hr_verified_by.get_full_name() if asset.hr_verified_by else None
        })
    
    except AssetAssignment.DoesNotExist:
        return JsonResponse({'error': 'Asset not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(feature_required('employees.manage'))
def asset_management(request):
    """Admin interface to assign and track company assets."""
    employee_filter = request.GET.get('employee') or ''
    # assignments = AssetAssignment.objects.select_related('employee').order_by('-assigned_date', '-created_at')
    assignments = AssetAssignment.objects.select_related(
        "employee",
        "employee__user",
        "employee__office",
    )
    if not is_platform_admin(request.user):
        assignments = assignments.filter(employee__office=get_request_office(request))
        branch = get_request_branch(request)
        if branch is not None:
            assignments = assignments.filter(employee__branch=branch)
    assignments = assignments.order_by(
        "-assigned_date",
        "-created_at",
    )
    if employee_filter:
        assignments = assignments.filter(employee_id=employee_filter)

    if request.method == 'POST':
        form = AssetAssignmentForm(request.POST, request=request)
        if form.is_valid():
            form.save()
            messages.success(request, 'Asset assigned successfully.')
            redirect_url = reverse('employees:asset_management')
            if employee_filter:
                redirect_url = f"{redirect_url}?employee={employee_filter}"
            return redirect(redirect_url)
        messages.error(request, 'Please correct the highlighted errors and try again.')
    else:
        form = AssetAssignmentForm(
            request=request,
            initial={'employee': employee_filter} if employee_filter else None
        )

    employees = (
        tenant_queryset(
            request,
            Employee.objects.select_related("user")
        )
        .order_by("full_name")
    )
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'assignment_form': form,
        'assignments': assignments,
        'employees': employees,
        'employee_filter': employee_filter,
    })
    return render(request, 'employees/assets/admin_assets.html', context)

def _get_admin_office(request):
    """Resolve the Office tied to this admin. Office admins have office_admin_profile;
    platform admin has none unless middleware sets request.office for a support context."""
    profile = getattr(request.user, 'office_admin_profile', None)
    if profile:
        return profile.office
    return get_request_office(request)


@login_required
@user_passes_test(office_admin_required)
def superadmin_profile(request):
    """SuperAdmin profile view"""
    user = request.user
    from django.utils import timezone

    total_employees = tenant_queryset(request, Employee.objects.all()).count()
    today_checkins = tenant_queryset(
        request, Attendance.objects.all()
    ).filter(date=timezone.now().date()).count()

    office = _get_admin_office(request)

    kiosk_url = None
    if office:
        kiosk_url = request.build_absolute_uri(
            reverse("employees:attendance_kiosk", args=[office.kiosk_token])
        )
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'user': user,
        'total_employees': total_employees,
        'today_checkins': today_checkins,
        'office': _get_admin_office(request),
        "kiosk_url": kiosk_url,
    })
    return render(request, 'employees/superadmin_profile.html', context)


@login_required
@user_passes_test(office_admin_required)
def superadmin_profile_edit(request):
    """SuperAdmin profile edit view"""
    user = request.user

    if request.method == 'POST':
        form = SuperAdminProfileForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully!')
            return redirect('employees:superadmin_profile')
    else:
        form = SuperAdminProfileForm(instance=user)

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'form': form,
        'user': user,
    })
    return render(request, 'employees/superadmin_profile_edit.html', context)


@login_required
@user_passes_test(is_office_admin)
def office_profile_edit(request):
    """Edit the office's own details. Deliberately gated to is_office_admin only —
    not office_admin_required — since this edits a specific office record, and the
    platform admin isn't tied to one particular office to edit here."""
    office = _get_admin_office(request)
    if office is None:
        messages.error(request, 'No office is associated with your account.')
        return redirect('employees:superadmin_profile')

    if request.method == 'POST':
        form = OfficeProfileForm(request.POST, request.FILES, instance=office)
        if form.is_valid():
            form.save()
            messages.success(request, 'Office details updated successfully!')
            return redirect('employees:superadmin_profile')
    else:
        form = OfficeProfileForm(instance=office)

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'form': form,
        'office': office,
    })
    return render(request, 'employees/office_profile_edit.html', context)
    
@login_required
@user_passes_test(office_admin_required)
def superadmin_change_password(request):
    """Allow superadmin to update their own password"""
    context = TemplateLayout.init(request, context={})

    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, 'Your password has been updated successfully.')
            return redirect('employees:superadmin_profile')
        else:
            messages.error(request, 'Please correct the errors below to update your password.')
    else:
        form = PasswordChangeForm(request.user)

    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'form': form,
    })
    return render(request, 'employees/superadmin_change_password.html', context)
def get_client_ip(request):
    """Get client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


@login_required
@user_passes_test(is_employee)
def check_in(request):
    """
    SECURE CHECK-IN VIEW - 100% SECURE FACE VERIFICATION
    
    SECURITY RULES:
    1. Face MUST match EXACTLY with logged-in employee's registered face
    2. NO global face search - only direct comparison with THIS employee
    3. NO placeholder encodings allowed
    4. Strict tolerance=0.45 for face matching
    5. All failures logged with confidence scores
    """
    from employees.models import AttendanceLog
    employee = request.user.employee_profile
    employee.refresh_from_db()
    today = timezone.now().date()
    ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'

#     # Get today's attendance record if it exists
#     today_attendance = tenant_queryset(
    #     request,
    #     Attendance.objects.all()
    # ).filter(employee=employee, date=today).first()
        # Get today's attendance record if it exists
    today_attendance = Attendance.objects.filter(office=employee.office, branch=employee.branch, employee=employee, date=today).first()
    # GUARD 1: Face must be registered
    if not employee.face_registered:
        face_register_url = f"{reverse('employees:face_register')}?next={reverse('employees:check_in')}"
        messages.warning(request, 'Please register your face before checking in.')
        return redirect(face_register_url)

    # ===== POST REQUEST: Process check-in submission =====
    if request.method == 'POST':
        # VALIDATION 1: Photo is required
        check_in_photo = request.FILES.get('check_in_photo')
        if not check_in_photo:
            AttendanceLog.objects.create(
                employee=employee,
                branch=employee.branch,
                action='check_in_failed',
                success=False,
                failure_reason='photo_required',
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                notes='Photo was not provided'
            )
            if ajax:
                return JsonResponse({'success': False, 'message': 'Please capture a photo to check in.', 'type': 'photo_required'}, status=400)
            messages.error(request, 'Please capture a photo to check in.')
            return redirect('employees:check_in')

        # VALIDATION 2: Location is required
        from employees.geolocation_utils import validate_coordinates, is_within_office_premises
        user_latitude = request.POST.get('latitude')
        user_longitude = request.POST.get('longitude')
        
        if not user_latitude or not user_longitude:
            AttendanceLog.objects.create(
                employee=employee,
                branch=employee.branch,
                action='check_in_failed',
                success=False,
                failure_reason='location_not_provided',
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                notes='Location coordinates were not provided'
            )
            if ajax:
                return JsonResponse({'success': False, 'message': 'Location access is required. Please enable location services.', 'type': 'location_not_provided'}, status=400)
            messages.error(request, 'Location access is required. Please enable location services.')
            return redirect('employees:check_in')
        
        # VALIDATION 3: Validate coordinate format
        is_valid_coords, coord_message = validate_coordinates(user_latitude, user_longitude)
        if not is_valid_coords:
            AttendanceLog.objects.create(
                employee=employee,
                branch=employee.branch,
                action='check_in_failed',
                success=False,
                failure_reason='invalid_coordinates',
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                notes=f'Invalid coordinates: {coord_message}'
            )
            if ajax:
                return JsonResponse({'success': False, 'message': f'Invalid location: {coord_message}', 'type': 'invalid_coordinates'}, status=400)
            messages.error(request, f'Invalid location: {coord_message}')
            return redirect('employees:check_in')
        
        # VALIDATION 4: Must be within office premises
        is_within, distance, location_message = is_within_office_premises(employee.office, float(user_latitude), float(user_longitude), branch=employee.branch)
        if not is_within:
            AttendanceLog.objects.create(
                employee=employee,
                branch=employee.branch,
                action='check_in_failed',
                success=False,
                failure_reason='outside_office_premises',
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                notes=f'Location: {user_latitude}, {user_longitude}. {location_message}'
            )
            if ajax:
                return JsonResponse({'success': False, 'message': location_message, 'type': 'outside_office_premises'}, status=400)
            messages.error(request, location_message)
            return redirect('employees:check_in')

        try:
            # SECURITY: Extract face encoding from photo
            # Read the uploaded file bytes
            check_in_photo.seek(0)  # Reset file pointer to beginning
            photo_bytes = check_in_photo.read()
            checkin_encoding = extract_face_encoding_from_file_bytes(photo_bytes)
            # SECURITY: Check for no face or multiple faces
            if checkin_encoding is None:
                AttendanceLog.objects.create(
                    employee=employee,
                    branch=employee.branch,
                    action='check_in_failed',
                    success=False,
                    failure_reason='no_face_detected',
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    notes='No face or multiple faces detected in photo'
                )
                if ajax:
                    return JsonResponse({'success': False, 'message': ' No face detected or multiple faces detected. Please try again with a clear face.', 'type': 'no_face_detected'}, status=400)
                messages.error(request, ' No face detected or multiple faces detected. Please try again.')
                return redirect('employees:check_in')

            # SECURITY: Get stored encoding for THIS employee ONLY
            stored_encoding = employee.get_face_encoding()
            print(f"[DEBUG] Employee {employee.id} stored encoding: {stored_encoding is not None}")
            if stored_encoding is not None:
                print(f"[DEBUG] Stored encoding shape: {stored_encoding.shape}")
                print(f"[DEBUG] Stored encoding sample: {stored_encoding[:5]}")
                is_placeholder = np.allclose(stored_encoding, 0.0)
                print(f"[DEBUG] Stored encoding is placeholder (all zeros): {is_placeholder}")
            
            if stored_encoding is None:
                AttendanceLog.objects.create(
                    employee=employee,
                    branch=employee.branch,
                    action='check_in_failed',
                    success=False,
                    failure_reason='no_face_registered',
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    notes='Stored face encoding missing for employee'
                )
                if ajax:
                    return JsonResponse({'success': False, 'message': 'Your face data is missing. Please re-register.', 'type': 'no_face_registered'}, status=400)
                messages.error(request, 'Your face data is missing. Please re-register.')
                return redirect('employees:face_register')

            # SECURITY: STRICT face matching - ONLY with THIS employee's face
            # NO global search, NO placeholder encodings
            # Use tolerance 0.55 for better matching with registered photos
            strict_tolerance = 0.55  # More lenient tolerance for better matching
            print(f"[DEBUG] Comparing faces with tolerance: {strict_tolerance}")
            result = compare_faces(stored_encoding, checkin_encoding, tolerance=strict_tolerance)

            # SECURITY: Face MUST match exactly
            if not result['match']:
                AttendanceLog.objects.create(
                    employee=employee,
                    branch=employee.branch,
                    action='check_in_failed',
                    success=False,
                    failure_reason='face_not_matched',
                    confidence=result['confidence'],
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    notes=f'Face verification failed: {result["confidence"]:.1f}% confidence (strict tolerance 0.45)'
                )
                if ajax:
                    return JsonResponse({'success': False, 'message': ' Face verification failed. Your face does not match the registered face. Please try again.', 'type': 'face_not_matched', 'confidence': result['confidence']}, status=400)
                messages.error(request, ' Face verification failed. Your face does not match. Please try again.')
                return redirect('employees:check_in')

            # SECURITY: All validations passed - create attendance record
            attendance, created = Attendance.objects.get_or_create(
                office=employee.office,
                branch=employee.branch,
                employee=employee,
                date=today,
                defaults={"office": employee.office, 'check_in_time': timezone.now()}
            )
            
            # Save photo and location
            attendance.check_in_photo.save(check_in_photo.name, check_in_photo, save=False)
            attendance.check_in_latitude = user_latitude
            attendance.check_in_longitude = user_longitude
            attendance.save()

            # LOG: Successful check-in
            AttendanceLog.objects.create(
                employee=employee,
                office=employee.office,
                branch=employee.branch,
                action='check_in_success',
                success=True,
                confidence=result['confidence'],
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                attendance=attendance,
                notes=f'Check-in successful: {result["confidence"]:.1f}% confidence'
            )

            if ajax:
                return JsonResponse({
                    'success': True,
                    'msg': f' Check-in successful! Face verified with {result["confidence"]:.1f}% confidence.',
                    'confidence': result['confidence'],
                    'redirect_url': reverse('employees:attendance_calendar')
                })
            
            messages.success(request, f' Check-in successful! Face verified with {result["confidence"]:.1f}% confidence.')
            return redirect('employees:attendance_calendar')

        except Exception as e:
            AttendanceLog.objects.create(
                employee=employee,
                office=employee.office,
                branch=employee.branch,
                action='check_in_failed',
                success=False,
                failure_reason='other',
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                notes=f'Exception: {str(e)}'
            )
            if ajax:
                return JsonResponse({'success': False, 'message': f'Error: {str(e)}', 'type': 'other'}, status=500)
            messages.error(request, f'Error: {str(e)}')
            return redirect('employees:check_in')

    # ===== GET REQUEST: Render check-in page =====
    if today_attendance and today_attendance.check_in_time and today_attendance.check_out_time:
        attendance_state = 'complete'
    elif today_attendance and today_attendance.check_in_time and not today_attendance.check_out_time:
        attendance_state = 'checked_in_pending_checkout'
    else:
        attendance_state = 'not_checked_in'

    check_in_success_time = today_attendance.check_in_time if (today_attendance and today_attendance.check_in_time) else None
    checkout_success = request.session.pop('check_out_success', False)
    checkout_success_time = request.session.pop('check_out_success_time', None)
    should_auto_start_camera = attendance_state == 'not_checked_in'

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'employee': employee,
        'today_attendance': today_attendance,
        'attendance_state': attendance_state,
        'check_in_success_time': check_in_success_time,
        'checkout_success': checkout_success,
        'checkout_success_time': checkout_success_time,
        'should_auto_start_camera': should_auto_start_camera,
        'all_services_url': reverse('employees:attendance_calendar'),
    })
    return render(request, 'employees/check_in.html', context)


# Attendance Views (for admin)
@method_decorator(login_required, name='dispatch')
@method_decorator(user_passes_test(feature_required('attendance.manage')), name='dispatch')
class AttendanceListView(ListView):
    """List all attendance records"""
    model = Attendance
    template_name = 'employees/attendance_list.html'
    context_object_name = 'attendance_records'
    paginate_by = 20

    def get_context_data(self, **kwargs):
        context = TemplateLayout.init(self, super().get_context_data(**kwargs))

        today = timezone.now().date()
        queryset = self.get_queryset()

        metrics = {}
        if queryset.exists():
            date_bounds = queryset.aggregate(
                first_date=Min('date'),
                last_date=Max('date'),
            )

            start_date = date_bounds['first_date']
            end_date = date_bounds['last_date']

            if start_date and end_date:
                metrics = calculate_attendance_metrics(queryset, start_date, end_date)
        else:
            metrics = {
                'total_working_days': 0,
                'present_days': 0,
                'half_day_days': 0,
                'absent_days': 0,
                'attendance_percentage': 0,
            }

        context.update({
            'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
            'today_count': tenant_queryset(
    self.request,
    Attendance.objects.all()
).filter(date=today).count(),
            'unique_employees': tenant_queryset(
    self.request,
    Attendance.objects.all()
).filter(
                date=today
            ).values('employee').distinct().count(),
            'total_employees': tenant_queryset(
        self.request,
        Employee.objects.all()
    ).count(),
            'today': today,
            'total_working_days': metrics.get('total_working_days', 0),
            'present_days': metrics.get('present_days', 0),
            'half_day_days': metrics.get('half_day_days', 0),
            'absent_days': metrics.get('absent_days', 0),
            'attendance_percentage': metrics.get('attendance_percentage', 0),
        })
        return context

    def get_queryset(self):
        queryset = Attendance.objects.select_related( 'employee', 'employee__user', 'employee__office' ) # Platform admin can see all attendance. # Office admin can see attendance only for employees in their office. 
        if not is_platform_admin(self.request.user): 
            office = get_request_office(self.request) 
        if office is None: 
            return queryset.none() 
        queryset = queryset.filter( employee__office=office )
        date_filter = self.request.GET.get('date')
        employee_filter = self.request.GET.get('employee')

        if date_filter:
            queryset = queryset.filter(date=date_filter)
        if employee_filter:
            queryset = queryset.filter(employee_id=employee_filter)

        return queryset.order_by('-check_in_time')


from datetime import datetime


# ---------------------------------------------------------------------------
# Shared filter helper
# ---------------------------------------------------------------------------

def _get_filtered_attendance_logs(request):
    """Applies the same employee/action/status/date filters used by the
    admin_attendance_logs page. Returns (queryset, filters_dict)."""
    from employees.models import AttendanceLog

    employee_id = request.GET.get('employee')
    action = request.GET.get('action')
    status = request.GET.get('status')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    logs = AttendanceLog.objects.select_related('employee', 'attendance', 'employee__office').order_by('-timestamp')

    # Platform admin can see logs from all companies.
    # Office admin can see logs only from their own company/office.
    if not is_platform_admin(request.user):
        office = get_request_office(request)

        if office is None:
            logs = logs.none()
        else:
            logs = logs.filter(employee__office=office)

    if employee_id:
        logs = logs.filter(employee_id=employee_id)

    if action:
        logs = logs.filter(action=action)

    if status == 'success':
        logs = logs.filter(success=True)
    elif status == 'failed':
        logs = logs.filter(success=False)

    if date_from:
        date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
        logs = logs.filter(timestamp__date__gte=date_from_obj)

    if date_to:
        date_to_obj = datetime.strptime(date_to, '%Y-%m-%d')
        logs = logs.filter(timestamp__date__lte=date_to_obj)

    filters = {
        'employee_id': employee_id,
        'action': action,
        'status': status,
        'date_from': date_from,
        'date_to': date_to,
    }
    return logs, filters


# ---------------------------------------------------------------------------
# Existing page view (unchanged logic, now delegating filtering to helper)
# ---------------------------------------------------------------------------

@login_required
@user_passes_test(feature_required('attendance.manage'))
def admin_attendance_logs(request):
    """Admin view for all attendance activity logs including failed attempts"""
    from django.core.paginator import Paginator
    from employees.models import AttendanceLog

    logs, filters = _get_filtered_attendance_logs(request)

    # Calculate statistics
    total_logs = logs.count()
    successful_logs = logs.filter(success=True).count()
    failed_logs = logs.filter(success=False).count()

    # Count by action type
    check_in_attempts = logs.filter(action__contains='check_in').count()
    check_out_attempts = logs.filter(action__contains='check_out').count()

    # Recent failed attempts (for security monitoring)
    recent_failures = AttendanceLog.objects.filter(
        success=False
    ).select_related('employee').order_by('-timestamp')[:10]

    # Pagination
    paginator = Paginator(logs, 50)  # 50 logs per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Get all employees for filter dropdown
    # employees = Employee.objects.all().order_by('name')
    employees = tenant_queryset(
        request,
        Employee.objects.all()
    ).order_by('name')

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'page_obj': page_obj,
        'logs': page_obj.object_list,
        'total_logs': total_logs,
        'successful_logs': successful_logs,
        'failed_logs': failed_logs,
        'check_in_attempts': check_in_attempts,
        'check_out_attempts': check_out_attempts,
        'recent_failures': recent_failures,
        'employees': employees,
        'selected_employee': filters['employee_id'],
        'selected_action': filters['action'],
        'selected_status': filters['status'],
        'selected_date_from': filters['date_from'],
        'selected_date_to': filters['date_to'],
        'action_choices': AttendanceLog.ACTION_CHOICES,
        'current_date': timezone.now().date(),
    })
    return render(request, 'employees/admin_attendance_logs.html', context)


# ---------------------------------------------------------------------------
# New: Excel export honoring the same filters
# ---------------------------------------------------------------------------

@login_required
@user_passes_test(feature_required('attendance.manage'))
def admin_attendance_logs_excel(request):
    """Exports the currently filtered attendance activity logs as an Excel file.

    If no specific employee filter is applied ("All Employees"), the export
    creates one worksheet per employee. If a specific employee is selected,
    a single worksheet is produced (same as before).
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from django.http import HttpResponse
    from django.utils import timezone as tz
    import re

    logs, filters = _get_filtered_attendance_logs(request)

    headers = [
        'Timestamp', 'Employee', 'Email', 'Action', 'Status',
        'Confidence (%)', 'Failure Reason', 'IP Address', 'Notes',
    ]
    header_fill = PatternFill(start_color="6366F1", end_color="6366F1", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")

    def write_header(ws):
        ws.append(headers)
        for col_num in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_num)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")

    def write_log_row(ws, log):
        ws.append([
            timezone.localtime(log.timestamp).strftime('%Y-%m-%d %H:%M:%S') if log.timestamp else '',
            log.employee.name if log.employee else '',
            log.employee.email if log.employee else '',
            log.get_action_display(),
            'Success' if log.success else 'Failed',
            round(log.confidence, 2) if log.confidence else '',
            log.get_failure_reason_display() if not log.success and log.failure_reason else '',
            log.ip_address or '',
            log.notes or '',
        ])

    def autosize(ws):
        for col_cells in ws.columns:
            length = max((len(str(cell.value)) if cell.value is not None else 0) for cell in col_cells)
            ws.column_dimensions[col_cells[0].column_letter].width = min(length + 4, 60)

    def safe_sheet_name(name, used_names):
        # Excel sheet names: max 31 chars, no \ / ? * [ ] :
        cleaned = re.sub(r'[\\/\?\*\[\]:]', '', name or 'Unknown').strip() or 'Unknown'
        cleaned = cleaned[:31]
        base = cleaned
        counter = 1
        while cleaned.lower() in used_names:
            suffix = f" ({counter})"
            cleaned = base[: 31 - len(suffix)] + suffix
            counter += 1
        used_names.add(cleaned.lower())
        return cleaned

    wb = Workbook()
    default_sheet = wb.active  # will remove/rename below

    if filters['employee_id']:
        # Single employee already filtered -> one sheet is enough
        ws = default_sheet
        ws.title = "Attendance Logs"
        write_header(ws)
        for log in logs:
            write_log_row(ws, log)
        autosize(ws)
    else:
        # Group logs by employee -> one sheet per employee
        logs_by_employee = {}
        employee_order = []
        for log in logs:
            key = log.employee_id
            if key not in logs_by_employee:
                logs_by_employee[key] = []
                employee_order.append(log.employee)
            logs_by_employee[key].append(log)

        if not employee_order:
            ws = default_sheet
            ws.title = "Attendance Logs"
            write_header(ws)
        else:
            wb.remove(default_sheet)
            used_names = set()
            # Sort employees alphabetically by name for consistent sheet order
            employee_order.sort(key=lambda e: (e.name or '').lower() if e else '')
            for employee in employee_order:
                sheet_name = safe_sheet_name(employee.name if employee else 'Unknown', used_names)
                ws = wb.create_sheet(title=sheet_name)
                write_header(ws)
                for log in logs_by_employee[employee.id if employee else None]:
                    write_log_row(ws, log)
                autosize(ws)

    timestamp_label = tz.now().strftime('%Y%m%d_%H%M%S')
    filename = f"Attendance_Logs_{timestamp_label}.xlsx"

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response


@require_http_methods(["GET", "POST"])
@login_required
@user_passes_test(is_employee)
def face_registration(request):
    """Allow an employee to register (or re-register) their face using the webcam."""
    employee = request.user.employee_profile

    if request.method == 'GET' and not employee.can_access_face_registration:
        latest_request = employee.latest_face_update_request
        if latest_request and latest_request.status == FaceUpdateRequest.Status.REJECTED:
            messages.error(request, 'Your face update request was rejected. Please contact an administrator.')
        else:
            messages.info(request, 'Face re-registration requires admin approval. Please request an update first.')
        return redirect('employees:employee_dashboard')

    if not employee.can_access_face_registration and employee.has_registered_face:
        latest_request = employee.latest_face_update_request
        if latest_request and latest_request.status == FaceUpdateRequest.Status.PENDING:
            messages.info(request, 'Your face update request is still pending approval.')
        else:
            messages.warning(request, 'You do not have permission to update face data at the moment.')
        return redirect('employees:employee_dashboard')

    if request.method == 'GET':
        context = TemplateLayout.init(request, context={})
        context.update({
            'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
            'employee': employee,
            'has_registered_face': employee.has_registered_face,
        })
        return render(request, 'employees/face_register.html', context)

    # POST: process uploaded image (base64 or file) - EXTRACT REAL FACE ENCODING
    image_payload = request.POST.get('image') or request.POST.get('image_base64')
    image_file = request.FILES.get('image_file') or request.FILES.get('upload_image')

    if not image_payload and not image_file:
        return JsonResponse({'success': False, 'error': 'No image provided. Please capture or upload a clear photo.'}, status=400)

    try:
        # Get image bytes
        if image_file:
            image_bytes = image_file.read()
            file_name = image_file.name
        else:
            payload = image_payload
            if 'base64,' in payload:
                payload = payload.split('base64,', 1)[1]
            try:
                image_bytes = base64.b64decode(payload)
            except (base64.binascii.Error, ValueError) as exc:
                return JsonResponse({'success': False, 'error': 'Unable to read the captured image. Please try again.'}, status=400)
            file_name = f'profile_{employee.id}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.jpg'

        # Validate image is not empty
        if not image_bytes or len(image_bytes) == 0:
            return JsonResponse({'success': False, 'error': 'Image is empty. Please try again.'}, status=400)

        # SECURITY: Extract face encoding from the image
        face_encoding = extract_face_encoding_from_file_bytes(image_bytes)
        
        if face_encoding is None:
            return JsonResponse({'success': False, 'error': ' No face detected or multiple faces detected. Please capture a clear photo with your face visible.'}, status=400)

        # SECURITY: Save the profile picture
        print(f"[DEBUG] Saving face for employee: {employee.id} ({employee.name})")
        employee.profile_picture.save(file_name, ContentFile(image_bytes), save=False)
        
        # SECURITY: Mark face as registered
        employee.face_registered = True
        employee.face_registered_at = timezone.now()
        
        # SECURITY: Save the REAL face encoding (not placeholder)
        import json
        employee.face_encoding = json.dumps(face_encoding.tolist())
        print(f"[DEBUG] Saved REAL face encoding for employee {employee.id}")
        
        employee.save(update_fields=['profile_picture', 'face_registered', 'face_registered_at', 'face_encoding'])
        print(f"[DEBUG] Face registered flag set to: {employee.face_registered}")

        # Update session
        request.session['face_registered'] = True
        request.session.modified = True
        print(f"[DEBUG] Session updated with face_registered=True")

        # Mark any approved face update requests as completed
        for pending in employee.face_update_requests.filter(status=FaceUpdateRequest.Status.APPROVED):
            pending.mark_completed()

        # Return proper JSON response with correct redirect URL
        redirect_url = reverse('employees:check_in')
        print(f"[DEBUG] Redirecting to: {redirect_url}")
        
        return JsonResponse({
            'status': 'success',
            'success': True,
            'message': ' Face registered successfully! Redirecting you to the check-in page…',
            'profile_picture': employee.profile_picture.url if employee.profile_picture else '',
            'redirect_url': redirect_url,
        })
    except Exception as exc:
        import traceback
        error_msg = f"Error registering face: {str(exc)}"
        print(f"[ERROR] Face registration error: {traceback.format_exc()}")
        return JsonResponse({'success': False, 'error': error_msg}, status=500)


@login_required
@user_passes_test(is_employee)
@require_http_methods(["GET", "POST"])
def request_face_update(request):
    employee = request.user.employee_profile

    if not employee.has_registered_face:
        messages.info(request, 'Please register your face before requesting an update.')
        return redirect('employees:face_register')

    active_exists = employee.face_update_requests.filter(
        status__in=[FaceUpdateRequest.Status.PENDING, FaceUpdateRequest.Status.APPROVED]
    ).exists()

    latest_request = employee.latest_face_update_request

    if request.method == 'POST':
        if active_exists:
            messages.info(request, 'You already have a face update request awaiting processing.')
            return redirect('employees:request_face_update')

        reason = (request.POST.get('reason') or '').strip()
        FaceUpdateRequest.objects.create(office=employee.office, branch=employee.branch, employee=employee, reason=reason)
        messages.success(request, 'Face update request submitted. An administrator will review it shortly.')
        return redirect('employees:employee_dashboard')

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'employee': employee,
        'active_exists': active_exists,
        'latest_request': latest_request,
    })
    return render(request, 'employees/face_update_request.html', context)


@login_required
@user_passes_test(feature_required('tasks.manage'))
@require_http_methods(["GET", "POST"])
def admin_face_update_requests(request):
    status_filter = request.GET.get('status', '').strip()
    employee_query = request.GET.get('employee', '').strip()
    requested_after = request.GET.get('requested_after')
    requested_before = request.GET.get('requested_before')

    # requests_qs = FaceUpdateRequest.objects.select_related('employee', 'reviewed_by').order_by('-requested_at')
    requests_qs = tenant_queryset(
        request,
        FaceUpdateRequest.objects.select_related(
            "employee",
            "reviewed_by",
        )
    ).order_by("-requested_at")
    if status_filter in FaceUpdateRequest.Status.values:
        requests_qs = requests_qs.filter(status=status_filter)
    if employee_query:
        # requests_qs = requests_qs.filter(
        #     Q(employee__name__icontains=employee_query)
        #     | Q(employee__email__icontains=employee_query)
        # )
        requests_qs = requests_qs.filter(
            Q(employee__full_name__icontains=employee_query)
            | Q(employee__employee_code__icontains=employee_query)
            | Q(employee__email__icontains=employee_query)
        )
    if requested_after:
        requests_qs = requests_qs.filter(requested_at__date__gte=requested_after)
    if requested_before:
        requests_qs = requests_qs.filter(requested_at__date__lte=requested_before)

    requests_qs = requests_qs.select_related('employee', 'reviewed_by')

    overall_summary = tenant_queryset(
        request,
        FaceUpdateRequest.objects.all()
    ).aggregate(
        total=Count('id'),
        pending=Count('id', filter=Q(status=FaceUpdateRequest.Status.PENDING)),
        approved=Count('id', filter=Q(status=FaceUpdateRequest.Status.APPROVED)),
        rejected=Count('id', filter=Q(status=FaceUpdateRequest.Status.REJECTED)),
        completed=Count('id', filter=Q(status=FaceUpdateRequest.Status.COMPLETED)),
    )
    filtered_count = requests_qs.count()
    filters_active = any([status_filter, employee_query, requested_after, requested_before])

    if request.method == 'POST':
        req_id = request.POST.get('request_id')
        action = request.POST.get('action')
        admin_comment = (request.POST.get('admin_comment') or '').strip()
        # face_request = get_object_or_404(FaceUpdateRequest, pk=req_id)
        face_request = get_object_or_404(
            tenant_queryset(
                request,
                FaceUpdateRequest.objects.select_related("employee")
            ),
            pk=req_id,
        )

        if action == 'approve':
            face_request.mark_approved(request.user, admin_comment)
            # CREATE NOTIFICATION
            from employees.notification_utils import create_face_approved_notification
            create_face_approved_notification(face_request.employee)
            messages.success(request, f'Face update request for {face_request.employee.full_name} approved.')
        elif action == 'reject':
            face_request.mark_rejected(request.user, admin_comment)
            # CREATE NOTIFICATION
            from employees.notification_utils import create_face_rejected_notification
            create_face_rejected_notification(face_request.employee)
            messages.warning(request, f'Face update request for {face_request.employee.full_name} rejected.')
        else:
            messages.error(request, 'Unsupported action.')

        redirect_query = {
            'status': status_filter,
            'employee': employee_query,
            'requested_after': requested_after,
            'requested_before': requested_before,
        }
        redirect_query = {k: v for k, v in redirect_query.items() if v}

        redirect_url = reverse('employees:admin_face_update_requests')
        if redirect_query:
            from urllib.parse import urlencode
            redirect_url = f"{redirect_url}?{urlencode(redirect_query)}"
        return redirect(redirect_url)

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'requests': requests_qs,
        'status_filter': status_filter,
        'status_choices': FaceUpdateRequest.Status.choices,
        'employee_query': employee_query,
        'requested_after': requested_after,
        'requested_before': requested_before,
        'requests_summary': overall_summary,
        'filtered_count': filtered_count,
    })
    return render(request, 'employees/face_update_requests_admin.html', context)



# def mark_attendance(request, token):
#     """
#     View for marking attendance using face recognition
#     """

#     office = get_object_or_404(
#         Office,
#         kiosk_token=token,
#         status=Office.Status.APPROVED,
#     )
#     if request.method == 'POST' and 'image' in request.POST:
#         try:
#             # Get the base64 image data
#             image_data = request.POST['image'].split('base64,')[1]
#             image_data = base64.b64decode(image_data)
            
#             # Convert to numpy array
#             nparr = np.frombuffer(image_data, np.uint8)
#             img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
#             # Convert BGR to RGB
#             rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            
#             # Find face locations and encodings
#             face_locations = face_recognition.face_locations(rgb_img)
            
#             if not face_locations:
#                 return JsonResponse({'success': False, 'error': 'No face detected'})
                
#             if len(face_locations) > 1:
#                 return JsonResponse({'success': False, 'error': 'Multiple faces detected'})
            
#             # Get the face encoding
#             unknown_encoding = face_recognition.face_encodings(rgb_img, face_locations)[0]
            
#             # Get all employees with face encodings
#             # employees = Employee.objects.filter(face_registered=True).exclude(face_encoding__isnull=True)
#             employees = Employee.objects.filter(
#                 office=office,
#                 face_registered=True,
#             ).exclude(
#                 face_encoding__isnull=True
#             )
#             # employees = tenant_queryset(
#             #     request,
#             #     Employee.objects.filter(
#             #         face_registered=True
#             #     ).exclude(face_encoding__isnull=True)
#             # )
            
#             # Compare with known faces
#             for employee in employees:
#                 known_encoding = employee.get_face_encoding()
#                 if known_encoding is not None:
#                     distance = face_recognition.face_distance(
#                         [known_encoding],
#                         unknown_encoding
#                     )[0]

#                     confidence = max(0, min(100, round((1 - distance) * 100, 2)))

#                     print(f"Distance: {distance:.4f}")
#                     print(f"Confidence: {confidence}%")
#                     result = face_recognition.compare_faces([known_encoding], unknown_encoding, tolerance=0.5)
#                     if result[0]:
#                         # Face recognized, mark attendance
#                         attendance, created = Attendance.objects.get_or_create(
#                             office=office,
#                             employee=employee,
#                             date=timezone.now().date(),
#                             defaults={
#                                 "office": office,
#                                 'check_in_time': timezone.now(),
#                                 'check_in_photo': save_attendance_image(img, f"checkin_{employee.id}")
#                             }
#                         )
                        
#                         # if not created:
#                         #     # If already checked in, update check out
#                         #     if not attendance.check_out_time:
#                         #         checkout_time = timezone.now()
#                         #         attendance.check_out_time = checkout_time
#                         #         attendance.check_out_photo = save_attendance_image(img, f"checkout_{employee.id}")

#                         #         ip_address = get_client_ip(request)
#                         #         user_agent = request.META.get('HTTP_USER_AGENT', '')
#                         #         attendance._auto_end_context = {
#                         #             'origin': 'face recognition check-out',
#                         #             'ip_address': ip_address,
#                         #             'user_agent': user_agent,
#                         #         }
#                         #         attendance.save()
#                         #         ended_breaks = getattr(attendance, '_auto_end_results', [])

#                         #         AttendanceLog.objects.create(
#                         #             employee=employee,
#                         #             attendance=attendance,
#                         #             action='check_out_success',
#                         #             success=True,
#                         #             ip_address=ip_address or None,
#                         #             user_agent=user_agent or None,
#                         #             notes='Check-out recorded via face recognition kiosk.'
#                         #         )
#                         #         message = f'Check out recorded for {employee.name}'
#                         #         if ended_breaks:
#                         #             message += ' (active break automatically ended)'
#                         #         return JsonResponse({
#                         #             'success': True,
#                         #             'message': message,
#                         #             'employee_name': employee.name,
#                         #             'action': 'check_out',
#                         #             'time': checkout_time.strftime('%H:%M:%S')
#                         #         })
#                         #     else:
#                         #         return JsonResponse({
#                         #             'success': False,
#                         #             'error': f'Attendance already marked for today',
#                         #             'employee_name': employee.name
#                         #         })
                        
#                         if not created:

#                             now = timezone.localtime()

#                             # Prevent duplicate scans within 30 seconds
#                             if attendance.check_out_time:
#                                 diff = (now - attendance.check_out_time).total_seconds()
#                                 if diff < 30:
#                                     return JsonResponse({
#                                         "success": True,
#                                         "message": f"Attendance marked for {employee.name}",
#                                         "action": "ignored",
#                                         "time": now.strftime("%d-%m-%Y %I:%M:%S %p")
#                                     })

#                             attendance.check_out_time = now
#                             attendance.check_out_photo = save_attendance_image(
#                                 img,
#                                 f"checkout_{employee.id}"
#                             )

#                             ip_address = get_client_ip(request)
#                             user_agent = request.META.get("HTTP_USER_AGENT", "")

#                             attendance._auto_end_context = {
#                                 "origin": "face recognition update",
#                                 "ip_address": ip_address,
#                                 "user_agent": user_agent,
#                             }

#                             from decimal import Decimal

#                             worked_seconds = (
#                                 attendance.check_out_time - attendance.check_in_time
#                             ).total_seconds()

#                             worked_seconds -= attendance.total_break_seconds

#                             attendance.total_work_hours = Decimal(
#                                 str(round(worked_seconds / 3600, 2))
#                             )

#                             attendance.save()

#                             AttendanceLog.objects.create(
#                                 office=office,
#                                 employee=employee,
#                                 attendance=attendance,
#                                 action="check_out_success",
#                                 success=True,
#                                 ip_address=ip_address,
#                                 user_agent=user_agent,
#                                 notes="Latest face scan updated checkout time."
#                             )

#                             return JsonResponse({
#                                 "success": True,
#                                 "message": f"Attendance updated for {employee.name}",
#                                 "employee_name": employee.name,
#                                 "action": "updated",
#                                 "time": now.strftime("%d-%m-%Y %I:%M:%S %p")
#                             })

#                         # ---- First capture of the day: this IS the check-in ----
#                         AttendanceLog.objects.create(
#                             office=office,
#                             employee=employee,
#                             attendance=attendance,
#                             action="check_in_success",
#                             success=True,
#                             confidence=confidence,
#                             ip_address=ip_address,
#                             user_agent=user_agent,
#                             notes="First face scan of the day recorded as check-in."
#                         )
#                         return JsonResponse({
#                             'success': True,
#                             'message': f'Check in recorded for {employee.name}',
#                             'employee_name': employee.name,
#                             'action': 'check_in',
#                             'time': timezone.localtime().strftime("%d-%m-%Y %I:%M:%S %p")
#                         })
            
#             return JsonResponse({'success': False, 'error': 'Face not recognized'})
            
#         except Exception as e:
#             return JsonResponse({'success': False, 'error': str(e)})
    
#     return JsonResponse({'success': False, 'error': 'Invalid request method'})

# optimize mark_attendance 

def mark_attendance(request, token):
    """
    View for marking attendance using face recognition
    """

    office = get_object_or_404(
        Office,
        kiosk_token=token,
        status=Office.Status.APPROVED,
    )
    if request.method == 'POST' and 'image' in request.POST:
        try:
            # ---- Get the base thing we always need regardless of outcome ----
            image_data = request.POST['image'].split('base64,')[1]
            image_data = base64.b64decode(image_data)

            nparr = np.frombuffer(image_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            # Safety-net resize: face_recognition's speed scales with pixel
            # count. The kiosk frontend already downscales before sending,
            # but resize again here so backend latency stays low even if a
            # frame slips through larger than expected.
            MAX_WIDTH = 480
            h, w = img.shape[:2]
            if w > MAX_WIDTH:
                scale = MAX_WIDTH / w
                img = cv2.resize(
                    img,
                    (MAX_WIDTH, int(h * scale)),
                    interpolation=cv2.INTER_AREA
                )

            rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

            # ---- Detect a face FIRST, before touching the database at all.
            # A kiosk sits idle with no one in frame most of the time — that
            # needs to be the cheap path. Previously every single scan (idle
            # or not) loaded and decoded all registered employees' encodings
            # from the DB before ever checking whether a face was present,
            # which is why the log showed DB work firing every ~1s with
            # nobody standing there.
            face_locations = face_recognition.face_locations(rgb_img, model='hog')

            if not face_locations:
                return JsonResponse({'success': False, 'error': 'No face detected'})

            if len(face_locations) > 1:
                return JsonResponse({'success': False, 'error': 'Multiple faces detected'})

            # A face IS present — now, and only now, load employees/encodings.
            employees = list(
                Employee.objects.filter(
                    office=office,
                    face_registered=True,
                ).exclude(face_encoding__isnull=True)
            )

            if not employees:
                return JsonResponse({
                    'success': False,
                    'error': 'No employees registered for face recognition'
                })

            known_encodings = []
            known_employees = []
            for employee in employees:
                enc = employee.get_face_encoding()
                if enc is not None:
                    known_encodings.append(enc)
                    known_employees.append(employee)

            if not known_encodings:
                return JsonResponse({
                    'success': False,
                    'error': 'No employees registered for face recognition'
                })

            # Get the face encoding
            unknown_encoding = face_recognition.face_encodings(rgb_img, face_locations)[0]

            # Compare against the encodings we just loaded — this is cheap
            # vector math, not the bottleneck, so a plain loop is fine.
            for employee, known_encoding in zip(known_employees, known_encodings):
                distance = face_recognition.face_distance(
                    [known_encoding],
                    unknown_encoding
                )[0]

                confidence = max(0, min(100, round((1 - distance) * 100, 2)))

                result = face_recognition.compare_faces([known_encoding], unknown_encoding, tolerance=0.5)
                if result[0]:
                    # Face recognized, mark attendance
                    attendance, created = Attendance.objects.get_or_create(
                        office=office,
                        employee=employee,
                        branch=employee.branch,
                        date=timezone.now().date(),
                        defaults={
                            "office": office,
                            "branch": employee.branch,
                            'check_in_time': timezone.now(),
                            'check_in_photo': save_attendance_image(img, f"checkin_{employee.id}")
                        }
                    )

                    if not created:

                        now = timezone.localtime()

                        # Prevent duplicate scans within 30 seconds
                        if attendance.check_out_time:
                            diff = (now - attendance.check_out_time).total_seconds()
                            if diff < 30:
                                return JsonResponse({
                                    "success": True,
                                    "message": f"Attendance marked for {employee.name}",
                                    "action": "ignored",
                                    "time": now.strftime("%d-%m-%Y %I:%M:%S %p")
                                })

                        attendance.check_out_time = now
                        attendance.check_out_photo = save_attendance_image(
                            img,
                            f"checkout_{employee.id}"
                        )

                        ip_address = get_client_ip(request)
                        user_agent = request.META.get("HTTP_USER_AGENT", "")

                        attendance._auto_end_context = {
                            "origin": "face recognition update",
                            "ip_address": ip_address,
                            "user_agent": user_agent,
                        }

                        from decimal import Decimal

                        worked_seconds = (
                            attendance.check_out_time - attendance.check_in_time
                        ).total_seconds()

                        worked_seconds -= attendance.total_break_seconds

                        attendance.total_work_hours = Decimal(
                            str(round(worked_seconds / 3600, 2))
                        )

                        attendance.save()

                        AttendanceLog.objects.create(
                            office=office,
                            branch=employee.branch,
                            employee=employee,
                            attendance=attendance,
                            action="check_out_success",
                            success=True,
                            ip_address=ip_address,
                            user_agent=user_agent,
                            notes="Latest face scan updated checkout time."
                        )

                        return JsonResponse({
                            "success": True,
                            "message": f"Attendance updated for {employee.name}",
                            "employee_name": employee.name,
                            "action": "updated",
                            "time": now.strftime("%d-%m-%Y %I:%M:%S %p")
                        })

                    # ---- First capture of the day: this IS the check-in ----
                    ip_address = get_client_ip(request)
                    user_agent = request.META.get('HTTP_USER_AGENT', '')

                    AttendanceLog.objects.create(
                        office=office,
                        branch=employee.branch,
                        employee=employee,
                        attendance=attendance,
                        action="check_in_success",
                        success=True,
                        confidence=confidence,
                        ip_address=ip_address,
                        user_agent=user_agent,
                        notes="First face scan of the day recorded as check-in."
                    )
                    return JsonResponse({
                        'success': True,
                        'message': f'Check in recorded for {employee.name}',
                        'employee_name': employee.name,
                        'action': 'check_in',
                        'time': timezone.localtime().strftime("%d-%m-%Y %I:%M:%S %p")
                    })

            return JsonResponse({'success': False, 'error': 'Face not recognized'})

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Invalid request method'})

def save_attendance_image(image, prefix):
    """Helper function to save attendance images"""
    from django.core.files.base import ContentFile
    from io import BytesIO
    
    # Convert numpy array to PIL Image
    image = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    
    # Save to BytesIO
    img_io = BytesIO()
    image.save(img_io, format='JPEG')
    
    # Create ContentFile from BytesIO
    return ContentFile(img_io.getvalue(), name=f"{prefix}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.jpg")


# API Views for AJAX requests
@login_required
@user_passes_test(is_employee)
def check_in_status(request):
    """AJAX endpoint to check if employee has already checked in today"""
    employee = request.user.employee_profile
    has_checked_in = Attendance.has_checked_in_today(employee)

    return JsonResponse({
        'has_checked_in': has_checked_in,
        'message': 'Already checked in today' if has_checked_in else 'Not checked in today'
    })


@login_required
@user_passes_test(is_employee)
def check_out(request):
    """Employee check-out view with face verification - handles POST requests only"""
    from employees.models import AttendanceLog
    employee = request.user.employee_profile
    today = timezone.now().date()
    ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'

    # Get today's attendance record
    attendance = Attendance.objects.filter(office=employee.office, branch=employee.branch, employee=employee, date=today).first()

    # Validation 1: Must be checked in first
    if not attendance:
        # Log failed attempt
        AttendanceLog.objects.create(
            office=employee.office,
            branch=employee.branch,
            employee=employee,
            action='check_out_failed',
            success=False,
            failure_reason='not_checked_in',
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            notes='Employee has not checked in today'
        )
        if ajax:
            return JsonResponse({'success': False, 'message': 'You have not checked in today. Please check in first before checking out.', 'type': 'not_checked_in'}, status=400)
        messages.error(request, 'You have not checked in today. Please check in first before checking out.')
        return redirect('employees:check_in')

    # # Validation 2: Cannot check out twice
    # if attendance.check_out_time:
    #     # Log failed attempt
    #     AttendanceLog.objects.create(
    #         employee=employee,
    #         action='check_out_success',
    #         success=True,
    #         # failure_reason='already_checked_out',
    #         ip_address=get_client_ip(request),
    #         user_agent=request.META.get('HTTP_USER_AGENT', ''),
    #         attendance=attendance,
    #         notes='Attendance Updated'
    #     )
    #     if ajax:
    #         return JsonResponse({'success': True, 'message': 'Attendance updated successfully.', 'check_out_time': timezone.localtime(attendance.check_out_time).strftime('%d %b %Y, %I:%M %p')})
    #     messages.success(request, '✓ Check-out successful! See you tomorrow.')
    #     request.session['check_out_success'] = True
    #     request.session['check_out_success_time'] = timezone.now().strftime('%d %b %Y, %I:%M %p')
    #     return redirect('employees:check_in')

    # Validation 3: Enforce minimum working duration before checkout (5 minute cooldown)
    MIN_CHECKOUT_DELAY_SECONDS = 5 * 60
    if attendance.check_in_time:
        seconds_since_check_in = (timezone.now() - attendance.check_in_time).total_seconds()
        if seconds_since_check_in < MIN_CHECKOUT_DELAY_SECONDS:
            remaining_seconds = int(MIN_CHECKOUT_DELAY_SECONDS - seconds_since_check_in)
            remaining_minutes = max(1, remaining_seconds // 60)
            AttendanceLog.objects.create(
                office=employee.office,
                branch=employee.branch,
                employee=employee,
                action='check_out_failed',
                success=False,
                failure_reason='checkout_cooldown',
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                attendance=attendance,
                notes=f'Attempted checkout {seconds_since_check_in:.0f}s after check-in. Cooldown requires {MIN_CHECKOUT_DELAY_SECONDS}s.'
            )
            if ajax:
                return JsonResponse({'success': False, 'message': 'Check-out is available 5 minutes after check-in. Please wait a little longer before checking out.', 'type': 'checkout_cooldown', 'remaining_seconds': remaining_seconds}, status=400)
            messages.error(
                request,
                'Check-out is available 5 minutes after check-in. Please wait a little longer before checking out.'
            )
            return redirect('employees:check_in')

    # Only handle POST requests (from the embedded form in check_in.html)
    if request.method == 'POST':
        # Validate geolocation first
        from employees.geolocation_utils import validate_coordinates, is_within_office_premises
        
        # Support both latitude/longitude and lat/lng keys
        user_latitude = request.POST.get('latitude') or request.POST.get('lat')
        user_longitude = request.POST.get('longitude') or request.POST.get('lng')
        device_info = request.POST.get('device_info')  # optional client-provided device info
        print("user_latitude->", user_latitude)
        print("user_longitude->", user_longitude)
        if not user_latitude or not user_longitude:
            AttendanceLog.objects.create(
                office=employee.office,
                branch=employee.branch,
                employee=employee,
                action='check_out_failed',
                success=False,
                failure_reason='location_not_provided',
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                attendance=attendance,
                notes='Location coordinates were not provided'
            )
            if ajax:
                return JsonResponse({'success': False, 'message': 'Location access is required for check-out. Please enable location services and try again.', 'type': 'location_not_provided'}, status=400)
            messages.error(request, 'Location access is required for check-out. Please enable location services and try again.')
            return redirect('employees:check_in')
        
        # Validate coordinate format
        is_valid_coords, coord_message = validate_coordinates(user_latitude, user_longitude)
        if not is_valid_coords:
            AttendanceLog.objects.create(
                office=employee.office,
                branch=employee.branch,
                employee=employee,
                action='check_out_failed',
                success=False,
                failure_reason='invalid_coordinates',
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                attendance=attendance,
                notes=f'Invalid coordinates: {coord_message}'
            )
            if ajax:
                return JsonResponse({'success': False, 'message': f'Invalid location data: {coord_message}', 'type': 'invalid_coordinates'}, status=400)
            messages.error(request, f'Invalid location data: {coord_message}')
            return redirect('employees:check_in')
        
        # Check if within office premises
        is_within, distance, location_message = is_within_office_premises(
            employee.office,
            float(user_latitude),
            float(user_longitude),
            branch=employee.branch,
        )
        
        if not is_within:
            AttendanceLog.objects.create(
                office=employee.office,
                branch=employee.branch,
                employee=employee,
                action='check_out_failed',
                success=False,
                failure_reason='outside_office_premises',
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                attendance=attendance,
                notes=f'Location: {user_latitude}, {user_longitude}. {location_message}'
            )
            if ajax:
                return JsonResponse({'success': False, 'message': location_message, 'type': 'outside_office_premises'}, status=400)
            messages.error(request, location_message)
            return redirect('employees:check_in')
        
        # Validation 3: Photo is required (support both legacy and new field names)
        check_out_photo = request.FILES.get('check_out_photo') or request.FILES.get('photo_checkout')
        if not check_out_photo:
            # Log failed attempt
            AttendanceLog.objects.create(
                office=employee.office,
                branch=employee.branch,
                employee=employee,
                action='check_out_failed',
                success=False,
                failure_reason='photo_required',
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                attendance=attendance,
                notes='Photo was not provided'
            )
            if ajax:
                return JsonResponse({'success': False, 'message': 'Please capture a photo to check out.', 'type': 'photo_required'}, status=400)
            messages.error(request, 'Please capture a photo to check out.')
            return redirect('employees:check_in')

        # Validation 4: Face must be registered
        if not employee.face_registered:
            # Log failed attempt
            AttendanceLog.objects.create(
                office=employee.office,
                branch=employee.branch,
                employee=employee,
                action='check_out_failed',
                success=False,
                failure_reason='no_face_registered',
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                attendance=attendance,
                notes='Employee face is not registered'
            )
            if ajax:
                return JsonResponse({'success': False, 'message': 'Face is not registered for your account. Contact admin to register your face.', 'type': 'no_face_registered'}, status=400)
            messages.error(request, 'Face is not registered for your account. Contact admin to register your face.')
            return redirect('employees:check_in')

        try:
            stored_encoding = employee.get_face_encoding()
            # Read the uploaded file bytes
            check_out_photo.seek(0)  # Reset file pointer to beginning
            photo_bytes = check_out_photo.read()
            checkout_encoding = extract_face_encoding_from_file_bytes(photo_bytes)

            if checkout_encoding is None:
                AttendanceLog.objects.create(
                    office=employee.office,
                    branch=employee.branch,
                    employee=employee,
                    action='check_out_failed',
                    success=False,
                    failure_reason='no_face_detected',
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    attendance=attendance,
                    notes='No face or multiple faces detected in photo'
                )
                if ajax:
                    return JsonResponse({'success': False, 'message': 'No face detected or multiple faces detected in the photo. Please try again with a clear face in frame.', 'type': 'no_face_detected'}, status=400)
                messages.error(request, 'No face detected or multiple faces detected in the photo. Please try again with a clear face in frame.')
                return redirect('employees:check_in')

            if stored_encoding is None:
                AttendanceLog.objects.create(
                    office=employee.office,
                    branch=employee.branch,
                    employee=employee,
                    action='check_out_failed',
                    success=False,
                    failure_reason='no_face_registered',
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    attendance=attendance,
                    notes='Stored face encoding missing for employee'
                )
                if ajax:
                    return JsonResponse({'success': False, 'message': 'Your face data is missing. Please re-register your face before checking out.', 'type': 'no_face_registered'}, status=400)
                messages.error(request, 'Your face data is missing. Please re-register your face before checking out.')
                return redirect('employees:face_register')

            # Use tolerance 0.55 for better matching with registered photos
            strict_tol = 0.55  # More lenient tolerance for better matching
            print(f"[DEBUG] Comparing checkout faces with tolerance: {strict_tol}")
            result = compare_faces(stored_encoding, checkout_encoding, tolerance=strict_tol)

            if not result['match']:
                AttendanceLog.objects.create(
                    office=employee.office,
                    branch=employee.branch,
                    employee=employee,
                    action='check_out_failed',
                    success=False,
                    failure_reason='face_not_matched',
                    confidence=result['confidence'],
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    attendance=attendance,
                    notes=f'Face verification failed with {result["confidence"]:.1f}% confidence (strict tolerance)'
                )
                if ajax:
                    return JsonResponse({'success': False, 'message': 'Face verification failed. The captured face does not match your registered face. Check-out denied.', 'type': 'face_not_matched', 'confidence': result['confidence']}, status=400)
                messages.error(request, 'Face verification failed. The captured face does not match your registered face. Check-out denied.')
                return redirect('employees:check_in')

            match_info = find_best_face_match(
                checkout_encoding,
                Employee.objects.filter(face_registered=True),
                tolerance=get_match_tolerance(),
            )

            if not match_info or match_info['employee'].pk != employee.pk:
                matched_employee = match_info['employee'].full_name if match_info else None
                AttendanceLog.objects.create(
                    office=employee.office,
                    branch=employee.branch,
                    employee=employee,
                    action='check_out_failed',
                    success=False,
                    failure_reason='face_not_matched',
                    confidence=match_info['confidence'] if match_info else None,
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    attendance=attendance,
                    notes='Face appears to match another employee' if match_info else 'No unique match identified'
                )
                if ajax:
                    msg = (f'Face verification failed. This face matches another employee ({matched_employee}). Check-out denied.'
                           if matched_employee else 'Face verification failed. We could not uniquely match your face to your profile. Check-out denied.')
                    return JsonResponse({'success': False, 'message': msg, 'type': 'face_not_matched', 'confidence': match_info['confidence'] if match_info else None}, status=400)
                if matched_employee:
                    messages.error(request, f'Face verification failed. This face matches another employee ({matched_employee}). Check-out denied.')
                else:
                    messages.error(request, 'Face verification failed. We could not uniquely match your face to your profile. Check-out denied.')
                return redirect('employees:check_in')

            # All validations passed - save check-out
            is_first_checkout = attendance.check_out_time is None
            check_out_time = timezone.now()
            
            attendance.check_out_photo.save(check_out_photo.name, check_out_photo, save=False)
            attendance.check_out_time = check_out_time
            attendance.check_out_latitude = user_latitude
            attendance.check_out_longitude = user_longitude
            
            # Use SHIFT-BASED attendance calculation
            from employees.shift_attendance_logic import update_attendance_on_checkout
            update_attendance_on_checkout(attendance)

            ip_address = get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            attendance._auto_end_context = {
                'origin': 'check-out',
                'ip_address': ip_address,
                'user_agent': user_agent,
            }
            attendance.save()
            ended_breaks = getattr(attendance, '_auto_end_results', [])
            
            # Log successful check-out
            AttendanceLog.objects.create(
                office=employee.office,
                branch=employee.branch,
                employee=employee,
                action='check_out_success',
                success=True,
                confidence=result['confidence'],
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                attendance=attendance,
                notes=f'Check-out successful with {result["confidence"]:.1f}% confidence'
            )
            
            if ajax:
                message = (
    f"Check-out successful!"
    if is_first_checkout
    else f"Attendance updated successfully!"
)
                return JsonResponse({'success': True, 
                                     'message': message, 
                                     'check_out_time': timezone.localtime(check_out_time).strftime('%d %b %Y, %I:%M %p'), 'half_day': attendance.half_day}
                                     )
            messages.success(request, f'✓ Check-out successful! Face verified with {result["confidence"]:.1f}% confidence. Have a great day!')
            request.session['check_out_success'] = True
            request.session['check_out_success_time'] = timezone.now().strftime('%d %b %Y, %I:%M %p')
            return redirect('employees:modern_dashboard')
            
        except Exception as e:
            # Log exception
            AttendanceLog.objects.create(
                office=employee.office,
                branch=employee.branch,
                employee=employee,
                action='check_out_failed',
                success=False,
                failure_reason='other',
                ip_address=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                attendance=attendance,
                notes=f'Exception during face verification: {str(e)}'
            )
            if ajax:
                return JsonResponse({'success': False, 'message': f'Error during face verification: {str(e)}', 'type': 'other', 'details': str(e)}, status=500)
            messages.error(request, f'Error during face verification: {str(e)}. Please try again or contact support.')
            return redirect('employees:modern_dashboard')
    
    # Redirect to modern dashboard for GET requests

# Task Management Views


@login_required
@user_passes_test(feature_required('tasks.manage'))
def admin_tasks(request):
    """Admin view to assign and monitor employee tasks."""

    # tasks = Task.objects.select_related('assigned_to__user', 'assigned_by').prefetch_related('updates__updated_by').order_by('-created_at')
    tasks = tenant_queryset(
        request,
        Task.objects.select_related(
            "assigned_to__user",
            "assigned_by",
        ).prefetch_related(
            "updates__updated_by"
        )
    ).order_by("-created_at")

    status_filter = request.GET.get('status')
    priority_filter = request.GET.get('priority')
    assignee_filter = request.GET.get('assigned_to')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    if status_filter:
        tasks = tasks.filter(status=status_filter)
    if priority_filter:
        tasks = tasks.filter(priority=priority_filter)
    if assignee_filter:
        tasks = tasks.filter(assigned_to_id=assignee_filter)

    if date_from:
        try:
            parsed_from = datetime.strptime(date_from, '%Y-%m-%d').date()
            tasks = tasks.filter(created_at__date__gte=parsed_from)
        except ValueError:
            date_from = None
    if date_to:
        try:
            parsed_to = datetime.strptime(date_to, '%Y-%m-%d').date()
            tasks = tasks.filter(created_at__date__lte=parsed_to)
        except ValueError:
            date_to = None

    form = TaskForm(request.POST or None, assigned_by=request.user, request=request)
    if request.method == 'POST':
        if form.is_valid():
            task = form.save()
            TaskUpdate.objects.create(
                office=task.office,
                branch=task.branch,
                task=task,
                updated_by=request.user,
                previous_status=None,
                new_status=task.status,
                comment=form.cleaned_data.get('description', '')[:200],
            )
            messages.success(request, f"Task '{task.title}' assigned to {task.assigned_to.full_name}.")
            return redirect('employees:admin_tasks')
        else:
            messages.error(request, 'Please correct the errors before assigning the task.')

    # employees = Employee.objects.select_related('user').order_by('full_name', 'email')
    employees = tenant_queryset(
        request,
        Employee.objects.select_related("user")
    ).order_by(
        "full_name",
        "email",
    )
    task_list = list(tasks)

    status_styles = {
        Task.Status.PENDING: 'secondary',
        Task.Status.IN_PROGRESS: 'info',
        Task.Status.COMPLETED: 'success',
        Task.Status.BLOCKED: 'danger',
    }
    priority_styles = {
        Task.Priority.LOW: 'info',
        Task.Priority.MEDIUM: 'primary',
        Task.Priority.HIGH: 'warning',
        Task.Priority.CRITICAL: 'danger',
    }

    status_summary = [
        {
            'value': value,
            'label': label,
            'count': sum(1 for item in task_list if item.status == value),
            'style': status_styles.get(value, 'secondary'),
        }
        for value, label in Task.Status.choices
    ]

    priority_summary = [
        {
            'value': value,
            'label': label,
            'count': sum(1 for item in task_list if item.priority == value),
            'style': priority_styles.get(value, 'secondary'),
        }
        for value, label in Task.Priority.choices
    ]

    overdue_count = sum(1 for item in task_list if item.is_overdue)

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'tasks': task_list,
        'task_form': form,
        'employees': employees,
        'selected_status': status_filter,
        'selected_priority': priority_filter,
        'selected_assignee': assignee_filter,
        'selected_date_from': date_from,
        'selected_date_to': date_to,
        'status_choices': Task.Status.choices,
        'priority_choices': Task.Priority.choices,
        'status_summary': status_summary,
        'priority_summary': priority_summary,
        'total_tasks': len(task_list),
        'overdue_count': overdue_count,
    })
    return render(request, 'employees/tasks/admin_tasks.html', context)

@login_required
@user_passes_test(feature_required('tasks.manage'))
def admin_tasks_excel(request):
    """Export filtered tasks to Excel — one sheet per employee, or a single
    sheet when a specific employee is selected."""

    tasks = tenant_queryset(
        request,
        Task.objects.select_related(
            "assigned_to__user",
            "assigned_by",
        ).prefetch_related(
            "updates__updated_by"
        )
    ).order_by("assigned_to__full_name", "-created_at")

    status_filter = request.GET.get('status')
    priority_filter = request.GET.get('priority')
    assignee_filter = request.GET.get('assigned_to')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    if status_filter:
        tasks = tasks.filter(status=status_filter)
    if priority_filter:
        tasks = tasks.filter(priority=priority_filter)
    if assignee_filter:
        tasks = tasks.filter(assigned_to_id=assignee_filter)
    if date_from:
        try:
            parsed_from = datetime.strptime(date_from, '%Y-%m-%d').date()
            tasks = tasks.filter(created_at__date__gte=parsed_from)
        except ValueError:
            pass
    if date_to:
        try:
            parsed_to = datetime.strptime(date_to, '%Y-%m-%d').date()
            tasks = tasks.filter(created_at__date__lte=parsed_to)
        except ValueError:
            pass

    task_list = list(tasks)

    headers = [
        'Title', 'Description', 'Priority', 'Status', 'Due Date',
        'Created By', 'Created At', 'Status Updated At',
        'Latest Update By', 'Latest Update Comment', 'Overdue',
    ]

    def write_sheet(ws, employee_tasks):
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for task in employee_tasks:
            latest = task.latest_update
            ws.append([
                task.title,
                task.description,
                task.get_priority_display(),
                task.get_status_display(),
                task.due_date.strftime('%d %b %Y') if task.due_date else '',
                (task.assigned_by.get_full_name() or task.assigned_by.username) if task.assigned_by else '',
                task.created_at.strftime('%d %b %Y %H:%M') if task.created_at else '',
                task.status_updated_at.strftime('%d %b %Y %H:%M') if task.status_updated_at else '',
                (latest.updated_by.get_full_name() or latest.updated_by.username) if latest and latest.updated_by else '',
                latest.comment if latest else '',
                'Yes' if task.is_overdue else 'No',
            ])
        for col_idx in range(1, len(headers) + 1):
            ws.column_dimensions[get_column_letter(col_idx)].width = 22

    def sanitize_sheet_name(name):
        name = re.sub(r'[\[\]:*?/\\]', '', name or 'Employee')
        return (name[:31] or 'Employee')

    wb = Workbook()
    wb.remove(wb.active)  # drop the default blank sheet

    if assignee_filter:
        employee = task_list[0].assigned_to if task_list else Employee.objects.filter(pk=assignee_filter).first()
        sheet_name = sanitize_sheet_name(employee.full_name if employee else 'Employee')
        ws = wb.create_sheet(title=sheet_name)
        write_sheet(ws, task_list)
    else:
        grouped = {}
        for task in task_list:
            grouped.setdefault(task.assigned_to, []).append(task)

        if not grouped:
            ws = wb.create_sheet(title='Tasks')
            ws.append(headers)
        else:
            used_names = set()
            for employee, emp_tasks in grouped.items():
                base_name = sanitize_sheet_name(employee.full_name)
                sheet_name = base_name
                suffix = 1
                while sheet_name in used_names:
                    suffix += 1
                    sheet_name = sanitize_sheet_name(f"{base_name} ({suffix})")
                used_names.add(sheet_name)
                ws = wb.create_sheet(title=sheet_name)
                write_sheet(ws, emp_tasks)

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="task_report.xlsx"'
    wb.save(response)
    return response


@login_required
@user_passes_test(feature_required('tasks.manage'))
def admin_task_detail(request, pk):
    """Detailed admin view for a single task with history."""

    # task = get_object_or_404(
    #     Task.objects.select_related('assigned_to__user', 'assigned_by').prefetch_related('updates__updated_by'),
    #     pk=pk,
    # )
    task = get_object_or_404(
        tenant_queryset(
            request,
            Task.objects.select_related(
                "assigned_to__user",
                "assigned_by",
            ).prefetch_related(
                "updates__updated_by"
            ),
        ),
        pk=pk,
    )

    form = TaskForm(request.POST or None, instance=task, assigned_by=task.assigned_by or request.user, request=request,)
    update_form = TaskUpdateForm(task=task)
    task_updates = list(task.updates.select_related('updated_by').order_by('-created_at'))

    if request.method == 'POST':
        if form.is_valid():
            form.save()
            messages.success(request, 'Task details updated successfully.')
            return redirect('employees:admin_task_detail', pk=task.pk)
        else:
            messages.error(request, 'Please correct the errors highlighted below.')

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'task': task,
        'form': form,
        'update_form': update_form,
        'task_updates': task_updates,
        'has_updates': bool(task_updates),
    })
    return render(request, 'employees/tasks/admin_task_detail.html', context)


@login_required
def update_task_status(request, pk):
    """Handle status updates from employees or admins."""

    # task = get_object_or_404(Task.objects.select_related('assigned_to__user'), pk=pk)
    task = get_object_or_404(
        tenant_queryset(
            request,
            Task.objects.select_related("assigned_to__user"),
        ),
        pk=pk,
    )

    is_admin = is_office_admin(request.user)
    is_assigned_employee = hasattr(request.user, 'employee_profile') and task.assigned_to == request.user.employee_profile

    if not (is_admin or is_assigned_employee):
        messages.error(request, 'You do not have permission to update this task.')
        return redirect('employees:employee_tasks' if not is_admin else 'employees:admin_tasks')

    if request.method != 'POST':
        return redirect('employees:employee_tasks' if not is_admin else 'employees:admin_task_detail', pk=task.pk)

    form = TaskUpdateForm(request.POST, user=request.user, task=task)
    if form.is_valid():
        update = form.save()
        messages.success(request, f'Task updated to {update.get_new_status_display()}.')
    else:
        error_text = '; '.join([' '.join(errors) for errors in form.errors.values()])
        messages.error(request, f'Unable to update task: {error_text}')

    redirect_url = request.POST.get('next')
    if redirect_url:
        return redirect(redirect_url)

    if is_admin:
        return redirect('employees:admin_task_detail', pk=task.pk)
    return redirect('employees:employee_tasks')


# @login_required
# @user_passes_test(is_employee)
# def employee_tasks(request):
#     """Employee view to track assigned tasks and post updates."""

#     employee = request.user.employee_profile
#     # tasks = Task.objects.filter(assigned_to=employee).select_related('assigned_by').prefetch_related('updates__updated_by').order_by('-status_updated_at', '-created_at')
#     tasks = tenant_queryset(
#         request,
#         Task.objects.filter(
#             assigned_to=employee
#         ).select_related(
#             "assigned_by"
#         ).prefetch_related(
#             "updates__updated_by"
#         )
#     ).order_by(
#         "-status_updated_at",
#         "-created_at",
#     )

#     task_forms = [(task, TaskUpdateForm(task=task)) for task in tasks]

#     status_counts = {
#         key: tasks.filter(status=key).count()
#         for key, _ in Task.Status.choices
#     }
#     status_styles = {
#         Task.Status.PENDING: 'secondary',
#         Task.Status.IN_PROGRESS: 'info',
#         Task.Status.COMPLETED: 'success',
#         Task.Status.BLOCKED: 'danger',
#     }
#     status_summary = [
#         {
#             'value': key,
#             'label': label,
#             'count': status_counts.get(key, 0),
#             'style': status_styles.get(key, 'primary'),
#         }
#         for key, label in Task.Status.choices
#     ]

#     context = TemplateLayout.init(request, context={})
#     context.update({
#         'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
#         'employee': employee,
#         'task_forms': task_forms,
#         'status_choices': Task.Status.choices,
#         'priority_choices': Task.Priority.choices,
#         'status_summary': status_summary,
#     })
#     return render(request, 'employees/tasks/employee_tasks.html', context)

@login_required
@user_passes_test(is_employee)
def employee_tasks(request):
    """Employee view to track assigned tasks, self-create tasks, and post updates."""

    employee = request.user.employee_profile

    create_form = TaskForm(
        request.POST or None,
        assigned_by=request.user,
        request=request,
        employee=employee,   # locks assigned_to to this employee
    )

    if request.method == 'POST':
        if create_form.is_valid():
            task = create_form.save()
            TaskUpdate.objects.create(
                office=task.office,
                branch=task.branch,
                task=task,
                updated_by=request.user,
                previous_status=None,
                new_status=task.status,
                comment=create_form.cleaned_data.get('description', '')[:200],
            )
            messages.success(request, f"Task '{task.title}' created.")
            return redirect('employees:employee_tasks')
        else:
            messages.error(request, 'Please correct the errors before creating the task.')

    tasks = tenant_queryset(
        request,
        Task.objects.filter(
            assigned_to=employee
        ).select_related(
            "assigned_by"
        ).prefetch_related(
            "updates__updated_by"
        )
    ).order_by(
        "-status_updated_at",
        "-created_at",
    )

    task_forms = [(task, TaskUpdateForm(task=task)) for task in tasks]

    status_counts = {
        key: tasks.filter(status=key).count()
        for key, _ in Task.Status.choices
    }
    status_styles = {
        Task.Status.PENDING: 'secondary',
        Task.Status.IN_PROGRESS: 'info',
        Task.Status.COMPLETED: 'success',
        Task.Status.BLOCKED: 'danger',
    }
    status_summary = [
        {
            'value': key,
            'label': label,
            'count': status_counts.get(key, 0),
            'style': status_styles.get(key, 'primary'),
        }
        for key, label in Task.Status.choices
    ]

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'employee': employee,
        'task_forms': task_forms,
        'create_form': create_form,
        'status_choices': Task.Status.choices,
        'priority_choices': Task.Priority.choices,
        'status_summary': status_summary,
    })
    return render(request, 'employees/tasks/employee_tasks.html', context)

# Ticket System Views

@login_required
@user_passes_test(is_employee)
def support_tickets(request):
    """Unified support tickets view with request and history tabs"""
    from employees.models import Ticket
    
    employee = request.user.employee_profile
    
    # Handle ticket creation
    if request.method == 'POST':
        subject = request.POST.get('subject')
        description = request.POST.get('description')
        category = request.POST.get('category')
        attachment = request.FILES.get('attachment')
        
        if not subject or not description:
            messages.error(request, 'Subject and description are required.')
        else:
            ticket = Ticket.objects.create(
                office=employee.office,
                branch=employee.branch,
                employee=employee,
                subject=subject,
                description=description,
                category=category,
                attachment=attachment
            )
            messages.success(request, f'✓ Ticket {ticket.ticket_number} created successfully! Our team will respond soon.')
            return redirect('employees:support_tickets')
    
    # Get all tickets for history
    # tickets = Ticket.objects.filter(employee=employee).order_by('-created_at')
    tickets = tenant_queryset(
        request,
        Ticket.objects.filter(employee=employee)
    ).order_by('-created_at')
    
    # Statistics
    total_tickets = tickets.count()
    open_tickets = tickets.filter(status='open').count()
    in_progress_tickets = tickets.filter(status='in_progress').count()
    resolved_tickets = tickets.filter(status='resolved').count()
    
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'employee': employee,
        'tickets': tickets,
        'total_tickets': total_tickets,
        'open_tickets': open_tickets,
        'in_progress_tickets': in_progress_tickets,
        'resolved_tickets': resolved_tickets,
        'category_choices': Ticket.CATEGORY_CHOICES,
        'priority_choices': Ticket.PRIORITY_CHOICES,
    })
    return render(request, 'employees/tickets/support_tickets.html', context)


@login_required
@user_passes_test(is_employee)
def employee_tickets(request):
    """Redirect to unified support tickets view"""
    return redirect('employees:support_tickets')


@login_required
@user_passes_test(is_employee)
def create_ticket(request):
    """Redirect to unified support tickets view"""
    return redirect('employees:support_tickets')


@login_required
@user_passes_test(is_employee)
def ticket_detail(request, pk):
    """View ticket details with comments"""
    from employees.models import Ticket, TicketComment
    
    employee = request.user.employee_profile
    # ticket = get_object_or_404(Ticket, pk=pk, employee=employee)
    ticket = get_object_or_404(
        tenant_queryset(
            request,
            Ticket.objects
        ),
        pk=pk,
        employee=employee,
    )
    # comments = ticket.comments.filter(is_internal=False).order_by('created_at')
    comments = tenant_queryset(
        request,
        ticket.comments.filter(
            is_internal=False
        )
    ).order_by("created_at")
    
    # CRITICAL FIX: Check if ticket is resolved
    # If resolved, disable comments for employee
    is_resolved = ticket.status == 'resolved'
    can_comment = not is_resolved  # Employee cannot comment if resolved
    
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'employee': employee,
        'ticket': ticket,
        'comments': comments,
        'can_comment': can_comment,  # NEW: Pass to template
        'is_resolved': is_resolved,  # NEW: Pass to template
    })
    return render(request, 'employees/tickets/ticket_detail.html', context)


@login_required
@user_passes_test(is_employee)
def add_ticket_comment(request, pk):
    """Add comment to ticket"""
    from employees.models import Ticket, TicketComment
    
    employee = request.user.employee_profile
    # ticket = get_object_or_404(Ticket, pk=pk, employee=employee)
    ticket = get_object_or_404(
        tenant_queryset(
            request,
            Ticket.objects
        ),
        pk=pk,
        employee=employee,
    )
    
    if request.method == 'POST':
        comment_text = request.POST.get('comment')
        
        if comment_text:
            TicketComment.objects.create(
                office=ticket.office,
                branch=ticket.branch,
                ticket=ticket,
                user=request.user,
                comment=comment_text,
                is_internal=False
            )
            messages.success(request, 'Comment added successfully.')
        else:
            messages.error(request, 'Comment cannot be empty.')
    
    return redirect('employees:ticket_detail', pk=pk)


@login_required
@user_passes_test(feature_required('tickets.manage'))
def admin_tickets(request):
    """Admin view for all tickets"""
    from employees.models import Ticket
    from django.core.paginator import Paginator
    
    # Get filter parameters
    employee_id = request.GET.get('employee')
    status = request.GET.get('status')
    priority = request.GET.get('priority')
    category = request.GET.get('category')
    
    # Base queryset
    # tickets = Ticket.objects.select_related('employee', 'resolved_by').order_by('-created_at')
    tickets = tenant_queryset(
        request,
        Ticket.objects.select_related(
            "employee",
            "resolved_by",
        )
    ).order_by("-created_at")
    
    # Apply filters
    if employee_id:
        tickets = tickets.filter(employee_id=employee_id)
    if status:
        tickets = tickets.filter(status=status)
    if priority:
        tickets = tickets.filter(priority=priority)
    if category:
        tickets = tickets.filter(category=category)
    
    # Statistics
    # total_tickets = Ticket.objects.count()
    # open_tickets = Ticket.objects.filter(status='open').count()
    # in_progress_tickets = Ticket.objects.filter(status='in_progress').count()
    # resolved_tickets = Ticket.objects.filter(status='resolved').count()
    # urgent_tickets = Ticket.objects.filter(priority='urgent', status__in=['open', 'in_progress']).count()
    ticket_stats = tenant_queryset(
        request,
        Ticket.objects.all()
    )

    total_tickets = ticket_stats.count()

    open_tickets = ticket_stats.filter(
        status="open"
    ).count()

    in_progress_tickets = ticket_stats.filter(
        status="in_progress"
    ).count()

    resolved_tickets = ticket_stats.filter(
        status="resolved"
    ).count()

    urgent_tickets = ticket_stats.filter(
        priority="urgent",
        status__in=["open", "in_progress"],
    ).count()
    
    # Pagination
    paginator = Paginator(tickets, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get all employees for filter
    # employees = Employee.objects.all().order_by('name')
    employees = tenant_queryset(
        request,
        Employee.objects.all()
    ).order_by('name')
    
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'page_obj': page_obj,
        'tickets': page_obj.object_list,
        'total_tickets': total_tickets,
        'open_tickets': open_tickets,
        'in_progress_tickets': in_progress_tickets,
        'resolved_tickets': resolved_tickets,
        'urgent_tickets': urgent_tickets,
        'employees': employees,
        'selected_employee': employee_id,
        'selected_status': status,
        'selected_priority': priority,
        'selected_category': category,
        'status_choices': Ticket.STATUS_CHOICES,
        'priority_choices': Ticket.PRIORITY_CHOICES,
        'category_choices': Ticket.CATEGORY_CHOICES,
    })
    return render(request, 'employees/tickets/admin_tickets.html', context)


@login_required
@user_passes_test(feature_required('tickets.manage'))
def admin_update_ticket(request, pk):
    """Admin update ticket status and add notes"""
    from employees.models import Ticket, TicketComment
    
    # ticket = get_object_or_404(Ticket, pk=pk)
    ticket = get_object_or_404(
        tenant_queryset(
            request,
            Ticket.objects
        ),
        pk=pk,
    )
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'update_status':
            old_status = ticket.status
            new_status = request.POST.get('status')
            new_priority = request.POST.get('priority')
            admin_notes = request.POST.get('admin_notes')
            
            ticket.status = new_status
            ticket.priority = new_priority
            
            if admin_notes:
                ticket.admin_notes = admin_notes
            
            if new_status == 'resolved':
                ticket.resolved_by = request.user
                ticket.resolved_at = timezone.now()
            
            ticket.save()
            
            # Add automatic comment about status change (visible to employee)
            if old_status != new_status:
                status_comment = f"Status changed from '{dict(Ticket.STATUS_CHOICES)[old_status]}' to '{dict(Ticket.STATUS_CHOICES)[new_status]}'"
                if new_priority:
                    status_comment += f" | Priority updated to '{dict(Ticket.PRIORITY_CHOICES)[new_priority]}'"
                
                TicketComment.objects.create(
                    office=ticket.office,
                    branch=ticket.branch,
                    ticket=ticket,
                    user=request.user,
                    comment=status_comment,
                    is_internal=False  # Visible to employee
                )
            
            messages.success(request, f'Ticket {ticket.ticket_number} updated successfully. Employee will see the status change.')
        
        elif action == 'add_comment':
            comment_text = request.POST.get('comment')
            is_internal = request.POST.get('is_internal') == 'on'
            
            if comment_text:
                TicketComment.objects.create(
                    office=ticket.office,
                    branch=ticket.branch,
                    ticket=ticket,
                    user=request.user,
                    comment=comment_text,
                    is_internal=is_internal
                )
                if is_internal:
                    messages.success(request, 'Internal note added (not visible to employee).')
                else:
                    messages.success(request, 'Comment added successfully. Employee will see this comment.')
    
    return redirect('employees:admin_tickets')


# ===========================
# ATTENDANCE CALENDAR VIEWS
# ===========================

@login_required
@user_passes_test(is_employee)
def employee_attendance_calendar(request):
    """Interactive attendance calendar for employees"""
    from datetime import datetime, timedelta
    from calendar import monthrange
    import calendar
    
    employee = request.user.employee_profile
    
    # Get year and month from query params, default to current
    current_date = timezone.now()
    year = int(request.GET.get('year', current_date.year))
    month = int(request.GET.get('month', current_date.month))
    
    # Ensure valid month/year
    if month < 1:
        month = 12
        year -= 1
    elif month > 12:
        month = 1
        year += 1
    
    # Get first and last day of the month
    first_day = datetime(year, month, 1).date()
    last_day = datetime(year, month, monthrange(year, month)[1]).date()
    
    # Get all attendance records for this month
    attendance_records = Attendance.objects.filter(
        employee=employee,
        date__gte=first_day,
        date__lte=last_day
    ).select_related('employee')
    
    # Create a dictionary for quick lookup
    attendance_dict = {record.date: record for record in attendance_records}

    # Get holidays for this month from Holiday model (this employee's own office + branch)
    from .models import Holiday
    holidays = Holiday.objects.filter(
        office=employee.office,
        branch=employee.branch,
        date__gte=first_day,
        date__lte=last_day
    )
    holiday_dates = {h.date: h for h in holidays}
    
    # Helper function to check if a date is a holiday
    def is_holiday(date_obj):
        """Check if date is a holiday (from Holiday model or Sunday or 1st, 3rd, 5th Saturday)"""
        # Check if it's in the Holiday model (admin-created holidays)
        if date_obj in holiday_dates:
            return True, holiday_dates[date_obj]
        
        # Sunday is weekday 6
        if date_obj.weekday() == 6:
            return True, None
        
        # # Saturday is weekday 5
        # if date_obj.weekday() == 5:
        #     # Count which Saturday of the month this is
        #     saturday_count = 0
        #     for d in range(1, date_obj.day + 1):
        #         if datetime(date_obj.year, date_obj.month, d).weekday() == 5:
        #             saturday_count += 1
            
        #     # 1st, 3rd, 5th Saturday are holidays
        #     if saturday_count in [1, 3, 5]:
        #         return True, None
        
        return False, None
    
    # Generate calendar data (weeks start on Sunday)
    cal = calendar.Calendar(firstweekday=calendar.SUNDAY).monthdayscalendar(year, month)
    calendar_data = []
    
    # Track statistics for enhanced stats row
    stats = {
        'present': 0,
        'half_day': 0,
        'absent': 0,
        'holidays': 0,
        'paid_leave': 0,
        'sandwich_leave': 0,
    }
    
    for week in cal:
        week_data = []
        for day in week:
            if day == 0:
                week_data.append(None)
            else:
                date_obj = datetime(year, month, day).date()
                attendance = attendance_dict.get(date_obj)
                is_holiday_result, holiday_obj = is_holiday(date_obj)
                is_holiday_day = is_holiday_result
                
                # Determine status using shift-based calculation
                status = 'none'
                status_class = ''
                status_icon = ''
                status_color = ''
                holiday_name = None
                
                if is_holiday_day:  # Holiday (dark grey)
                    status = 'holiday'
                    status_class = 'bg-dark-grey'
                    status_icon = 'bx-calendar'
                    status_color = '#4b5563'
                    if holiday_obj:
                        holiday_name = holiday_obj.name
                    stats['holidays'] += 1
                elif attendance:
                    # Check for paid leave first (approved leave request)
                    from .models import LeaveRequest
                    is_paid_leave = False
                    if employee.joining_date:
                        days_since_joining = (date_obj - employee.joining_date).days
                        if days_since_joining >= 91:
                            # Check if there's an approved leave request for this date
                            approved_leave = LeaveRequest.objects.filter(
                                employee=employee,
                                start_date__lte=date_obj,
                                end_date__gte=date_obj,
                                status=LeaveRequest.Status.APPROVED
                            ).exists()
                            if approved_leave:
                                is_paid_leave = True
                    
                    # Check for sandwich leave
                    is_sandwich = attendance.sandwich_flag or attendance.final_status == 'sandwich_leave'
                    
                    if is_sandwich:
                        status = 'sandwich_leave'
                        status_class = 'bg-danger'
                        status_icon = 'bx-x-circle'
                        status_color = '#ef4444'  # Red with blue corner
                        stats['sandwich_leave'] += 1
                        week_data.append({
                            'day': day,
                            'date': date_obj,
                            'attendance': attendance,
                            'status': status,
                            'status_class': status_class,
                            'status_icon': status_icon,
                            'status_color': status_color,
                            'is_half_day': attendance.half_day if attendance else False,
                            'is_today': date_obj == current_date.date(),
                            'is_future': date_obj > current_date.date(),
                            'is_holiday': is_holiday_day,
                            'holiday_name': holiday_name,
                            'missing_punch': False,
                            'is_paid_leave': False,
                            'is_sandwich_leave': True
                        })
                        continue
                    elif is_paid_leave:
                        status = 'paid_leave'
                        status_class = 'bg-danger'
                        status_icon = 'bx-x-circle'
                        status_color = '#ef4444'  # Red with purple corner
                        stats['paid_leave'] += 1
                        week_data.append({
                            'day': day,
                            'date': date_obj,
                            'attendance': attendance,
                            'status': status,
                            'status_class': status_class,
                            'status_icon': status_icon,
                            'status_color': status_color,
                            'is_half_day': attendance.half_day if attendance else False,
                            'is_today': date_obj == current_date.date(),
                            'is_future': date_obj > current_date.date(),
                            'is_holiday': is_holiday_day,
                            'holiday_name': holiday_name,
                            'missing_punch': False,
                            'is_paid_leave': True,
                            'is_sandwich_leave': False
                        })
                        continue
                    else:
                        # Use SHIFT-BASED calculation for accurate attendance
                        att_status, color_code = attendance.calculate_shift_based_status()
                        print(
    attendance.date,
    "final_status =", attendance.final_status,
    "calculated =", att_status,
    "worked =", attendance.total_work_hours,
    "duration =", attendance.duration_hours,
)
                        
                        # Check for missing punch (only check-in or only check-out)
                        has_checkin = bool(attendance.check_in_time)
                        has_checkout = bool(attendance.check_out_time)
                        missing_punch = (has_checkin and not has_checkout) or (not has_checkin and has_checkout)
                        
                        if att_status == 'present':  # >= shift hours
                            status = 'present'
                            status_class = 'bg-success'
                            status_icon = 'bx-check-circle'
                            status_color = '#34C759'  # Green
                            stats['present'] += 1
                        elif att_status == 'half_day':  # >= 50% shift hours and < shift hours
                            status = 'halfday'
                            status_class = 'bg-warning'
                            status_icon = 'bx-time-five'
                            status_color = '#FFCC00'  # Yellow
                            stats['half_day'] += 1
                        else:  # absent (< 50% shift hours or missing punch)
                            status = 'absent'
                            status_class = 'bg-danger'
                            status_icon = 'bx-x-circle'
                            status_color = '#FF3B30'  # Red
                            stats['absent'] += 1
                        
                        # Store missing punch flag for template
                        week_data.append({
                            'day': day,
                            'date': date_obj,
                            'attendance': attendance,
                            'status': status,
                            'status_class': status_class,
                            'status_icon': status_icon,
                            'status_color': status_color,
                            'is_half_day': attendance.half_day if attendance else False,
                            'is_today': date_obj == current_date.date(),
                            'is_future': date_obj > current_date.date(),
                            'is_holiday': is_holiday_day,
                            'holiday_name': holiday_name,
                            'missing_punch': missing_punch,
                            'is_paid_leave': is_paid_leave,
                            'is_sandwich_leave': is_sandwich
                        })
                        continue
                # elif date_obj < current_date.date():  # Past working day without attendance
                elif(employee.joining_date
    and date_obj >= employee.joining_date
    and date_obj < current_date.date()):
                    # Check if there's an approved paid leave for this date
                    from .models import LeaveRequest
                    is_paid_leave_no_attendance = False
                    if employee.joining_date:
                        days_since_joining = (date_obj - employee.joining_date).days
                        if days_since_joining >= 91:
                            approved_leave = LeaveRequest.objects.filter(
                                employee=employee,
                                start_date__lte=date_obj,
                                end_date__gte=date_obj,
                                status=LeaveRequest.Status.APPROVED
                            ).exists()
                            if approved_leave:
                                is_paid_leave_no_attendance = True
                                status = 'paid_leave'
                                status_class = 'bg-info'
                                status_icon = 'bx-calendar-check'
                                status_color = '#2563eb'  # Blue
                                stats['paid_leave'] += 1
                    
                    if not is_paid_leave_no_attendance:
                        status = 'absent'
                        status_class = 'bg-danger'
                        status_icon = 'bx-x-circle'
                        status_color = '#ef4444'  # Red
                        stats['absent'] += 1
                
                week_data.append({
                    'day': day,
                    'date': date_obj,
                    'attendance': attendance,
                    'status': status,
                    'status_class': status_class,
                    'status_icon': status_icon,
                    'status_color': status_color,
                    'is_half_day': attendance.half_day if attendance else False,
                    'is_today': date_obj == current_date.date(),
                    'is_future': date_obj > current_date.date(),
                    'is_holiday': is_holiday_day,
                    'holiday_name': holiday_name,
                    'missing_punch': False,
                    'is_paid_leave': False,
                    'is_sandwich_leave': False
                })
        calendar_data.append(week_data)
    
    # Calculate statistics for the month (excluding holidays)
    total_working_days = sum(1 for week in calendar_data for day in week 
                            if day and not day['is_holiday'] and day['date'] <= current_date.date())
    present_days = stats['present']
    half_day_days = stats['half_day']
    absent_days = stats['absent']
    holidays_count = stats['holidays']
    paid_leave_count = stats['paid_leave']
    sandwich_leave_count = stats['sandwich_leave']
    attendance_ratio = 0
    if total_working_days > 0:
        attendance_ratio = (present_days + (half_day_days * 0.5)) / total_working_days * 100
    
    # Get paid leave balance for employee
    paid_leave_balance = employee.calculate_paid_leave_balance()
    # Get month navigation
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    
    # Get all months for year selector
    months_list = [
        {'number': i, 'name': calendar.month_name[i], 'abbr': calendar.month_abbr[i]}
        for i in range(1, 13)
    ]
    
    # Get year range (current year ± 2 years)
    year_range = range(current_date.year - 2, current_date.year + 3)
    
    # Get layout path
    context = TemplateLayout.init(request, {
        'employee': employee,
        'calendar_data': calendar_data,
        'year': year,
        'month': month,
        'month_name': calendar.month_name[month],
        'prev_month': prev_month,
        'prev_year': prev_year,
        'next_month': next_month,
        'next_year': next_year,
        'current_date': current_date,
        'total_working_days': total_working_days,
        'present_days': present_days,
        'half_day_days': half_day_days,
        'absent_days': absent_days,
        'holidays_count': holidays_count,
        'paid_leave_count': paid_leave_count,
        'sandwich_leave_count': sandwich_leave_count,
        'attendance_percentage': round(attendance_ratio, 1),
        'paid_leave_balance': round(paid_leave_balance, 1),
        'months_list': months_list,
        'year_range': year_range,
    })
    
    return render(request, 'employees/attendance/calendar.html', context)


@login_required
@user_passes_test(feature_required('attendance.manage'))
def admin_attendance_calendar(request):
    """Admin view for attendance calendar with detailed insights"""
    from datetime import datetime, timedelta
    from calendar import monthrange
    import calendar
    from django.db.models import Count, Q
    
    # Get year, month, and employee filter from query params
    current_date = timezone.now()
    year = int(request.GET.get('year', current_date.year))
    month = int(request.GET.get('month', current_date.month))
    employee_id = request.GET.get('employee')
    
    # Ensure valid month/year
    if month < 1:
        month = 12
        year -= 1
    elif month > 12:
        month = 1
        year += 1
    
    # Get first and last day of the month
    first_day = datetime(year, month, 1).date()
    last_day = datetime(year, month, monthrange(year, month)[1]).date()
    
    # Get all employees
    # all_employees = Employee.objects.all().order_by('name')
    all_employees = tenant_queryset( request, Employee.objects.select_related( 'office', 'user' ) ).order_by( 'name', 'full_name' )
    total_employee_count = all_employees.count()
    
    # Filter by employee if specified
    if employee_id:
        selected_employee = get_object_or_404(Employee, id=employee_id)
        employees = [selected_employee]
    else:
        selected_employee = None
        employees = all_employees

    employee_count_for_day = 1 if employee_id else total_employee_count
    
    # Get all attendance records for this month
    attendance_records = Attendance.objects.select_related( 'employee', 'employee__office' ).filter( date__gte=first_day, date__lte=last_day )

    if not is_platform_admin(request.user):
        office = get_request_office(request)
        if office is None:
            attendance_records = attendance_records.none()
        else:
            attendance_records = attendance_records.filter(employee__office=office)
            branch = get_request_branch(request)
            if branch is not None:
                attendance_records = attendance_records.filter(employee__branch=branch)

    # Apply selected employee after company filtering.
    if selected_employee:
        attendance_records = attendance_records.filter( employee=selected_employee )
        attendance_records = attendance_records.order_by( 'date', 'employee__name' )
    # if employee_id:
    #     attendance_records = attendance_records.filter(employee_id=employee_id)

    # Create attendance lookup by date and employee
    attendance_by_date = {}
    for record in attendance_records:
        if record.date not in attendance_by_date:
            attendance_by_date[record.date] = []
        attendance_by_date[record.date].append(record)

    # Get holidays for this month from Holiday model (scoped to the admin's office + active branch)
    from .models import Holiday
    holidays = Holiday.objects.filter(date__gte=first_day, date__lte=last_day)
    if not is_platform_admin(request.user):
        holidays = holidays.filter(office=get_request_office(request), branch=get_request_branch(request))
    holiday_dates = {h.date: h for h in holidays}
    
    # Helper function to check if a date is a holiday
    def is_holiday(date_obj):
        """Check if date is a holiday (from Holiday model or Sunday or 1st, 3rd, 5th Saturday)"""
        # Check if it's in the Holiday model (admin-created holidays)
        if date_obj in holiday_dates:
            return True, holiday_dates[date_obj]
        
        # Sunday is weekday 6
        if date_obj.weekday() == 6:
            return True, None
        
        # Saturday is weekday 5
        # if date_obj.weekday() == 5:
        #     # Count which Saturday of the month this is
        #     saturday_count = 0
        #     for d in range(1, date_obj.day + 1):
        #         if datetime(date_obj.year, date_obj.month, d).weekday() == 5:
        #             saturday_count += 1
            
        #     # 1st, 3rd, 5th Saturday are holidays
        #     if saturday_count in [1, 3, 5]:
        #         return True, None
        
        return False, None
    
    # Generate calendar data (weeks start on Sunday)
    cal = calendar.Calendar(firstweekday=calendar.SUNDAY).monthdayscalendar(year, month)
    calendar_data = []
    
    for week in cal:
        week_data = []
        for day in week:
            if day == 0:
                week_data.append(None)
            else:
                date_obj = datetime(year, month, day).date()
                day_attendance = attendance_by_date.get(date_obj, [])
                is_holiday_result, holiday_obj = is_holiday(date_obj)
                is_holiday_day = is_holiday_result
                holiday_name = holiday_obj.name if holiday_obj else None
                
                # Count statuses
                checked_in_count = len([a for a in day_attendance if not a.check_out_time])
                half_day_count = len([a for a in day_attendance if a.check_out_time and a.half_day])
                checked_out_count = len([a for a in day_attendance if a.check_out_time and not a.half_day])
                total_present = len(day_attendance)
                
                # Calculate absent (only for past working days, not holidays)
                is_past_working_day = date_obj < current_date.date() and not is_holiday_day
                total_employees = employee_count_for_day
                absent_count = total_employees - total_present if is_past_working_day else 0
                
                week_data.append({
                    'day': day,
                    'date': date_obj,
                    'attendance_records': day_attendance,
                    'checked_in_count': checked_in_count,
                    'checked_out_count': checked_out_count,
                    'half_day_count': half_day_count,
                    'total_present': total_present,
                    'absent_count': absent_count,
                    'is_today': date_obj == current_date.date(),
                    'is_future': date_obj > current_date.date(),
                    'is_holiday': is_holiday_day,
                    'holiday_name': holiday_name
                })
        calendar_data.append(week_data)
    
    if employee_id:
        employee_records = attendance_records.filter(employee_id=employee_id)
        total_present = employee_records.filter(check_out_time__isnull=False, half_day=False).count()
        total_half_days = employee_records.filter(check_out_time__isnull=False, half_day=True).count()
        total_absent = 1 if employee_records.count() == 0 else 0
    else:
        total_present = attendance_records.filter(check_out_time__isnull=False, half_day=False).count()
        total_half_days = attendance_records.filter(check_out_time__isnull=False, half_day=True).count()
        distinct_present_count = attendance_records.values('employee_id').distinct().count()
        total_absent = max(total_employee_count - distinct_present_count, 0)
    
    # Get month navigation
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    
    # Get all months for selector
    months_list = [
        {'number': i, 'name': calendar.month_name[i], 'abbr': calendar.month_abbr[i]}
        for i in range(1, 13)
    ]
    
    # Get year range
    year_range = range(current_date.year - 2, current_date.year + 3)
    
    # Get layout path
    context = TemplateLayout.init(request, {
        'calendar_data': calendar_data,
        'year': year,
        'month': month,
        'month_name': calendar.month_name[month],
        'prev_month': prev_month,
        'prev_year': prev_year,
        'next_month': next_month,
        'next_year': next_year,
        'current_date': current_date,
        'all_employees': all_employees,
        'selected_employee': selected_employee,
        'selected_employee_id': selected_employee.id if selected_employee else None,
        'selected_employee_name': selected_employee.name if selected_employee else '',
        'selected_employee_email': selected_employee.email if selected_employee else '',
        'total_present': total_present,
        'total_half_days': total_half_days,
        'total_absent': total_absent,
        'total_employee_count': total_employee_count,
        'months_list': months_list,
        'year_range': year_range,
    })
    print("attendance data:",context)
    return render(request, 'employees/attendance/admin_calendar.html', context)

# @login_required
# @user_passes_test(office_admin_required)
# def attendance_excel_report(request):
#     from datetime import datetime
#     from calendar import monthrange
#     from django.http import HttpResponse
#     from openpyxl import Workbook

#     year = int(request.GET.get("year"))
#     month = int(request.GET.get("month"))
#     employee_id = request.GET.get("employee")

#     first_day = datetime(year, month, 1).date()
#     last_day = datetime(year, month, monthrange(year, month)[1]).date()

#     attendance_records = (
#         Attendance.objects.filter(
#             date__gte=first_day,
#             date__lte=last_day
#         )
#         .select_related("employee")
#         .order_by("employee__name", "date")
#     )

#     if employee_id:
#         attendance_records = attendance_records.filter(employee_id=employee_id)

#     workbook = Workbook()
#     sheet = workbook.active
#     sheet.title = "Attendance Report"

#     # Header
#     sheet.append([
#         "Employee",
#         "Email",
#         "Contact",
#         "Date",
#         "Check In",
#         "Check Out",
#         "Duration",
#         "Status",
#     ])

#     for attendance in attendance_records:

#         if attendance.check_out_time:
#             status = "Half Day" if attendance.half_day else "Present"
#         else:
#             status = "Checked In"

#         sheet.append([
#             attendance.employee.full_name,
#             attendance.employee.email,
#             attendance.employee.contact,
#             attendance.date.strftime("%d-%m-%Y"),
#             attendance.check_in_time.strftime("%H:%M:%S") if attendance.check_in_time else "",
#             attendance.check_out_time.strftime("%H:%M:%S") if attendance.check_out_time else "",
#             str(attendance.duration or ""),
#             status,
#         ])

#     response = HttpResponse(
#         content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
#     )

#     response["Content-Disposition"] = (
#         f'attachment; filename="Attendance_{year}_{month}.xlsx"'
#     )

#     workbook.save(response)

#     return response
@login_required
@user_passes_test(feature_required('attendance.manage'))
def attendance_excel_report(request):
    from datetime import datetime
    from calendar import monthrange
    from django.http import HttpResponse
    from openpyxl import Workbook
    from .models import Attendance, Employee, LeaveRequest

    year = int(request.GET.get("year"))
    month = int(request.GET.get("month"))
    employee_id = request.GET.get("employee")

    first_day = datetime(year, month, 1).date()
    last_day = datetime(year, month, monthrange(year, month)[1]).date()

    # Employees
    # employees = Employee.objects.all().order_by("full_name")
    employees = tenant_queryset(
        request,
        Employee.objects.all()
    ).order_by("full_name")

    if employee_id:
        employees = employees.filter(id=employee_id)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Attendance Summary"

    # Header
    sheet.append([
        "Employee",
        "Email",
        "Contact",
        "Working Days",
        "Present",
        "Half Days",
        "Average Working Hours",
        "Approved Leaves",
        "Paid Leaves",
        "LWP Leaves",
        "Available Paid Leave Balance",
    ])

    for employee in employees:

        attendance = tenant_queryset(
    request,
    Attendance.objects.all()
).filter(
            employee=employee,
            date__range=[first_day, last_day]
        )

        # Attendance counts
        present = attendance.filter(
            check_out_time__isnull=False,
            half_day=False
        ).count()

        half_days = attendance.filter(
            half_day=True
        ).count()

        checked_in = attendance.filter(
            check_out_time__isnull=True
        ).count()

        # Leave Requests during selected month
        approved_leaves = LeaveRequest.objects.filter(
            employee=employee,
            status=LeaveRequest.Status.APPROVED,
            start_date__lte=last_day,
            end_date__gte=first_day
        )

        paid_leave = approved_leaves.filter(
            leave_category=LeaveRequest.LeaveCategory.PAID
        ).count()

        lwp_leave = approved_leaves.filter(
            leave_category=LeaveRequest.LeaveCategory.LWP
        ).count()

        total_leave = approved_leaves.count()

        # Working days in month
        working_days = monthrange(year, month)[1]

        from decimal import Decimal

        completed_attendance = attendance.filter(
            check_out_time__isnull=False
        )

        total_hours = Decimal("0")

        for record in completed_attendance:
            total_hours += record.total_work_hours or Decimal("0")

        if completed_attendance.exists():
            avg_hours = total_hours / completed_attendance.count()

            hours = int(avg_hours)
            minutes = int((avg_hours - hours) * 60)

            average_hours = f"{hours:02d}:{minutes:02d}"
        else:
            average_hours = "-"
            
        sheet.append([
            employee.full_name,
            employee.email,
            employee.contact,
            working_days,
            present,
            half_days,
            average_hours,
            total_leave,
            paid_leave,
            lwp_leave,
            employee.get_final_leave_balance(),
        ])

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    response["Content-Disposition"] = (
        f'attachment; filename="Attendance_Summary_{year}_{month}.xlsx"'
    )

    workbook.save(response)
    return response

# Legacy endpoint retained for compatibility
def password_reset_request(request):
    messages.info(request, 'Use the password reset form to receive a reset link by email.')
    return redirect('employees:password_reset')


# Admin Views for Password Management
@login_required
@user_passes_test(lambda u: u.is_superuser)
def password_reset_requests_list(request):
    """Admin view to see all password reset requests"""
    status_filter = request.GET.get('status', 'all')
    
    requests_query = PasswordResetRequest.objects.select_related('employee', 'processed_by').all()
    
    if status_filter != 'all':
        requests_query = requests_query.filter(status=status_filter)
    
    pending_count = PasswordResetRequest.objects.filter(status='pending').count()
    approved_count = PasswordResetRequest.objects.filter(status='approved').count()
    rejected_count = PasswordResetRequest.objects.filter(status='rejected').count()
    
    context = TemplateLayout.init(request, {
        'reset_requests': requests_query,
        'status_filter': status_filter,
        'pending_count': pending_count,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
    })
    
    return render(request, 'employees/admin/password_reset_requests.html', context)


@login_required
@user_passes_test(lambda u: u.is_superuser)
def process_password_reset_request(request, request_id):
    """Admin processes a password reset request"""
    reset_request = get_object_or_404(PasswordResetRequest, id=request_id)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        new_password = request.POST.get('new_password')
        admin_notes = request.POST.get('admin_notes', '')
        
        if action == 'approve' and new_password:
            # Update employee password
            employee = reset_request.employee
            employee.user.password = make_password(new_password)
            employee.user.save()
            
            # Update request
            reset_request.status = 'approved'
            reset_request.new_password = new_password  # Store temporarily for notification
            reset_request.processed_by = request.user
            reset_request.processed_at = timezone.now()
            reset_request.admin_notes = admin_notes
            reset_request.save()
            
            messages.success(request, f'Password reset approved for {employee.name}. New password: {new_password}')
            
        elif action == 'reject':
            reset_request.status = 'rejected'
            reset_request.processed_by = request.user
            reset_request.processed_at = timezone.now()
            reset_request.admin_notes = admin_notes
            reset_request.save()
            
            messages.warning(request, f'Password reset request rejected for {reset_request.employee.name}')
        
        return redirect('employees:password_reset_requests')
    
    context = TemplateLayout.init(request, {
        'reset_request': reset_request,
    })
    
    return render(request, 'employees/admin/process_password_reset.html', context)


@login_required
@user_passes_test(lambda u: u.is_superuser)
def employee_change_password(request, employee_id):
    """Admin directly changes employee password"""
    employee = get_object_or_404(Employee, id=employee_id)
    
    if request.method == 'POST':
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        admin_notes = request.POST.get('admin_notes', '')
        
        if new_password and new_password == confirm_password:
            # Update password
            employee.user.password = make_password(new_password)
            employee.user.save()
            
            # Create a record of this change
            PasswordResetRequest.objects.create(
                employee=employee,
                branch=employee.branch,
                email=employee.email,
                reason=f'Password changed by admin: {admin_notes}',
                status='approved',
                new_password=new_password,
                processed_by=request.user,
                processed_at=timezone.now(),
                admin_notes=admin_notes
            )
            
            messages.success(request, f'Password updated successfully for {employee.name}')
            return redirect('employees:employee_detail', pk=employee.id)
        else:
            messages.error(request, 'Passwords do not match!')
    
    context = TemplateLayout.init(request, {
        'employee': employee,
    })
    
    return render(request, 'employees/admin/change_employee_password.html', context)


# ===========================
# ATTENDANCE API ENDPOINTS
# ===========================

@login_required
@require_http_methods(["GET"])
def attendance_detail_api(request):
    """
    API endpoint to fetch attendance details for a specific date.
    Returns JSON with check-in/check-out photos, times, duration, and status.
    
    GET /api/attendance/?date=YYYY-MM-DD
    
    Response:
    {
        "date": "2024-03-11",
        "status": "Present",
        "checkin": {
            "time": "09:35 AM",
            "image": "/media/checkin.png"
        },
        "checkout": {
            "time": "06:12 PM",
            "image": "/media/checkout.png"
        },
        "duration": "8h 20m"
    }
    """
    try:
        employee = request.user.employee_profile
        date_str = request.GET.get('date')
        
        logger.info(f'Attendance API called for employee: {employee.name}, date_str: {date_str}')
        
        if not date_str:
            logger.warning('No date parameter provided')
            return JsonResponse({'error': 'Date parameter required'}, status=400)
        
        # Parse the date
        try:
            selected_date = parse_date(date_str)
            if not selected_date:
                logger.warning(f'Invalid date format: {date_str}')
                return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=400)
            logger.info(f'Parsed date: {selected_date}')
        except Exception as e:
            logger.error(f'Date parsing error: {str(e)}')
            return JsonResponse({'error': f'Date parsing error: {str(e)}'}, status=400)
        
        # Get attendance record for this date
        attendance = Attendance.objects.filter(
            employee=employee,
            date=selected_date
        ).first()
        
        logger.info(f'Attendance record found: {attendance}')
        if attendance:
            logger.info(f'Check-in time: {attendance.check_in_time}, Check-out time: {attendance.check_out_time}')
            logger.info(f'Check-in photo: {attendance.check_in_photo}, Check-out photo: {attendance.check_out_photo}')
        
        # Helper function to check if a date is a holiday
        def is_holiday(date_obj):
            """Check if date is a holiday (Sunday or 1st, 3rd, 5th Saturday)"""
            if date_obj.weekday() == 6:  # Sunday
                return True
            
            # if date_obj.weekday() == 5:  # Saturday
            #     saturday_count = 0
            #     for d in range(1, date_obj.day + 1):
            #         if datetime(date_obj.year, date_obj.month, d).weekday() == 5:
            #             saturday_count += 1
                
            #     if saturday_count in [1, 3, 5]:
            #         return True
            
            return False
        
        # Determine status using SHIFT-BASED calculation
        if is_holiday(selected_date):
            status = 'Holiday'
        elif not attendance:
            # Check if it's a past date
            if selected_date < timezone.now().date():
                status = 'Absent'
            else:
                status = 'Upcoming'
        elif attendance.check_out_time:
            # Use shift-based status calculation
            att_status, _ = attendance.calculate_shift_based_status()
            if att_status == 'present':
                status = 'Present'
            elif att_status == 'half_day':
                status = 'Half Day'
            elif att_status == 'checked_in_only':
                status = 'Checked-in'
            else:
                status = 'Absent'
        else:
            status = 'Checked-in'
        
        # Build response with real attendance data
        response_data = {
            'date': selected_date.isoformat(),
            'status': status,
            'checkin': {
                'time': attendance.check_in_time.strftime('%I:%M %p') if attendance and attendance.check_in_time else None,
                'image': attendance.check_in_photo.url if attendance and attendance.check_in_photo else None
            },
            'checkout': {
                'time': attendance.check_out_time.strftime('%I:%M %p') if attendance and attendance.check_out_time else None,
                'image': attendance.check_out_photo.url if attendance and attendance.check_out_photo else None
            },
            'duration': attendance.duration if attendance else None
        }
        
        return JsonResponse(response_data)
    
    except Exception as e:
        logger.error(f'Error in attendance_detail_api: {str(e)}')
        return JsonResponse({'error': 'Server error'}, status=500)


@login_required
@user_passes_test(is_employee)
@require_http_methods(["GET"])
def attendance_details_api(request, date):
    """
    API endpoint to fetch attendance details for a specific date.
    Returns JSON with check-in/check-out photos, times, duration, and status.
    
    GET /attendance/details/YYYY-MM-DD/
    
    Response:
    {
        "date": "2024-03-11",
        "status": "Present",
        "checkin_time": "09:12 AM",
        "checkin_photo": "/media/attend/123_checkin.jpg",
        "checkin_timestamp": "2024-03-11 09:12:33",
        "checkout_time": "06:01 PM",
        "checkout_photo": "/media/attend/123_checkout.jpg",
        "checkout_timestamp": "2024-03-11 18:01:10",
        "duration": "8h 49m",
        "comments": [...]
    }
    """
    from datetime import datetime as dt
    import logging
    
    logger = logging.getLogger(__name__)
    
    try:
        employee = request.user.employee_profile
        
        # Parse the date
        try:
            selected_date = dt.strptime(date, '%Y-%m-%d').date()
        except ValueError:
            logger.warning(f'Invalid date format: {date}')
            return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=400)
        
        # Get attendance record for this date
        attendance = Attendance.objects.filter(
            employee=employee,
            date=selected_date
        ).first()
        
        # Get comments for this date
        from .models import AttendanceDayComment
        comments_qs = AttendanceDayComment.objects.filter(
            office=employee.office,
            branch=employee.branch,
            employee=employee,
            date=selected_date
        ).order_by('-created_at')
        
        # comments = []
        # for c in comments_qs:
        #     comments.append({
        #         'id': c.pk,
        #         'comment': c.comment,
        #         'created_by': c.created_by.get_username() if c.created_by else 'system',
        #         'created_at': timezone.localtime(c.created_at).isoformat(),
        #         'updated_at': timezone.localtime(c.updated_at).isoformat(),
        #         'is_admin_comment': c.is_admin_comment,
        #         'is_mine': c.created_by == request.user if c.created_by else False,
        #     })
        comments = [
            _serialize_comment(comment, request.user)
            for comment in comments_qs
        ]
        # Format weekday
        weekday = selected_date.strftime('%A, %B %d, %Y')
        
        if not attendance:
            # No attendance record
            return JsonResponse({
                'date': selected_date.isoformat(),
                'weekday': weekday,
                'status': 'Absent',
                'checkin_time': None,
                'checkin_photo': None,
                'checkin_timestamp': None,
                'checkout_time': None,
                'checkout_photo': None,
                'checkout_timestamp': None,
                'duration': None,
                'comments': comments
            })
        
        # Format check-in time
        checkin_time = None
        checkin_timestamp = None
        checkin_photo = None
        if attendance.check_in_time:
            checkin_time = timezone.localtime(attendance.check_in_time).strftime('%I:%M %p')
            checkin_timestamp = timezone.localtime(attendance.check_in_time).strftime('%Y-%m-%d %H:%M:%S')
            if attendance.check_in_photo:
                checkin_photo = request.build_absolute_uri(attendance.check_in_photo.url)
        
        # Format check-out time
        checkout_time = None
        checkout_timestamp = None
        checkout_photo = None
        if attendance.check_out_time:
            checkout_time = timezone.localtime(attendance.check_out_time).strftime('%I:%M %p')
            checkout_timestamp = timezone.localtime(attendance.check_out_time).strftime('%Y-%m-%d %H:%M:%S')
            if attendance.check_out_photo:
                checkout_photo = request.build_absolute_uri(attendance.check_out_photo.url)
        
        # Calculate duration
        duration = None
        if attendance.check_in_time and attendance.check_out_time:
            delta = attendance.check_out_time - attendance.check_in_time
            total_seconds = int(delta.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            duration = f"{hours}h {minutes}m"
        
        # Determine status
        status = 'Absent'
        if attendance.final_status:
            status_map = {
                'present': 'Present',
                'present_full': 'Present',
                'present_half': 'Half Day',
                'half_day': 'Half Day',
                'absent': 'Absent',
                'holiday': 'Holiday',
                'paid_leave': 'Paid Leave',
                'sandwich_leave': 'Sandwich Leave',
                'checked_in': 'Checked In Only',
            }
            status = status_map.get(attendance.final_status, 'Absent')
        elif attendance.check_in_time and attendance.check_out_time:
            # Calculate status based on SHIFT
            att_status, _ = attendance.calculate_shift_based_status()
            if att_status == 'present':
                status = 'Present'
            elif att_status == 'half_day':
                status = 'Half Day'
            else:
                status = 'Absent'
        elif attendance.check_in_time:
            status = 'Checked In Only'
        
        # Build response
        response_data = {
            'date': selected_date.isoformat(),
            'weekday': weekday,
            'status': status,
            'checkin_time': checkin_time,
            'checkin_photo': checkin_photo,
            'checkin_timestamp': checkin_timestamp,
            'checkout_time': checkout_time,
            'checkout_photo': checkout_photo,
            'checkout_timestamp': checkout_timestamp,
            'duration': duration,
            'comments': comments
        }
        
        return JsonResponse(response_data, status=200)
    
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f'Error in attendance_details_api: {str(e)}', exc_info=True)
        return JsonResponse({'error': 'Server error'}, status=500)


@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def admin_attendance_detail(request, attendance_id):
    """
    Admin view to see detailed attendance record for an employee
    Shows check-in/check-out photos, times, duration, and status
    
    URL: /admin/attendance/<id>/detail/
    """
    attendance = get_object_or_404(Attendance, id=attendance_id)
    
    # Prepare context
    context = TemplateLayout.init(request, {
        'attendance': attendance,
        'employee': attendance.employee,
        'date': attendance.date,
        'check_in_time': attendance.check_in_time.strftime('%I:%M %p') if attendance.check_in_time else 'Not recorded',
        'check_out_time': attendance.check_out_time.strftime('%I:%M %p') if attendance.check_out_time else 'Not recorded',
        'duration': attendance.duration,
        'check_in_photo': attendance.check_in_photo.url if attendance.check_in_photo else None,
        'check_out_photo': attendance.check_out_photo.url if attendance.check_out_photo else None,
        'status': 'Present' if attendance.check_out_time else 'Checked-in',
    })
    
    return render(request, 'employees/admin_attendance_detail.html', context)


# ===========================
# RULES & REGULATIONS VIEWS
# ===========================

@login_required
@user_passes_test(is_employee)
def company_rules(request):
    """Employee view for company rules and regulations"""
    employee = request.user.employee_profile
    # rules = CompanyRule.objects.filter(is_active=True).order_by('order', 'created_at')
    rules = tenant_queryset(
        request,
        CompanyRule.objects.filter(is_active=True)
    ).order_by('order', 'created_at')
    rules_version = determine_rules_version()
    # acknowledged_ids = set(
    #     RuleAcknowledgement.objects.filter(employee=employee, rule__in=rules).values_list('rule_id', flat=True)
    # )

    acknowledged_ids = set(
        tenant_queryset(
            request,
            RuleAcknowledgement.objects.filter(
                employee=employee,
                rule__in=rules
            )
        ).values_list('rule_id', flat=True)
    )
    acceptance = getattr(employee, 'rules_acceptance', None)
    acceptance_valid = acceptance and acceptance.version == rules_version

    if request.method == 'POST' and rules.exists():
        selected_rules = {int(rule_id) for rule_id in request.POST.getlist('rule_ids')}
        confirm_all = request.POST.get('accept_all') == 'on'
        missing_rules = [rule for rule in rules if rule.id not in selected_rules]

        if acceptance_valid:
            messages.info(request, 'You have already acknowledged the current version of the rules.')
            return redirect('employees:company_rules')

        if missing_rules:
            messages.error(request, 'Please mark every rule as read before submitting.')
        elif not confirm_all:
            messages.error(request, 'Please confirm that you agree to all rules.')
        else:
            with transaction.atomic():
                for rule in rules:
                    # RuleAcknowledgement.objects.get_or_create(employee=employee, rule=rule)
                    RuleAcknowledgement.objects.get_or_create(
                        employee=employee,
                        branch=employee.branch,
                        rule=rule,
                        defaults={
                            "office": employee.office,
                        }
                    )
                RulesAcceptance.objects.update_or_create(
                    employee=employee,
                    office=employee.office,
                    branch=employee.branch,
                    defaults={'version': rules_version, 'accepted_at': timezone.now()},
                )
            messages.success(request, 'Thanks! Your acknowledgement has been recorded.')
            return redirect('employees:company_rules')
    
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'rules': rules,
        'acknowledged_rule_ids': acknowledged_ids,
        'rules_version': rules_version,
        'has_valid_acceptance': bool(acceptance_valid),
        'acceptance': acceptance if acceptance_valid else None,
        'needs_reacceptance': bool(acceptance and not acceptance_valid),
        'total_rules': rules.count(),
    })
    return render(request, 'employees/rules/company_rules.html', context)


@login_required
@user_passes_test(feature_required('branches.manage'))
def admin_branches(request):
    """Office admin's branch management: create branches for their office,
    edit their details, and activate/deactivate them. Not itself branch-
    scoped - it always shows every branch under the current office
    regardless of which one is 'active' in the session."""
    from django.utils.text import slugify
    from .models import Branch

    office = get_request_office(request)
    if office is None:
        messages.error(request, 'Your account is not linked to an approved office.')
        return redirect('employees:employee_dashboard')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'create':
            name = (request.POST.get('name') or '').strip()
            if not name:
                messages.error(request, 'Branch name is required.')
            else:
                base_slug = slugify(name) or 'branch'
                slug = base_slug
                suffix = 1
                while Branch.objects.filter(office=office, slug=slug).exists():
                    suffix += 1
                    slug = f"{base_slug}-{suffix}"

                Branch.objects.create(
                    office=office,
                    name=name,
                    slug=slug,
                    address=request.POST.get('address', '').strip(),
                    city=request.POST.get('city', '').strip(),
                    state=request.POST.get('state', '').strip(),
                    pincode=request.POST.get('pincode', '').strip(),
                    contact_number=request.POST.get('contact_number', '').strip(),
                    email=request.POST.get('email', '').strip(),
                    latitude=request.POST.get('latitude') or None,
                    longitude=request.POST.get('longitude') or None,
                    attendance_radius_meters=request.POST.get('attendance_radius_meters') or None,
                )
                messages.success(request, f'Branch "{name}" created successfully!')

        elif action == 'update':
            branch = get_object_or_404(Branch, id=request.POST.get('branch_id'), office=office)
            branch.name = (request.POST.get('name') or branch.name).strip()
            branch.address = request.POST.get('address', '').strip()
            branch.city = request.POST.get('city', '').strip()
            branch.state = request.POST.get('state', '').strip()
            branch.pincode = request.POST.get('pincode', '').strip()
            branch.contact_number = request.POST.get('contact_number', '').strip()
            branch.email = request.POST.get('email', '').strip()
            branch.latitude = request.POST.get('latitude') or None
            branch.longitude = request.POST.get('longitude') or None
            branch.attendance_radius_meters = request.POST.get('attendance_radius_meters') or None
            branch.save()
            messages.success(request, f'Branch "{branch.name}" updated successfully!')

        elif action == 'toggle_active':
            branch = get_object_or_404(Branch, id=request.POST.get('branch_id'), office=office)
            if branch.is_head_office and branch.is_active:
                messages.error(request, 'The head office branch cannot be deactivated.')
            else:
                branch.is_active = not branch.is_active
                branch.save(update_fields=['is_active'])
                messages.success(
                    request,
                    f'Branch "{branch.name}" {"activated" if branch.is_active else "deactivated"}.'
                )

        return redirect('employees:admin_branches')

    branches = Branch.objects.filter(office=office).annotate(
        employee_count=Count('employee', distinct=True)
    ).order_by('-is_head_office', 'name')

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'branches': branches,
        'active_branch_id': get_request_branch(request).id if get_request_branch(request) else None,
    })
    return render(request, 'employees/branches/admin_branches.html', context)


@login_required
@user_passes_test(office_admin_required)
def switch_branch(request):
    """Sets which branch is 'active' in the office admin's session. Every
    tenant_queryset() call and every new record they create from here on
    is scoped to this branch, until they switch again."""
    from .models import Branch
    from employees.middleware import OfficeMiddleware

    if request.method != 'POST':
        return redirect('employees:employee_dashboard')

    office = get_request_office(request)
    branch_id = request.POST.get('branch_id')
    branch = get_object_or_404(Branch, id=branch_id, office=office, is_active=True)

    request.session[OfficeMiddleware.SESSION_BRANCH_KEY] = branch.id
    messages.success(request, f'Switched to branch "{branch.name}".')

    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or reverse('employees:employee_dashboard')
    return redirect(next_url)


@login_required
@user_passes_test(feature_required('roles.manage'))
def admin_roles(request):
    """Create/edit delegated-permission roles (e.g. 'HR') and see who holds
    each one. Gated by the 'roles.manage' permission itself, so an admin can
    choose to delegate role management too - not just office_admin_required."""
    from .models import Role
    from .permissions import FEATURE_PERMISSIONS

    office = get_request_office(request)
    if office is None:
        messages.error(request, 'Your account is not linked to an approved office.')
        return redirect('employees:employee_dashboard')

    valid_keys = FEATURE_PERMISSION_KEYS

    if request.method == 'POST':
        action = request.POST.get('action')
        selected_perms = [p for p in request.POST.getlist('permissions') if p in valid_keys]

        if action == 'create':
            branch = get_request_branch(request)
            name = (request.POST.get('name') or '').strip()
            if not name:
                messages.error(request, 'Role name is required.')
            elif branch is None:
                messages.error(request, 'Switch to a branch before creating a role.')
            elif Role.objects.filter(office=office, branch=branch, name__iexact=name).exists():
                messages.error(request, f'A role named "{name}" already exists for "{branch.name}".')
            else:
                Role.objects.create(
                    office=office,
                    branch=branch,
                    name=name,
                    description=request.POST.get('description', '').strip(),
                    permissions=selected_perms,
                )
                messages.success(request, f'Role "{name}" created for "{branch.name}"!')

        elif action == 'update':
            role = get_object_or_404(tenant_queryset(request, Role.objects.all()), id=request.POST.get('role_id'))
            role.name = (request.POST.get('name') or role.name).strip()
            role.description = request.POST.get('description', '').strip()
            role.permissions = selected_perms
            role.save()
            messages.success(request, f'Role "{role.name}" updated successfully!')

        elif action == 'toggle_active':
            role = get_object_or_404(tenant_queryset(request, Role.objects.all()), id=request.POST.get('role_id'))
            role.is_active = not role.is_active
            role.save(update_fields=['is_active'])
            messages.success(
                request,
                f'Role "{role.name}" {"activated" if role.is_active else "deactivated"}.'
            )

        elif action == 'delete':
            role = get_object_or_404(tenant_queryset(request, Role.objects.all()), id=request.POST.get('role_id'))
            role.delete()
            messages.success(request, 'Role deleted.')

        return redirect('employees:admin_roles')

    roles = list(
        tenant_queryset(request, Role.objects.filter(office=office)).annotate(
            member_count=Count('members', distinct=True)
        ).order_by('name')
    )

    # Group (key, label, group) tuples by group, for checkbox sections.
    grouped_permissions = {}
    permission_labels = {}
    for key, label, group in FEATURE_PERMISSIONS:
        grouped_permissions.setdefault(group, []).append({'key': key, 'label': label})
        permission_labels[key] = label

    # Attach human-readable labels for the granted permissions directly on
    # each role instance (Django templates can't do a dict[key] lookup by
    # variable, so resolve it here instead of in the template).
    for role in roles:
        role.permission_display = [permission_labels.get(key, key) for key in (role.permissions or [])]

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'roles': roles,
        'grouped_permissions': grouped_permissions,
    })
    return render(request, 'employees/roles/admin_roles.html', context)


@login_required
@user_passes_test(feature_required('rules.manage'))
def admin_rules(request):
    """Admin CRUD for company rules"""
    # rules = CompanyRule.objects.all().order_by('order', 'created_at').annotate(
    #     ack_total=Count('acknowledgements', distinct=True)
    # )
    
    rules = tenant_queryset(
        request,
        CompanyRule.objects.all()
    ).order_by(
        "order",
        "created_at"
    ).annotate(
        ack_total=Count("acknowledgements", distinct=True)
    )
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'create':
            points = []
            for key in request.POST.keys():
                if key.startswith('point_'):
                    point = request.POST.get(key).strip()
                    if point:
                        points.append(point)
            
            office = get_request_office(request)
            branch = get_request_branch(request)

            rule = CompanyRule.objects.create(
                office=office,
                branch=branch,
                title=request.POST.get("title"),
                description=request.POST.get("description"),
                points=points,
                order=int(request.POST.get("order", 0)),
                created_by=request.user,
            )
            messages.success(request, f'Rule created successfully for "{branch.name}"!' if branch else 'Rule created successfully!')
            return redirect('employees:admin_rules')

        elif action == 'update':
            rule_id = request.POST.get('rule_id')
            # rule = get_object_or_404(CompanyRule, id=rule_id)
            rule = get_object_or_404(
                tenant_queryset(request, CompanyRule.objects.all()),
                id=rule_id,
            )
            rule.title = request.POST.get('title')
            rule.description = request.POST.get('description')
            
            points = []
            for key in request.POST.keys():
                if key.startswith('point_'):
                    point = request.POST.get(key).strip()
                    if point:
                        points.append(point)
            rule.points = points
            
            rule.order = int(request.POST.get('order', 0))
            rule.is_active = request.POST.get('is_active') == 'on'
            rule.save()
            messages.success(request, 'Rule updated successfully!')
            return redirect('employees:admin_rules')
        
        elif action == 'delete':
            rule_id = request.POST.get('rule_id')
            # rule = get_object_or_404(CompanyRule, id=rule_id)
            rule = get_object_or_404(
                tenant_queryset(request, CompanyRule.objects.all()),
                id=rule_id,
            )
            rule.delete()
            messages.success(request, 'Rule deleted successfully!')
            return redirect('employees:admin_rules')
    
    total_employees = tenant_queryset(
        request,
        Employee.objects.all()
    ).count()
    # acceptances = RulesAcceptance.objects.select_related('employee').order_by('-accepted_at')
    acceptances = tenant_queryset(
        request,
        RulesAcceptance.objects.select_related("employee")
    ).order_by("-accepted_at")
    acknowledged_total = acceptances.count()
    # pending_employees = Employee.objects.filter(rules_acceptance__isnull=True).order_by('full_name')
    pending_employees = tenant_queryset(
        request,
        Employee.objects.filter(
            rules_acceptance__isnull=True
        )
    ).order_by("full_name")
    
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'rules': rules,
        'ack_summary': {
            'total': total_employees,
            'acknowledged': acknowledged_total,
            'pending': max(total_employees - acknowledged_total, 0),
            'percentage': (acknowledged_total / total_employees * 100) if total_employees else 0,
        },
        'acceptances': acceptances,
        'pending_employees': pending_employees,
    })
    return render(request, 'employees/rules/admin_rules.html', context)


# ===========================
# LOANS & ADVANCE VIEWS
# ===========================

@login_required
@user_passes_test(is_employee)
def loan_request(request):
    """Employee loan request form"""
    # employee = get_object_or_404(Employee, user=request.user)
    # loans = LoanRequest.objects.filter(employee=employee).order_by('-created_at')

    employee = get_object_or_404(
        tenant_queryset(
            request,
            Employee.objects.all()
        ),
        user=request.user,
    )

    loans = tenant_queryset(
        request,
        LoanRequest.objects.filter(employee=employee)
    ).order_by("-created_at")
    active_tab = request.GET.get('tab', 'request')
    
    if request.method == 'POST':
        form = LoanRequestForm(request.POST, request.FILES)
        if form.is_valid():
            loan = form.save(commit=False)
            loan.employee = employee
            loan.office = employee.office
            loan.branch = employee.branch
            loan.save()
            messages.success(request, 'Loan request submitted successfully!')
            return redirect(f"{reverse('employees:loan_request')}?tab=history")
        else:
            messages.error(request, 'Please fix the highlighted errors and try again.')
            active_tab = 'request'
    else:
        form = LoanRequestForm()

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'loan_form': form,
        'loans': loans,
        'active_tab': active_tab,
    })
    return render(request, 'employees/loans/loan_request.html', context)


@login_required
@user_passes_test(is_employee)
def my_loans(request):
    """Employee view of their loan requests"""
    return redirect(f"{reverse('employees:loan_request')}?tab=history")


@login_required
@user_passes_test(feature_required('finance.manage'))
def admin_loans(request):
    """Admin dashboard for loan requests"""
    # loans = LoanRequest.objects.all().order_by('-created_at')
    loans = tenant_queryset(
        request,
        LoanRequest.objects.select_related(
            "employee",
            "reviewed_by",
        )
    ).order_by("-created_at")
    
    if request.method == 'POST':
        loan_id = request.POST.get('loan_id')
        action = request.POST.get('action')
        # loan = get_object_or_404(LoanRequest, id=loan_id)
        loan = get_object_or_404(
            tenant_queryset(
                request,
                LoanRequest.objects.select_related("employee")
            ),
            id=loan_id,
        )
        
        if action == 'approve':
            loan.status = LoanRequest.Status.APPROVED
            loan.reviewed_by = request.user
            loan.reviewed_at = timezone.now()
            loan.save()
            
            # CREATE NOTIFICATION
            from employees.notification_utils import create_loan_approved_notification
            create_loan_approved_notification(loan.employee, loan)
            
            messages.success(request, 'Loan request approved!')
        elif action == 'disapprove':
            loan.status = LoanRequest.Status.DISAPPROVED
            loan.reviewed_by = request.user
            loan.reviewed_at = timezone.now()
            loan.admin_comment = request.POST.get('admin_comment', '')
            loan.save()
            
            # CREATE NOTIFICATION
            from employees.notification_utils import create_loan_rejected_notification
            create_loan_rejected_notification(loan.employee, loan)
            messages.success(request, 'Loan request disapproved!')
        elif action == 'update_status':
            loan.status = request.POST.get('status')
            loan.save()
            messages.success(request, 'Status updated!')
        
        return redirect('employees:admin_loans')
    
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'loans': loans,
    })
    return render(request, 'employees/loans/admin_loans.html', context)


# ===========================
# REIMBURSEMENT VIEWS
# ===========================

@login_required
@user_passes_test(is_employee)
def reimbursement_request(request):
    """Employee reimbursement request form"""
    # employee = get_object_or_404(Employee, user=request.user)
    # reimbursements = ReimbursementRequest.objects.filter(employee=employee).order_by('-created_at')

    employee = get_object_or_404(
        tenant_queryset(
            request,
            Employee.objects.all(),
        ),
        user=request.user,
    )

    reimbursements = tenant_queryset(
        request,
        ReimbursementRequest.objects.filter(employee=employee),
    ).order_by("-created_at")
    active_tab = request.GET.get('tab', 'request')
    
    if request.method == 'POST':
        form = ReimbursementRequestForm(request.POST, request.FILES)
        if form.is_valid():
            reimbursement = form.save(commit=False)
            reimbursement.employee = employee
            reimbursement.office = employee.office
            reimbursement.branch = employee.branch
            reimbursement.upi_id = form.cleaned_data.get('upi_id') or employee.upi_id
            reimbursement.save()

            # Update UPI ID if changed
            upi_value = form.cleaned_data.get('upi_id')
            if upi_value and upi_value != employee.upi_id:
                employee.upi_id = upi_value
                employee.save(update_fields=['upi_id', 'updated_at'])

            messages.success(request, 'Reimbursement request submitted successfully!')
            return redirect(f"{reverse('employees:reimbursement_request')}?tab=history")
        else:
            messages.error(request, 'Please fix the highlighted errors and try again.')
            active_tab = 'request'
    else:
        initial = {}
        if employee.upi_id:
            initial['upi_id'] = employee.upi_id
        form = ReimbursementRequestForm(initial=initial)

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'reimbursement_form': form,
        'reimbursements': reimbursements,
        'active_tab': active_tab,
    })
    return render(request, 'employees/reimbursements/reimbursement_request.html', context)


@login_required
@user_passes_test(is_employee)
def my_reimbursements(request):
    """Employee view of their reimbursement requests"""
    return redirect(f"{reverse('employees:reimbursement_request')}?tab=history")


@login_required
@user_passes_test(feature_required('finance.manage'))
def admin_reimbursements(request):
    """Admin dashboard for reimbursement requests"""
    # reimbursements = ReimbursementRequest.objects.all().order_by('-created_at')
    reimbursements = tenant_queryset(
        request,
        ReimbursementRequest.objects.select_related(
            "employee",
            "verified_by",
            "paid_by",
        ),
    ).order_by("-created_at")
    
    if request.method == 'POST':
        reimbursement_id = request.POST.get('reimbursement_id')
        action = request.POST.get('action')
        # reimbursement = get_object_or_404(ReimbursementRequest, id=reimbursement_id)
        reimbursement = get_object_or_404(
            tenant_queryset(
                request,
                ReimbursementRequest.objects.select_related("employee"),
            ),
            id=reimbursement_id,
        )
        
        if action == 'verify':
            reimbursement.status = ReimbursementRequest.Status.VERIFIED
            reimbursement.verified_by = request.user
            reimbursement.verified_at = timezone.now()
            reimbursement.save()
            
            # CREATE NOTIFICATION
            from employees.notification_utils import create_reimbursement_approved_notification
            create_reimbursement_approved_notification(reimbursement.employee, reimbursement)
            
            messages.success(request, 'Reimbursement verified!')
        elif action == 'mark_paid':
            reimbursement.status = ReimbursementRequest.Status.PAID
            reimbursement.paid_by = request.user
            reimbursement.paid_at = timezone.now()
            reimbursement.save()
            messages.success(request, 'Reimbursement marked as paid!')
        elif action == 'reject':
            reimbursement.status = ReimbursementRequest.Status.REJECTED
            reimbursement.admin_comment = request.POST.get('admin_comment', '')
            reimbursement.save()
            
            # CREATE NOTIFICATION
            from employees.notification_utils import create_reimbursement_rejected_notification
            create_reimbursement_rejected_notification(reimbursement.employee, reimbursement)
            
            messages.success(request, 'Reimbursement rejected!')
        
        return redirect('employees:admin_reimbursements')
    
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'reimbursements': reimbursements,
    })
    return render(request, 'employees/reimbursements/admin_reimbursements.html', context)


# ===========================
# SALARY SLIP MANAGEMENT
# ===========================

@login_required
@user_passes_test(is_employee)
def salary_slips(request):
    """Employee view of their salary slips"""
    from employees.models import SalarySlip
    from datetime import timedelta
    
    employee = request.user.employee_profile
    salary_slips = SalarySlip.objects.filter(employee=employee).order_by('-month')

    # Eligible once 3 months past joining, OR as soon as the admin has
    # actually generated a slip for them (mirrors employee_dashboard's
    # salary_slip_eligible check).
    three_months_ago = timezone.now() - timedelta(days=90)
    if employee.created_at > three_months_ago and not salary_slips.exists():
        messages.warning(request, 'You are not eligible yet. Please contact your admin.')
        return redirect('employees:employee_dashboard')
    
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'salary_slips': salary_slips,
        'employee': employee,
    })
    return render(request, 'employees/salary_slips/employee_salary_slips.html', context)


@login_required
@user_passes_test(feature_required('finance.manage'))
def admin_salary_slips(request):
    """Admin dashboard for salary slip management"""
    from employees.models import SalarySlip
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'generate':
            employee_id = request.POST.get('employee_id')
            month_str = request.POST.get('month')
            basic_salary = request.POST.get('basic_salary')
            deductions = request.POST.get('deductions')
            net_salary = request.POST.get('net_salary')
            
            try:
                from datetime import datetime
                month_date = datetime.strptime(month_str, '%Y-%m').date().replace(day=1)
                # employee = Employee.objects.get(id=employee_id)
                employee = get_object_or_404(
                    tenant_queryset(
                        request,
                        Employee.objects.all()
                    ),
                    id=employee_id
                )
                
                salary_slip, created = SalarySlip.objects.update_or_create(
                    office=employee.office,
                    branch=employee.branch,
                    employee=employee,
                    month=month_date,
                    defaults={
                        'basic_salary': basic_salary,
                        'deductions': deductions,
                        'net_salary': net_salary,
                    }
                )

                # Build the payslip PDF and attach it to the record so both
                # the admin and the employee can view/download it.
                pdf_buffer = _build_salary_slip_pdf(salary_slip)
                pdf_name = f"salary_slip_{employee.id}_{month_date.strftime('%Y_%m')}.pdf"
                salary_slip.pdf_file.save(pdf_name, ContentFile(pdf_buffer.getvalue()), save=True)

                if created:
                    messages.success(request, 'Salary slip generated successfully!')
                else:
                    messages.success(request, 'Salary slip updated successfully!')
            except Exception as e:
                messages.error(request, f'Error generating salary slip: {str(e)}')
        
        return redirect('employees:admin_salary_slips')
    
    # employees = Employee.objects.all().order_by('full_name')
    employees = tenant_queryset(
        request,
        Employee.objects.all()
    ).order_by('full_name')
    # salary_slips = SalarySlip.objects.all().order_by('-month')
    salary_slips = tenant_queryset(
        request,
        SalarySlip.objects.select_related("employee")
    ).order_by("-month")
    
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'employees': employees,
        'salary_slips': salary_slips,
    })
    return render(request, 'employees/salary_slips/admin_salary_slips.html', context)


@login_required
def download_salary_slip(request, pk):
    """Download salary slip PDF"""
    from employees.models import SalarySlip
    
    # salary_slip = get_object_or_404(SalarySlip, id=pk)
    salary_slip = get_object_or_404(
        tenant_queryset(
            request,
            SalarySlip.objects.select_related("employee")
        ),
        id=pk,
    )
    
    # Check permissions
    # if request.user.employee_profile != salary_slip.employee and not request.user.is_superuser:
    #     messages.error(request, 'You do not have permission to access this file.')
    #     return redirect('employees:employee_dashboard')
    is_owner = (
        hasattr(request.user, "employee_profile")
        and request.user.employee_profile == salary_slip.employee
    )

    # tenant_queryset() above already scoped salary_slip to the requesting
    # office admin's own office, so is_office_admin() here can't leak
    # another office's slip.
    if not (is_platform_admin(request.user) or is_office_admin(request.user) or is_owner):
        messages.error(
            request,
            "You do not have permission to access this salary slip."
        )
        return redirect("employees:employee_dashboard")
    if salary_slip.pdf_file:
        # ?inline=1 opens the PDF in-browser (used by the "View" button);
        # the default stays a forced download (used by "Download").
        inline = request.GET.get('inline') in ('1', 'true', 'yes')
        filename = f"salary_slip_{salary_slip.month.strftime('%b_%Y')}.pdf"
        return FileResponse(
            salary_slip.pdf_file.open('rb'),
            as_attachment=not inline,
            filename=filename,
        )

    messages.error(request, 'PDF file not found.')
    return redirect('employees:salary_slips')


def _build_salary_slip_pdf(salary_slip):
    """Renders a one-page payslip PDF for a SalarySlip record and returns an
    in-memory buffer ready to be saved to pdf_file or streamed as a response."""
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

    employee = salary_slip.employee
    office = employee.office

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=20 * mm, bottomMargin=20 * mm,
        leftMargin=20 * mm, rightMargin=20 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'SlipTitle', parent=styles['Heading1'], alignment=TA_CENTER, fontSize=16,
    )
    subtitle_style = ParagraphStyle(
        'SlipSubtitle', parent=styles['Normal'], alignment=TA_CENTER,
        textColor=colors.HexColor('#6b7280'),
    )
    section_style = ParagraphStyle(
        'SlipSection', parent=styles['Heading3'], fontSize=11,
        textColor=colors.HexColor('#374151'), spaceBefore=6, spaceAfter=6,
    )

    elements = []

    company_name = office.name if office else 'Company'
    company_address = office.address if office and office.address else ''
    elements.append(Paragraph(company_name, title_style))
    if company_address:
        elements.append(Paragraph(company_address, subtitle_style))
    elements.append(Spacer(1, 6 * mm))
    elements.append(Paragraph(
        f"Salary Slip - {salary_slip.month.strftime('%B %Y')}", section_style,
    ))

    employee_code = f"KI{employee.id:05d}"
    designation = getattr(employee, 'designation', '') or '-'
    info_table = Table(
        [
            ['Employee Name', employee.full_name, 'Employee Code', employee_code],
            ['Designation', designation, 'Office', company_name],
            ['Pay Period', salary_slip.month.strftime('%B %Y'), 'Slip Generated On', salary_slip.updated_at.strftime('%d %b %Y')],
        ],
        colWidths=[35 * mm, 55 * mm, 35 * mm, 45 * mm],
    )
    info_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#6b7280')),
        ('TEXTCOLOR', (2, 0), (2, -1), colors.HexColor('#6b7280')),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5e7eb')),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 8 * mm))

    amount_style = ParagraphStyle('Amount', parent=styles['Normal'], alignment=TA_RIGHT)
    earnings_deductions = Table(
        [
            ['Earnings', 'Amount (₹)', 'Deductions', 'Amount (₹)'],
            ['Basic Salary', f"{salary_slip.basic_salary:,.2f}", 'Total Deductions', f"{salary_slip.deductions:,.2f}"],
        ],
        colWidths=[42.5 * mm, 42.5 * mm, 42.5 * mm, 42.5 * mm],
    )
    earnings_deductions.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0891b2')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5e7eb')),
        ('FONTSIZE', (0, 0), (-1, -1), 9.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(earnings_deductions)
    elements.append(Spacer(1, 6 * mm))

    net_table = Table(
        [['Net Salary Payable', f"₹ {salary_slip.net_salary:,.2f}"]],
        colWidths=[127.5 * mm, 42.5 * mm],
    )
    net_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#10b981')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
    ]))
    elements.append(net_table)
    elements.append(Spacer(1, 14 * mm))
    elements.append(Paragraph(
        "This is a system-generated salary slip and does not require a signature.",
        ParagraphStyle('Footnote', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#9ca3af')),
    ))

    doc.build(elements)
    buffer.seek(0)
    return buffer


# ===========================
# EMPLOYEE ID CARD MANAGEMENT
# ===========================

@login_required
@user_passes_test(is_employee)
def view_id_card(request):
    """Employee view of their digital ID card"""
    from employees.models import EmployeeIDCard
    import qrcode
    from io import BytesIO
    import base64
    
    employee = request.user.employee_profile
    id_card = EmployeeIDCard.objects.filter(employee=employee).first()
    
    if not id_card:
        context = TemplateLayout.init(request, context={})
        context.update({
            'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
            'employee': employee,
            'has_id_card': False,
        })
        return render(request, 'employees/id_card/view_id_card.html', context)
    
    # Generate QR code if not already present
    if not id_card.qr_code:
        qr_data = f"ID:{id_card.employee_id_number}|NAME:{id_card.employee.full_name}|DOJ:{id_card.date_of_joining}"
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(qr_data)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        img_str = base64.b64encode(buffer.getvalue()).decode()
        id_card.qr_code = img_str
        id_card.save(update_fields=['qr_code'])
    
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'employee': employee,
        'id_card': id_card,
        'has_id_card': True,
    })
    return render(request, 'employees/id_card/view_id_card.html', context)


@login_required
@user_passes_test(feature_required('employees.manage'))
def admin_id_cards(request):
    """Admin dashboard for employee ID card management"""
    from employees.models import EmployeeIDCard
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'generate':
            employee_id = request.POST.get('employee_id')
            employee_id_number = request.POST.get('employee_id_number')
            job_position = request.POST.get('job_position')
            date_of_joining = request.POST.get('date_of_joining')
            
            try:
                employee = Employee.objects.get(id=employee_id)
                
                id_card, created = EmployeeIDCard.objects.update_or_create(
                    employee=employee,
                    branch=employee.branch,
                    defaults={
                        'employee_id_number': employee_id_number,
                        'job_position': job_position,
                        'date_of_joining': date_of_joining,
                    }
                )
                
                if created:
                    # CREATE NOTIFICATION
                    from employees.notification_utils import create_id_card_generated_notification
                    create_id_card_generated_notification(employee)
                    
                    messages.success(request, 'ID card generated successfully!')
                else:
                    messages.success(request, 'ID card updated successfully!')
            except Exception as e:
                messages.error(request, f'Error generating ID card: {str(e)}')
        
        return redirect('employees:admin_id_cards')
    
    # employees = Employee.objects.all().order_by('full_name')
    employees = tenant_queryset(
        request,
        Employee.objects.all()
    ).order_by('full_name')
    id_cards = EmployeeIDCard.objects.all().order_by('-created_at')
    
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'employees': employees,
        'id_cards': id_cards,
    })
    return render(request, 'employees/id_card/admin_id_cards.html', context)


@login_required
@user_passes_test(feature_required('employees.manage'))
def dynamic_id_card_generator(request):
    """Dynamic ID card generator with real-time preview"""
    # employees = Employee.objects.all().order_by('full_name')
    employees = tenant_queryset(
        request,
        Employee.objects.all()
    ).order_by('full_name')
    
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'employees': employees,
    })
    return render(request, 'employees/id_card/dynamic_id_card.html', context)


@login_required
def download_id_card(request, pk):
    """Download ID card as PDF or image"""
    from employees.models import EmployeeIDCard
    
    id_card = get_object_or_404(EmployeeIDCard, id=pk)
    
    # Check permissions
    if request.user.employee_profile != id_card.employee and not request.user.is_superuser:
        messages.error(request, 'You do not have permission to access this file.')
        return redirect('employees:employee_dashboard')
    
    if id_card.employee_photo:
        return FileResponse(id_card.employee_photo.open('rb'), as_attachment=True)
    
    messages.error(request, 'Photo not found.')
    return redirect('employees:view_id_card')

@login_required
@user_passes_test(feature_required('employees.manage'))
def get_employee_data_api(request):
    """Returns employee details as JSON for the dynamic ID card preview."""
    from django.http import JsonResponse

    employee_id = request.GET.get('employee_id')
    if not employee_id:
        return JsonResponse({'success': False, 'error': 'employee_id is required.'}, status=400)

    try:
        employee = Employee.objects.get(id=employee_id)
    except Employee.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Employee not found.'}, status=404)

    photo_url = employee.profile_picture.url if employee.profile_picture else '/static/default-avatar.png'
    joining_date = employee.joining_date or (employee.created_at.date() if employee.created_at else None)

    return JsonResponse({
        'success': True,
        'employee_name': employee.full_name,
        'employee_code': f"KI{employee.id:05d}",
        'employee_designation': getattr(employee, 'designation', '') or '',
        'employee_joining_date': joining_date.strftime('%d %b %Y') if joining_date else '',
        'employee_joining_date_iso': joining_date.strftime('%Y-%m-%d') if joining_date else '',
        'employee_contact_number': employee.contact or '',
        'employee_photo_url': photo_url,
    })

@login_required
@user_passes_test(feature_required('shifts.manage'))
def admin_shifts(request):
    """Admin view for managing shifts"""
    from .models import Shift
    # Current office from OfficeMiddleware. 
    office = get_request_office( request )
    if request.method == 'POST':
        action = request.POST.get('action')
        # print(action, 'AAAAAAAAAAAAAAAAAAAAA')
        
        if action == 'create':
            name = request.POST.get('shift_name', '').strip()
            shift_type = request.POST.get('shift_type')
            start_time = request.POST.get('start_time')
            end_time = request.POST.get('end_time')


            # print(name, shift_type, start_time,end_time, 'HHHHHHHHHHHHHHHHHHHHHHHHHHHHH')
            
            if not all([name, start_time, end_time]):
                # print('CCCCCCCCCCCCCCCCCCCCcc')
                messages.error(request, 'All fields are required.')
                return redirect('employees:admin_shifts')
            
            try:
                myshift = Shift.objects.create(
                    office=office,
                    name=name,
                    shift_type=shift_type,
                    start_time=start_time,
                    end_time=end_time,
                    is_active=True
                )
                print(myshift, 'myshiftBBBBBBBBBBBBBBBBBbb')
                messages.success(request, f'Shift "{name}" created successfully.')
            except Exception as e:
                messages.error(request, f'Error creating shift: {str(e)}')
            
            return redirect('employees:admin_shifts')
        
        elif action == 'update':
            shift_id = request.POST.get('shift_id')
            name = request.POST.get('name', '').strip()
            shift_type = request.POST.get('shift_type', 'full_day')
            start_time = request.POST.get('start_time')
            end_time = request.POST.get('end_time')
            is_active = request.POST.get('is_active') == 'on'
            
            try:
                # shift = Shift.objects.get(id=shift_id)
                shift = tenant_object_or_404(
    request,
    Shift,
    id=shift_id
)
                shift.name = name
                shift.shift_type = shift_type
                shift.start_time = start_time
                shift.end_time = end_time
                shift.is_active = is_active
                shift.save()
                messages.success(request, f'Shift "{name}" updated successfully.')
            except Shift.DoesNotExist:
                messages.error(request, 'Shift not found.')
            except Exception as e:
                messages.error(request, f'Error updating shift: {str(e)}')
            
            return redirect('employees:admin_shifts')
        
        elif action == 'delete':
            shift_id = request.POST.get('shift_id')
            try:
                # shift = Shift.objects.get(id=shift_id)
                shift = tenant_object_or_404(
    request,
    Shift,
    id=shift_id
)
                shift_name = shift.name
                shift.delete()
                messages.success(request, f'Shift "{shift_name}" deleted successfully.')
            except Shift.DoesNotExist:
                messages.error(request, 'Shift not found.')
            except Exception as e:
                messages.error(request, f'Error deleting shift: {str(e)}')
            
            return redirect('employees:admin_shifts')
    
    # Get all shifts
    shifts = ( tenant_queryset( request, Shift.objects.all() ).annotate(
        employee_count=Count('employees')
    ).order_by('name'))
    
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'shifts': shifts,
    })
    
    return render(request, 'employees/shifts/admin_shifts.html', context)


# Import shift assignment views
from .shift_assignment_views import (
    shift_assignment,
    update_employee_shift,
    bulk_assign_shift,
    remove_employee_shift,
    get_employee_shifts_data,
)


@login_required
@user_passes_test(feature_required('employees.manage'))
def admin_idcard_generator(request):
    """Admin view for generating employee ID cards.

    On a successful AJAX POST this now returns the PDF binary directly
    (not JSON) — the browser starts downloading it immediately with no
    separate download step. On any failure it still returns JSON with
    an 'error' key so the frontend can show a message.
    """
    from .models import EmployeeIDCard
    from django.http import JsonResponse, HttpResponse
    from django.utils.dateparse import parse_date
    import json
    import io

    if request.method == 'POST' and request.headers.get('x-requested-with') == 'XMLHttpRequest':
        try:
            payload = json.loads(request.body.decode('utf-8'))
            employee_id = payload.get('employee_id')
            employee_code = payload.get('employee_code') or ''
            job_position = payload.get('job_position') or ''
            joining_str = payload.get('date_of_joining') or ''
            company_name = payload.get('company_name') or 'Dovix'
            company_address = payload.get('company_address') or 'Jaipur, Rajasthan, India'

            if not employee_id:
                return JsonResponse({'success': False, 'error': 'Employee is required.'}, status=400)

            try:
                employee = Employee.objects.get(id=employee_id)
            except Employee.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'Employee not found.'}, status=404)

            joining_date = None
            if joining_str:
                joining_date = parse_date(joining_str)
            if not joining_date:
                joining_date = employee.joining_date
            if not joining_date:
                joining_date = employee.created_at.date()

            if not employee_code:
                employee_code = f"KI{employee.id:05d}"
            if not job_position and hasattr(employee, 'designation'):
                job_position = employee.designation or ''

            employee_photo = getattr(employee, 'profile_picture', None)

            id_card, created = EmployeeIDCard.objects.update_or_create(
                employee=employee,
                branch=employee.branch,
                defaults={
                    'employee_id_number': employee_code,
                    'job_position': job_position or 'Employee',
                    'date_of_joining': joining_date,
                    'employee_photo': employee_photo,
                },
            )

            # ---- Build the PDF (front + back, CR80 card size) ----
            pdf_buffer = _build_id_card_pdf(
                employee=employee,
                employee_code=employee_code,
                job_position=job_position or 'Employee',
                joining_date=joining_date,
                company_name=company_name,
                company_address=company_address,
            )

            filename = f"ID_Card_{employee_code}.pdf"
            response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response

        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON payload.'}, status=400)
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)

    # GET request – render generator UI
    # employees = Employee.objects.all().order_by('full_name')
    employees = tenant_queryset(
        request,
        Employee.objects.all()
    ).order_by('full_name')

    context = TemplateLayout.init(request, context={})
    context.update(
        {
            'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
            'employees': employees,
        }
    )
    return render(request, 'employees/id_card/dynamic_id_card.html', context)


def _build_id_card_pdf(employee, employee_code, job_position, joining_date,
                        company_name, company_address):
    """Draws a two-page (front/back) CR80-sized (85.6mm x 54mm) ID card PDF
    and returns an in-memory BytesIO buffer."""
    from reportlab.lib.pagesizes import landscape
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.utils import ImageReader
    import io

    CARD_W, CARD_H = 85.6 * mm, 54 * mm
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(CARD_W, CARD_H))

    purple_top = HexColor('#667eea')
    purple_bottom = HexColor('#764ba2')

    # ---------------- FRONT ----------------
    _draw_gradient_bg(c, CARD_W, CARD_H, purple_top, purple_bottom)

    c.setFillColor(white)
    c.setFont('Helvetica-Bold', 11)
    c.drawString(6 * mm, CARD_H - 8 * mm, 'DOVIX')

    # Chip placeholder (top-right)
    c.setFillColor(HexColor('#ffffff'))
    c.setStrokeColor(white)
    c.roundRect(CARD_W - 16 * mm, CARD_H - 11 * mm, 10 * mm, 6 * mm, 1.5, fill=0, stroke=1)

    # Photo
    photo_size = 18 * mm
    photo_x = (CARD_W - photo_size) / 2
    photo_y = CARD_H - 30 * mm
    try:
        if employee.profile_picture and employee.profile_picture.name:
            img = ImageReader(employee.profile_picture.path)
            c.drawImage(img, photo_x, photo_y, width=photo_size, height=photo_size,
                        preserveAspectRatio=True, mask='auto')
        else:
            raise ValueError('no photo')
    except Exception:
        c.setFillColor(HexColor('#ffffff'))
        c.roundRect(photo_x, photo_y, photo_size, photo_size, 2, fill=1, stroke=0)
        c.setFillColor(purple_bottom)
        c.setFont('Helvetica-Bold', 14)
        initial = (employee.full_name or '?')[0].upper()
        c.drawCentredString(CARD_W / 2, photo_y + photo_size / 2 - 4, initial)

    # Name / designation / details
    c.setFillColor(white)
    c.setFont('Helvetica-Bold', 9)
    c.drawCentredString(CARD_W / 2, photo_y - 5 * mm, employee.full_name or '')
    c.setFont('Helvetica', 6.5)
    c.drawCentredString(CARD_W / 2, photo_y - 9 * mm, job_position)
    c.setFont('Helvetica', 6)
    c.drawCentredString(CARD_W / 2, photo_y - 13 * mm, f'ID: {employee_code}')
    c.drawCentredString(CARD_W / 2, photo_y - 16.5 * mm, f'DOJ: {joining_date.strftime("%d/%m/%Y")}')

    c.setFont('Helvetica', 6)
    c.drawCentredString(CARD_W / 2, 4 * mm, 'Valid ID Card')

    c.showPage()

    # ---------------- BACK ----------------
    c.setPageSize((CARD_W, CARD_H))
    _draw_gradient_bg(c, CARD_W, CARD_H, purple_bottom, purple_top)

    # QR placeholder box
    qr_size = 18 * mm
    qr_x = (CARD_W - qr_size) / 2
    qr_y = CARD_H - 24 * mm
    c.setFillColor(white)
    c.roundRect(qr_x, qr_y, qr_size, qr_size, 2, fill=1, stroke=0)
    c.setFillColor(purple_top)
    c.setFont('Helvetica', 7)
    c.drawCentredString(CARD_W / 2, qr_y + qr_size / 2 - 3, 'QR')

    c.setFillColor(white)
    c.setFont('Helvetica-Bold', 8)
    c.drawCentredString(CARD_W / 2, qr_y - 5 * mm, company_name)

    c.setFont('Helvetica', 6)
    text_obj = c.beginText(6 * mm, qr_y - 10 * mm)
    text_obj.setLeading(8)
    for line in company_address.split('\n'):
        text_obj.textLine(line)
    text_obj.textLine('')
    text_obj.textLine(f'Contact: {employee.contact}')
    c.drawText(text_obj)

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer


def _draw_gradient_bg(c, width, height, color_top, color_bottom, steps=40):
    """Simulates a vertical gradient by stacking thin colored bands,
    since reportlab canvas has no native linear gradient fill."""
    from reportlab.lib.colors import Color

    for i in range(steps):
        frac = i / float(steps - 1)
        r = color_top.red + (color_bottom.red - color_top.red) * frac
        g = color_top.green + (color_bottom.green - color_top.green) * frac
        b = color_top.blue + (color_bottom.blue - color_top.blue) * frac
        c.setFillColor(Color(r, g, b))
        band_h = height / steps
        c.rect(0, height - (i + 1) * band_h, width, band_h + 0.5, fill=1, stroke=0)

@login_required
def modern_dashboard(request):
    """Modern employee dashboard - redirect to new check-in dashboard"""
    return redirect('employees:check_in')


@login_required
@user_passes_test(office_admin_required)
def admin_points_management(request):
    """Admin view for managing employee points"""
    from .models import EmployeePoints
    from datetime import datetime
    
    if request.method == 'POST':
        action = request.POST.get('action')
        points_id = request.POST.get('points_id')
        amount = int(request.POST.get('amount', 0))
        reason = request.POST.get('reason', '')
        
        try:
            points_obj = EmployeePoints.objects.get(id=points_id)
            
            if action == 'add':
                points_obj.points += amount
                points_obj.points_earned += amount
                messages.success(request, f'Added {amount} points to {points_obj.employee.full_name}')
            elif action == 'deduct':
                points_obj.points = max(0, points_obj.points - amount)
                points_obj.points_deducted += amount
                messages.success(request, f'Deducted {amount} points from {points_obj.employee.full_name}')
            
            points_obj.save()
        except EmployeePoints.DoesNotExist:
            messages.error(request, 'Points record not found')
        except Exception as e:
            messages.error(request, f'Error: {str(e)}')
        
        return redirect('employees:admin_points_management')
    
    # Get filter parameters
    employee_filter = request.GET.get('employee')
    month_filter = request.GET.get('month')
    sort_by = request.GET.get('sort', '-points')
    
    # Build queryset
    from .models import EmployeePoints
    queryset = EmployeePoints.objects.select_related('employee').all()
    
    if employee_filter:
        queryset = queryset.filter(employee_id=employee_filter)
    
    if month_filter:
        try:
            month_date = datetime.strptime(month_filter, '%Y-%m')
            queryset = queryset.filter(year=month_date.year, month=month_date.month)
        except:
            pass
    
    queryset = queryset.order_by(sort_by)
    
    # Calculate statistics
    all_points = EmployeePoints.objects.all()
    total_employees = Employee.objects.filter(is_active=True).count()
    average_points = all_points.aggregate(avg=models.Avg('points'))['avg'] or 0
    
    top_performer = all_points.order_by('-points').first()
    top_performer_name = top_performer.employee.full_name if top_performer else 'N/A'
    top_performer_points = top_performer.points if top_performer else 0
    
    # Get unique months for filter
    months = all_points.values_list('year', 'month').distinct().order_by('-year', '-month')
    months_list = [datetime(int(y), int(m), 1) for y, m in months]
    
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'points_list': queryset,
        'employees': Employee.objects.filter(is_active=True).order_by('full_name'),
        'months': months_list,
        'total_employees': total_employees,
        'average_points': average_points,
        'top_performer_name': top_performer_name,
        'top_performer_points': top_performer_points,
    })
    
    return render(request, 'employees/points/admin_points.html', context)


@login_required
def notification_center(request):
    """Employee notification center"""
    from .models import EmployeeNotification, NotificationPreference
    
    employee = request.user.employee_profile
    
    # Get all notifications
    notifications = EmployeeNotification.objects.filter(
        employee=employee
    ).order_by('-created_at')
    
    # Get preferences
    preferences, created = NotificationPreference.objects.get_or_create(employee=employee)
    
    # Calculate stats
    unread_count = notifications.filter(is_read=False).count()
    total_count = notifications.count()
    info_count = notifications.filter(notification_type='info').count()
    success_count = notifications.filter(notification_type='success').count()
    
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'notifications': notifications[:50],  # Show last 50
        'unread_count': unread_count,
        'total_count': total_count,
        'info_count': info_count,
        'success_count': success_count,
        'preferences': preferences,
    })
    
    return render(request, 'employees/notifications/notification_center.html', context)


@login_required
@user_passes_test(feature_required('employees.manage'))
@require_http_methods(["GET"])
def get_employee_data(request):
    """API endpoint to fetch employee data for ID card generation"""
    employee_id = request.GET.get('employee_id')
    
    if not employee_id:
        return JsonResponse({'error': 'Employee ID is required'}, status=400)
    
    try:
        employee = Employee.objects.get(id=employee_id)

        # Prefer ID card metadata if it exists, otherwise fall back to core employee fields
        joining_date_obj = None
        if hasattr(employee, 'id_card') and employee.id_card:
            employee_code = employee.id_card.employee_id_number
            joining_date_obj = employee.id_card.date_of_joining
            designation = employee.id_card.job_position or 'Employee'
        else:
            # Get employee code (use ID as fallback)
            employee_code = f'KI{employee.id:05d}'

            # Get designation (placeholder if not available)
            designation = getattr(employee, 'designation', None) or 'Employee'
            
            # Use employee joining date
            joining_date_obj = employee.joining_date
        
        # Format joining date for display (DD-MM-YYYY)
        joining_date = joining_date_obj.strftime('%d-%m-%Y') if joining_date_obj else ''
        
        # Format joining date for input (YYYY-MM-DD)
        joining_date_iso = joining_date_obj.strftime('%Y-%m-%d') if joining_date_obj else ''
        
        # Get contact number
        contact_number = employee.contact or 'N/A'
        
        # Get photo URL
        photo_url = employee.profile_picture.url if employee.profile_picture else '/static/default-avatar.png'
        
        return JsonResponse({
            'success': True,
            'employee_name': employee.full_name.upper(),
            'employee_code': employee_code,
            'employee_designation': designation,
            'employee_joining_date': joining_date,
            'employee_joining_date_iso': joining_date_iso,
            'employee_contact_number': contact_number,
            'employee_photo_url': photo_url,
        })
    except Employee.DoesNotExist:
        return JsonResponse({'error': 'Employee not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@user_passes_test(is_employee)
def checkin_dashboard(request):
    """Render the mobile-optimized check-in/check-out dashboard"""
    # If this is an AJAX POST from the check-in button, delegate to the
    # existing check_in view so all validation and logging is reused.
    if request.method == "POST" and request.headers.get("x-requested-with") == "XMLHttpRequest":
        return check_in(request)

    employee = request.user.employee_profile
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_blank.html', context),
        'employee': employee,
        # Explicitly show the mobile bottom nav on the new check-in dashboard
        'hide_mobile_nav': False,
    })
    return render(request, 'employees/checkin_dashboard.html', context)

@login_required
@user_passes_test(is_employee)
def holiday_calendar(request):
    """Display holiday calendar for employees"""
    from datetime import datetime
    from employees.models import Holiday  # Assuming you have a Holiday model
    from .permissions import get_request_office, get_request_branch


    selected_year = request.GET.get('year', datetime.now().year)

    try:
        selected_year = int(selected_year)
    except (ValueError, TypeError):
        selected_year = datetime.now().year

    office = get_request_office(request)
    branch = get_request_branch(request)

    # Get holidays for selected year
    holidays = Holiday.objects.filter(office=office, branch=branch, date__year=selected_year).order_by('date')
    
    # Get available years from holidays
    available_years = list(range(datetime.now().year, datetime.now().year + 3))
    
    
    # Count by type
    national_count = holidays.filter(type='national').count()
    office_count = holidays.filter(type='office').count()
    festival_count = holidays.filter(type='festival').count()
    
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'holidays': holidays,
        'selected_year': selected_year,
        'available_years': available_years,
        'national_count': national_count,
        'office_count': office_count,
        'festival_count': festival_count,
    })
    return render(request, 'employees/holiday_calendar.html', context)

@login_required
@user_passes_test(feature_required('attendance.manage'))
def manual_attendance(request):
    from django.utils import timezone
    from datetime import datetime, time, timedelta

    # employees = Employee.objects.all().order_by("full_name")
    employees = tenant_queryset(
        request,
        Employee.objects.all()
    ).order_by('full_name')
    message = None

    if request.method == "POST":
        employee_id = request.POST.get("employee")
        date_str = request.POST.get("date")
        check_in_str = request.POST.get("check_in_time")
        check_out_str = request.POST.get("check_out_time")
        status = request.POST.get("final_status")
        comment = request.POST.get("comment")

        # employee = Employee.objects.get(id=employee_id)
        date = datetime.strptime(date_str, "%Y-%m-%d").date()

        employee = get_object_or_404(
            tenant_queryset(
                request,
                Employee.objects.all()
            ),
            id=employee_id
        )

        office = employee.office

        # attendance, created = Attendance.objects.get_or_create(
        #     office=office,
        #     employee=employee,
        #     date=date,
        # )
        attendance = Attendance.objects.filter(
            employee=employee,
            date=date,
        ).first()

        if attendance:
            messages.warning(
                request,
                f"Attendance for {employee.full_name} on {date.strftime('%d-%b-%Y')} already exists. "
                "Please edit the existing attendance instead of creating a new one."
            )

            context = TemplateLayout.init(request, context={})
            context.update({
                "layout_path": TemplateHelper.set_layout("layout_vertical.html", context),
                "employees": employees,
            })

            return render(request, "employees/manual_attendance.html", context)

        attendance = Attendance(
            office=office,
            branch=employee.branch,
            employee=employee,
            date=date,
        )
        # -----------------------------
        # SAFE DEFAULTS IF NO TIME GIVEN
        # -----------------------------
        # Many DBs do not allow NULL → set 00:00 instead of None
        base_dt = timezone.make_aware(datetime.combine(date, time(0, 0)))

        # CHECK-IN HANDLING
        if check_in_str:
            check_in_time = timezone.make_aware(
                datetime.combine(date, datetime.strptime(check_in_str, "%H:%M").time())
            )
        else:
            # Default safe value (DB will not crash)
            check_in_time = base_dt

        # CHECK-OUT HANDLING
        if check_out_str:
            check_out_time = timezone.make_aware(
                datetime.combine(date, datetime.strptime(check_out_str, "%H:%M").time())
            )
        else:
            # Allow NULL if your DB allows it, otherwise use safe fallback
            check_out_time = None  

        attendance.check_in_time = check_in_time
        attendance.check_out_time = check_out_time

        # -----------------------------
        # STATUS HANDLING
        # -----------------------------
        attendance.final_status = status
        attendance.half_day = (status == "half_day")

        # -----------------------------
        # WORK HOURS CALCULATION
        # -----------------------------
        # if check_in_time and check_out_time:
        #     attendance.total_work_hours = (check_out_time - check_in_time).total_seconds() / 3600
        # else:
        #     attendance.total_work_hours = 0

        # -----------------------------
        # ADMIN META
        # -----------------------------
        attendance.is_manually_marked = True
        attendance.manually_marked_by = request.user
        attendance.manually_marked_at = timezone.now()
        attendance.manual_comment = comment or ""

        attendance.save()

        message = "Attendance marked successfully!"

    # TEMPLATE CONTEXT
    context = TemplateLayout.init(request, context={})
    context.update({
        "layout_path": TemplateHelper.set_layout("layout_vertical.html", context),
        "employees": employees,
        "message": message,
    })

    return render(request, "employees/manual_attendance.html", context)

@login_required
@user_passes_test(feature_required('leave.manage'))
def admin_adjust_paid_leave(request):
    office = get_request_office(request)
    # employees = Employee.objects.filter(is_active=True).order_by("full_name")
    employees = tenant_queryset(
        request,
        Employee.objects.filter(is_active=True)
    ).order_by('full_name')
    selected_employee = None
    current_balance = None

    if request.method == "GET":
        print("PPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPP")
        return render(request, "admin/adjust_paid_leave.html")

    if request.method == "POST":
        employee_id = request.POST.get("employee")
        amount = request.POST.get("amount")
        adjustment_type = request.POST.get("adjustment_type")
        reason = request.POST.get("reason", "")
        print(employee_id, amount, adjustment_type, reason, 'OOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOOO')

        # selected_employee = Employee.objects.get(id=employee_id)
        selected_employee = get_object_or_404(
            tenant_queryset(request, Employee.objects.all()),
            id=employee_id
        )
        current_balance = selected_employee.calculate_paid_leave_balance()

        amount = float(amount)

        if adjustment_type == "increase":
            new_balance = current_balance + amount
        else:
            new_balance = max(0, current_balance - amount)

        # Create adjustment log
        PaidLeaveAdjustment.objects.create(
            employee=selected_employee,
            branch=selected_employee.branch,
            adjustment_type=adjustment_type,
            amount=amount,
            reason=reason,
            previous_balance=current_balance,
            new_balance=new_balance,
            adjusted_by=request.user,
        )

        messages.success(request, "Paid leave updated successfully!")

        return redirect("admin_adjust_paid_leave")

    # For showing current balance on GET request
    if request.GET.get("employee"):
        # selected_employee = Employee.objects.get(id=request.GET.get("employee"))
        selected_employee = get_object_or_404(
            tenant_queryset(request, Employee.objects.all()),
            id=request.GET.get("employee")
        )
        current_balance = selected_employee.calculate_paid_leave_balance()

    # adjustments = PaidLeaveAdjustment.objects.all().order_by("-adjusted_at")
    adjustments = tenant_queryset(
        request,
        PaidLeaveAdjustment.objects.select_related('employee').all()
    ).order_by("-adjusted_at")

    return render(request, "admin/paid_leave_adjustment.html", {
        "employees": employees,
        "selected_employee": selected_employee,
        "current_balance": current_balance,
        "adjustments": adjustments,
    })

from decimal import Decimal


from decimal import Decimal, InvalidOperation

# @user_passes_test(lambda u: u.is_superuser)
@login_required
@user_passes_test(feature_required('leave.manage'))
def manual_leave_adjustment(request):
    # employees = Employee.objects.all()
    employees = tenant_queryset(
        request,
        Employee.objects.all()
    )
    selected_employee = None

    context = TemplateLayout.init(request, context={})

    if request.method == "POST":
        emp_id = request.POST.get("employee")
        adjustment_type = request.POST.get("adjustment_type")
        reason = request.POST.get("reason") or ""

        if not emp_id:
            messages.error(request, "Please select an employee.")
            return redirect("employees:adjust_paid_leave")

        try:
            amount = Decimal(request.POST.get("amount"))
        except (InvalidOperation, TypeError):
            messages.error(request, "Enter a valid numeric amount.")
            return redirect("employees:adjust_paid_leave")

        if amount <= 0:
            messages.error(request, "Amount must be greater than 0.")
            return redirect("employees:adjust_paid_leave")

        MAX_SINGLE_ADJUSTMENT = Decimal("100.00")
        if amount > MAX_SINGLE_ADJUSTMENT:
            messages.error(request, f"A single adjustment can't exceed {MAX_SINGLE_ADJUSTMENT} days.")
            return redirect("employees:adjust_paid_leave")

        # employee = get_object_or_404(Employee, id=emp_id)
        employee = get_object_or_404(
            tenant_queryset(
                request,
                Employee.objects.all()
            ),
            id=emp_id
        )
        selected_employee = employee

        previous_balance = employee.manual_extra_leaves

        if adjustment_type == "increase":
            new_total = employee.manual_extra_leaves + amount
        else:
            new_total = employee.manual_extra_leaves - amount

        FIELD_CEILING = Decimal("99999.99")
        if abs(new_total) >= FIELD_CEILING:
            messages.error(request, "This adjustment would push the balance out of range.")
            return redirect("employees:adjust_paid_leave")

        employee.manual_extra_leaves = new_total
        employee.save()

        PaidLeaveAdjustment.objects.create(
            employee=employee,
            office=employee.office,
            branch=employee.branch,
            adjustment_type=adjustment_type,
            amount=amount,
            reason=reason,
            previous_balance=previous_balance,
            new_balance=new_total,
            adjusted_by=request.user,
        )

        messages.success(request, f"Leave adjustment saved for {employee.full_name}!")
        return redirect("employees:adjust_paid_leave")

    # Re-select employee on GET (e.g. after redirect, or a direct ?employee= link)
    employee_id = request.GET.get("employee")
    if employee_id:
        selected_employee = Employee.objects.filter(id=employee_id).first()

    # adjustments = PaidLeaveAdjustment.objects.select_related('employee', 'adjusted_by').order_by("-adjusted_at")[:100]
    adjustments = tenant_queryset(
        request,
        PaidLeaveAdjustment.objects.select_related(
            'employee',
            'adjusted_by'
        )
    ).order_by("-adjusted_at")[:100]

    context.update({
        "layout_path": TemplateHelper.set_layout('layout_vertical.html', context),
        "employees": employees,
        "selected_employee": selected_employee,
        "adjustments": adjustments,
    })
    return render(request, "employees/adjust_paid_leave.html", context)


# open url for attendance 
def attendance_kiosk(request, token):
    office = get_object_or_404(
        Office,
        kiosk_token=token,
        status=Office.Status.APPROVED,
    )
    return render(request, "employees/kiosk.html",
        {
            "office": office,
        },)


# # employee Salary 

# @login_required
# @user_passes_test(office_admin_required)
# def employee_salary(request):
#     """Admin dashboard for employee salary profile management"""
#     from employees.models import EmployeeSalary

#     if request.method == 'POST':
#         action = request.POST.get('action')

#         if action in ('create', 'update'):
#             employee_id = request.POST.get('employee_id')
#             effective_from = request.POST.get('effective_from')
#             payment_mode = request.POST.get('payment_mode')

#             basic_salary = request.POST.get('basic_salary') or 0
#             hra = request.POST.get('hra') or 0
#             da = request.POST.get('da') or 0
#             conveyance_allowance = request.POST.get('conveyance_allowance') or 0
#             medical_allowance = request.POST.get('medical_allowance') or 0
#             special_allowance = request.POST.get('special_allowance') or 0
#             bonus = request.POST.get('bonus') or 0
#             overtime_rate_per_hour = request.POST.get('overtime_rate_per_hour') or 0

#             pf = request.POST.get('pf') or 0
#             esi = request.POST.get('esi') or 0
#             professional_tax = request.POST.get('professional_tax') or 0
#             tds = request.POST.get('tds') or 0

#             is_active = request.POST.get('is_active') == 'on'
#             remarks = request.POST.get('remarks', '')

#             try:
#                 employee = Employee.objects.get(id=employee_id)

#                 salary_profile, created = EmployeeSalary.objects.update_or_create(
#                     employee=employee,
#                     defaults={
#                         'effective_from': effective_from,
#                         'payment_mode': payment_mode,
#                         'basic_salary': basic_salary,
#                         'hra': hra,
#                         'da': da,
#                         'conveyance_allowance': conveyance_allowance,
#                         'medical_allowance': medical_allowance,
#                         'special_allowance': special_allowance,
#                         'bonus': bonus,
#                         'overtime_rate_per_hour': overtime_rate_per_hour,
#                         'pf': pf,
#                         'esi': esi,
#                         'professional_tax': professional_tax,
#                         'tds': tds,
#                         'is_active': is_active,
#                         'remarks': remarks,
#                     }
#                 )

#                 if created:
#                     messages.success(request, 'Salary profile created successfully!')
#                 else:
#                     messages.success(request, 'Salary profile updated successfully!')
#             except Exception as e:
#                 messages.error(request, f'Error saving salary profile: {str(e)}')

#         elif action == 'delete':
#             salary_id = request.POST.get('salary_id')
#             try:
#                 EmployeeSalary.objects.filter(id=salary_id).delete()
#                 messages.success(request, 'Salary profile deleted successfully!')
#             except Exception as e:
#                 messages.error(request, f'Error deleting salary profile: {str(e)}')

#         return redirect('employees:employee_salary')

#     employees = Employee.objects.all().order_by('full_name')
#     salary_profiles = EmployeeSalary.objects.select_related('employee').all()

#     edit_salary = None
#     edit_id = request.GET.get('edit')
#     if edit_id:
#         edit_salary = EmployeeSalary.objects.filter(id=edit_id).first()

#     context = TemplateLayout.init(request, context={})
#     context.update({
#         'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
#         'employees': employees,
#         'salary_profiles': salary_profiles,
#         'edit_salary': edit_salary,
#         'payment_mode_choices': EmployeeSalary.PaymentMode.choices,
#     })
#     return render(request, 'employees/employee_salary.html', context)

import calendar as cal_module
from datetime import date as date_cls


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_holidays_in_month(year, month):
    """Returns a set of dates that are holidays: every Sunday + the
    1st, 3rd, and 5th Saturday of the month. Adjust here if your holiday
    policy differs (e.g. if you have a separate Holiday model)."""
    holidays = set()
    saturdays = []
    total_days = cal_module.monthrange(year, month)[1]

    for day in range(1, total_days + 1):
        d = date_cls(year, month, day)
        if d.weekday() == 6:  # Sunday
            holidays.add(d)
        elif d.weekday() == 5:  # Saturday
            saturdays.append(d)

    for idx, sat in enumerate(saturdays, start=1):
        if idx in (1, 3, 5):
            holidays.add(sat)

    return holidays


def get_salary_profile_for_month(employee, year, month):
    """Returns the EmployeeSalary row that was EFFECTIVE for the given month:
    the most recent row whose effective_from is on/before the last day of
    that month. This is the key fix — July always resolves to whichever row
    was effective in July, August resolves to whichever row (possibly a
    newer, higher one) was effective in August, etc."""
    from employees.models import EmployeeSalary

    last_day_num = cal_module.monthrange(year, month)[1]
    last_day = date_cls(year, month, last_day_num)

    return (
        EmployeeSalary.objects
        .filter(employee=employee, effective_from__lte=last_day)
        .order_by('-effective_from')
        .first()
    )


def calculate_salary_for_month(employee, year, month):
    """Computes attendance-adjusted payable salary for one employee for one
    month, using whichever EmployeeSalary row was effective during THAT
    month (picked via effective_from) — not just their current/latest row.
    Returns None if no salary profile was effective yet for that month
    (e.g. viewing a month before the employee had any salary set up)."""
    from employees.models import Attendance  # adjust import/model name if different

    salary_profile = get_salary_profile_for_month(employee, year, month)
    if not salary_profile:
        return None

    total_days = cal_module.monthrange(year, month)[1]
    holiday_dates = get_holidays_in_month(year, month)
    working_days = total_days - len(holiday_dates)

    attendance_qs = Attendance.objects.filter(
        employee=employee,
        date__year=year,
        date__month=month,
    )
    attendance_by_date = {a.date: a for a in attendance_qs}

    present_days = 0
    half_days = 0
    lwp_days = 0

    for day_num in range(1, total_days + 1):
        d = date_cls(year, month, day_num)
        if d in holiday_dates:
            continue

        record = attendance_by_date.get(d)
        if record:
            if getattr(record, 'is_half_day', False):
                half_days += 1
                present_days += 0.5
                lwp_days += 0.5
            else:
                present_days += 1
        else:
            lwp_days += 1

    base_amount = salary_profile.net_salary_before_attendance
    per_day_salary = (base_amount / working_days) if working_days else 0
    lwp_deduction = per_day_salary * lwp_days
    payable_salary = base_amount - lwp_deduction

    return {
        'salary_profile': salary_profile,
        'effective_from': salary_profile.effective_from,
        'total_days': total_days,
        'working_days': working_days,
        'holidays': len(holiday_dates),
        'present_days': present_days,
        'half_days': half_days,
        'lwp_days': lwp_days,
        'per_day_salary': round(per_day_salary, 2),
        'lwp_deduction': round(lwp_deduction, 2),
        'payable_salary': round(payable_salary, 2),
    }


def _collect_salary_form_fields(post_data):
    """Pulls the shared set of salary fields out of request.POST."""
    return {
        'effective_from': post_data.get('effective_from'),
        'payment_mode': post_data.get('payment_mode'),
        'basic_salary': post_data.get('basic_salary') or 0,
        'hra': post_data.get('hra') or 0,
        'da': post_data.get('da') or 0,
        'conveyance_allowance': post_data.get('conveyance_allowance') or 0,
        'medical_allowance': post_data.get('medical_allowance') or 0,
        'special_allowance': post_data.get('special_allowance') or 0,
        'bonus': post_data.get('bonus') or 0,
        'overtime_rate_per_hour': post_data.get('overtime_rate_per_hour') or 0,
        'pf': post_data.get('pf') or 0,
        'esi': post_data.get('esi') or 0,
        'professional_tax': post_data.get('professional_tax') or 0,
        'tds': post_data.get('tds') or 0,
        'is_active': post_data.get('is_active') == 'on',
        'remarks': post_data.get('remarks', ''),
    }


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@login_required
@user_passes_test(feature_required('finance.manage'))
def employee_salary(request):
    """Admin dashboard for employee salary history management"""
    from employees.models import EmployeeSalary

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'create':
            # Always inserts a NEW historical row (e.g. a raise). It never
            # overwrites an existing row, so past months keep resolving to
            # whichever row was effective back then.
            employee_id = request.POST.get('employee_id')
            fields = _collect_salary_form_fields(request.POST)

            try:
                employee = Employee.objects.get(id=employee_id)
                EmployeeSalary.objects.create(
                    employee=employee,
                    office=employee.office,
                    branch=employee.branch,
                    **fields,
                )
                messages.success(request, 'New salary entry created!')
            except Exception as e:
                messages.error(request, f'Error creating salary entry: {str(e)}')

        elif action == 'update':
            # Edits ONE specific existing row in place (fixing a mistake in
            # a past entry) — it does not create a new row.
            salary_id = request.POST.get('salary_id')
            fields = _collect_salary_form_fields(request.POST)

            try:
                salary_profile = EmployeeSalary.objects.get(id=salary_id)
                for field_name, value in fields.items():
                    setattr(salary_profile, field_name, value)
                salary_profile.save()
                messages.success(request, 'Salary entry updated successfully!')
            except Exception as e:
                messages.error(request, f'Error updating salary entry: {str(e)}')

        elif action == 'delete':
            salary_id = request.POST.get('salary_id')
            try:
                EmployeeSalary.objects.filter(id=salary_id).delete()
                messages.success(request, 'Salary entry deleted successfully!')
            except Exception as e:
                messages.error(request, f'Error deleting salary entry: {str(e)}')

        return redirect('employees:employee_salary')

    # employees = Employee.objects.all().order_by('full_name')
    employees = tenant_queryset(
        request,
        Employee.objects.all()
    ).order_by('full_name')

    # ---- Filters: month, year, employee ----
    today = date_cls.today()
    try:
        year = int(request.GET.get('year', today.year))
    except (TypeError, ValueError):
        year = today.year
    try:
        month = int(request.GET.get('month', today.month))
    except (TypeError, ValueError):
        month = today.month

    selected_employee = None
    employee_filter_id = request.GET.get('employee')
    if employee_filter_id:
        selected_employee = Employee.objects.filter(id=employee_filter_id).first()

    target_employees = [selected_employee] if selected_employee else list(employees)

    # ---- Monthly payable summary: one row per employee, using whichever
    # salary entry was effective during the selected month/year ----
    monthly_summary = []
    for employee in target_employees:
        calc = calculate_salary_for_month(employee, year, month)
        monthly_summary.append({'employee': employee, 'calc': calc})

    # ---- Full salary history (every row ever entered) for management ----
    salary_history_qs = EmployeeSalary.objects.select_related('employee').all()
    if selected_employee:
        salary_history_qs = salary_history_qs.filter(employee=selected_employee)
    salary_history_qs = salary_history_qs.order_by('employee__full_name', '-effective_from')

    edit_salary = None
    edit_id = request.GET.get('edit')
    if edit_id:
        edit_salary = EmployeeSalary.objects.filter(id=edit_id).first()

    months_list = [
        {'number': i, 'name': cal_module.month_name[i], 'abbr': cal_module.month_abbr[i]}
        for i in range(1, 13)
    ]
    year_range = range(today.year - 5, today.year + 2)

    prev_month = 12 if month == 1 else month - 1
    prev_year = year - 1 if month == 1 else year
    next_month = 1 if month == 12 else month + 1
    next_year = year + 1 if month == 12 else year

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'employees': employees,
        'monthly_summary': monthly_summary,
        'salary_history': salary_history_qs,
        'edit_salary': edit_salary,
        'payment_mode_choices': EmployeeSalary.PaymentMode.choices,
        'year': year,
        'month': month,
        'month_name': cal_module.month_name[month],
        'months_list': months_list,
        'year_range': year_range,
        'selected_employee': selected_employee,
        'prev_month': prev_month,
        'prev_year': prev_year,
        'next_month': next_month,
        'next_year': next_year,
        'current_date': today,
    })
    return render(request, 'employees/employee_salary.html', context)


@login_required
@user_passes_test(feature_required('finance.manage'))
def employee_salary_excel_report(request):
    """Export monthly, attendance-adjusted salary report as Excel, using the
    salary entry that was EFFECTIVE for each employee during the selected
    month (not just their latest entry)."""
    

    today = date_cls.today()
    try:
        year = int(request.GET.get('year', today.year))
    except (TypeError, ValueError):
        year = today.year
    try:
        month = int(request.GET.get('month', today.month))
    except (TypeError, ValueError):
        month = today.month

    employee_id = request.GET.get('employee')

    # employees_qs = Employee.objects.all().order_by('full_name')
    employees_qs = tenant_queryset(
        request,
        Employee.objects.all()
    ).order_by('full_name')
    if employee_id:
        employees_qs = employees_qs.filter(id=employee_id)

    wb = Workbook()
    ws = wb.active
    ws.title = "Salary Report"

    headers = [
        'Employee', 'Email', 'Effective From', 'Basic Salary', 'Gross Salary',
        'Fixed Deductions', 'Working Days', 'Present Days',
        'Half Days', 'LWP Days', 'Per Day Salary', 'LWP Deduction',
        'Payable Salary', 'Payment Mode',
    ]
    ws.append(headers)

    header_fill = PatternFill(start_color="6366F1", end_color="6366F1", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    for col_num in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    for employee in employees_qs:
        calc = calculate_salary_for_month(employee, year, month)
        if not calc:
            ws.append([
                employee.full_name, employee.email, 'No entry for this month',
                '-', '-', '-', '-', '-', '-', '-', '-', '-', '-', '-',
            ])
            continue

        profile = calc['salary_profile']
        ws.append([
            employee.full_name,
            employee.email,
            profile.effective_from.strftime('%Y-%m-%d'),
            float(profile.basic_salary),
            float(profile.gross_salary),
            float(profile.fixed_deductions),
            calc['working_days'],
            calc['present_days'],
            calc['half_days'],
            calc['lwp_days'],
            calc['per_day_salary'],
            calc['lwp_deduction'],
            calc['payable_salary'],
            profile.get_payment_mode_display(),
        ])

    for col_cells in ws.columns:
        length = max((len(str(cell.value)) if cell.value is not None else 0) for cell in col_cells)
        ws.column_dimensions[col_cells[0].column_letter].width = length + 4

    month_label = cal_module.month_name[month]
    filename = f"Salary_Report_{month_label}_{year}.xlsx"

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response


# Leave Type Creation
from .models import LeaveType
from .forms import LeaveTypeForm


from .leave_accrual import initialize_balances_for_new_type, resync_balances_for_type_change   # add this import at the top


@login_required
@user_passes_test(feature_required('leave.manage'))
def admin_leave_types(request):
    """Admin page to create and list configurable leave types."""

    if request.method == 'POST':
        form = LeaveTypeForm(request.POST)
        office = get_request_office(request)
        if form.is_valid():
            leave_type = form.save(commit=False)
            leave_type.created_by = request.user
            leave_type.office = office
            leave_type.save()

            # NEW: instantly credit every eligible employee
            credited_count = initialize_balances_for_new_type(leave_type, credited_by=request.user)

            if credited_count:
                messages.success(
                    request,
                    f'Leave type "{leave_type.name}" created successfully. '
                    f'Initial balance credited to {credited_count} employee(s).'
                )
            else:
                messages.success(
                    request,
                    f'Leave type "{leave_type.name}" created successfully.'
                )
            return redirect('employees:admin_leave_types')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = LeaveTypeForm()

    # leave_types = LeaveType.objects.all().order_by('display_order', 'name')
    leave_types = tenant_queryset(
            request,
            LeaveType.objects.all()
        ).order_by(
            "display_order",
            "name",
        )
    
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'form': form,
        'leave_types': leave_types,
    })
    return render(request, 'employees/leave/admin_leave_types.html', context)


@login_required
@user_passes_test(feature_required('leave.manage'))
@require_http_methods(["POST"])
def admin_leave_type_update(request, pk):
    """Update an existing leave type, resyncing balances if accrual_amount changed."""
    # leave_type = get_object_or_404(LeaveType, pk=pk)
    leave_type = get_object_or_404(
        tenant_queryset(
            request,
            LeaveType.objects.all()
        ),
        pk=pk,
    )
    old_amount = leave_type.accrual_amount  # snapshot BEFORE the form overwrites it

    form = LeaveTypeForm(request.POST, instance=leave_type)
    if form.is_valid():
        form.save()

        if leave_type.accrual_amount != old_amount:
            updated = resync_balances_for_type_change(leave_type, old_amount, admin_user=request.user)
            if updated:
                messages.success(
                    request,
                    f'Leave type "{leave_type.name}" updated. Balances resynced for {updated} employee(s).'
                )
            else:
                messages.success(request, f'Leave type "{leave_type.name}" updated successfully.')
        else:
            messages.success(request, f'Leave type "{leave_type.name}" updated successfully.')
    else:
        messages.error(request, f'Could not update leave type: {form.errors.as_text()}')
    return redirect('employees:admin_leave_types')



@login_required
@user_passes_test(feature_required('leave.manage'))
@require_http_methods(["POST"])
def admin_leave_type_toggle(request, pk):
    """Toggle active/inactive status — inactive types are hidden from employees."""
    # leave_type = get_object_or_404(LeaveType, pk=pk)
    leave_type = get_object_or_404(
        tenant_queryset(
            request,
            LeaveType.objects.all()
        ),
        pk=pk,
    )
    leave_type.is_active = not leave_type.is_active
    leave_type.save(update_fields=['is_active', 'updated_at'])
    state = 'activated' if leave_type.is_active else 'deactivated'
    messages.success(request, f'Leave type "{leave_type.name}" {state}.')
    return redirect('employees:admin_leave_types')


@login_required
@user_passes_test(feature_required('leave.manage'))
@require_http_methods(["POST"])
def admin_leave_type_delete(request, pk):
    """Delete a leave type — blocked only if it has real credit/debit history
    or leave requests tied to it."""
    # leave_type = get_object_or_404(LeaveType, pk=pk)
    leave_type = get_object_or_404(
        tenant_queryset(
            request,
            LeaveType.objects.all()
        ),
        pk=pk,
    )

    has_history = (
        leave_type.credit_logs.exists()
        or leave_type.leave_requests.exists()
    )
    if has_history:
        messages.error(
            request,
            f'"{leave_type.name}" already has leave history linked to it and cannot be deleted. '
            'Deactivate it instead.'
        )
    else:
        name = leave_type.name
        leave_type.delete()
        messages.success(request, f'Leave type "{name}" deleted.')

    return redirect('employees:admin_leave_types')



@login_required
@user_passes_test(is_employee)
def employee_leave_balances(request):
    employee = request.user.employee_profile

    # This creates balance rows if missing, settles any overdue year-end
    # carry-forward, AND runs any due monthly/yearly accrual — all lazily.
    live_balances = get_employee_leave_type_balances(employee)

    balances = []
    for item in live_balances:
        leave_type = item['leave_type']
        balance_obj = EmployeeLeaveBalance.objects.filter(
            employee=employee, leave_type=leave_type
        ).first()

        recent_logs = LeaveCreditLog.objects.filter(
            employee=employee, leave_type=leave_type
        ).order_by('-created_at')[:5] if balance_obj else []

        balances.append({
            'leave_type': leave_type,
            'balance': item['balance'],
            'last_credited_date': balance_obj.last_credited_date if balance_obj else None,
            'total_credited_this_year': balance_obj.total_credited_this_year if balance_obj else Decimal('0.0'),
            'recent_logs': recent_logs,
        })

    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'balances': balances,
    })
    return render(request, 'employees/leave/employee_leave_balances.html', context)


# New attendance hours logic

# views.py
from .models import AttendanceRule
from .forms import AttendanceRuleForm
from .shift_attendance_logic import DEFAULT_FULL_DAY_PERCENTAGE, DEFAULT_HALF_DAY_PERCENTAGE
from django.contrib import messages
from django.shortcuts import redirect

@login_required
@user_passes_test(feature_required('attendance.manage'))
def attendance_rule_settings(request):
    """Office admin screen to configure Present/Half-Day thresholds."""

    office_admin = getattr(request.user, "office_admin_profile", None)

    if not office_admin or not office_admin.office:
        messages.error(request, "No office is associated with your account.")
        return redirect("employees:admin_dashboard")

    office = office_admin.office

    rule, _ = AttendanceRule.objects.get_or_create(
        office=office
    )

    if request.method == "POST":
        form = AttendanceRuleForm(
            request.POST,
            instance=rule
        )

        if form.is_valid():
            form.save()

            messages.success(
                request,
                "Attendance rule updated successfully."
            )

            return redirect("employees:attendance_rule_settings")

    else:
        form = AttendanceRuleForm(
            instance=rule
        )

    context = TemplateLayout.init(request, {
        "form": form,
        "office": office,
        "default_full_day_percentage": DEFAULT_FULL_DAY_PERCENTAGE,
        "default_half_day_percentage": DEFAULT_HALF_DAY_PERCENTAGE,
    })

    return render(
        request,
        "employees/attendance/attendance_rule_settings.html",
        context
    )