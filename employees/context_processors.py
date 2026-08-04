from django.utils import timezone

from .models import Attendance


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
