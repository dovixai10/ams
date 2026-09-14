"""
Shared response envelope + base view for the mobile attendance app API
(employees/mobile_*.py), built against DOVIX_AI_Attendance_Backend_API_Spec.pdf
v1.0 (14 Sep 2026), section 2.3-2.4 and 3.3.

Every mobile endpoint returns exactly:
    {"success": bool, "data": ..., "message": str, "error": {...} | null}
via MobileAPIView.ok(...) / .fail(...) - never DRF's default Response() shape.
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import serializers
from rest_framework.exceptions import (
    APIException, ValidationError as DRFValidationError, NotAuthenticated,
    AuthenticationFailed, PermissionDenied as DRFPermissionDenied,
    NotFound, Throttled, ParseError,
)
from rest_framework import status
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError


class EnvelopeResponseSerializer(serializers.Serializer):
    """The one response shape every mobile endpoint returns - {success, data,
    message, error}. `data`'s inner shape varies per endpoint; see that
    operation's description and examples for what it actually contains.
    Declared once and reused via `responses=EnvelopeResponseSerializer` on
    every @extend_schema so drf-spectacular has something to attach the
    per-endpoint response examples to, instead of guessing (and failing to
    guess) a bespoke schema from a plain APIView with no serializer_class."""
    success = serializers.BooleanField()
    data = serializers.JSONField(allow_null=True)
    message = serializers.CharField(allow_blank=True)
    error = serializers.JSONField(allow_null=True)


# error.code -> default HTTP status, from spec section 3.3. A view can still
# pass an explicit status_code to .fail() to override any of these.
ERROR_STATUS = {
    "INVALID_CREDENTIALS": 401,
    "ACCOUNT_LOCKED": 429,
    "TOKEN_EXPIRED": 401,
    "TOKEN_INVALID": 401,
    "ALREADY_CHECKED_IN": 409,
    "NOT_CHECKED_IN": 409,
    "FACE_NOT_REGISTERED": 409,
    "FACE_MISMATCH": 422,
    "NO_FACE_DETECTED": 422,
    "MULTIPLE_FACES": 422,
    "OUTSIDE_GEOFENCE": 422,
    "INSUFFICIENT_LEAVE_BALANCE": 422,
    "OVERLAPPING_LEAVE": 422,
    "INVALID_DATE_RANGE": 422,
    "UNSUPPORTED_FILE_TYPE": 415,
    "FILE_TOO_LARGE": 413,
    "VALIDATION_ERROR": 400,
    "NOT_FOUND": 404,
    "FORBIDDEN": 403,
    "SERVER_ERROR": 500,
}


class MobileAPIException(APIException):
    """Raise this from any mobile view/serializer to produce a spec-shaped
    error envelope automatically, e.g.:
        raise MobileAPIException('FACE_MISMATCH', 'Face does not match...', details={...})
    """
    def __init__(self, code, message, status_code=None, field=None, details=None):
        self.code = code
        self.field = field
        self.details = details
        self.status_code = status_code or ERROR_STATUS.get(code, 400)
        super().__init__(detail=message, code=code)


def envelope_success(data=None, message=""):
    return {"success": True, "data": data, "message": message, "error": None}


def envelope_error(code, message, field=None, details=None):
    return {
        "success": False,
        "data": None,
        "message": message,
        "error": {"code": code, "field": field, "details": details},
    }


class MobileAPIView(APIView):
    """Base class for every mobile endpoint. Handles auth (JWT by default),
    the response envelope, and mapping both our own MobileAPIException and
    DRF's built-in exceptions into the spec's error shape."""

    authentication_classes = [JWTAuthentication]

    def ok(self, data=None, message="", status_code=status.HTTP_200_OK):
        return Response(envelope_success(data, message), status=status_code)

    def fail(self, code, message, status_code=None, field=None, details=None):
        status_code = status_code or ERROR_STATUS.get(code, 400)
        return Response(envelope_error(code, message, field, details), status=status_code)

    def handle_exception(self, exc):
        if isinstance(exc, MobileAPIException):
            return self.fail(exc.code, str(exc.detail), exc.status_code, exc.field, exc.details)

        if isinstance(exc, (InvalidToken, TokenError)):
            return self.fail("TOKEN_EXPIRED", "Access token expired or invalid.", 401)

        if isinstance(exc, (NotAuthenticated, AuthenticationFailed)):
            return self.fail("TOKEN_EXPIRED", "Authentication required.", 401)

        if isinstance(exc, DRFPermissionDenied):
            return self.fail("FORBIDDEN", "You do not have permission to perform this action.", 403)

        if isinstance(exc, NotFound):
            return self.fail("NOT_FOUND", "The requested resource was not found.", 404)

        if isinstance(exc, Throttled):
            wait = getattr(exc, 'wait', None)
            return self.fail(
                "ACCOUNT_LOCKED", "Too many attempts. Please try again later.", 429,
                details={"retryAfterSeconds": wait} if wait else None,
            )

        if isinstance(exc, (DRFValidationError, ParseError)):
            detail = exc.detail
            field = None
            if isinstance(detail, dict) and detail:
                field = next(iter(detail.keys()))
                message = str(detail[field][0]) if isinstance(detail[field], list) else str(detail[field])
            elif isinstance(detail, list) and detail:
                message = str(detail[0])
            else:
                message = str(detail)
            return self.fail("VALIDATION_ERROR", message, 400, field=field)

        # Anything else: let it surface as a generic 500 in the envelope
        # rather than DRF's plain-text/HTML error page.
        import logging
        logging.getLogger(__name__).exception("Unhandled mobile API error")
        return self.fail("SERVER_ERROR", "Something went wrong. Please try again.", 500)
