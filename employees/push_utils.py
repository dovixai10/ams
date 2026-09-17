"""Firebase Cloud Messaging (push notifications) to the mobile app.

One function to call: send_push_to_employee(). Everything else here is
plumbing. Hooked into notification_utils.create_notification() so every
existing in-app notification trigger (task assigned, leave approved/
rejected, face update decided, ticket resolved, ...) automatically also
sends a push, with no changes needed at any of those call sites.

Fails soft everywhere on purpose: a phone with a dead token, a missing
service account file (not configured yet), or Firebase being down should
never break the request that triggered the notification - the in-app
EmployeeNotification row is the source of truth; push is a best-effort
nudge on top of it.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_firebase_app = None
_firebase_init_attempted = False


def _get_firebase_app():
    """Lazily initializes the Firebase Admin app from
    settings.FIREBASE_CREDENTIALS_PATH, once per process. Returns None
    (without raising) if the credentials file isn't there yet, or if the
    firebase-admin package isn't installed, or init otherwise fails -
    callers treat that as "push isn't configured, skip it" rather than
    an error."""
    global _firebase_app, _firebase_init_attempted

    if _firebase_app is not None:
        return _firebase_app
    if _firebase_init_attempted:
        return None
    _firebase_init_attempted = True

    import os
    cred_path = getattr(settings, 'FIREBASE_CREDENTIALS_PATH', None)
    if not cred_path or not os.path.exists(cred_path):
        logger.info(
            "Firebase push notifications not configured (no service account "
            "file at %s) - notifications will still be created in-app, just "
            "not pushed.", cred_path,
        )
        return None

    try:
        import firebase_admin
        from firebase_admin import credentials
        cred = credentials.Certificate(cred_path)
        _firebase_app = firebase_admin.initialize_app(cred)
        logger.info("Firebase Admin SDK initialized for push notifications.")
        return _firebase_app
    except Exception:
        logger.exception("Failed to initialize Firebase Admin SDK - push notifications disabled.")
        return None


def send_push_to_employee(employee, title, body, data=None):
    """Push `title`/`body` to every device this employee has registered
    (see DeviceRegistration - an employee can have more than one, e.g.
    phone + tablet, and each gets its own send). `data` is an optional
    dict of extra string fields delivered alongside the notification for
    the app to use when the user taps it (e.g. deep-linking to the right
    screen) - values are coerced to str since FCM data payloads must be
    string-to-string.

    Safe to call unconditionally from anywhere: does nothing (no
    exception) if Firebase isn't configured, the employee has no
    registered devices, or sending fails for some/all of them. Any device
    whose token FCM reports as no-longer-valid gets deleted from
    DeviceRegistration so it stops being tried."""
    app = _get_firebase_app()
    if app is None:
        return

    from .models import DeviceRegistration
    devices = list(DeviceRegistration.objects.filter(employee=employee).exclude(fcm_token=''))
    if not devices:
        return

    from firebase_admin import messaging

    string_data = {str(k): str(v) for k, v in (data or {}).items() if v is not None}

    for device in devices:
        try:
            messaging.send(messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                data=string_data,
                token=device.fcm_token,
                android=messaging.AndroidConfig(priority='high'),
                apns=messaging.APNSConfig(
                    payload=messaging.APNSPayload(aps=messaging.Aps(sound='default'))
                ),
            ))
        except messaging.UnregisteredError:
            # Token is dead (app uninstalled, etc.) - stop trying it.
            device.delete()
        except Exception:
            # Any other failure (network blip, bad token format, Firebase
            # outage) - log and move on to the next device; never let a
            # push failure bubble up into the caller's own request.
            logger.exception("Push notification failed for device %s (employee %s).", device.device_id, employee.id)
