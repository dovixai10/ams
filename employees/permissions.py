"""Single source of truth for role checks across the whole app.
Import these everywhere instead of redefining is_superadmin/is_admin locally."""


def is_platform_admin(user):
    """The real Django superuser — you. Approves offices, sees everything for support."""
    return user.is_authenticated and user.is_superuser


def is_office_admin(user):
    """HR/admin for one specific, approved office."""
    return (
        user.is_authenticated
        and hasattr(user, 'office_admin_profile')
        and user.office_admin_profile.office.status == 'approved'
    )


def office_admin_required(user):
    """Grants access to HR-facing views: platform admin OR an approved office's HR admin."""
    return is_platform_admin(user) or is_office_admin(user)


def is_employee(user):
    return user.is_authenticated and hasattr(user, 'employee_profile')


def is_office_owner(user):
    """The user who registered the office and owns the subscription."""
    return (
        user.is_authenticated
        and hasattr(user, 'office_admin_profile')
        and user.office_admin_profile.is_owner
        and user.office_admin_profile.office.status == 'approved'
    )


def get_user_display_role(user):
    """Return the user's primary assigned PMS role name, or None."""
    if not user or not user.is_authenticated:
        return None
    if user.is_superuser:
        return 'Platform Admin'
    try:
        from pms.models import UserRoleAssignment
        assignment = (
            UserRoleAssignment.objects.filter(user=user)
            .select_related('role')
            .order_by('-assigned_at')
            .first()
        )
        if assignment:
            return assignment.role.name
    except Exception:
        pass
    if is_office_owner(user):
        return 'Office Admin'
    if is_office_admin(user):
        return 'HR Admin'
    if is_employee(user):
        return None
    return None


def get_profile_url_name(user):
    """Template-safe profile route name for the current user."""
    if not user or not user.is_authenticated:
        return 'employees:login'
    if office_admin_required(user):
        return 'employees:superadmin_profile'
    if is_employee(user):
        return 'employees:employee_profile'
    return 'employees:login'


def get_request_office(request):
    """Returns the Office to scope queries to, or None for the platform admin
    browsing without picking a specific office (support/debug context)."""
    return getattr(request, 'office', None)