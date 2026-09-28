"""Symmetric encryption for third-party credentials stored in the database
(e.g. a WhatsApp access token), so a database dump alone doesn't expose them.

The key is derived from INTEGRATION_ENCRYPTION_KEY if set, otherwise from
SECRET_KEY. Changing either makes previously stored credentials undecryptable
(admins simply re-enter them), so set INTEGRATION_ENCRYPTION_KEY explicitly in
production rather than relying on a SECRET_KEY that might be rotated.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet():
    seed = getattr(settings, 'INTEGRATION_ENCRYPTION_KEY', None) or settings.SECRET_KEY
    key = base64.urlsafe_b64encode(hashlib.sha256(seed.encode('utf-8')).digest())
    return Fernet(key)


def encrypt(plain_text):
    if not plain_text:
        return ''
    return _fernet().encrypt(plain_text.encode('utf-8')).decode('utf-8')


def decrypt(cipher_text):
    """Returns the plain text, or raises ValueError if it can't be decrypted
    (wrong key, corrupted value)."""
    if not cipher_text:
        return ''
    try:
        return _fernet().decrypt(cipher_text.encode('utf-8')).decode('utf-8')
    except InvalidToken as exc:
        raise ValueError('Stored credential could not be decrypted - the encryption key has changed.') from exc
