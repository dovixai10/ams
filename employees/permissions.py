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


def get_request_office(request):
    """Returns the Office to scope queries to, or None for the platform admin
    browsing without picking a specific office (support/debug context)."""
    return getattr(request, 'office', None)