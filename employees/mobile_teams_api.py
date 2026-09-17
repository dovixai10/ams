"""
Mobile API - Teams & Team Task Board (beyond the original spec - added to
mirror the web app's Team Task Board: teams you're on, a team's board
grouped by sprint/status, quick-add, the one flexible "update anything"
endpoint, and comments/attachments on a task).

This is a thin JSON wrapper around the exact same model operations the web
views already use (employees/views.py: admin_teams, team_board,
team_board_move_task, team_board_add_task, team_board_add_comment,
team_board_add_task_attachment) - same merge rules, same activity-note
generation, same attachment validation - just handed to the app as JSON
instead of rendered HTML.

GET /teams, GET /teams/{id}/board, POST /teams/{id}/board/tasks,
GET /teams/tasks/{id}, PATCH /teams/tasks/{id},
POST /teams/tasks/{id}/comments, POST /teams/tasks/{id}/attachments
"""
from django.db.models import Count, Prefetch
from rest_framework import serializers
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample, OpenApiParameter, OpenApiTypes

from .mobile_response import MobileAPIView, MobileAPIException, EnvelopeResponseSerializer
from .mobile_tasks_api import _task_id, _project_id, _serialize_project_brief, _parse_project_id
from .models import Team, Sprint, Task, TaskUpdate, TaskAttachment, Project
from .permissions import is_team_member, can_manage_team
from .sprint_utils import ensure_upcoming_sprints, current_sprint
from .attachment_utils import validate_task_attachment_upload as _validate_task_attachment_upload

TAG = 'Teams'

# Same fixed palette the web board uses for a project's tag color - kept in
# sync so a task looks the same color whichever client shows it. See
# employees/views.py:PROJECT_TAG_COLORS.
PROJECT_TAG_COLORS = [
    '#4338ca', '#047857', '#c2410c', '#a21caf', '#1d4ed8', '#b91c1c', '#0f766e', '#a16207',
]


def _project_color(project_id):
    if not project_id:
        return None
    return PROJECT_TAG_COLORS[project_id % len(PROJECT_TAG_COLORS)]


class TeamQuickAddRequestSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=150)
    type = serializers.ChoiceField(choices=Task.Type.values, required=False, help_text="Defaults to TASK")
    severity = serializers.ChoiceField(choices=Task.Severity.values, required=False, help_text="Only meaningful when type=BUG; defaults to MEDIUM")
    assignedTo = serializers.IntegerField(required=False, help_text="An employee id from this team's members - omit to leave unassigned")
    project = serializers.CharField(required=False, allow_blank=True, help_text="A project id, e.g. 'prj_00003'")
    sprint = serializers.IntegerField(required=False, help_text="A sprint id from GET /teams/{id}/board - omit for Backlog")


class TeamTaskUpdateRequestSerializer(serializers.Serializer):
    """Every field is optional - only the ones present in the request are
    changed, exactly like the web board's side panel Save button. Sending
    assignedTo/sprint/project as an empty string explicitly clears them
    (unassigns / moves to Backlog / removes the project)."""
    title = serializers.CharField(max_length=150, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=Task.Status.values, required=False)
    type = serializers.ChoiceField(choices=Task.Type.values, required=False)
    severity = serializers.ChoiceField(choices=Task.Severity.values, required=False)
    assignedTo = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    sprint = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    project = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class TeamCommentRequestSerializer(serializers.Serializer):
    comment = serializers.CharField(required=False, allow_blank=True)
    attachment = serializers.FileField(required=False, help_text="Image (JPG/PNG/GIF/WEBP, max 8MB) or short video (MP4/WEBM/MOV, max 30MB)")


class TeamAttachmentOnlyRequestSerializer(serializers.Serializer):
    attachment = serializers.FileField(help_text="Image (JPG/PNG/GIF/WEBP, max 8MB) or short video (MP4/WEBM/MOV, max 30MB)")


def _serialize_member(employee):
    return {"id": employee.id, "name": employee.full_name or employee.name}


def _serialize_sprint(sprint, selected_key):
    return {
        "id": sprint.id, "name": sprint.name,
        "startDate": sprint.start_date.isoformat(), "endDate": sprint.end_date.isoformat(),
        "isCurrent": sprint.is_current, "isSelected": str(sprint.id) == selected_key,
    }


def _serialize_team(team, employee, user):
    return {
        "id": team.id, "name": team.name, "description": team.description or None,
        "manager": team.manager.full_name if team.manager_id else None,
        "memberCount": team.member_count_annotated if hasattr(team, 'member_count_annotated') else team.members.count(),
        "taskCount": team.task_count_annotated if hasattr(team, 'task_count_annotated') else team.tasks.count(),
        "canManage": can_manage_team(user, team),
    }


def _serialize_activity(update):
    return {
        "author": update.updated_by.get_full_name() or update.updated_by.username if update.updated_by else 'Unknown',
        "comment": update.comment or None,
        "previousStatus": update.previous_status.upper() if update.previous_status else None,
        "newStatus": update.new_status.upper(),
        "createdAt": update.created_at.isoformat(),
        "attachments": [{"url": a.file.url, "kind": a.kind.upper()} for a in update.attachments.all()],
    }


def _serialize_board_task(task):
    return {
        "id": _task_id(task),
        "title": task.title,
        "description": task.description or None,
        "status": task.status.upper(),
        "type": task.type.upper(),
        "severity": task.severity.upper() if task.severity else None,
        "priority": task.priority.upper(),
        "assignedTo": (
            {"id": task.assigned_to_id, "name": task.assigned_to.full_name or task.assigned_to.name}
            if task.assigned_to_id else None
        ),
        "project": _serialize_project_brief(task.project) if task.project_id else None,
        "projectColor": _project_color(task.project_id),
        "sprintId": task.sprint_id,
        "dueDate": task.due_date.isoformat() if task.due_date else None,
        "commentCount": sum(1 for u in task.updates.all() if u.comment),
        "createdAt": task.created_at.isoformat(),
    }


def _serialize_task_detail(task):
    data = _serialize_board_task(task)
    data["attachments"] = [
        {"url": a.file.url, "kind": a.kind.upper()}
        for a in task.attachments.filter(update__isnull=True)
    ]
    data["activity"] = [
        _serialize_activity(u) for u in task.updates.select_related('updated_by').prefetch_related('attachments').order_by('created_at')
    ]
    return data


def _get_task_for_team_member(request, pk):
    """Every task-level endpoint below shares this: the task must exist,
    be on a team, and the caller must be a member of that team (any
    member - not just the manager - can view/edit/comment, same rule as
    the web board)."""
    task = Task.objects.filter(pk=pk).select_related('team', 'assigned_to', 'assigned_by', 'project').first()
    if task is None or not task.team_id or not is_team_member(request.user, task.team):
        raise MobileAPIException('NOT_FOUND', 'Task not found.', 404)
    return task


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="My teams",
    description="Every team you're a member of. Open a team's board with GET /teams/{id}/board.",
    examples=[OpenApiExample('200 response', value={
        "teams": [
            {"id": 3, "name": "Backend", "description": "API + infra", "manager": "Akshay",
             "memberCount": 4, "taskCount": 12, "canManage": False},
        ],
    }, response_only=True)],
)
class MyTeamsView(MobileAPIView):
    """GET /teams"""

    def get(self, request):
        employee = request.user.employee_profile
        teams = list(
            employee.teams.select_related('manager')
            .annotate(member_count_annotated=Count('members', distinct=True), task_count_annotated=Count('tasks', distinct=True))
            .order_by('name')
        )
        return self.ok({"teams": [_serialize_team(t, employee, request.user) for t in teams]})


@extend_schema(
    responses={200: EnvelopeResponseSerializer, 403: EnvelopeResponseSerializer, 404: EnvelopeResponseSerializer},
    tags=[TAG], summary="Team board", parameters=[
        OpenApiParameter('id', OpenApiTypes.INT, location=OpenApiParameter.PATH),
        OpenApiParameter('sprint', OpenApiTypes.STR, description='A sprint id, or "backlog" - defaults to whichever sprint covers today, or backlog if none is configured'),
        OpenApiParameter('project', OpenApiTypes.STR, description="Filter to one project id, e.g. 'prj_00003'"),
    ],
    description=(
        "One fetch for the whole board screen: sprint tabs, member list (for the "
        "assignee filter), projects (for the project filter/quick-add), insight "
        "counts, and every task in the selected sprint/project - group these "
        "into your own To Do/In Progress/Blocked/Done columns and "
        "assignee filter client-side, same as the web board does server-side."
    ),
    examples=[OpenApiExample('200 response', value={
        "team": {"id": 3, "name": "Backend", "description": "API + infra", "canManage": False},
        "members": [{"id": 14, "name": "Kamal"}, {"id": 13, "name": "Akshay"}],
        "sprints": [
            {"id": 4, "name": "Sprint 1", "startDate": "2026-09-13", "endDate": "2026-09-26", "isCurrent": True, "isSelected": True},
            {"id": 5, "name": "Sprint 2", "startDate": "2026-09-27", "endDate": "2026-10-10", "isCurrent": False, "isSelected": False},
        ],
        "selectedSprint": "4",
        "projects": [{"id": "prj_00004", "code": "PRJ00004", "name": "Finance Automation"}],
        "insights": {"total": 5, "pending": 2, "inProgress": 2, "blocked": 0, "completed": 1},
        "tasks": [
            {"id": "tsk_00016", "title": "Fix login bug", "description": "Repro on Safari", "status": "PENDING",
             "type": "BUG", "severity": "HIGH", "priority": "MEDIUM",
             "assignedTo": {"id": 14, "name": "Kamal"}, "project": None, "projectColor": None,
             "sprintId": 4, "dueDate": None, "commentCount": 1, "createdAt": "2026-09-16T08:37:41+05:30"},
        ],
    }, response_only=True)],
)
class TeamBoardView(MobileAPIView):
    """GET /teams/{id}/board"""

    def get(self, request, id):
        team = Team.objects.select_related('manager', 'branch', 'office').filter(pk=id).first()
        if team is None:
            raise MobileAPIException('NOT_FOUND', 'Team not found.', 404)
        if not is_team_member(request.user, team):
            raise MobileAPIException('FORBIDDEN', "You're not on this team.", 403)

        sprints = []
        if team.branch is not None:
            ensure_upcoming_sprints(team.branch)
            sprints = list(Sprint.objects.filter(branch=team.branch).order_by('number'))

        sprint_param = request.GET.get('sprint')
        selected_sprint = None
        if sprint_param and sprint_param != 'backlog':
            selected_sprint = next((s for s in sprints if str(s.id) == sprint_param), None)
        elif not sprint_param and team.branch is not None:
            selected_sprint = current_sprint(team.branch)
        selected_key = str(selected_sprint.id) if selected_sprint else 'backlog'

        task_qs = Task.objects.filter(team=team)
        task_qs = task_qs.filter(sprint=selected_sprint) if selected_sprint else task_qs.filter(sprint__isnull=True)

        project_filter = _parse_project_id(request.GET.get('project'))
        if project_filter:
            task_qs = task_qs.filter(project_id=project_filter)

        tasks = list(
            task_qs.select_related('assigned_to', 'project')
            .prefetch_related('updates')
            .order_by('-priority', '-created_at')
        )

        members = list(team.members.select_related('user').order_by('full_name'))
        projects = list(Project.objects.filter(tasks__team=team).distinct().order_by('name'))
        insights = {
            'total': len(tasks),
            'pending': sum(1 for t in tasks if t.status == Task.Status.PENDING),
            'inProgress': sum(1 for t in tasks if t.status == Task.Status.IN_PROGRESS),
            'blocked': sum(1 for t in tasks if t.status == Task.Status.BLOCKED),
            'completed': sum(1 for t in tasks if t.status == Task.Status.COMPLETED),
        }

        return self.ok({
            "team": {"id": team.id, "name": team.name, "description": team.description or None, "canManage": can_manage_team(request.user, team)},
            "members": [_serialize_member(m) for m in members],
            "sprints": [_serialize_sprint(s, selected_key) for s in sprints],
            "selectedSprint": selected_key,
            "projects": [_serialize_project_brief(p) for p in projects],
            "insights": insights,
            "tasks": [_serialize_board_task(t) for t in tasks],
        })


@extend_schema(
    responses={201: EnvelopeResponseSerializer, 400: EnvelopeResponseSerializer, 403: EnvelopeResponseSerializer, 404: EnvelopeResponseSerializer},
    tags=[TAG], summary="Quick-add a task/bug to the board", parameters=[OpenApiParameter('id', OpenApiTypes.INT, location=OpenApiParameter.PATH)],
    description="Left unassigned unless you set assignedTo - it's a shared team backlog item, not automatically handed to anyone.",
    request=TeamQuickAddRequestSerializer,
    examples=[
        OpenApiExample('Request', value={"title": "Fix login bug", "type": "BUG", "severity": "HIGH", "assignedTo": 14, "sprint": 4}, request_only=True),
        OpenApiExample('201 response', value={"id": "tsk_00021"}, response_only=True, status_codes=['201']),
        OpenApiExample('400 bad assignee', value={
            "success": False, "data": None, "message": "That person is not on this team.",
            "error": {"code": "VALIDATION_ERROR", "field": "assignedTo", "details": None},
        }, response_only=True, status_codes=['400']),
    ],
)
class TeamBoardAddTaskView(MobileAPIView):
    """POST /teams/{id}/board/tasks"""

    def post(self, request, id):
        team = Team.objects.filter(pk=id).first()
        if team is None:
            raise MobileAPIException('NOT_FOUND', 'Team not found.', 404)
        if not is_team_member(request.user, team):
            raise MobileAPIException('FORBIDDEN', "You're not on this team.", 403)

        title = (request.data.get('title') or '').strip()
        if not title:
            raise MobileAPIException('VALIDATION_ERROR', 'title is required.', 400, field='title')

        assigned_to = None
        assigned_to_id = request.data.get('assignedTo')
        if assigned_to_id:
            assigned_to = team.members.filter(pk=assigned_to_id).first()
            if assigned_to is None:
                raise MobileAPIException('VALIDATION_ERROR', 'That person is not on this team.', 400, field='assignedTo')

        item_type = (request.data.get('type') or Task.Type.TASK).lower()
        if item_type not in Task.Type.values:
            raise MobileAPIException('VALIDATION_ERROR', 'Invalid type.', 400, field='type')

        severity = (request.data.get('severity') or Task.Severity.MEDIUM).lower()
        if severity not in Task.Severity.values:
            raise MobileAPIException('VALIDATION_ERROR', 'Invalid severity.', 400, field='severity')

        sprint = None
        sprint_id = request.data.get('sprint')
        if sprint_id:
            sprint = Sprint.objects.filter(pk=sprint_id, branch=team.branch).first()
            if sprint is None:
                raise MobileAPIException('VALIDATION_ERROR', 'Unknown sprint.', 400, field='sprint')

        project = None
        project_ref = request.data.get('project')
        if project_ref:
            project_pk = _parse_project_id(project_ref)
            project = Project.objects.filter(pk=project_pk).first() if project_pk else None
            if project is None:
                raise MobileAPIException('VALIDATION_ERROR', f'Unknown project "{project_ref}".', 400, field='project')

        task = Task.objects.create(
            office=team.office, branch=team.branch, team=team, sprint=sprint, project=project,
            title=title, assigned_to=assigned_to, assigned_by=request.user,
            status=Task.Status.PENDING, type=item_type, severity=severity,
        )
        TaskUpdate.objects.create(
            office=task.office, branch=task.branch, task=task, updated_by=request.user,
            previous_status=None, new_status=task.status,
            comment=f'{task.get_type_display()} added to the team board.',
        )
        if assigned_to is not None and assigned_to.id != request.user.employee_profile.id:
            from .notification_utils import create_task_notification
            create_task_notification(assigned_to, task)

        return self.ok({"id": _task_id(task)}, message="Task created.", status_code=201)


@extend_schema_view(
    get=extend_schema(
        responses={200: EnvelopeResponseSerializer, 404: EnvelopeResponseSerializer},
        tags=[TAG], summary="Task detail", parameters=[OpenApiParameter('id', OpenApiTypes.INT, location=OpenApiParameter.PATH, description='Numeric suffix of the tsk_N id')],
        description="Full task detail plus its whole activity feed (status/assignee/sprint/project changes and comments, each with any attachment), newest last.",
    ),
    patch=extend_schema(
        responses={200: EnvelopeResponseSerializer, 400: EnvelopeResponseSerializer, 403: EnvelopeResponseSerializer, 404: EnvelopeResponseSerializer},
        tags=[TAG], summary="Update a task", parameters=[OpenApiParameter('id', OpenApiTypes.INT, location=OpenApiParameter.PATH)],
        description=(
            "Send only the fields you're changing - status alone for a board-column move, "
            "assignedTo alone to reassign, or several at once from the task detail screen. "
            "assignedTo/sprint/project: omit the key entirely to leave unchanged, or send an "
            "empty string to explicitly clear it (unassign / move to Backlog / remove the "
            "project). Every change is recorded in the activity feed with who and when."
        ),
        request=TeamTaskUpdateRequestSerializer,
        examples=[
            OpenApiExample('Move to In Progress (drag equivalent)', value={"status": "IN_PROGRESS"}, request_only=True),
            OpenApiExample('Reassign', value={"assignedTo": "14"}, request_only=True),
            OpenApiExample('Unassign', value={"assignedTo": ""}, request_only=True),
            OpenApiExample('200 response', value={"id": "tsk_00016", "status": "IN_PROGRESS"}, response_only=True),
            OpenApiExample('400 bad sprint', value={
                "success": False, "data": None, "message": "Unknown sprint.",
                "error": {"code": "VALIDATION_ERROR", "field": "sprint", "details": None},
            }, response_only=True, status_codes=['400']),
        ],
    ),
)
class TeamTaskDetailView(MobileAPIView):
    """GET/PATCH /teams/tasks/{id}"""

    def get(self, request, id):
        task = _get_task_for_team_member(request, id)
        return self.ok(_serialize_task_detail(task))

    def patch(self, request, id):
        task = _get_task_for_team_member(request, id)
        payload = request.data

        previous_status = task.status
        notes = []
        update_fields = []

        if 'title' in payload:
            new_title = (payload.get('title') or '').strip()
            if not new_title:
                raise MobileAPIException('VALIDATION_ERROR', 'title cannot be empty.', 400, field='title')
            if new_title != task.title:
                task.title = new_title[:150]
                update_fields.append('title')
                notes.append('Title updated.')

        if 'description' in payload:
            new_description = payload.get('description') or ''
            if new_description != task.description:
                task.description = new_description
                update_fields.append('description')
                notes.append('Description updated.')

        if 'status' in payload:
            new_status = (payload.get('status') or '').lower()
            if new_status not in Task.Status.values:
                raise MobileAPIException('VALIDATION_ERROR', 'Invalid status.', 400, field='status')
            if new_status != task.status:
                task.status = new_status
                update_fields += ['status', 'status_updated_at', 'updated_at']

        if 'type' in payload:
            new_type = (payload.get('type') or '').lower()
            if new_type not in Task.Type.values:
                raise MobileAPIException('VALIDATION_ERROR', 'Invalid type.', 400, field='type')
            if new_type != task.type:
                task.type = new_type
                update_fields.append('type')
                notes.append(f'Type set to {task.get_type_display()}.')

        if 'severity' in payload:
            new_severity = (payload.get('severity') or '').lower()
            if new_severity not in Task.Severity.values:
                raise MobileAPIException('VALIDATION_ERROR', 'Invalid severity.', 400, field='severity')
            if new_severity != task.severity:
                task.severity = new_severity
                update_fields.append('severity')
                notes.append(f'Severity set to {task.get_severity_display()}.')

        newly_assigned = None
        if 'assignedTo' in payload:
            assigned_to_id = payload.get('assignedTo')
            if assigned_to_id:
                new_assignee = task.team.members.filter(pk=assigned_to_id).first()
                if not new_assignee:
                    raise MobileAPIException('VALIDATION_ERROR', 'That person is not on this team.', 400, field='assignedTo')
                if new_assignee.pk != task.assigned_to_id:
                    notes.append(f'Reassigned to {new_assignee.full_name or new_assignee.name}.')
                    task.assigned_to = new_assignee
                    newly_assigned = new_assignee
            elif task.assigned_to_id is not None:
                notes.append('Unassigned.')
                task.assigned_to = None
            update_fields.append('assigned_to')

        if 'sprint' in payload:
            sprint_id = payload.get('sprint')
            if sprint_id:
                new_sprint = Sprint.objects.filter(pk=sprint_id, branch=task.branch).first()
                if not new_sprint:
                    raise MobileAPIException('VALIDATION_ERROR', 'Unknown sprint.', 400, field='sprint')
                if new_sprint.pk != task.sprint_id:
                    old_label = task.sprint.name if task.sprint_id else 'Backlog'
                    notes.append(f'Moved from {old_label} to {new_sprint.name}.')
                    task.sprint = new_sprint
                    update_fields.append('sprint')
            elif task.sprint_id is not None:
                notes.append(f'Moved from {task.sprint.name} to Backlog.')
                task.sprint = None
                update_fields.append('sprint')

        if 'project' in payload:
            project_ref = payload.get('project')
            if project_ref:
                project_pk = _parse_project_id(project_ref) or (int(project_ref) if str(project_ref).isdigit() else None)
                new_project = Project.objects.filter(pk=project_pk).first() if project_pk else None
                if not new_project:
                    raise MobileAPIException('VALIDATION_ERROR', f'Unknown project "{project_ref}".', 400, field='project')
                if new_project.pk != task.project_id:
                    old_label = task.project.name if task.project_id else 'no project'
                    notes.append(f'Project changed from {old_label} to {new_project.name}.')
                    task.project = new_project
                    update_fields.append('project')
            elif task.project_id is not None:
                notes.append(f'Removed from project "{task.project.name}".')
                task.project = None
                update_fields.append('project')

        if update_fields:
            task.save(update_fields=list(dict.fromkeys(update_fields)))

        if notes or 'status' in payload:
            TaskUpdate.objects.create(
                office=task.office, branch=task.branch, task=task, updated_by=request.user,
                previous_status=previous_status, new_status=task.status,
                comment=('Updated from the app.' + (' ' + ' '.join(notes) if notes else '')),
            )

        if newly_assigned is not None and newly_assigned.id != request.user.employee_profile.id:
            from .notification_utils import create_task_notification
            create_task_notification(newly_assigned, task)

        return self.ok(_serialize_board_task(task), message="Task updated.")


@extend_schema(
    responses={200: EnvelopeResponseSerializer, 400: EnvelopeResponseSerializer, 404: EnvelopeResponseSerializer},
    tags=[TAG], summary="Comment on a task", parameters=[OpenApiParameter('id', OpenApiTypes.INT, location=OpenApiParameter.PATH)],
    description=(
        "multipart/form-data, not JSON, so an image or short video can ride along "
        "(e.g. a screen recording showing a bug happening) - both `comment` and "
        "`attachment` are optional but at least one is required."
    ),
    request=TeamCommentRequestSerializer,
    examples=[
        OpenApiExample('400 empty', value={
            "success": False, "data": None, "message": "Add a comment or attach a file.",
            "error": {"code": "VALIDATION_ERROR", "field": None, "details": None},
        }, response_only=True, status_codes=['400']),
    ],
)
class TeamTaskCommentView(MobileAPIView):
    """POST /teams/tasks/{id}/comments"""

    def post(self, request, id):
        task = _get_task_for_team_member(request, id)

        comment = (request.data.get('comment') or '').strip()
        upload = request.FILES.get('attachment')
        if not comment and not upload:
            raise MobileAPIException('VALIDATION_ERROR', 'Add a comment or attach a file.', 400)

        attachment_kind = None
        if upload:
            attachment_kind, error = _validate_task_attachment_upload(upload)
            if error:
                raise MobileAPIException('VALIDATION_ERROR', error, 400, field='attachment')

        update = TaskUpdate.objects.create(
            office=task.office, branch=task.branch, task=task, updated_by=request.user,
            previous_status=task.status, new_status=task.status, comment=comment,
        )
        attachment = None
        if upload:
            attachment = TaskAttachment.objects.create(
                task=task, update=update, file=upload, kind=attachment_kind, uploaded_by=request.user,
            )

        return self.ok({
            "author": request.user.get_full_name() or request.user.username,
            "comment": update.comment or None,
            "createdAt": update.created_at.isoformat(),
            "attachment": {"url": attachment.file.url, "kind": attachment.kind.upper()} if attachment else None,
        }, message="Comment posted.", status_code=201)


@extend_schema(
    responses={201: EnvelopeResponseSerializer, 400: EnvelopeResponseSerializer, 404: EnvelopeResponseSerializer},
    tags=[TAG], summary="Attach media to a task's description",
    parameters=[OpenApiParameter('id', OpenApiTypes.INT, location=OpenApiParameter.PATH)],
    description="Attaches directly to the task itself (not tied to any one comment) - e.g. the bug's own repro evidence.",
    request=TeamAttachmentOnlyRequestSerializer,
)
class TeamTaskAttachmentView(MobileAPIView):
    """POST /teams/tasks/{id}/attachments"""

    def post(self, request, id):
        task = _get_task_for_team_member(request, id)

        upload = request.FILES.get('attachment')
        if not upload:
            raise MobileAPIException('VALIDATION_ERROR', 'Choose a file first.', 400, field='attachment')

        kind, error = _validate_task_attachment_upload(upload)
        if error:
            raise MobileAPIException('VALIDATION_ERROR', error, 400, field='attachment')

        attachment = TaskAttachment.objects.create(
            task=task, update=None, file=upload, kind=kind, uploaded_by=request.user,
        )
        TaskUpdate.objects.create(
            office=task.office, branch=task.branch, task=task, updated_by=request.user,
            previous_status=task.status, new_status=task.status,
            comment=f'Attached a{"n" if kind == TaskAttachment.Kind.IMAGE else ""} {kind} to the description.',
        )
        return self.ok({"url": attachment.file.url, "kind": attachment.kind.upper()}, message="Attached.", status_code=201)
