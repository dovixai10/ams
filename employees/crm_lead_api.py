"""Public, unauthenticated endpoint a client's own website can POST its
contact form to, so its leads land directly in this office's CRM - no
account, login or CSRF token needed, since the request comes from a page
this app doesn't control. Identified by the office's CrmWebsiteLeadPage.api_key
(a long random token, safe to embed in client-side HTML/JS - it only scopes
and routes the submission, it isn't a secret credential).

Accepts both a classic HTML <form method="post"> (application/x-www-form-urlencoded)
and a JSON body - DRF's default parsers handle both without extra config, so
a client with no JavaScript at all can integrate by just pointing their
existing form's action= at this URL.
"""
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import CrmWebsiteLeadPage, Lead


@extend_schema(
    tags=['CRM Lead Capture'],
    summary="Submit a lead from your own website's contact form",
    description=(
        "Public endpoint - no authentication required. Point your website's existing contact form's "
        "`action` at this URL (or POST to it with `fetch`/AJAX for an on-page experience), and every "
        "submission becomes a Lead in this office's CRM immediately.\n\n"
        "**Finding your `api_key`**: CRM -> Settings -> Website API, on the office's own CRM Settings page.\n\n"
        "**Required fields**: `name`, `phone`. **Optional**: `email`, `company`, `message`.\n\n"
        "Accepts either a classic HTML form post (`application/x-www-form-urlencoded` / "
        "`multipart/form-data`) or a JSON body - use whichever is easier to integrate."
    ),
    request={
        'application/x-www-form-urlencoded': {
            'type': 'object',
            'properties': {
                'name': {'type': 'string', 'example': 'Mohit Sharma'},
                'phone': {'type': 'string', 'example': '9898989898'},
                'email': {'type': 'string', 'example': 'mohit@example.com'},
                'company': {'type': 'string', 'example': 'Sharma Traders'},
                'message': {'type': 'string', 'example': 'Interested in a demo for our 20-person team.'},
            },
            'required': ['name', 'phone'],
        },
    },
    responses={
        201: {
            'type': 'object',
            'properties': {
                'success': {'type': 'boolean'},
                'message': {'type': 'string'},
                'lead_id': {'type': 'integer'},
            },
        },
        403: {'type': 'object', 'properties': {'success': {'type': 'boolean'}, 'message': {'type': 'string'}}},
        404: {'type': 'object', 'properties': {'success': {'type': 'boolean'}, 'message': {'type': 'string'}}},
        422: {'type': 'object', 'properties': {'success': {'type': 'boolean'}, 'message': {'type': 'string'}}},
    },
    examples=[
        OpenApiExample(
            'Form fields',
            value={'name': 'Mohit Sharma', 'phone': '9898989898', 'email': 'mohit@example.com',
                   'company': 'Sharma Traders', 'message': 'Interested in a demo for our 20-person team.'},
            request_only=True,
        ),
        OpenApiExample(
            '201 response',
            value={'success': True, 'message': "Thanks! We'll be in touch soon.", 'lead_id': 482},
            response_only=True, status_codes=['201'],
        ),
        OpenApiExample(
            '422 missing required field',
            value={'success': False, 'message': 'Please provide your name and phone number.'},
            response_only=True, status_codes=['422'],
        ),
        OpenApiExample(
            '404 unknown/invalid key',
            value={'success': False, 'message': 'Invalid submission link.'},
            response_only=True, status_codes=['404'],
        ),
    ],
)
class CaptureLeadView(APIView):
    """POST /api/v1/leads/capture/<api_key>/"""

    authentication_classes = []  # no session/JWT - a stray cookie would otherwise trip CSRF enforcement
    permission_classes = [AllowAny]

    def post(self, request, api_key):
        page = CrmWebsiteLeadPage.objects.filter(api_key=api_key).select_related('office').first()
        if page is None:
            return Response({'success': False, 'message': 'Invalid submission link.'}, status=status.HTTP_404_NOT_FOUND)
        if not page.is_active:
            return Response(
                {'success': False, 'message': 'This submission link is currently inactive.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        name = str(request.data.get('name', '')).strip()
        phone = str(request.data.get('phone', '')).strip()
        email = str(request.data.get('email', '')).strip()
        company = str(request.data.get('company', '')).strip()
        message = str(request.data.get('message', '')).strip()

        if not name or not phone:
            return Response(
                {'success': False, 'message': 'Please provide your name and phone number.'},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        lead = Lead.objects.create(
            office=page.office, name=name, phone=phone, email=email,
            company=company, message=message, source=Lead.Source.WEBSITE,
        )
        lead.log_activity('Submitted via the website API')

        return Response(
            {'success': True, 'message': "Thanks! We'll be in touch soon.", 'lead_id': lead.pk},
            status=status.HTTP_201_CREATED,
        )
