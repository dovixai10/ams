"""Client for the local WhatsApp helper (`whatsapp_web/server.mjs`) that keeps
QR-linked phones logged in and sends through them.

Errors are raised as WhatsAppError - the same type the Business API client uses -
so the Celery retry rules and the message log treat both channels identically.
`transient=True` means "worth retrying" (helper restarting, phone reconnecting).
"""
import io
import logging
from pathlib import Path

import requests
from django.conf import settings

from .whatsapp_client import WhatsAppError

logger = logging.getLogger(__name__)

DEFAULT_URL = 'http://127.0.0.1:3100'
HELPER_DIR = Path(settings.BASE_DIR) / 'whatsapp_web'
HELPER_DOWN = (
    "The WhatsApp helper service isn't running. Start it with "
    "'node server.mjs' inside the whatsapp_web folder."
)


def _base_url():
    return (getattr(settings, 'WHATSAPP_WEB_URL', '') or DEFAULT_URL).rstrip('/')


def _token():
    token = getattr(settings, 'WHATSAPP_WEB_TOKEN', '')
    if token:
        return token
    try:  # the helper creates this file on its first start
        return (HELPER_DIR / 'data' / 'token').read_text(encoding='utf-8').strip()
    except OSError:
        return ''


def _request(method, path, json=None, params=None, timeout=(3, 15)):
    try:
        response = requests.request(
            method, f'{_base_url()}{path}', json=json, params=params,
            headers={'x-sidecar-token': _token()}, timeout=timeout,
        )
    except requests.ConnectionError:
        raise WhatsAppError(HELPER_DOWN, transient=True)
    except requests.Timeout:
        raise WhatsAppError('The WhatsApp helper did not answer in time.', transient=True)
    except requests.RequestException as exc:
        raise WhatsAppError(f'Could not reach the WhatsApp helper: {exc}', transient=True)

    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code == 401:
        raise WhatsAppError(
            'The WhatsApp helper rejected the shared token. Make sure WHATSAPP_WEB_TOKEN matches '
            "the helper's, or delete whatsapp_web/data/token and restart the helper.",
        )
    if response.status_code >= 400:
        message = data.get('error') or f'The WhatsApp helper returned HTTP {response.status_code}.'
        transient = data.get('transient', response.status_code >= 500)
        raise WhatsAppError(message, transient=bool(transient), status_code=response.status_code)
    return data


def status(session_id):
    """{'status': not_started|connecting|qr|connected|closed|logged_out, 'qr', 'phone', 'name'}"""
    return _request('GET', f'/sessions/{session_id}', timeout=(2, 5))


def start(session_id):
    """Begin (or resume) linking - a QR code appears in status() shortly after."""
    return _request('POST', f'/sessions/{session_id}/start')


def logout(session_id):
    return _request('POST', f'/sessions/{session_id}/logout')


def groups(session_id, refresh=False):
    return _request('GET', f'/sessions/{session_id}/groups', params={'refresh': '1'} if refresh else None, timeout=(3, 30))['groups']


def send(session_id, *, kind, to, text):
    """Send plain text. kind='person' (a phone number) or 'group' (a group name or @g.us id).
    Returns the WhatsApp message id."""
    data = _request('POST', f'/sessions/{session_id}/send', json={'kind': kind, 'to': to, 'text': text}, timeout=(3, 60))
    return data.get('id', '')


def qr_svg(qr_text):
    """Render the pairing string as an inline SVG QR code (no image files needed)."""
    import qrcode
    import qrcode.image.svg

    image = qrcode.make(qr_text, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buffer = io.BytesIO()
    image.save(buffer)
    return buffer.getvalue().decode('utf-8')
