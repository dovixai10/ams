"""
Mobile API - Authentication (spec section 4, 5 endpoints).
POST /auth/login, /auth/refresh, /auth/logout, /auth/forgot-password, /auth/reset-password
"""
import re

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.mail import send_mail
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.conf import settings

# Independent of Django's global PASSWORD_RESET_TIMEOUT (which the existing
# web "forgot password" flow uses, default_token_generator-based, and stays
# untouched) - the spec calls for exactly 30 minutes for the mobile API.
RESET_TOKEN_MAX_AGE_SECONDS = 30 * 60
_reset_signer = TimestampSigner(salt='mobile-api-password-reset')
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken

from rest_framework import serializers
from drf_spectacular.utils import extend_schema, OpenApiExample

from .mobile_response import MobileAPIView, MobileAPIException, EnvelopeResponseSerializer
from .mobile_common import employee_code, resolve_employee_by_identifier
from .permissions import is_employee

LOGIN_RATE_LIMIT = 5
LOGIN_RATE_WINDOW_SECONDS = 15 * 60

TAG = 'Authentication'


class LoginRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField(help_text="Employee code (e.g. KI00014) or work email")
    password = serializers.CharField(style={'input_type': 'password'})
    rememberMe = serializers.BooleanField(required=False, default=False, help_text="30-day refresh token instead of 7")
    deviceId = serializers.CharField(required=False, help_text="Stable device identifier, for push targeting")


class RefreshRequestSerializer(serializers.Serializer):
    refreshToken = serializers.CharField()


class LogoutRequestSerializer(serializers.Serializer):
    refreshToken = serializers.CharField(required=False)
    deviceId = serializers.CharField(required=False)


class ForgotPasswordRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField(help_text="Employee code or work email")


class ResetPasswordRequestSerializer(serializers.Serializer):
    token = serializers.CharField(help_text="From the link in the reset email")
    newPassword = serializers.CharField(style={'input_type': 'password'})

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _issue_tokens(user, remember_me=False):
    refresh = RefreshToken.for_user(user)
    if remember_me:
        from datetime import timedelta
        refresh.set_exp(lifetime=timedelta(days=30))
    access = refresh.access_token
    return {
        "accessToken": str(access),
        "refreshToken": str(refresh),
        "expiresIn": int(access.lifetime.total_seconds()),
        "tokenType": "Bearer",
    }


def _user_payload(employee):
    return {
        "employeeId": employee_code(employee),
        "name": employee.full_name or employee.name,
        "workEmail": employee.email,
        "department": employee.department.name if employee.department else None,
        "designation": employee.designation.name if employee.designation else None,
        "avatarUrl": (employee.profile_picture.url if employee.profile_picture else None),
        "faceIdRegistered": bool(employee.has_registered_face),
    }


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG],
    summary="Log in",
    description=(
        "Authenticate by employee code or work email. Rate-limited to 5 attempts per "
        "identifier per 15 minutes, then ACCOUNT_LOCKED. On success, `device_id` (if sent) "
        "registers this device for push notifications too."
    ),
    request=LoginRequestSerializer,
    examples=[
        OpenApiExample('Request', value={"identifier": "kamal@dovixai.com", "password": "••••••••", "rememberMe": False}, request_only=True),
        OpenApiExample('200 response', value={
            "accessToken": "eyJhbGciOi...", "refreshToken": "eyJhbGciOi...", "expiresIn": 3600, "tokenType": "Bearer",
            "user": {"employeeId": "KI00014", "name": "Kamal", "workEmail": "kamal@dovixai.com",
                     "department": None, "designation": None, "avatarUrl": None, "faceIdRegistered": True},
        }, response_only=True),
    ],
)
class LoginView(MobileAPIView):
    """POST /auth/login"""
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        identifier = (request.data.get('identifier') or '').strip()
        password = request.data.get('password') or ''
        remember_me = bool(request.data.get('rememberMe'))
        device_id = request.data.get('deviceId')

        if not identifier or not password:
            raise MobileAPIException('VALIDATION_ERROR', 'identifier and password are required.', 400, field='identifier')

        cache_key = f"mobile_login_attempts:{identifier.lower()}"
        attempts = cache.get(cache_key, 0)
        if attempts >= LOGIN_RATE_LIMIT:
            raise MobileAPIException(
                'ACCOUNT_LOCKED',
                'Too many failed login attempts. Please try again later.',
                429, details={"retryAfterSeconds": LOGIN_RATE_WINDOW_SECONDS},
            )

        employee = resolve_employee_by_identifier(identifier)
        user = None
        if employee is not None and employee.user_id:
            user = authenticate(request, username=employee.user.username, password=password)

        if user is None or employee is None or not is_employee(user):
            cache.set(cache_key, attempts + 1, LOGIN_RATE_WINDOW_SECONDS)
            raise MobileAPIException('INVALID_CREDENTIALS', 'Invalid identifier or password.', 401)

        cache.delete(cache_key)

        if device_id:
            from .models import DeviceRegistration
            DeviceRegistration.objects.update_or_create(
                employee=employee, device_id=device_id, defaults={},
            )

        tokens = _issue_tokens(user, remember_me)
        return self.ok({**tokens, "user": _user_payload(employee)})


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="Refresh the access token",
    description="Rotates the refresh token on every use - the previous one is blacklisted immediately.",
    request=RefreshRequestSerializer,
)
class RefreshView(MobileAPIView):
    """POST /auth/refresh - rotates the refresh token on every use
    (ROTATE_REFRESH_TOKENS + BLACKLIST_AFTER_ROTATION in SIMPLE_JWT settings
    make TokenRefreshSerializer blacklist the old one and issue a new one)."""
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get('refreshToken')
        if not token:
            raise MobileAPIException('VALIDATION_ERROR', 'refreshToken is required.', 400, field='refreshToken')

        from rest_framework_simplejwt.serializers import TokenRefreshSerializer
        serializer = TokenRefreshSerializer(data={'refresh': token})
        try:
            serializer.is_valid(raise_exception=True)
        except Exception:
            raise MobileAPIException('TOKEN_EXPIRED', 'Refresh token expired or invalid.', 401)

        validated = serializer.validated_data
        from rest_framework_simplejwt.settings import api_settings as jwt_settings
        return self.ok({
            "accessToken": validated['access'],
            "refreshToken": validated.get('refresh', token),
            "expiresIn": int(jwt_settings.ACCESS_TOKEN_LIFETIME.total_seconds()),
        })


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="Log out",
    description="Blacklists the refresh token and unregisters the device. Always returns 200, even for an already-invalid token.",
    request=LogoutRequestSerializer,
)
class LogoutView(MobileAPIView):
    """POST /auth/logout - always 200, even on an already-invalid token."""

    def post(self, request):
        refresh_token = request.data.get('refreshToken')
        if refresh_token:
            try:
                RefreshToken(refresh_token).blacklist()
            except (TokenError, Exception):
                pass

        device_id = request.data.get('deviceId')
        if device_id and hasattr(request.user, 'employee_profile'):
            from .models import DeviceRegistration
            DeviceRegistration.objects.filter(
                employee=request.user.employee_profile, device_id=device_id,
            ).delete()

        return self.ok(message="Logged out successfully.")


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="Request a password reset",
    description="Always returns 200 with a neutral message, whether or not the identifier exists - never leaks account existence. Reset link is valid 30 minutes, single use.",
    request=ForgotPasswordRequestSerializer,
)
class ForgotPasswordView(MobileAPIView):
    """POST /auth/forgot-password - always 200, never leaks account existence."""
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        identifier = (request.data.get('identifier') or '').strip()
        if not identifier:
            raise MobileAPIException('VALIDATION_ERROR', 'identifier is required.', 400, field='identifier')

        if '@' in identifier:
            if not EMAIL_RE.match(identifier):
                raise MobileAPIException('VALIDATION_ERROR', 'Enter a valid email address.', 400, field='identifier')
        elif len(identifier) < 4 or ' ' in identifier:
            raise MobileAPIException('VALIDATION_ERROR', 'Enter a valid employee ID.', 400, field='identifier')

        employee = resolve_employee_by_identifier(identifier)
        if employee is not None and employee.user_id:
            user = employee.user
            # Single-use, 30-minute token: embeds the CURRENT password hash,
            # so once it's used (and the password changes) or a fresher
            # token is requested and used, this one stops verifying too -
            # no extra DB state needed to track "already used".
            token = _reset_signer.sign(f"{user.pk}:{user.password}")
            reset_base = getattr(settings, 'MOBILE_APP_RESET_PASSWORD_URL_BASE', 'https://app.dovixai.com/reset-password')
            reset_link = f"{reset_base}?token={token}"
            try:
                send_mail(
                    subject="Reset your DOVIX AI password",
                    message=f"Use this link to reset your password (valid 30 minutes): {reset_link}",
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email or employee.email],
                    fail_silently=True,
                )
            except Exception:
                pass

        return self.ok(message="If an account exists for that identifier, a reset link has been sent.")


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="Complete a password reset",
    description="On success, every existing session/refresh token for this user is invalidated - the client should treat this like a fresh login.",
    request=ResetPasswordRequestSerializer,
)
class ResetPasswordView(MobileAPIView):
    """POST /auth/reset-password"""
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get('token') or ''
        new_password = request.data.get('newPassword') or ''

        if not token or not new_password:
            raise MobileAPIException('VALIDATION_ERROR', 'token and newPassword are required.', 400, field='token')

        try:
            unsigned = _reset_signer.unsign(token, max_age=RESET_TOKEN_MAX_AGE_SECONDS)
            user_pk, password_hash_at_send_time = unsigned.split(':', 1)
            user = User.objects.get(pk=int(user_pk))
        except (BadSignature, SignatureExpired, User.DoesNotExist, ValueError):
            raise MobileAPIException('VALIDATION_ERROR', 'Invalid or expired reset link.', 400, field='token')

        if user.password != password_hash_at_send_time:
            # Password already changed since this link was sent (another
            # reset completed, or an admin changed it) - token is spent.
            raise MobileAPIException('VALIDATION_ERROR', 'Invalid or expired reset link.', 400, field='token')

        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError as DjangoValidationError
        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as e:
            raise MobileAPIException('VALIDATION_ERROR', '; '.join(e.messages), 400, field='newPassword',
                                      details={"rules": e.messages})

        user.set_password(new_password)
        user.save(update_fields=['password'])

        # Invalidate all existing sessions/refresh tokens for this user.
        for outstanding in OutstandingToken.objects.filter(user=user):
            BlacklistedToken.objects.get_or_create(token=outstanding)

        return self.ok(message="Password reset successfully. Please log in again.")
