"""Single source of truth for PMS permission keys and module definitions."""

PMS_MODULES = [
    {'key': 'people_access', 'name': 'People & Access', 'hub_section': 'people_access'},
    {'key': 'projects', 'name': 'Projects', 'hub_section': 'projects'},
    {'key': 'work_schedule', 'name': 'Work & Schedule', 'hub_section': 'work_schedule'},
    {'key': 'resources_time', 'name': 'Resources & Time', 'hub_section': 'resources_time'},
    {'key': 'commercial', 'name': 'Commercial', 'hub_section': 'commercial'},
    {'key': 'delivery_quality', 'name': 'Delivery & Quality', 'hub_section': 'delivery_quality'},
    {'key': 'platform_ai', 'name': 'Platform & AI', 'hub_section': 'platform_ai'},
]

MODULE_KEYS = [m['key'] for m in PMS_MODULES]

# Permission catalog: key, module, name, description
PERMISSION_DEFINITIONS = [
    # People & Access
    ('people_access.roles.view', 'people_access', 'View roles', 'View role definitions and assignments'),
    ('people_access.roles.manage', 'people_access', 'Manage roles', 'Create, edit, clone and delete roles'),
    ('people_access.permissions.view', 'people_access', 'View permission catalog', 'Browse the permission catalog'),
    ('people_access.module_permissions.manage', 'people_access', 'Manage module permissions', 'Edit module access matrix'),
    ('people_access.users.view', 'people_access', 'View users', 'View system user accounts'),
    ('people_access.users.manage', 'people_access', 'Manage users', 'Invite, suspend and assign roles to users'),
    ('people_access.skills.view', 'people_access', 'View skills', 'View skill matrix'),
    ('people_access.skills.manage', 'people_access', 'Manage skills', 'Create skills and assign employees'),
    ('people_access.groups.view', 'people_access', 'View user groups', 'View security and distribution groups'),
    ('people_access.groups.manage', 'people_access', 'Manage user groups', 'Create and edit user groups'),
    ('people_access.availability.view', 'people_access', 'View availability', 'View capacity and allocation dashboard'),
    ('people_access.status.view', 'people_access', 'View user status', 'View workforce status board'),
    ('people_access.status.manage', 'people_access', 'Manage user status', 'Change employee work status'),
    # Projects (Phase 2 placeholders)
    ('projects.list.view', 'projects', 'View projects', 'View project list and details'),
    ('projects.list.manage', 'projects', 'Manage projects', 'Create and edit projects'),
    # Work & Schedule placeholders
    ('work_schedule.tasks.view', 'work_schedule', 'View tasks', 'View tasks workspace'),
    ('work_schedule.tasks.manage', 'work_schedule', 'Manage tasks', 'Create and edit tasks'),
]

SENSITIVE_FIELD_DEFAULTS = [
    ('employee', 'ctc', 'CTC / salary'),
    ('employee', 'bank_account', 'Bank account'),
    ('employee', 'pan', 'PAN'),
    ('employee', 'aadhar', 'Aadhaar'),
]

PROFICIENCY_CHOICES = [
    ('beginner', 'Beginner'),
    ('intermediate', 'Intermediate'),
    ('advanced', 'Advanced'),
    ('expert', 'Expert'),
]

GROUP_TYPE_CHOICES = [
    ('security', 'Security'),
    ('distribution', 'Distribution'),
]

WORK_STATUS_CHOICES = [
    ('active', 'Active'),
    ('bench', 'Bench'),
    ('on_leave', 'On leave'),
    ('inactive', 'Inactive'),
]

ACCESS_LEVELS = [
    ('none', 'No access'),
    ('view', 'View'),
    ('full', 'Full'),
]

FIELD_ACCESS_LEVELS = [
    ('hidden', 'Hidden'),
    ('read', 'Read'),
    ('read_write', 'Read & write'),
    ('masked', 'Masked'),
]
