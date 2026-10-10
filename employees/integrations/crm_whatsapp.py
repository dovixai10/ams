"""Polls each office's configured CrmWhatsAppLeadSource (a third-party
WhatsApp marketing service's "received messages" endpoint) and turns new
messages into Leads. Called periodically by employees.tasks.poll_crm_whatsapp_leads.

The source endpoint has no "since" parameter - it just returns whatever it
currently has - so dedup is done by checking each message's wamid against
Lead.external_id before creating a row.
"""
import logging

import requests
from django.utils import timezone

logger = logging.getLogger(__name__)


def _extract_leads(payload):
    """The endpoint returns a JSON array of message dicts. Be tolerant of a
    dict wrapper (e.g. {'messages': [...]}) in case the service's shape
    varies between accounts."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ('messages', 'data', 'results'):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def poll_source(source):
    """Poll one CrmWhatsAppLeadSource and create any new Leads from it.
    Returns the number of leads created. Never raises - failures are
    recorded on the source row for the admin to see in CRM Settings."""
    from employees.models import Lead

    headers = {}
    token = source.get_access_token()
    if token:
        headers['Authorization'] = token

    params = {}
    if source.reengage_after_days:
        params['reengage_after_days'] = source.reengage_after_days

    created = 0
    try:
        response = requests.get(source.source_url, headers=headers, params=params, timeout=(5, 20))
        response.raise_for_status()
        messages = _extract_leads(response.json())
    except requests.RequestException as exc:
        source.last_polled_at = timezone.now()
        source.last_poll_ok = False
        source.last_poll_error = str(exc)
        source.save(update_fields=['last_polled_at', 'last_poll_ok', 'last_poll_error'])
        logger.warning('CRM WhatsApp poll failed for office %s: %s', source.office_id, exc)
        return 0
    except ValueError as exc:  # bad JSON
        source.last_polled_at = timezone.now()
        source.last_poll_ok = False
        source.last_poll_error = f'Response was not valid JSON: {exc}'
        source.save(update_fields=['last_polled_at', 'last_poll_ok', 'last_poll_error'])
        return 0

    for item in messages:
        if not isinstance(item, dict):
            continue
        wamid = (item.get('wamid') or '').strip()
        phone = (item.get('contact_number') or item.get('wa_id') or '').strip()
        if not wamid or not phone:
            continue
        if Lead.objects.filter(office=source.office, source=Lead.Source.WHATSAPP, external_id=wamid).exists():
            continue

        lead = Lead.objects.create(
            office=source.office,
            name=(item.get('name') or '').strip() or phone,
            phone=phone,
            message=(item.get('message') or '').strip(),
            source=Lead.Source.WHATSAPP,
            external_id=wamid,
        )
        lead.log_activity(f"WhatsApp message: {lead.message[:80]}" if lead.message else "WhatsApp message received")
        created += 1

    source.last_polled_at = timezone.now()
    source.last_poll_ok = True
    source.last_poll_error = ''
    source.save(update_fields=['last_polled_at', 'last_poll_ok', 'last_poll_error'])
    return created


def poll_all_sources():
    """Poll every active CrmWhatsAppLeadSource. Returns {office_id: created_count}."""
    from employees.models import CrmWhatsAppLeadSource

    results = {}
    for source in CrmWhatsAppLeadSource.objects.filter(is_active=True).select_related('office'):
        results[source.office_id] = poll_source(source)
    return results
