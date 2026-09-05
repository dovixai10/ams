"""Engagement program admin workspace (#48)."""

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from employees.permissions import get_request_office, is_employee, office_admin_required
from web_project import TemplateLayout
from web_project.template_helpers.theme import TemplateHelper

from .models import (
    EngagementComment,
    EngagementPollOption,
    EngagementPollVote,
    EngagementProgram,
    EngagementReaction,
)
from .views import tenant_object_or_404, tenant_queryset


def _layout(request, extra=None):
    ctx = TemplateLayout.init(request, context={})
    ctx.update({'layout_path': TemplateHelper.set_layout('layout_vertical.html', ctx)})
    if extra:
        ctx.update(extra)
    return ctx


@login_required
@user_passes_test(office_admin_required)
def engagement_admin_list(request):
    office = get_request_office(request)
    programs = (
        EngagementProgram.objects.filter(office=office)
        .annotate(
            comment_count=Count('comments', distinct=True),
            reaction_count=Count('reactions', distinct=True),
            vote_count=Count('poll_votes', distinct=True),
        )
        .order_by('-created_at')
    ) if office else EngagementProgram.objects.none()

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        program_type = request.POST.get('program_type', EngagementProgram.ProgramType.ANNOUNCEMENT)
        body = request.POST.get('body', '')
        start_date = request.POST.get('start_date') or None
        end_date = request.POST.get('end_date') or None
        allow_anonymous = request.POST.get('allow_anonymous') == 'on'
        comments_enabled = request.POST.get('comments_enabled', 'on') == 'on'

        if not title:
            messages.error(request, 'Title is required.')
        elif office:
            program = EngagementProgram.objects.create(
                office=office,
                title=title,
                program_type=program_type,
                body=body,
                start_date=start_date or None,
                end_date=end_date or None,
                allow_anonymous=allow_anonymous,
                comments_enabled=comments_enabled,
                created_by=request.user,
            )
            if program_type == EngagementProgram.ProgramType.POLL:
                for idx, label in enumerate(request.POST.getlist('poll_option')):
                    label = label.strip()
                    if label:
                        EngagementPollOption.objects.create(program=program, label=label, sort_order=idx)
            messages.success(request, 'Program created as draft.')
            return redirect('employees:engagement_admin_detail', pk=program.pk)

    return render(request, 'employees/engagement/admin_list.html', _layout(request, {
        'programs': programs,
        'type_choices': EngagementProgram.ProgramType.choices,
        'status_choices': EngagementProgram.Status.choices,
        'page_title': 'Engagement programs',
    }))


@login_required
@user_passes_test(office_admin_required)
def engagement_admin_detail(request, pk):
    program = get_object_or_404(
        tenant_queryset(request, EngagementProgram.objects.all()),
        pk=pk,
    )
    poll_options = program.poll_options.annotate(votes=Count('votes'))
    comments = program.comments.filter(is_hidden=False).select_related('author')[:50]
    reactions = program.reactions.values('reaction').annotate(c=Count('id'))

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'publish' and program.status == EngagementProgram.Status.DRAFT:
            program.publish()
            messages.success(request, 'Program published.')
        elif action == 'close':
            program.status = EngagementProgram.Status.CLOSED
            program.save(update_fields=['status', 'updated_at'])
            messages.success(request, 'Program closed.')
        elif action == 'delete':
            program.delete()
            messages.success(request, 'Program deleted.')
            return redirect('employees:engagement_admin_list')
        return redirect('employees:engagement_admin_detail', pk=pk)

    return render(request, 'employees/engagement/admin_detail.html', _layout(request, {
        'program': program,
        'poll_options': poll_options,
        'comments': comments,
        'reactions': reactions,
        'page_title': program.title,
    }))


@login_required
@user_passes_test(is_employee)
def engagement_portal(request):
    """Employee-facing engagement feed."""
    employee = request.user.employee_profile
    office = employee.office
    programs = EngagementProgram.objects.filter(
        office=office,
        status=EngagementProgram.Status.PUBLISHED,
    ).order_by('-published_at') if office else EngagementProgram.objects.none()

    return render(request, 'employees/engagement/portal.html', _layout(request, {
        'programs': programs,
        'employee': employee,
        'page_title': 'Engagement',
    }))


@login_required
@user_passes_test(is_employee)
def engagement_program_detail(request, pk):
    employee = request.user.employee_profile
    program = get_object_or_404(
        EngagementProgram.objects.filter(
            office=employee.office,
            status=EngagementProgram.Status.PUBLISHED,
        ),
        pk=pk,
    )
    poll_options = program.poll_options.annotate(votes=Count('votes'))
    user_vote = EngagementPollVote.objects.filter(program=program, employee=employee).first()
    comments = program.comments.filter(is_hidden=False, parent__isnull=True).select_related('author')

    if request.method == 'POST':
        if request.POST.get('action') == 'vote' and program.program_type == EngagementProgram.ProgramType.POLL:
            option_id = request.POST.get('poll_option_id')
            option = get_object_or_404(EngagementPollOption, pk=option_id, program=program)
            EngagementPollVote.objects.update_or_create(
                program=program,
                employee=employee,
                defaults={'option': option},
            )
            messages.success(request, 'Vote recorded.')
            return redirect('employees:engagement_program_detail', pk=pk)

        reaction = request.POST.get('reaction')
        if reaction in EngagementReaction.ReactionType.values:
            EngagementReaction.objects.update_or_create(
                program=program,
                employee=employee,
                defaults={'reaction': reaction},
            )
            messages.success(request, 'Reaction saved.')
            return redirect('employees:engagement_program_detail', pk=pk)

        if program.comments_enabled:
            body = request.POST.get('comment', '').strip()
            if body:
                EngagementComment.objects.create(
                    program=program,
                    author=request.user,
                    body=body,
                    is_anonymous=program.allow_anonymous and request.POST.get('anonymous') == 'on',
                )
                messages.success(request, 'Comment posted.')
            return redirect('employees:engagement_program_detail', pk=pk)

    return render(request, 'employees/engagement/program_detail.html', _layout(request, {
        'program': program,
        'poll_options': poll_options,
        'user_vote': user_vote,
        'comments': comments,
        'page_title': program.title,
    }))
