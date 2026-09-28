"""Orchestration for WhatsApp report sending - independent of Celery so it can
be called from a task, a view, or a shell, and tested without a broker.

Flow for one report run:
  run_schedule()       builds the report once and writes one WhatsAppMessageLog
                       row per recipient (the row stores the exact message)
  enqueue_send(log)    hands each row to Celery (falls back to sending inline if
                       the broker is unreachable, so "Send now" still works)
  deliver_log(log)     the actual Meta API call; records sent / failed on the row
Because the row carries the whole message, a retry re-sends the identical text.
"""
import logging
from datetime import datetime, timedelta

from django.utils import timezone

from ..models import (
    WhatsAppAccount, WhatsAppMessageLog, WhatsAppRecipient, WhatsAppReportSchedule, WhatsAppWebSession,
)
from . import web_client
from .attendance_report import build_attendance_report, render_text, template_params
from .whatsapp_client import (
    WhatsAppError, create_group, get_invite_link, list_groups, send_message,
)

logger = logging.getLogger(__name__)

# If the scheduler was down at send time, still send when it comes back - but
# only within this window. Later than that a "10:30 report" would be misleading
# (it would describe attendance as of a much later time), so it's skipped and
# logged instead.
GRACE_MINUTES = 60


def _scope_label(schedule):
    office = schedule.office.name if schedule.office else 'Office'
    return f'{office} - {schedule.branch.name}' if schedule.branch else office


def _log(schedule, *, recipient=None, status, error='', payload=None, mode='', kind='report', triggered_by='schedule', address=None, recipient_type='person'):
    return WhatsAppMessageLog.objects.create(
        office=schedule.office, branch=schedule.branch, schedule=schedule, recipient=recipient,
        recipient_label=recipient.label if recipient else _scope_label(schedule),
        to_address=(address if address is not None else recipient.summary) if recipient else '',
        recipient_type=recipient_type,
        kind=kind, channel=schedule.channel, mode=mode or schedule.message_mode, payload=payload or {},
        status=status, error=error, triggered_by=triggered_by,
    )


def enqueue_send(log_id):
    """Queue one message on Celery. If the broker (Redis) is unreachable the
    message is sent right here instead of being lost. Returns 'queued' or 'inline'."""
    from ..tasks import send_whatsapp_log
    try:
        send_whatsapp_log.delay(log_id)
        return 'queued'
    except Exception as exc:  # broker down / not configured - don't lose the message
        logger.warning('Celery broker unavailable (%s) - sending WhatsApp message %s inline', exc, log_id)
        try:
            deliver_log(log_id)
        except WhatsAppError:
            pass  # already recorded on the log row
        return 'inline'


def run_schedule(schedule_id, triggered_by='schedule'):
    """Build the report for a schedule and queue a message to each recipient.
    Returns the list of message-log rows created."""
    schedule = (
        WhatsAppReportSchedule.objects.select_related('office', 'branch').get(pk=schedule_id)
    )

    if schedule.office is None or schedule.office.status != 'approved':
        return [_log(schedule, status='skipped', error='This office is not active.', triggered_by=triggered_by)]

    report = build_attendance_report(
        schedule.office, schedule.branch, skip_holidays=schedule.skip_holidays,
    )
    if report['skipped_reason']:
        return [_log(schedule, status='skipped', error=report['skipped_reason'], triggered_by=triggered_by)]

    recipients = list(schedule.recipients.filter(is_active=True))
    if not recipients:
        return [_log(schedule, status='skipped', error='No active recipients on this schedule.', triggered_by=triggered_by)]

    is_web = schedule.channel == WhatsAppReportSchedule.Channel.WEB
    if is_web:
        # A linked phone sends ordinary chat messages - no templates involved.
        mode, payload = 'text', {'body': render_text(report)}
    elif schedule.message_mode == WhatsAppReportSchedule.MessageMode.TEMPLATE:
        if not schedule.template_name:
            return [_log(schedule, status='failed', error='Template mode needs a template name.', triggered_by=triggered_by)]
        mode = 'template'
        payload = {
            'template': schedule.template_name,
            'language': schedule.template_language or 'en',
            'params': template_params(report),
        }
    else:
        mode, payload = 'text', {'body': render_text(report)}

    logs, queued, seen = [], [], set()
    for recipient in recipients:
        targets = recipient.targets_for(schedule.channel)
        if not targets:
            need = 'a group name' if is_web else 'a Business API group ID'
            logs.append(_log(
                schedule, recipient=recipient, status='failed', mode=mode, triggered_by=triggered_by, address=recipient.summary,
                error=f"\"{recipient.label}\" has nothing that can be reached through the {schedule.get_channel_display()} - it needs a phone number or {need}. Edit the recipient to add one.",
            ))
            continue
        for recipient_type, address in targets:
            if (recipient_type, address) in seen:  # the same place listed in two entries - send once
                continue
            seen.add((recipient_type, address))
            log = _log(
                schedule, recipient=recipient, status='queued', mode=mode, payload=payload,
                triggered_by=triggered_by, address=address, recipient_type=recipient_type,
            )
            logs.append(log)
            queued.append(log)
    for log in queued:
        enqueue_send(log.pk)
    return logs


def _fail(log, message):
    log.status = WhatsAppMessageLog.Status.FAILED
    log.error = message
    log.save(update_fields=['attempts', 'status', 'error', 'updated_at'])


def deliver_log(log_id):
    """Send one queued message (Business API or linked phone, per the row's
    channel) and record the outcome. Raises WhatsAppError after recording a
    failure, so a caller (the Celery task) can decide whether to retry a
    transient one."""
    log = WhatsAppMessageLog.objects.select_related('office', 'branch').get(pk=log_id)
    if log.status == WhatsAppMessageLog.Status.SENT:
        return log

    log.attempts += 1
    scope = log.branch.name if log.branch else 'this office'

    if log.channel == 'web':
        session = WhatsAppWebSession.resolve(log.office, log.branch)
        if session is None:
            message = f'No active linked phone is set up for {scope}. Add one under Integrations - WhatsApp - Linked Phones and scan its QR code.'
            _fail(log, message)
            raise WhatsAppError(message)

        def send():
            return web_client.send(session.pk, kind=log.recipient_type, to=log.to_address, text=(log.payload or {}).get('body', ''))
    else:
        account = WhatsAppAccount.resolve(log.office, log.branch)
        if account is None:
            message = f'No active WhatsApp account is set up for {scope}. Add one under Integrations - WhatsApp - Accounts.'
            _fail(log, message)
            raise WhatsAppError(message)

        def send():
            return send_message(
                account, to=log.to_address, recipient_type=log.recipient_type,
                mode=log.mode, payload=log.payload,
            )

    try:
        message_id = send()
    except WhatsAppError as exc:
        _fail(log, str(exc))
        raise

    log.status = WhatsAppMessageLog.Status.SENT
    log.wa_message_id = message_id
    log.error = ''
    log.sent_at = timezone.now()
    log.save(update_fields=['attempts', 'status', 'wa_message_id', 'error', 'sent_at', 'updated_at'])
    return log


def send_test_message(recipient, triggered_by='manual', channel='api'):
    """A harmless test message to every place in this recipient, to prove the
    setup works. Business API: Meta's built-in `hello_world` template (exists on
    every account, needs no template setup). Linked phone: a short plain text
    line. Returns the log rows."""
    if channel == 'web':
        mode, payload = 'text', {'body': 'Test message from the attendance system - your WhatsApp link is working.'}
    else:
        mode, payload = 'template', {'template': 'hello_world', 'language': 'en_US', 'params': []}

    def make(recipient_type, address):
        return WhatsAppMessageLog.objects.create(
            office=recipient.office, branch=recipient.branch, recipient=recipient,
            recipient_label=recipient.label, to_address=address,
            recipient_type=recipient_type, kind='test', channel=channel, mode=mode,
            payload=payload, status='queued', triggered_by=triggered_by,
        )

    targets = recipient.targets_for(channel)
    if not targets:
        need = 'a group name' if channel == 'web' else 'a Business API group ID'
        log = make('person', recipient.summary)
        log.attempts = 1
        _fail(log, f'"{recipient.label}" has nothing reachable this way - add a phone number or {need}.')
        log.refresh_from_db()
        return [log]

    logs = [make(recipient_type, address) for recipient_type, address in targets]
    for log in logs:
        enqueue_send(log.pk)
    return [WhatsAppMessageLog.objects.get(pk=log.pk) for log in logs]


# ---- Business API groups ---------------------------------------------------

def _find_group_by_subject(account, subject, known_ids=()):
    matches = [
        g for g in list_groups(account)
        if (g.get('subject') or '').strip() == subject.strip() and g.get('id') not in known_ids
    ]
    return matches[-1] if matches else None


def create_api_group(account, subject, description='', join_approval_mode='auto_approve'):
    """Create a group through the Business API and return (group_id, invite_link).
    Meta sometimes confirms the new group only asynchronously; in that case we
    look for it in the account's group list for a few seconds. Raises
    WhatsAppError if it can't be confirmed (the group may still appear - use
    "Sync groups from Meta" a moment later)."""
    import time

    try:
        known = {g.get('id') for g in list_groups(account)}
    except WhatsAppError:
        known = set()
    created = create_group(account, subject, description, join_approval_mode)
    group_id, invite_link = created['group_id'], created['invite_link']

    for _ in range(5):
        if group_id:
            break
        time.sleep(1.5)
        found = _find_group_by_subject(account, subject, known)
        if found:
            group_id = found['id']
    if not group_id:
        raise WhatsAppError(
            'Meta accepted the request but has not confirmed the new group yet. '
            'Wait a moment, then press "Sync groups from Meta" to bring it in.',
        )
    if not invite_link:
        try:
            invite_link = get_invite_link(account, group_id)
        except WhatsAppError:
            invite_link = ''  # the group exists; the link can be fetched later from its row
    return group_id, invite_link


def sync_api_groups(account, office, branch, user=None):
    """Import the account's Business API groups as recipients (skipping ones we
    already have). Returns the list of newly created recipients."""
    have = set()
    for existing in WhatsAppRecipient.objects.filter(office=office).exclude(group_ids=''):
        have.update(existing.group_id_list)
    added = []
    for group in list_groups(account):
        gid = group.get('id')
        if not gid or gid in have:
            continue
        try:
            link = get_invite_link(account, gid)
        except WhatsAppError:
            link = ''
        added.append(WhatsAppRecipient.objects.create(
            office=office, branch=branch, label=(group.get('subject') or 'WhatsApp group')[:100],
            group_ids=gid, invite_link=link, created_by=user,
        ))
    return added


def dispatch_due_schedules(now=None):
    """Called every minute by Celery beat. Runs each active schedule whose send
    time has arrived today and hasn't run yet today. Times live in the database,
    so editing a schedule needs no restart. Returns the schedule ids it ran."""
    now = timezone.localtime(now) if now else timezone.localtime()
    today = now.date()
    ran = []

    due = WhatsAppReportSchedule.objects.filter(is_active=True).exclude(last_run_date=today)
    for schedule in due:
        if now.weekday() not in schedule.weekdays:
            continue
        scheduled_at = timezone.make_aware(datetime.combine(today, schedule.send_time))
        if now < scheduled_at:
            continue

        # Claim the day atomically so two beat ticks / workers can't both send.
        claimed = (
            WhatsAppReportSchedule.objects.filter(pk=schedule.pk).exclude(last_run_date=today)
            .update(last_run_date=today)
        )
        if not claimed:
            continue

        if now - scheduled_at > timedelta(minutes=GRACE_MINUTES):
            _log(
                schedule, status='skipped', triggered_by='schedule',
                error=f'Missed: the scheduler wasn\'t running until {now:%I:%M %p}, more than {GRACE_MINUTES} minutes after the {schedule.send_time:%I:%M %p} send time.',
            )
            continue

        try:
            run_schedule(schedule.pk, triggered_by='schedule')
        except Exception as exc:
            logger.exception('WhatsApp report schedule %s failed to run', schedule.pk)
            _log(
                schedule, status='failed', triggered_by='schedule',
                error=f'The report could not be generated: {type(exc).__name__}: {str(exc)[:300]} (full details in the worker log). '
                      'If this appeared right after an update, restart the Celery worker and beat.',
            )
        ran.append(schedule.pk)
    return ran
