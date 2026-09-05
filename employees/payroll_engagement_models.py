"""Payroll run engine models (items #43–44)."""

from django.conf import settings
from django.db import models
from django.utils import timezone

from .models import Employee, Office


class PayrollRun(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        COMPUTED = 'computed', 'Computed'
        UNDER_REVIEW = 'under_review', 'Under review'
        APPROVED = 'approved', 'Approved'
        PAID = 'paid', 'Paid'
        CLOSED = 'closed', 'Closed'

    office = models.ForeignKey(Office, on_delete=models.CASCADE, related_name='payroll_runs')
    period_month = models.DateField(help_text='First day of payroll month')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='payroll_runs_created',
    )
    computed_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-period_month']
        unique_together = [('office', 'period_month')]

    def __str__(self):
        return f'Payroll {self.period_month:%B %Y} ({self.get_status_display()})'

    @property
    def is_locked(self):
        return self.status in (self.Status.PAID, self.Status.CLOSED)


class PayrollRunLine(models.Model):
    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name='lines')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='payroll_lines')
    paid_days = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    lop_days = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    working_days = models.PositiveSmallIntegerField(default=0)
    gross_earnings = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    prior_net_pay = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    earnings_json = models.JSONField(default=dict, blank=True)
    deductions_json = models.JSONField(default=dict, blank=True)
    employer_contrib_json = models.JSONField(default=dict, blank=True)
    exception_flags = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = [('run', 'employee')]
        ordering = ['employee__full_name']

    @property
    def variance(self):
        if self.prior_net_pay is None:
            return None
        return self.net_pay - self.prior_net_pay

    @property
    def variance_pct(self):
        if not self.prior_net_pay:
            return None
        return (self.variance / self.prior_net_pay) * 100


class EngagementProgram(models.Model):
    class ProgramType(models.TextChoices):
        SURVEY = 'survey', 'Survey'
        POLL = 'poll', 'Poll'
        ANNOUNCEMENT = 'announcement', 'Announcement'
        EVENT = 'event', 'Event'
        RECOGNITION = 'recognition', 'Recognition'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        SCHEDULED = 'scheduled', 'Scheduled'
        PUBLISHED = 'published', 'Published'
        CLOSED = 'closed', 'Closed'

    office = models.ForeignKey(Office, on_delete=models.CASCADE, related_name='engagement_programs')
    program_type = models.CharField(max_length=20, choices=ProgramType.choices)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    banner = models.ImageField(upload_to='engagement/banners/', blank=True, null=True)
    audience_json = models.JSONField(default=dict, blank=True, help_text='branch/dept/team/designation/user filters')
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    allow_anonymous = models.BooleanField(default=False)
    comments_enabled = models.BooleanField(default=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='engagement_programs_created',
    )
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    def publish(self):
        self.status = self.Status.PUBLISHED
        self.published_at = timezone.now()
        self.save(update_fields=['status', 'published_at', 'updated_at'])


class EngagementPollOption(models.Model):
    program = models.ForeignKey(
        EngagementProgram,
        on_delete=models.CASCADE,
        related_name='poll_options',
        limit_choices_to={'program_type': EngagementProgram.ProgramType.POLL},
    )
    label = models.CharField(max_length=200)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']


class EngagementPollVote(models.Model):
    program = models.ForeignKey(EngagementProgram, on_delete=models.CASCADE, related_name='poll_votes')
    option = models.ForeignKey(EngagementPollOption, on_delete=models.CASCADE, related_name='votes')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='poll_votes')
    voted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('program', 'employee')]


class EngagementReaction(models.Model):
    class ReactionType(models.TextChoices):
        LIKE = 'like', 'Like'
        LOVE = 'love', 'Love'
        INTERESTED = 'interested', 'Interested'

    program = models.ForeignKey(EngagementProgram, on_delete=models.CASCADE, related_name='reactions')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='engagement_reactions')
    reaction = models.CharField(max_length=20, choices=ReactionType.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('program', 'employee')]


class EngagementComment(models.Model):
    program = models.ForeignKey(EngagementProgram, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='engagement_comments',
    )
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies')
    body = models.TextField()
    is_anonymous = models.BooleanField(default=False)
    is_hidden = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
