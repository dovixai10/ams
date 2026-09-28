"""Thin client for the Meta WhatsApp Cloud API's send-message endpoint.

    POST https://graph.facebook.com/{version}/{phone_number_id}/messages

Two message shapes are used:
  * template - a Meta-approved template with filled-in variables. The only kind
    that can be sent to someone who hasn't messaged the business in the last
    24 hours, which is what a scheduled report is.
  * text     - free-form text. Only delivered inside that 24-hour window.

A group is addressed with recipient_type="group" and the group's ID as `to`
(Meta's Groups API - which Meta only enables for eligible business accounts, so
a group send can be rejected by Meta even when everything here is correct).
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_GRAPH_BASE = 'https://graph.facebook.com'

# Meta error codes worth explaining in plain words to whoever manages this.
ERROR_HINTS = {
    190: 'The access token is invalid or expired - update it in the WhatsApp account settings.',
    131047: "The recipient hasn't messaged this number in the last 24 hours, so plain text can't be delivered. Use an approved template instead.",
    131030: "This number isn't on your allowed recipient list (a Meta test number only sends to numbers added in the developer console).",
    131026: "The recipient can't receive WhatsApp messages (number not on WhatsApp, or hasn't accepted the latest terms).",
    132000: "The template's variable count doesn't match what was sent.",
    132001: "That template name/language doesn't exist or isn't approved yet.",
    132005: 'The template text was too long once the variables were filled in.',
    132007: 'The template content violates a WhatsApp policy.',
    100: 'Meta rejected a parameter - check the phone number ID, recipient or group ID.',
}
# Codes that mean "try again shortly" rather than "this will never work".
TRANSIENT_CODES = {1, 2, 4, 17, 341, 368, 80007, 130429, 131016, 131056}


class WhatsAppError(Exception):
    def __init__(self, message, *, code=None, transient=False, status_code=None):
        super().__init__(message)
        self.code = code
        self.transient = transient
        self.status_code = status_code


def _call(account, method, path, payload=None, params=None):
    """One authenticated call to the Graph API. Returns the parsed JSON;
    raises WhatsAppError (with a plain-English hint for known Meta codes)."""
    try:
        token = account.get_access_token()
    except ValueError as exc:
        raise WhatsAppError(str(exc))
    if not token:
        raise WhatsAppError('No access token is saved for this WhatsApp account.')

    base = getattr(settings, 'WHATSAPP_GRAPH_BASE', None) or DEFAULT_GRAPH_BASE
    url = f"{base.rstrip('/')}/{account.api_version}/{path.lstrip('/')}"
    headers = {'Authorization': f'Bearer {token}'}
    try:
        if method == 'GET':
            response = requests.get(url, params=params, headers=headers, timeout=(5, 20))
        else:
            response = requests.post(url, json=payload, headers=headers, timeout=(5, 20))
    except requests.RequestException as exc:
        raise WhatsAppError(f'Could not reach WhatsApp: {exc}', transient=True)

    try:
        data = response.json()
    except ValueError:
        data = {}

    if response.status_code >= 400 or 'error' in data:
        error = data.get('error') or {}
        code = error.get('code')
        details = (error.get('error_data') or {}).get('details') or error.get('message') or response.text[:300]
        hint = ERROR_HINTS.get(code)
        transient = response.status_code >= 500 or response.status_code == 429 or code in TRANSIENT_CODES
        message = f'{details} (code {code})' if code else str(details)
        if hint:
            message = f'{message} - {hint}'
        raise WhatsAppError(message, code=code, transient=transient, status_code=response.status_code)
    return data


def _post(account, payload):
    data = _call(account, 'POST', f'{account.phone_number_id}/messages', payload=payload)
    messages = data.get('messages') or []
    return messages[0].get('id', '') if messages else ''


# ---- Groups API (Official Business Accounts only) -------------------------

def create_group(account, subject, description='', join_approval_mode='auto_approve'):
    """Create a WhatsApp group owned by the business number.
    POST /{phone_number_id}/groups. Meta may answer with the group id and invite
    link straight away, or only a request id (the details then follow by webhook) -
    the caller handles both: `group_id` is '' in the second case."""
    payload = {'messaging_product': 'whatsapp', 'subject': subject, 'join_approval_mode': join_approval_mode}
    if description:
        payload['description'] = description
    data = _call(account, 'POST', f'{account.phone_number_id}/groups', payload=payload)
    return {
        'group_id': data.get('id') or data.get('group_id') or '',
        'invite_link': data.get('invite_link', ''),
        'request_id': data.get('request_id', ''),
    }


def list_groups(account, limit=1024):
    """Active groups of this business number: [{'id', 'subject', ...}]."""
    data = _call(account, 'GET', f'{account.phone_number_id}/groups', params={'limit': limit})
    return data.get('data') or []


def get_invite_link(account, group_id):
    """GET /{group_id}/invite_link"""
    data = _call(account, 'GET', f'{group_id}/invite_link')
    return data.get('invite_link', '')


def send_message(account, *, to, recipient_type, mode, payload):
    """Send one message. `payload` is the stored message content:
        text     -> {'body': '...'}
        template -> {'template': 'name', 'language': 'en', 'params': ['a', 'b']}
    Returns the WhatsApp message id; raises WhatsAppError on failure."""
    body = {
        'messaging_product': 'whatsapp',
        'recipient_type': 'group' if recipient_type == 'group' else 'individual',
        'to': to,
    }
    if mode == 'template':
        template = {'name': payload['template'], 'language': {'code': payload.get('language') or 'en'}}
        params = payload.get('params') or []
        if params:
            template['components'] = [{
                'type': 'body',
                'parameters': [{'type': 'text', 'text': str(p)} for p in params],
            }]
        body.update(type='template', template=template)
    else:
        body.update(type='text', text={'preview_url': False, 'body': payload['body']})
    return _post(account, body)
