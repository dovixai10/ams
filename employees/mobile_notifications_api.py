"""
Mobile API - Notifications (spec section 11, 5 endpoints).
GET /notifications, PATCH /notifications/{id}/read, POST /notifications/mark-all-read,
GET /notifications/unread-count, POST /notifications/register-device

The web app already generates notifications across many more types than the
spec's closed 5-value NotificationType enum (ATTENDANCE/DOCUMENT/LEAVE/SHIFT/
REPORT) - see TYPE_MAP below for how each of this app's real types collapses
onto the nearest spec value, documented in the shared API docs.
"""
from rest_framework import serializers
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiParameter, OpenApiTypes

from .mobile_response import MobileAPIView, MobileAPIException, EnvelopeResponseSerializer
from .mobile_common import paginate
from .models import EmployeeNotification, DeviceRegistration

TAG = 'Notifications'


class RegisterDeviceRequestSerializer(serializers.Serializer):
    deviceId = serializers.CharField()
    fcmToken = serializers.CharField(required=False)
    platform = serializers.ChoiceField(choices=['ANDROID', 'IOS'], required=False)


TYPE_MAP = {
    'leave_approved': 'LEAVE', 'leave_rejected': 'LEAVE', 'leave_pending': 'LEAVE',
    'document_required': 'DOCUMENT', 'document_verified': 'DOCUMENT', 'id_card_generated': 'DOCUMENT',
    'rule_update': 'SHIFT',
}


def _spec_type(notification_type):
    return TYPE_MAP.get(notification_type, 'ATTENDANCE')


def _serialize(n):
    return {
        "id": f"ntf_{n.id}",
        "type": _spec_type(n.notification_type),
        "title": n.title,
        "body": n.message,
        "createdAt": n.created_at.isoformat(),
        "isRead": n.is_read,
        "deepLink": n.action_url or None,
    }


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="List notifications",
    parameters=[OpenApiParameter('page', OpenApiTypes.INT), OpenApiParameter('pageSize', OpenApiTypes.INT)],
    description="Client groups items under Today/Yesterday/Earlier itself from `createdAt` - no grouping field needed here.",
)
class NotificationsListView(MobileAPIView):
    """GET /notifications?page=1&pageSize=20"""

    def get(self, request):
        employee = request.user.employee_profile
        qs = EmployeeNotification.objects.filter(employee=employee).order_by('-created_at')
        unread_count = qs.filter(is_read=False).count()
        items, pagination = paginate(list(qs), request.GET.get('page'), request.GET.get('pageSize'))
        return self.ok({
            "unreadCount": unread_count,
            "notifications": [_serialize(n) for n in items],
            "pagination": pagination,
        })


@extend_schema(
    request=None,
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="Mark one read",
    parameters=[OpenApiParameter('id', OpenApiTypes.INT, location=OpenApiParameter.PATH, description='Numeric suffix of the ntf_N id')],
)
class MarkNotificationReadView(MobileAPIView):
    """PATCH /notifications/{id}/read - id is the numeric suffix of ntf_N."""

    def patch(self, request, id):
        employee = request.user.employee_profile
        notification = EmployeeNotification.objects.filter(employee=employee, id=id).first()
        if notification is None:
            raise MobileAPIException('NOT_FOUND', 'Notification not found.', 404)
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=['is_read'])
        unread_count = EmployeeNotification.objects.filter(employee=employee, is_read=False).count()
        return self.ok({"unreadCount": unread_count})


@extend_schema(request=None, responses=EnvelopeResponseSerializer, tags=[TAG], summary="Mark all read", description="Backs the app bar's \"Mark all read\" action.")
class MarkAllNotificationsReadView(MobileAPIView):
    """POST /notifications/mark-all-read"""

    def post(self, request):
        employee = request.user.employee_profile
        EmployeeNotification.objects.filter(employee=employee, is_read=False).update(is_read=True)
        return self.ok({"unreadCount": 0})


@extend_schema(responses=EnvelopeResponseSerializer, tags=[TAG], summary="Header badge count", description="Polled on every screen focus - kept to a single COUNT query.")
class UnreadCountView(MobileAPIView):
    """GET /notifications/unread-count - kept deliberately cheap (one COUNT)."""

    def get(self, request):
        employee = request.user.employee_profile
        count = EmployeeNotification.objects.filter(employee=employee, is_read=False).count()
        return self.ok({"unreadCount": count})


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="Register a device for push",
    description=(
        "Call this once after login (and again whenever the FCM token refreshes - "
        "Firebase can rotate it at any time) so the backend knows where to push "
        "notifications for this device. `deviceId` should be a stable, "
        "client-generated identifier (persisted locally, not regenerated per "
        "launch) so re-registering the same device updates its token instead of "
        "creating a duplicate - a device with no `fcmToken` yet (e.g. permission "
        "not granted) is still fine to register, it just won't receive pushes "
        "until a token is added. An employee can have several registered devices "
        "at once (phone + tablet, etc.) - every one of them gets pushed to."
    ),
    request=RegisterDeviceRequestSerializer,
)
class RegisterDeviceView(MobileAPIView):
    """POST /notifications/register-device"""

    def post(self, request):
        device_id = request.data.get('deviceId')
        if not device_id:
            raise MobileAPIException('VALIDATION_ERROR', 'deviceId is required.', 400, field='deviceId')

        employee = request.user.employee_profile
        DeviceRegistration.objects.update_or_create(
            employee=employee, device_id=device_id,
            defaults={
                'fcm_token': request.data.get('fcmToken', ''),
                'platform': (request.data.get('platform') or '').upper(),
            },
        )
        return self.ok(message="Device registered for push notifications.")
