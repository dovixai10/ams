"""Sprint auto-generation for a branch's SprintConfig.

This project has no Celery/cron infrastructure, so "the next sprint gets
created automatically, one sprint in advance" can't be a scheduled job -
instead ensure_upcoming_sprints() is called opportunistically (from
team_board) and self-heals: it always makes sure every Sprint row from #1
through "whichever sprint covers today, plus one" exists, creating
whatever's missing. Idempotent (get_or_create), so calling it on every
board view is cheap and safe even if nothing needs to change.
"""
from datetime import timedelta

from django.utils import timezone

from .models import Sprint


def ensure_upcoming_sprints(branch):
    """Make sure `branch` has every Sprint generated through one sprint
    past whichever one covers today. No-op if the branch has no
    SprintConfig yet, or sprints are disabled for it."""
    config = getattr(branch, 'sprint_config', None)
    if config is None or not config.is_enabled:
        return

    today = timezone.localdate()
    days_since_anchor = (today - config.anchor_start_date).days
    span_days = config.duration_weeks * 7

    if days_since_anchor < 0:
        # Anchor date is in the future - today is still "before Sprint 1".
        current_number = 1
    else:
        current_number = (days_since_anchor // span_days) + 1

    for number in range(1, current_number + 2):  # +2, not +1: "one sprint in advance"
        start = config.anchor_start_date + timedelta(days=(number - 1) * span_days)
        end = start + timedelta(days=span_days - 1)
        Sprint.objects.get_or_create(
            branch=branch, number=number,
            defaults={'name': f'Sprint {number}', 'start_date': start, 'end_date': end},
        )


def current_sprint(branch):
    """Whichever Sprint's date range covers today, or None (Backlog-only /
    unconfigured)."""
    today = timezone.localdate()
    return Sprint.objects.filter(branch=branch, start_date__lte=today, end_date__gte=today).first()
