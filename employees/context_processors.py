# employees/context_processors.py
from django.utils import timezone

from .models import Attendance
from .permissions import (
    get_profile_url_name,
    get_request_office,
    get_user_display_role,
    is_office_admin,
    is_office_owner,
    is_platform_admin,
)



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

    if user and user.is_authenticated:
        if hasattr(user, 'office_admin_profile'):
            office = user.office_admin_profile.office
        elif hasattr(user, 'employee_profile'):
            office = user.employee_profile.office  # confirm this field name
        else:
            office = get_request_office(request)

    return {
        'current_office': office,
        'is_office_admin': is_office_admin(user) if user else False,
        'is_office_owner': is_office_owner(user) if user else False,
        'is_platform_admin': is_platform_admin(user) if user else False,
        'site_name': office.name if office else 'Dovix CRM',
        'site_logo_url': office.logo.url if office and office.logo else None,
        'site_url': office.website if office else 'Dovix.ai',
        'user_display_role': get_user_display_role(user) if user and user.is_authenticated else None,
        'profile_url_name': get_profile_url_name(user) if user and user.is_authenticated else 'employees:login',
    }
