from django.db.models import Q

from employees.models import Employee, Office
from employees.permissions import get_request_office, is_platform_admin

from .models import (
    PermissionDefinition,
    Role,
    RoleFieldAccess,
    RoleModuleAccess,
    RolePermission,
    UserRoleAssignment,
)


def office_queryset(request, queryset):
    if is_platform_admin(request.user):
        return queryset
    office = get_request_office(request)
    if office is None:
        return queryset.none()
    return queryset.filter(office=office)


def get_user_office(user):
    if not user or not user.is_authenticated:
        return None
    if hasattr(user, 'office_admin_profile'):
        return user.office_admin_profile.office
    if hasattr(user, 'employee_profile') and user.employee_profile.office_id:
        return user.employee_profile.office
    return None


def get_user_role_ids(user):
    if not user or not user.is_authenticated:
        return []
    if user.is_superuser:
        return list(Role.objects.values_list('id', flat=True))
    return list(
        UserRoleAssignment.objects.filter(user=user).values_list('role_id', flat=True)
    )


def get_effective_roles(user):
    if user.is_superuser:
        return Role.objects.all()
    role_ids = get_user_role_ids(user)
    return Role.objects.filter(id__in=role_ids)


def has_permission(user, permission_key):
    if user.is_superuser:
        return True
    role_ids = get_user_role_ids(user)
    if not role_ids:
        return False
    return RolePermission.objects.filter(
        role_id__in=role_ids,
        permission__key=permission_key,
        granted=True,
    ).exists()


def get_module_access(user, module_key):
    if user.is_superuser:
        return RoleModuleAccess.AccessLevel.FULL
    role_ids = get_user_role_ids(user)
    if not role_ids:
        return RoleModuleAccess.AccessLevel.NONE
    levels = RoleModuleAccess.objects.filter(
        role_id__in=role_ids,
        module=module_key,
    ).values_list('access_level', flat=True)
    if 'full' in levels:
        return RoleModuleAccess.AccessLevel.FULL
    if 'view' in levels:
        return RoleModuleAccess.AccessLevel.VIEW
    return RoleModuleAccess.AccessLevel.NONE


def get_field_access(user, module_key, field_key):
    if user.is_superuser:
        return RoleFieldAccess.FieldAccess.READ_WRITE
    role_ids = get_user_role_ids(user)
    if not role_ids:
        return RoleFieldAccess.FieldAccess.HIDDEN
    levels = list(
        RoleFieldAccess.objects.filter(
            role_id__in=role_ids,
            module=module_key,
            field_key=field_key,
        ).values_list('access_level', flat=True)
    )
    priority = ['read_write', 'read', 'masked', 'hidden']
    for level in priority:
        if level in levels:
            return level
    return RoleFieldAccess.FieldAccess.HIDDEN


def assign_role_to_user(user, role, assigned_by=None):
    assignment, _ = UserRoleAssignment.objects.get_or_create(
        user=user,
        role=role,
        defaults={'assigned_by': assigned_by},
    )
    if user.is_active is False and role.name.lower() != 'inactive':
        pass
    return assignment


def revoke_role_from_user(user, role):
    UserRoleAssignment.objects.filter(user=user, role=role).delete()


def clone_role(role, new_name, office=None):
    target_office = office or role.office
    new_role = Role.objects.create(
        office=target_office,
        name=new_name,
        description=role.description,
        cloned_from=role,
    )
    for ma in role.module_access.all():
        RoleModuleAccess.objects.create(
            role=new_role,
            module=ma.module,
            access_level=ma.access_level,
        )
    for rp in role.permissions.all():
        RolePermission.objects.create(
            role=new_role,
            permission=rp.permission,
            granted=rp.granted,
        )
    for fa in role.field_access.all():
        RoleFieldAccess.objects.create(
            role=new_role,
            module=fa.module,
            field_key=fa.field_key,
            access_level=fa.access_level,
        )
    return new_role


def ensure_default_roles(office):
    """Create baseline roles for a new office if missing."""
    defaults = [
        ('Office Admin', 'Full access to HRMS and PMS for this office', True),
        ('Project Manager', 'Manage projects and teams', False),
        ('Team Member', 'Standard employee access', False),
    ]
    for name, desc, is_system in defaults:
        role, created = Role.objects.get_or_create(
            office=office,
            name=name,
            defaults={'description': desc, 'is_system': is_system},
        )
        if created:
            _seed_role_defaults(role)


def _seed_role_defaults(role):
    from .permission_catalog import MODULE_KEYS, PERMISSION_DEFINITIONS, SENSITIVE_FIELD_DEFAULTS

    for module in MODULE_KEYS:
        level = RoleModuleAccess.AccessLevel.FULL if role.is_system else RoleModuleAccess.AccessLevel.NONE
        if role.name == 'Project Manager' and module in ('projects', 'work_schedule', 'people_access'):
            level = RoleModuleAccess.AccessLevel.FULL
        elif role.name == 'Team Member' and module in ('projects', 'work_schedule'):
            level = RoleModuleAccess.AccessLevel.VIEW
        RoleModuleAccess.objects.get_or_create(
            role=role,
            module=module,
            defaults={'access_level': level},
        )

    for key, module, _, _ in PERMISSION_DEFINITIONS:
        perm = PermissionDefinition.objects.filter(key=key).first()
        if not perm:
            continue
        granted = role.is_system
        if role.name == 'Project Manager' and key.startswith(('projects.', 'work_schedule.', 'people_access.')):
            granted = True
        elif role.name == 'Team Member' and key.endswith('.view'):
            granted = True
        RolePermission.objects.get_or_create(
            role=role,
            permission=perm,
            defaults={'granted': granted},
        )

    for module, field_key, _ in SENSITIVE_FIELD_DEFAULTS:
        level = RoleFieldAccess.FieldAccess.HIDDEN
        if role.is_system:
            level = RoleFieldAccess.FieldAccess.READ_WRITE
        RoleFieldAccess.objects.get_or_create(
            role=role,
            module=module,
            field_key=field_key,
            defaults={'access_level': level},
        )


def office_users(office):
    """Users belonging to an office via employee or office admin profile."""
    employee_user_ids = Employee.objects.filter(office=office).values_list('user_id', flat=True)
    from employees.models import OfficeAdmin
    admin_user_ids = OfficeAdmin.objects.filter(office=office).values_list('user_id', flat=True)
    from django.contrib.auth.models import User
    return User.objects.filter(
        Q(id__in=employee_user_ids) | Q(id__in=admin_user_ids)
    ).distinct().order_by('username')
