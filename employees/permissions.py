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


# ---------------------------------------------------------------------------
# Dynamic roles & permissions
# ---------------------------------------------------------------------------
# One source of truth for every delegable feature. Adding a new grantable
# feature later is just adding a tuple here - no migration needed, since
# Role.permissions is a plain JSON list of these keys.
#
# (key, human label, group shown in the role-editor / sidebar)
FEATURE_PERMISSIONS = [
    ('employees.manage', 'Manage Employees', 'Employees'),
    ('attendance.manage', 'Manage Attendance', 'Attendance'),
    ('leave.manage', 'Manage Leave (types & approvals)', 'Attendance'),
    ('tasks.manage', 'Manage Projects, Tasks & Face Update Requests', 'Tasks & Workflows'),
    ('tickets.manage', 'Manage Support Tickets', 'Support'),
    ('finance.manage', 'Manage Finance (salary, loans, reimbursements, payslips)', 'Finance'),
    ('holidays.manage', 'Manage Holidays Calendar', 'Company Settings'),
    ('rules.manage', 'Manage Rules & Regulations', 'Company Settings'),
    ('branches.manage', 'Manage Branches', 'Company Settings'),
    ('shifts.manage', 'Manage Shifts & Shift Assignment', 'Shift Management'),
    ('roles.manage', 'Manage Roles & Permissions', 'Company Settings'),
]

FEATURE_PERMISSION_KEYS = {key for key, _, _ in FEATURE_PERMISSIONS}


def employee_has_permission(employee, perm_key):
    """True if this employee holds an active role granting perm_key AND
    that role's branch matches the employee's own branch. A role only ever
    counts for employees in the branch it was created for - if an employee
    is later transferred to a different branch, or a role somehow ends up
    assigned across branches, it stops granting anything until it's a
    branch match again."""
    if employee is None:
        return False
    for role in employee.roles.filter(is_active=True):
        if role.branch_id is not None and role.branch_id != employee.branch_id:
            continue
        if perm_key in (role.permissions or []):
            return True
    return False


def employee_permission_keys(employee):
    """Every permission key this employee's active, same-branch roles
    grant, as a set (see employee_has_permission for the branch rule)."""
    if employee is None:
        return set()
    keys = set()
    for role in employee.roles.filter(is_active=True):
        if role.branch_id is not None and role.branch_id != employee.branch_id:
            continue
        keys.update(role.permissions or [])
    return keys


def has_permission(user, perm_key):
    """True if user is a full admin (platform/office) OR an employee
    holding a role that grants perm_key. Use via feature_required(key)
    for @user_passes_test, or call directly for finer checks."""
    if office_admin_required(user):
        return True
    if is_employee(user):
        return employee_has_permission(user.employee_profile, perm_key)
    return False


def feature_required(perm_key):
    """Returns a user_passes_test-compatible check function: full admins
    always pass; an employee passes only if one of their roles grants
    perm_key. Use exactly like office_admin_required:

        @user_passes_test(feature_required('attendance.manage'))
    """
    def check(user):
        return has_permission(user, perm_key)
    return check


def get_request_office(request):
    """Returns the Office to scope queries to, or None for the platform admin
    browsing without picking a specific office (support/debug context)."""
    return getattr(request, 'office', None)


def get_request_branch(request):
    """Returns the Branch to scope queries to.

    - Employee: always their own fixed branch.
    - Office admin: whichever branch is 'active' in their session (set via
      the branch switcher); OfficeMiddleware resolves and validates this
      into request.branch on every request, defaulting to the office's
      head-office branch if nothing/invalid is in session.
    - Platform admin browsing without picking an office: None (sees
      everything, same as get_request_office).
    """
    return getattr(request, 'branch', None)


def tenant_queryset(request, queryset):
    """Scope a queryset to the current office AND active branch.

    Platform admin: sees everything (no office/branch filter).
    Office admin: scoped to their office; within it, rows are included if
        they belong to the active branch OR have no branch at all.
        branch=NULL means "office-wide" (e.g. a LeaveType/CompanyRule/Shift
        definition that applies to every branch, or simply a model whose
        write path doesn't set branch yet) - it is never used to mean
        "belongs to no branch and should be hidden".
    Employee: scoped to their office and (their own fixed branch OR
        office-wide rows), same rule.
    Anyone else (no office): gets no tenant data at all.
    """
    if is_platform_admin(request.user):
        return queryset

    office = get_request_office(request)
    if office is None:
        return queryset.none()

    queryset = queryset.filter(office=office)

    branch = get_request_branch(request)
    if branch is not None:
        from django.db.models import Q
        queryset = queryset.filter(Q(branch=branch) | Q(branch__isnull=True))

    return queryset


def tenant_object_or_404(request, model, **lookup):
    """Fetch an object only if it belongs to the current office/branch.

    Platform admin can access every office/branch.
    """
    from django.shortcuts import get_object_or_404

    queryset = tenant_queryset(request, model.objects.all())
    return get_object_or_404(queryset, **lookup)