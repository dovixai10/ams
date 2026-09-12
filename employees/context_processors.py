# employees/context_processors.py
from django.utils import timezone

from .models import Attendance
from .permissions import get_request_office, is_office_admin



def mobile_nav(request):
    """Provide mobile navbar context for authenticated employees."""
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return {}

    employee = getattr(user, "employee_profile", None)
    if employee is None:
        return {}

    today = timezone.localdate()

    today_attendance = Attendance.objects.filter(
        employee=employee,
        date=today,
    ).order_by("-check_in_time").select_related("employee").first()

    return {
        "requires_face_registration": not employee.has_registered_face,
        "has_checked_in_today": bool(today_attendance),
        "today_attendance": today_attendance,
    }


def office_branding(request):
    office = None
    user = getattr(request, 'user', None)
    admin_is_office_admin = is_office_admin(user) if user else False

    if user and user.is_authenticated:
        if hasattr(user, 'office_admin_profile'):
            office = user.office_admin_profile.office
        elif hasattr(user, 'employee_profile'):
            office = user.employee_profile.office  # confirm this field name
        else:
            office = get_request_office(request)

    # Branch-switcher data - only meaningful for an office admin (an
    # employee is fixed to their own branch, nothing to switch between).
    active_branch = None
    available_branches = None
    if admin_is_office_admin and office is not None:
        from .permissions import get_request_branch
        active_branch = get_request_branch(request)
        available_branches = office.branches.filter(is_active=True).order_by('-is_head_office', 'name')

    # Delegated permissions (dynamic roles) - only meaningful for a plain
    # employee. An office admin already sees everything, so this stays empty
    # for them (the sidebar just checks is_office_admin first).
    employee_permissions = set()
    if user and user.is_authenticated and hasattr(user, 'employee_profile') and not admin_is_office_admin:
        from .permissions import employee_permission_keys
        employee_permissions = employee_permission_keys(user.employee_profile)

    return {
        'current_office': office,
        'is_office_admin': admin_is_office_admin,
        'site_name': office.name if office else 'Dovix CRM',
        'site_logo_url': office.logo.url if office and office.logo else None,
        'site_url': office.website if office else 'Dovix.ai',
        'active_branch': active_branch,
        'available_branches': available_branches,
        'employee_permissions': employee_permissions,
        'has_any_permission': bool(employee_permissions),
    }
