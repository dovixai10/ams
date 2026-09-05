from django.contrib import admin

from .models import (
    EmployeeSkill,
    EmployeeWorkStatus,
    PermissionDefinition,
    ResourceAllocation,
    Role,
    RoleFieldAccess,
    RoleModuleAccess,
    RolePermission,
    Skill,
    UserGroup,
    UserGroupMember,
    UserRoleAssignment,
)

admin.site.register(PermissionDefinition)
admin.site.register(Role)
admin.site.register(RoleModuleAccess)
admin.site.register(RolePermission)
admin.site.register(RoleFieldAccess)
admin.site.register(UserRoleAssignment)
admin.site.register(Skill)
admin.site.register(EmployeeSkill)
admin.site.register(UserGroup)
admin.site.register(UserGroupMember)
admin.site.register(ResourceAllocation)
admin.site.register(EmployeeWorkStatus)
