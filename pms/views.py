from collections import defaultdict
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from employees.models import Employee, LeaveRequest
from employees.permissions import get_request_office, office_admin_required
from web_project import TemplateLayout
from web_project.template_helpers.theme import TemplateHelper

from django.views.decorators.http import require_POST

from .forms import (
    AllocationForm,
    EmployeeSkillForm,
    RoleForm,
    SkillForm,
    UserGroupForm,
    UserRoleAssignForm,
    WorkStatusForm,
)
from .models import (
    EmployeeSkill,
    EmployeeWorkStatus,
    PermissionDefinition,
    ResourceAllocation,
    Role,
    RoleModuleAccess,
    RolePermission,
    Skill,
    UserGroup,
    UserGroupMember,
    UserRoleAssignment,
)
from .permission_catalog import MODULE_KEYS, PMS_MODULES
from .services import (
    assign_role_to_user,
    clone_role,
    has_permission,
    office_queryset,
    office_users,
    revoke_role_from_user,
)


CARD_PERMISSIONS = {
    'pms:role_list': 'people_access.roles.view',
    'pms:permission_catalog': 'people_access.permissions.view',
    'pms:module_permissions': 'people_access.module_permissions.manage',
    'pms:user_list': 'people_access.users.view',
    'pms:skill_list': 'people_access.skills.view',
    'pms:group_list': 'people_access.groups.view',
    'pms:user_availability': 'people_access.availability.view',
    'pms:user_status': 'people_access.status.view',
}


def _accessible_cards(request, cards):
    user = request.user
    if user.is_superuser:
        return cards
    has_pms_roles = UserRoleAssignment.objects.filter(user=user).exists()
    if not has_pms_roles and office_admin_required(user):
        return cards
    return [
        card for card in cards
        if has_permission(user, CARD_PERMISSIONS.get(card['url_name'], ''))
        or card['url_name'] not in CARD_PERMISSIONS
    ]


def _layout(request, extra=None):
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'hide_mobile_nav': True,
    })
    if extra:
        context.update(extra)
    return context


PEOPLE_ACCESS_CARDS = [
    {'title': 'Roles', 'description': 'Create, edit, clone and assign named roles', 'icon': 'bx-shield-quarter', 'url_name': 'pms:role_list', 'gradient': 'linear-gradient(135deg, #6366f1, #8b5cf6)'},
    {'title': 'Permissions', 'description': 'Read-only catalog of every permission key', 'icon': 'bx-list-check', 'url_name': 'pms:permission_catalog', 'gradient': 'linear-gradient(135deg, #0ea5e9, #38bdf8)'},
    {'title': 'Module permissions', 'description': 'Roles × modules access matrix', 'icon': 'bx-grid-alt', 'url_name': 'pms:module_permissions', 'gradient': 'linear-gradient(135deg, #14b8a6, #2dd4bf)'},
    {'title': 'Users', 'description': 'System user accounts and role assignment', 'icon': 'bx-user-circle', 'url_name': 'pms:user_list', 'gradient': 'linear-gradient(135deg, #f97316, #fb923c)'},
    {'title': 'Skills', 'description': 'Skill matrix with proficiency levels', 'icon': 'bx-brain', 'url_name': 'pms:skill_list', 'gradient': 'linear-gradient(135deg, #ec4899, #f472b6)'},
    {'title': 'User groups', 'description': 'Security and distribution groups', 'icon': 'bx-group', 'url_name': 'pms:group_list', 'gradient': 'linear-gradient(135deg, #84cc16, #a3e635)'},
    {'title': 'User availability', 'description': 'Weekly capacity and allocation grid', 'icon': 'bx-calendar-week', 'url_name': 'pms:user_availability', 'gradient': 'linear-gradient(135deg, #06b6d4, #22d3ee)'},
    {'title': 'User status', 'description': 'Active, bench, on leave and inactive board', 'icon': 'bx-user-check', 'url_name': 'pms:user_status', 'gradient': 'linear-gradient(135deg, #64748b, #94a3b8)'},
]

PMS_SECTIONS = [
    {
        'key': 'people_access',
        'title': 'People & Access',
        'description': 'Roles, permissions, users, skills and workforce status',
        'icon': 'bx-shield',
        'url_name': 'pms:people_access_hub',
        'live_count': 8,
        'gradient': 'linear-gradient(135deg, #6366f1, #a855f7)',
    },
    {
        'key': 'projects',
        'title': 'Project Management',
        'description': 'Projects, plan, timeline and team (Phase 2)',
        'icon': 'bx-folder',
        'url_name': None,
        'live_count': 0,
        'gradient': 'linear-gradient(135deg, #0ea5e9, #38bdf8)',
        'coming_soon': True,
    },
    {
        'key': 'work_schedule',
        'title': 'Work & Schedule',
        'description': 'Tasks, schedule and workload (Phase 2)',
        'icon': 'bx-task',
        'url_name': None,
        'live_count': 0,
        'gradient': 'linear-gradient(135deg, #f97316, #fb923c)',
        'coming_soon': True,
    },
]


@login_required
@user_passes_test(office_admin_required)
def pms_hub(request):
    sections = []
    for section in PMS_SECTIONS:
        entry = dict(section)
        if section['key'] == 'people_access':
            entry['live_count'] = len(_accessible_cards(request, PEOPLE_ACCESS_CARDS))
        sections.append(entry)
    ctx = _layout(request, {
        'sections': sections,
        'page_title': 'Project Management System',
    })
    return render(request, 'pms/hub.html', ctx)


@login_required
@user_passes_test(office_admin_required)
def people_access_hub(request):
    cards = _accessible_cards(request, PEOPLE_ACCESS_CARDS)
    ctx = _layout(request, {
        'cards': cards,
        'page_title': 'People & Access',
        'breadcrumb': [('PMS', reverse('pms:hub')), ('People & Access', None)],
    })
    return render(request, 'pms/people_access_hub.html', ctx)


# ---- Roles ----

@login_required
@user_passes_test(office_admin_required)
def role_list(request):
    roles = office_queryset(request, Role.objects.annotate(
        user_count=Count('user_assignments'),
    )).order_by('name')
    ctx = _layout(request, {'roles': roles, 'page_title': 'Roles'})
    return render(request, 'pms/roles/list.html', ctx)


@login_required
@user_passes_test(office_admin_required)
def role_create(request):
    office = get_request_office(request)
    if request.method == 'POST':
        form = RoleForm(request.POST)
        if form.is_valid():
            role = form.save(commit=False)
            role.office = office
            role.save()
            from .services import _seed_role_defaults
            _seed_role_defaults(role)
            messages.success(request, f'Role "{role.name}" created.')
            return redirect('pms:role_detail', pk=role.pk)
    else:
        form = RoleForm()
    ctx = _layout(request, {'form': form, 'page_title': 'Create role'})
    return render(request, 'pms/roles/form.html', ctx)


@login_required
@user_passes_test(office_admin_required)
def role_detail(request, pk):
    role = get_object_or_404(office_queryset(request, Role.objects.all()), pk=pk)
    permissions = RolePermission.objects.filter(role=role, granted=True).select_related('permission')
    module_access = {ma.module: ma.access_level for ma in role.module_access.all()}
    module_rows = [
        {'module': m, 'level': module_access.get(m['key'], 'none')}
        for m in PMS_MODULES
    ]
    assignments = role.user_assignments.select_related('user').order_by('-assigned_at')
    if request.method == 'POST':
        action = request.POST.get('action')
        perm_id = request.POST.get('permission_id')
        if action == 'toggle_permission' and perm_id:
            rp = get_object_or_404(RolePermission, role=role, permission_id=perm_id)
            rp.granted = not rp.granted
            rp.save()
            messages.success(request, 'Permission updated.')
            return redirect('pms:role_detail', pk=pk)
    ctx = _layout(request, {
        'role': role,
        'permissions': permissions,
        'module_access': module_access,
        'module_rows': module_rows,
        'assignments': assignments,
        'modules': PMS_MODULES,
        'all_permissions': PermissionDefinition.objects.order_by('module', 'key'),
        'page_title': role.name,
    })
    return render(request, 'pms/roles/detail.html', ctx)


@login_required
@user_passes_test(office_admin_required)
def role_edit(request, pk):
    role = get_object_or_404(office_queryset(request, Role.objects.all()), pk=pk)
    if role.is_system and not request.user.is_superuser:
        messages.error(request, 'System roles can only be edited by platform admins.')
        return redirect('pms:role_detail', pk=pk)
    if request.method == 'POST':
        form = RoleForm(request.POST, instance=role)
        if form.is_valid():
            form.save()
            messages.success(request, 'Role updated.')
            return redirect('pms:role_detail', pk=pk)
    else:
        form = RoleForm(instance=role)
    ctx = _layout(request, {'form': form, 'role': role, 'page_title': f'Edit {role.name}'})
    return render(request, 'pms/roles/form.html', ctx)


@login_required
@user_passes_test(office_admin_required)
@require_POST
def role_delete(request, pk):
    role = get_object_or_404(office_queryset(request, Role.objects.all()), pk=pk)
    if role.is_system:
        messages.error(request, 'System roles cannot be deleted.')
        return redirect('pms:role_list')
    name = role.name
    role.delete()
    messages.success(request, f'Role "{name}" deleted.')
    return redirect('pms:role_list')


@login_required
@user_passes_test(office_admin_required)
@require_POST
def role_clone(request, pk):
    role = get_object_or_404(office_queryset(request, Role.objects.all()), pk=pk)
    new_name = request.POST.get('name', f'{role.name} (copy)').strip()
    new_role = clone_role(role, new_name, office=role.office)
    messages.success(request, f'Role cloned as "{new_role.name}".')
    return redirect('pms:role_detail', pk=new_role.pk)


# ---- Permission catalog ----

@login_required
@user_passes_test(office_admin_required)
def permission_catalog(request):
    q = request.GET.get('q', '').strip()
    permissions = PermissionDefinition.objects.all().order_by('module', 'key')
    if q:
        permissions = permissions.filter(
            Q(key__icontains=q) | Q(name__icontains=q) | Q(module__icontains=q)
        )
    grouped = defaultdict(list)
    for perm in permissions:
        perm.role_count = RolePermission.objects.filter(
            permission=perm, granted=True,
            role__in=office_queryset(request, Role.objects.all()),
        ).count()
        grouped[perm.module].append(perm)
    ctx = _layout(request, {
        'grouped': dict(grouped),
        'query': q,
        'modules': PMS_MODULES,
        'page_title': 'Permission catalog',
    })
    return render(request, 'pms/permissions/catalog.html', ctx)


@login_required
@user_passes_test(office_admin_required)
def permission_roles_api(request, permission_id):
    perm = get_object_or_404(PermissionDefinition, pk=permission_id)
    roles = Role.objects.filter(
        permissions__permission=perm,
        permissions__granted=True,
        id__in=office_queryset(request, Role.objects.all()).values('id'),
    ).distinct()
    data = [{'id': r.id, 'name': r.name, 'url': reverse('pms:role_detail', args=[r.id])} for r in roles]
    return JsonResponse({'roles': data})


# ---- Module permissions matrix ----

@login_required
@user_passes_test(office_admin_required)
def module_permissions(request):
    roles = list(office_queryset(request, Role.objects.all()).order_by('name'))
    copy_from_id = request.GET.get('copy_from')
    if request.method == 'POST':
        role_id = request.POST.get('role_id')
        role = get_object_or_404(office_queryset(request, Role.objects.all()), pk=role_id)
        for module in MODULE_KEYS:
            level = request.POST.get(f'module_{module}', 'none')
            RoleModuleAccess.objects.update_or_create(
                role=role,
                module=module,
                defaults={'access_level': level},
            )
        messages.success(request, f'Module access saved for "{role.name}".')
        return redirect('pms:module_permissions')

    selected_role = roles[0] if roles else None
    role_id = request.GET.get('role') or (str(selected_role.pk) if selected_role else None)
    if role_id:
        selected_role = get_object_or_404(office_queryset(request, Role.objects.all()), pk=role_id)

    matrix = {}
    module_rows = []
    if selected_role:
        for ma in selected_role.module_access.all():
            matrix[ma.module] = ma.access_level
        module_rows = [
            {
                'module': m,
                'level': matrix.get(m['key'], 'none'),
            }
            for m in PMS_MODULES
        ]

    ctx = _layout(request, {
        'roles': roles,
        'selected_role': selected_role,
        'modules': PMS_MODULES,
        'module_rows': module_rows,
        'matrix': matrix,
        'access_levels': RoleModuleAccess.AccessLevel.choices,
        'page_title': 'Module permissions',
    })
    return render(request, 'pms/permissions/module_matrix.html', ctx)


# ---- Users ----

@login_required
@user_passes_test(office_admin_required)
def user_list(request):
    office = get_request_office(request)
    users = office_users(office) if office else User.objects.none()
    assignments = UserRoleAssignment.objects.filter(
        user__in=users,
        role__in=office_queryset(request, Role.objects.all()),
    ).select_related('role', 'user')
    user_roles = defaultdict(list)
    for a in assignments:
        user_roles[a.user_id].append(a.role)

    if request.method == 'POST':
        form = UserRoleAssignForm(request.POST, user_qs=users, role_qs=office_queryset(request, Role.objects.all()))
        if form.is_valid():
            assign_role_to_user(
                form.cleaned_data['user'],
                form.cleaned_data['role'],
                assigned_by=request.user,
            )
            messages.success(request, 'Role assigned.')
            return redirect('pms:user_list')
    else:
        form = UserRoleAssignForm(user_qs=users, role_qs=office_queryset(request, Role.objects.all()))

    rows = []
    for user in users:
        emp = getattr(user, 'employee_profile', None)
        rows.append({
            'user': user,
            'employee': emp,
            'roles': user_roles.get(user.id, []),
            'last_login': user.last_login,
            'is_active': user.is_active,
        })

    ctx = _layout(request, {'rows': rows, 'form': form, 'page_title': 'Users'})
    return render(request, 'pms/users/list.html', ctx)


@login_required
@user_passes_test(office_admin_required)
@require_POST
def user_revoke_role(request):
    user_id = request.POST.get('user_id')
    role_id = request.POST.get('role_id')
    user = get_object_or_404(User, pk=user_id)
    role = get_object_or_404(office_queryset(request, Role.objects.all()), pk=role_id)
    revoke_role_from_user(user, role)
    messages.success(request, 'Role unassigned.')
    return redirect('pms:user_list')


@login_required
@user_passes_test(office_admin_required)
@require_POST
def user_toggle_active(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    user.is_active = not user.is_active
    user.save(update_fields=['is_active'])
    state = 'reactivated' if user.is_active else 'suspended'
    messages.success(request, f'User {state}.')
    return redirect('pms:user_list')


# ---- Skills ----

@login_required
@user_passes_test(office_admin_required)
def skill_list(request):
    office = get_request_office(request)
    skills = Skill.objects.filter(office=office).annotate(
        people_count=Count('employee_skills'),
    ).order_by('category', 'name') if office else Skill.objects.none()

    if request.method == 'POST' and request.POST.get('form_type') == 'skill':
        form = SkillForm(request.POST)
        if form.is_valid():
            skill = form.save(commit=False)
            skill.office = office
            skill.save()
            messages.success(request, 'Skill created.')
            return redirect('pms:skill_list')
    else:
        form = SkillForm()

    assign_form = EmployeeSkillForm()
    if office:
        assign_form.fields['employee'].queryset = Employee.objects.filter(office=office)
        assign_form.fields['skill'].queryset = skills

    q = request.GET.get('q', '').strip()
    search_results = []
    if q and office:
        search_results = EmployeeSkill.objects.filter(
            skill__office=office,
            skill__name__icontains=q,
        ).select_related('employee', 'skill')[:50]

    ctx = _layout(request, {
        'skills': skills,
        'form': form,
        'assign_form': assign_form,
        'search_query': q,
        'search_results': search_results,
        'page_title': 'Skills',
    })
    return render(request, 'pms/skills/list.html', ctx)


@login_required
@user_passes_test(office_admin_required)
@require_POST
def skill_assign(request):
    office = get_request_office(request)
    form = EmployeeSkillForm(request.POST)
    form.fields['employee'].queryset = Employee.objects.filter(office=office)
    form.fields['skill'].queryset = Skill.objects.filter(office=office)
    if form.is_valid():
        form.save()
        messages.success(request, 'Skill assigned to employee.')
    else:
        messages.error(request, 'Could not assign skill.')
    return redirect('pms:skill_list')


# ---- User groups ----

@login_required
@user_passes_test(office_admin_required)
def group_list(request):
    office = get_request_office(request)
    groups = UserGroup.objects.filter(office=office).annotate(
        member_count=Count('members'),
    ).order_by('name') if office else UserGroup.objects.none()
    ctx = _layout(request, {'groups': groups, 'page_title': 'User groups'})
    return render(request, 'pms/groups/list.html', ctx)


@login_required
@user_passes_test(office_admin_required)
def group_create(request):
    office = get_request_office(request)
    users = office_users(office)
    if request.method == 'POST':
        form = UserGroupForm(request.POST, user_qs=users)
        if form.is_valid():
            group = form.save(commit=False)
            group.office = office
            group.save()
            for uid in form.cleaned_data.get('member_ids', []):
                UserGroupMember.objects.get_or_create(group=group, user=uid)
            messages.success(request, 'Group created.')
            return redirect('pms:group_list')
    else:
        form = UserGroupForm(user_qs=users)
    ctx = _layout(request, {'form': form, 'page_title': 'Create group'})
    return render(request, 'pms/groups/form.html', ctx)


@login_required
@user_passes_test(office_admin_required)
def group_edit(request, pk):
    office = get_request_office(request)
    group = get_object_or_404(UserGroup, pk=pk, office=office)
    users = office_users(office)
    if request.method == 'POST':
        form = UserGroupForm(request.POST, instance=group, user_qs=users)
        if form.is_valid():
            form.save()
            group.members.exclude(user__in=form.cleaned_data.get('member_ids', [])).delete()
            for uid in form.cleaned_data.get('member_ids', []):
                UserGroupMember.objects.get_or_create(group=group, user=uid)
            messages.success(request, 'Group updated.')
            return redirect('pms:group_list')
    else:
        form = UserGroupForm(instance=group, user_qs=users)
    ctx = _layout(request, {'form': form, 'group': group, 'page_title': f'Edit {group.name}'})
    return render(request, 'pms/groups/form.html', ctx)


@login_required
@user_passes_test(office_admin_required)
@require_POST
def group_delete(request, pk):
    office = get_request_office(request)
    group = get_object_or_404(UserGroup, pk=pk, office=office)
    group.delete()
    messages.success(request, 'Group deleted.')
    return redirect('pms:group_list')


# ---- User availability ----

@login_required
@user_passes_test(office_admin_required)
def user_availability(request):
    office = get_request_office(request)
    employees = Employee.objects.filter(office=office, user__is_active=True).select_related('user') if office else Employee.objects.none()
    today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())

    rows = []
    for emp in employees:
        allocs = ResourceAllocation.objects.filter(
            employee=emp,
            start_date__lte=today,
        ).filter(Q(end_date__isnull=True) | Q(end_date__gte=today))
        allocated = allocs.aggregate(total=Sum('allocation_percent'))['total'] or 0
        on_leave = LeaveRequest.objects.filter(
            employee=emp,
            status=LeaveRequest.Status.APPROVED,
            start_date__lte=today,
            end_date__gte=today,
        ).exists()
        free = max(0, 100 - int(allocated))
        if on_leave:
            free = 0
        rows.append({
            'employee': emp,
            'allocated': int(allocated),
            'free': free,
            'on_leave': on_leave,
            'over_allocated': allocated > 100,
            'allocations': allocs,
        })

    if request.method == 'POST':
        form = AllocationForm(request.POST, employee_qs=employees)
        if form.is_valid():
            alloc = form.save(commit=False)
            alloc.office = office
            alloc.save()
            messages.success(request, 'Allocation saved.')
            return redirect('pms:user_availability')
    else:
        form = AllocationForm(employee_qs=employees)

    ctx = _layout(request, {
        'rows': rows,
        'form': form,
        'week_start': week_start,
        'page_title': 'User availability',
    })
    return render(request, 'pms/availability/dashboard.html', ctx)


# ---- User status ----

@login_required
@user_passes_test(office_admin_required)
def user_status(request):
    office = get_request_office(request)
    employees = Employee.objects.filter(office=office).select_related('user', 'work_status') if office else Employee.objects.none()

    columns = {choice[0]: [] for choice in EmployeeWorkStatus.Status.choices}
    for emp in employees:
        ws = getattr(emp, 'work_status', None)
        status = ws.status if ws else EmployeeWorkStatus.Status.ACTIVE
        columns[status].append(emp)

    if request.method == 'POST':
        emp_id = request.POST.get('employee_id')
        employee = get_object_or_404(Employee, pk=emp_id, office=office)
        form = WorkStatusForm(request.POST)
        if form.is_valid():
            ws, _ = EmployeeWorkStatus.objects.get_or_create(employee=employee)
            ws.status = form.cleaned_data['status']
            ws.reason = form.cleaned_data['reason']
            ws.effective_date = form.cleaned_data['effective_date']
            ws.changed_by = request.user
            ws.save()
            if ws.status == EmployeeWorkStatus.Status.INACTIVE:
                employee.user.is_active = False
                employee.user.save(update_fields=['is_active'])
            elif ws.status == EmployeeWorkStatus.Status.ACTIVE and not employee.user.is_active:
                employee.user.is_active = True
                employee.user.save(update_fields=['is_active'])
            messages.success(request, f'Status updated for {employee.full_name}.')
            return redirect('pms:user_status')

    form = WorkStatusForm()
    status_columns = [
        {
            'value': value,
            'label': label,
            'count': len(columns.get(value, [])),
            'employees': columns.get(value, []),
        }
        for value, label in EmployeeWorkStatus.Status.choices
    ]
    ctx = _layout(request, {
        'status_columns': status_columns,
        'employees': employees,
        'form': form,
        'page_title': 'User status',
    })
    return render(request, 'pms/status/board.html', ctx)
