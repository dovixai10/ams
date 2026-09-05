from django.conf import settings
from django.db import models
from django.utils import timezone

from employees.models import Employee, Office


class PermissionDefinition(models.Model):
    """Read-only catalog entry; seeded from permission_catalog.py."""

    key = models.CharField(max_length=120, unique=True)
    module = models.CharField(max_length=50, db_index=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['module', 'key']

    def __str__(self):
        return self.key


class Role(models.Model):
    office = models.ForeignKey(
        Office,
        on_delete=models.CASCADE,
        related_name='pms_roles',
        null=True,
        blank=True,
        db_index=True,
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_system = models.BooleanField(default=False)
    cloned_from = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='clones',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['office', 'name'],
                name='unique_pms_role_name_per_office',
            ),
        ]

    def __str__(self):
        return self.name


class RoleModuleAccess(models.Model):
    class AccessLevel(models.TextChoices):
        NONE = 'none', 'No access'
        VIEW = 'view', 'View'
        FULL = 'full', 'Full'

    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='module_access')
    module = models.CharField(max_length=50)
    access_level = models.CharField(
        max_length=10,
        choices=AccessLevel.choices,
        default=AccessLevel.NONE,
    )

    class Meta:
        unique_together = [('role', 'module')]

    def __str__(self):
        return f'{self.role.name} / {self.module}: {self.access_level}'


class RolePermission(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='permissions')
    permission = models.ForeignKey(
        PermissionDefinition,
        on_delete=models.CASCADE,
        related_name='role_grants',
    )
    granted = models.BooleanField(default=True)

    class Meta:
        unique_together = [('role', 'permission')]


class RoleFieldAccess(models.Model):
    class FieldAccess(models.TextChoices):
        HIDDEN = 'hidden', 'Hidden'
        READ = 'read', 'Read'
        READ_WRITE = 'read_write', 'Read & write'
        MASKED = 'masked', 'Masked'

    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='field_access')
    module = models.CharField(max_length=50)
    field_key = models.CharField(max_length=100)
    access_level = models.CharField(
        max_length=20,
        choices=FieldAccess.choices,
        default=FieldAccess.HIDDEN,
    )

    class Meta:
        unique_together = [('role', 'module', 'field_key')]


class UserRoleAssignment(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='pms_role_assignments',
    )
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='user_assignments')
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pms_roles_assigned',
    )

    class Meta:
        unique_together = [('user', 'role')]


class Skill(models.Model):
    office = models.ForeignKey(
        Office,
        on_delete=models.CASCADE,
        related_name='skills',
        db_index=True,
    )
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['category', 'name']
        constraints = [
            models.UniqueConstraint(fields=['office', 'name'], name='unique_skill_per_office'),
        ]

    def __str__(self):
        return self.name

    @property
    def people_count(self):
        return self.employee_skills.count()


class EmployeeSkill(models.Model):
    class Proficiency(models.TextChoices):
        BEGINNER = 'beginner', 'Beginner'
        INTERMEDIATE = 'intermediate', 'Intermediate'
        ADVANCED = 'advanced', 'Advanced'
        EXPERT = 'expert', 'Expert'

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='employee_skills',
    )
    skill = models.ForeignKey(
        Skill,
        on_delete=models.CASCADE,
        related_name='employee_skills',
    )
    proficiency = models.CharField(
        max_length=20,
        choices=Proficiency.choices,
        default=Proficiency.INTERMEDIATE,
    )
    years_experience = models.DecimalField(max_digits=4, decimal_places=1, default=0)
    last_used = models.DateField(null=True, blank=True)
    certification = models.CharField(max_length=200, blank=True)
    cert_expires = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('employee', 'skill')]


class UserGroup(models.Model):
    class GroupType(models.TextChoices):
        SECURITY = 'security', 'Security'
        DISTRIBUTION = 'distribution', 'Distribution'

    office = models.ForeignKey(
        Office,
        on_delete=models.CASCADE,
        related_name='user_groups',
        db_index=True,
    )
    name = models.CharField(max_length=120)
    group_type = models.CharField(
        max_length=20,
        choices=GroupType.choices,
        default=GroupType.SECURITY,
    )
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['office', 'name'], name='unique_user_group_per_office'),
        ]

    def __str__(self):
        return self.name

    @property
    def member_count(self):
        return self.members.count()


class UserGroupMember(models.Model):
    group = models.ForeignKey(UserGroup, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='pms_group_memberships',
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('group', 'user')]


class ResourceAllocation(models.Model):
    """Shared allocation record for capacity planning (Phase 1 stub)."""

    office = models.ForeignKey(Office, on_delete=models.CASCADE, related_name='resource_allocations')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='resource_allocations')
    label = models.CharField(max_length=200, help_text='Project or work label')
    allocation_percent = models.PositiveSmallIntegerField(default=0)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-start_date']


class EmployeeWorkStatus(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        BENCH = 'bench', 'Bench'
        ON_LEAVE = 'on_leave', 'On leave'
        INACTIVE = 'inactive', 'Inactive'

    employee = models.OneToOneField(
        Employee,
        on_delete=models.CASCADE,
        related_name='work_status',
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    reason = models.CharField(max_length=255, blank=True)
    effective_date = models.DateField(default=timezone.now)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='work_status_changes',
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.employee.full_name}: {self.get_status_display()}'
