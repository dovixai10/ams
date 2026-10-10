"""Celery tasks. Thin wrappers - the logic lives in employees.integrations."""
import logging

from celery import shared_task

from .integrations.crm_whatsapp import poll_all_sources
from .integrations.services import deliver_log, dispatch_due_schedules
from .integrations.whatsapp_client import WhatsAppError
from .models import WhatsAppMessageLog

logger = logging.getLogger(__name__)


@shared_task(name='employees.tasks.dispatch_due_whatsapp_reports')
def dispatch_due_whatsapp_reports():
    """Beat runs this every minute: send any WhatsApp report schedule that's due."""
    ran = dispatch_due_schedules()
    if ran:
        logger.info('Dispatched WhatsApp report schedules: %s', ran)
    return ran


@shared_task(name='employees.tasks.poll_crm_whatsapp_leads')
def poll_crm_whatsapp_leads():
    """Beat runs this every couple of minutes: pull new messages from each
    office's configured WhatsApp lead source and create Leads from them."""
    results = poll_all_sources()
    created = sum(results.values())
    if created:
        logger.info('CRM WhatsApp poll created %s lead(s) across %s office(s)', created, len(results))
    return results


@shared_task(bind=True, max_retries=3, name='employees.tasks.send_whatsapp_log')
def send_whatsapp_log(self, log_id):
    """Send one queued WhatsApp message. A temporary problem (network, Meta
    rate limit / 5xx) is retried with growing delays; a permanent one (bad
    token, unknown number, unapproved template) is recorded and left alone."""
    try:
        deliver_log(log_id)
    except WhatsAppError as exc:
        if exc.transient and self.request.retries < self.max_retries:
            WhatsAppMessageLog.objects.filter(pk=log_id).update(status=WhatsAppMessageLog.Status.QUEUED)
            raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
        logger.warning('WhatsApp message %s failed: %s', log_id, exc)
