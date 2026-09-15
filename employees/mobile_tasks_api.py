"""
Mobile API - Tasks & Projects (beyond the original spec - added to mirror
the web app's employee self-service task board: view assigned tasks,
self-create one, post status updates with comments, and browse the
projects you're a team member or manager of).

GET/POST /tasks, GET /tasks/{id}, POST /tasks/{id}/updates, GET /projects
"""
import re

from django.db.models import Q
from rest_framework import serializers
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample, OpenApiParameter, OpenApiTypes

from .mobile_response import MobileAPIView, MobileAPIException, EnvelopeResponseSerializer
from .mobile_common import paginate
from .models import Task, TaskUpdate, Project

TAG = 'Tasks'
PROJECTS_TAG = 'Projects'

_PROJECT_ID_RE = re.compile(r'^prj_0*(\d+)$', re.IGNORECASE)


class TaskCreateRequestSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=150)
    description = serializers.CharField(required=False, allow_blank=True)
    priority = serializers.ChoiceField(choices=Task.Priority.values, required=False, help_text="Defaults to MEDIUM")
    dueDate = serializers.DateField(required=False)
    project = serializers.CharField(
        required=False, allow_blank=True,
        help_text="A project id from GET /projects (e.g. 'prj_00003') - must be a project you're a team member or manager of.",
    )


class TaskStatusUpdateRequestSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Task.Status.values)
    comment = serializers.CharField(required=False, allow_blank=True)


def _task_id(task):
    return f"tsk_{task.id:05d}"


def _project_id(project):
    return f"prj_{project.id:05d}"


def _parse_project_id(value):
    """'prj_00003' -> 3, or None if it doesn't look like a project id."""
    m = _PROJECT_ID_RE.match((value or '').strip())
    return int(m.group(1)) if m else None


def _serialize_project_brief(project):
    if project is None:
        return None
    return {"id": _project_id(project), "code": project.code, "name": project.name}


def _serialize_task_update(u):
    return {
        "status": u.new_status.upper(),
        "previousStatus": u.previous_status.upper() if u.previous_status else None,
        "comment": u.comment or None,
        "updatedBy": u.updated_by.get_full_name() or u.updated_by.username,
        "updatedAt": u.created_at.isoformat(),
    }


def _serialize_task(task, include_updates=False):
    data = {
        "id": _task_id(task),
        "title": task.title,
        "description": task.description or None,
        "status": task.status.upper(),
        "priority": task.priority.upper(),
        "project": _serialize_project_brief(task.project),
        "assignedBy": (task.assigned_by.get_full_name() or task.assigned_by.username) if task.assigned_by else None,
        "isSelfCreated": bool(task.assigned_by_id and task.assigned_by_id == task.assigned_to.user_id),
        "dueDate": task.due_date.isoformat() if task.due_date else None,
        "isOverdue": task.is_overdue,
        "createdAt": task.created_at.isoformat(),
        "statusUpdatedAt": task.status_updated_at.isoformat() if task.status_updated_at else None,
    }
    if include_updates:
        data["updates"] = [_serialize_task_update(u) for u in task.updates.select_related('updated_by').order_by('-created_at')]
    else:
        latest = task.latest_update
        data["latestUpdate"] = _serialize_task_update(latest) if latest else None
    return data


def _serialize_project_summary(project, employee):
    return {
        "id": _project_id(project),
        "code": project.code,
        "name": project.name,
        "status": project.status.upper(),
        "priority": project.priority.upper(),
        "progressPercent": project.progress_percent,
        "deadline": project.end_date.isoformat() if project.end_date else None,
        "isManager": project.manager_id == employee.id,
    }


@extend_schema_view(
    get=extend_schema(
        responses=EnvelopeResponseSerializer,
        tags=[TAG], summary="My tasks", parameters=[
            OpenApiParameter('status', OpenApiTypes.STR, description='Filter: PENDING, IN_PROGRESS, COMPLETED, BLOCKED'),
            OpenApiParameter('priority', OpenApiTypes.STR, description='Filter: LOW, MEDIUM, HIGH, CRITICAL'),
            OpenApiParameter('project', OpenApiTypes.STR, description="Filter by project id, e.g. 'prj_00003'"),
            OpenApiParameter('page', OpenApiTypes.INT), OpenApiParameter('pageSize', OpenApiTypes.INT),
        ],
        description="Every task assigned to you - both admin-assigned and self-created - newest activity first.",
        examples=[OpenApiExample('200 response', value={
            "tasks": [
                {
                    "id": "tsk_00016", "title": "Prepare Q3 report", "description": "Pull attendance + payroll numbers",
                    "status": "IN_PROGRESS", "priority": "HIGH",
                    "project": {"id": "prj_00004", "code": "PRJ00004", "name": "Finance Automation"},
                    "assignedBy": "Priya Sharma", "isSelfCreated": False,
                    "dueDate": "2026-09-30", "isOverdue": False,
                    "createdAt": "2026-09-10T09:00:00+05:30", "statusUpdatedAt": "2026-09-15T14:30:00+05:30",
                    "latestUpdate": {
                        "status": "IN_PROGRESS", "previousStatus": "PENDING", "comment": "Started pulling numbers",
                        "updatedBy": "Akshay", "updatedAt": "2026-09-15T14:30:00+05:30",
                    },
                },
            ],
            "pagination": {"page": 1, "pageSize": 20, "totalItems": 1, "totalPages": 1},
        }, response_only=True)],
    ),
    post=extend_schema(
        responses={201: EnvelopeResponseSerializer, 400: EnvelopeResponseSerializer},
        tags=[TAG], summary="Create a task for yourself",
        description="Always assigned to you; there's no way to assign a task to someone else from the app. "
                     "`project`, if given, must be one you're a team member or manager of (see GET /projects).",
        request=TaskCreateRequestSerializer,
        examples=[
            OpenApiExample('Request', value={
                "title": "Prepare Q3 report", "description": "Pull attendance + payroll numbers",
                "priority": "HIGH", "dueDate": "2026-09-30", "project": "prj_00003",
            }, request_only=True),
            OpenApiExample('201 response', value={
                "id": "tsk_00016", "title": "Prepare Q3 report", "description": "Pull attendance + payroll numbers",
                "status": "PENDING", "priority": "HIGH",
                "project": {"id": "prj_00003", "code": "PRJ00003", "name": "Finance Automation"},
                "assignedBy": "Akshay", "isSelfCreated": True,
                "dueDate": "2026-09-30", "isOverdue": False,
                "createdAt": "2026-09-15T14:00:00+05:30", "statusUpdatedAt": "2026-09-15T14:00:00+05:30",
                "latestUpdate": {
                    "status": "PENDING", "previousStatus": None, "comment": "Pull attendance + payroll numbers",
                    "updatedBy": "Akshay", "updatedAt": "2026-09-15T14:00:00+05:30",
                },
            }, response_only=True),
            OpenApiExample('400 unknown project', value={
                "success": False, "data": None,
                "message": 'Unknown or inaccessible project "prj_00099".',
                "error": {"code": "VALIDATION_ERROR", "field": "project", "details": None},
            }, response_only=True, status_codes=['400']),
        ],
    ),
)
class TasksView(MobileAPIView):
    """GET/POST /tasks"""

    def get(self, request):
        employee = request.user.employee_profile
        qs = Task.objects.filter(assigned_to=employee).select_related('assigned_by', 'project').prefetch_related('updates__updated_by')

        status_filter = (request.GET.get('status') or '').strip().lower()
        if status_filter:
            qs = qs.filter(status=status_filter)
        priority_filter = (request.GET.get('priority') or '').strip().lower()
        if priority_filter:
            qs = qs.filter(priority=priority_filter)
        project_filter = _parse_project_id(request.GET.get('project'))
        if project_filter:
            qs = qs.filter(project_id=project_filter)

        qs = qs.order_by('-status_updated_at', '-created_at')
        items, pagination = paginate(list(qs), request.GET.get('page'), request.GET.get('pageSize'))
        return self.ok({
            "tasks": [_serialize_task(t) for t in items],
            "pagination": pagination,
        })

    def post(self, request):
        employee = request.user.employee_profile
        title = (request.data.get('title') or '').strip()
        if not title:
            raise MobileAPIException('VALIDATION_ERROR', 'title is required.', 400, field='title')

        priority = (request.data.get('priority') or Task.Priority.MEDIUM).lower()
        if priority not in Task.Priority.values:
            raise MobileAPIException('VALIDATION_ERROR', f'priority must be one of: {", ".join(v.upper() for v in Task.Priority.values)}.', 400, field='priority')

        due_date = None
        due_date_str = request.data.get('dueDate')
        if due_date_str:
            from django.utils.dateparse import parse_date
            due_date = parse_date(due_date_str)
            if not due_date:
                raise MobileAPIException('VALIDATION_ERROR', 'dueDate must be YYYY-MM-DD.', 400, field='dueDate')

        project = None
        project_ref = request.data.get('project')
        if project_ref:
            project_pk = _parse_project_id(project_ref)
            project = Project.objects.filter(
                Q(assigned_employees=employee) | Q(manager=employee), pk=project_pk,
            ).first() if project_pk else None
            if project is None:
                raise MobileAPIException('VALIDATION_ERROR', f'Unknown or inaccessible project "{project_ref}".', 400, field='project')

        task = Task.objects.create(
            office=employee.office, branch=employee.branch,
            project=project, title=title, description=request.data.get('description', ''),
            assigned_to=employee, assigned_by=request.user,
            priority=priority, due_date=due_date, status=Task.Status.PENDING,
        )
        TaskUpdate.objects.create(
            office=task.office, branch=task.branch, task=task, updated_by=request.user,
            previous_status=None, new_status=task.status,
            comment=(task.description or '')[:200],
        )

        return self.ok(_serialize_task(task), message="Task created.", status_code=201)


@extend_schema(
    responses={200: EnvelopeResponseSerializer, 404: EnvelopeResponseSerializer},
    tags=[TAG], summary="Task detail", parameters=[
        OpenApiParameter('id', OpenApiTypes.INT, location=OpenApiParameter.PATH, description='Numeric suffix of the tsk_N id'),
    ],
    description="Includes the full update history (newest first), unlike the list endpoint which only carries the latest one.",
    examples=[
        OpenApiExample('200 response', value={
            "id": "tsk_00016", "title": "Prepare Q3 report", "description": "Pull attendance + payroll numbers",
            "status": "IN_PROGRESS", "priority": "HIGH",
            "project": {"id": "prj_00004", "code": "PRJ00004", "name": "Finance Automation"},
            "assignedBy": "Priya Sharma", "isSelfCreated": False,
            "dueDate": "2026-09-30", "isOverdue": False,
            "createdAt": "2026-09-10T09:00:00+05:30", "statusUpdatedAt": "2026-09-15T14:30:00+05:30",
            "updates": [
                {"status": "IN_PROGRESS", "previousStatus": "PENDING", "comment": "Started pulling numbers",
                 "updatedBy": "Akshay", "updatedAt": "2026-09-15T14:30:00+05:30"},
                {"status": "PENDING", "previousStatus": None, "comment": None,
                 "updatedBy": "Priya Sharma", "updatedAt": "2026-09-10T09:00:00+05:30"},
            ],
        }, response_only=True),
        OpenApiExample('404 not found', value={
            "success": False, "data": None, "message": "Task not found.",
            "error": {"code": "NOT_FOUND", "field": None, "details": None},
        }, response_only=True, status_codes=['404']),
    ],
)
class TaskDetailView(MobileAPIView):
    """GET /tasks/{id} - id is the numeric suffix of the tsk_NNNNN ids
    this API hands out, e.g. GET /tasks/12 for "tsk_00012"."""

    def get(self, request, id):
        employee = request.user.employee_profile
        task = Task.objects.filter(assigned_to=employee, id=id).select_related('assigned_by', 'project').first()
        if task is None:
            raise MobileAPIException('NOT_FOUND', 'Task not found.', 404)
        return self.ok(_serialize_task(task, include_updates=True))


@extend_schema(
    responses={200: EnvelopeResponseSerializer, 400: EnvelopeResponseSerializer, 404: EnvelopeResponseSerializer},
    tags=[TAG], summary="Post a status update", parameters=[
        OpenApiParameter('id', OpenApiTypes.INT, location=OpenApiParameter.PATH, description='Numeric suffix of the tsk_N id'),
    ],
    description="Changes the task's status and appends to its update history in one call.",
    request=TaskStatusUpdateRequestSerializer,
    examples=[
        OpenApiExample('Request', value={"status": "COMPLETED", "comment": "Report sent to finance"}, request_only=True),
        OpenApiExample('200 response', value={
            "id": "tsk_00016", "title": "Prepare Q3 report", "description": "Pull attendance + payroll numbers",
            "status": "COMPLETED", "priority": "HIGH",
            "project": {"id": "prj_00004", "code": "PRJ00004", "name": "Finance Automation"},
            "assignedBy": "Priya Sharma", "isSelfCreated": False,
            "dueDate": "2026-09-30", "isOverdue": False,
            "createdAt": "2026-09-10T09:00:00+05:30", "statusUpdatedAt": "2026-09-15T16:00:00+05:30",
            "latestUpdate": {"status": "COMPLETED", "previousStatus": "IN_PROGRESS", "comment": "Report sent to finance",
                              "updatedBy": "Akshay", "updatedAt": "2026-09-15T16:00:00+05:30"},
        }, response_only=True),
        OpenApiExample('400 invalid status', value={
            "success": False, "data": None,
            "message": "status must be one of: PENDING, IN_PROGRESS, COMPLETED, BLOCKED.",
            "error": {"code": "VALIDATION_ERROR", "field": "status", "details": None},
        }, response_only=True, status_codes=['400']),
        OpenApiExample('404 not found', value={
            "success": False, "data": None, "message": "Task not found.",
            "error": {"code": "NOT_FOUND", "field": None, "details": None},
        }, response_only=True, status_codes=['404']),
    ],
)
class TaskStatusUpdateView(MobileAPIView):
    """POST /tasks/{id}/updates"""

    def post(self, request, id):
        employee = request.user.employee_profile
        task = Task.objects.filter(assigned_to=employee, id=id).first()
        if task is None:
            raise MobileAPIException('NOT_FOUND', 'Task not found.', 404)

        new_status = (request.data.get('status') or '').strip().lower()
        if new_status not in Task.Status.values:
            raise MobileAPIException('VALIDATION_ERROR', f'status must be one of: {", ".join(v.upper() for v in Task.Status.values)}.', 400, field='status')

        previous_status = task.status
        comment = (request.data.get('comment') or '').strip()

        TaskUpdate.objects.create(
            office=task.office, branch=task.branch, task=task, updated_by=request.user,
            previous_status=previous_status, new_status=new_status, comment=comment,
        )
        if new_status != task.status:
            task.status = new_status
            task.save(update_fields=['status', 'status_updated_at', 'updated_at'])

        return self.ok(_serialize_task(task), message="Task updated.")


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[PROJECTS_TAG], summary="Projects you're on the team of",
    parameters=[OpenApiParameter('page', OpenApiTypes.INT), OpenApiParameter('pageSize', OpenApiTypes.INT)],
    description="Only projects you're an assigned team member or the manager of - build the project picker for "
                 "POST /tasks from this list's `id`, not a project's numeric database id.",
    examples=[OpenApiExample('200 response', value={
        "projects": [
            {
                "id": "prj_00004", "code": "PRJ00004", "name": "Finance Automation",
                "status": "IN_PROGRESS", "priority": "HIGH", "progressPercent": 40,
                "deadline": "2026-10-31", "isManager": False,
            },
        ],
        "pagination": {"page": 1, "pageSize": 20, "totalItems": 1, "totalPages": 1},
    }, response_only=True)],
)
class MyProjectsView(MobileAPIView):
    """GET /projects"""

    def get(self, request):
        employee = request.user.employee_profile
        qs = Project.objects.filter(
            Q(assigned_employees=employee) | Q(manager=employee)
        ).distinct().order_by('-created_at')
        items, pagination = paginate(list(qs), request.GET.get('page'), request.GET.get('pageSize'))
        return self.ok({
            "projects": [_serialize_project_summary(p, employee) for p in items],
            "pagination": pagination,
        })
