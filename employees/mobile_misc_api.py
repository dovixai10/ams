"""
Mobile API - Shift, holidays, and employee services (spec section 14, 7 endpoints).
GET /employees/me/shift, GET /employees/me/achievements, GET /holidays,
POST /shift-swap-requests, POST /expense-claims, POST /hr-tickets, GET /company-policies
(the last four are explicit phase-2 stubs per the spec - no client screens yet)
"""
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import serializers
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiParameter, OpenApiTypes

from .mobile_response import MobileAPIView, MobileAPIException, EnvelopeResponseSerializer
from .models import Holiday, Attendance

HOLIDAY_TYPE_MAP = {'public': 'NATIONAL', 'company': 'COMPANY', 'optional': 'OPTIONAL'}
TAG_SHIFT = 'Shift & Holidays'
TAG_PHASE2 = 'Employee Services (Phase 2)'


class ShiftSwapRequestSerializer(serializers.Serializer):
    requestedDate = serializers.DateField()
    swapWithEmployeeId = serializers.CharField(help_text="Employee code or work email")
    reason = serializers.CharField(required=False)


class ExpenseClaimRequestSerializer(serializers.Serializer):
    category = serializers.CharField()
    amount = serializers.FloatField()
    date = serializers.DateField()
    description = serializers.CharField(required=False)
    receipt = serializers.FileField(required=False, help_text="JPEG, PNG or PDF, 10 MB cap")


class HRTicketRequestSerializer(serializers.Serializer):
    subject = serializers.CharField()
    category = serializers.CharField(required=False)
    description = serializers.CharField(required=False)


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG_SHIFT], summary="Shift timing, grace period, geofence",
    description="`workingDays` currently always returns Mon-Sat - there's no per-shift working-day configuration in this system yet.",
)
class ShiftView(MobileAPIView):
    """GET /employees/me/shift"""

    def get(self, request):
        employee = request.user.employee_profile
        shift = employee.shift
        if shift is None:
            raise MobileAPIException('NOT_FOUND', 'No shift is assigned to this employee yet.', 404)

        branch = employee.branch
        office_payload = None
        if branch and branch.latitude is not None and branch.longitude is not None:
            office_payload = {
                "name": branch.name, "latitude": float(branch.latitude), "longitude": float(branch.longitude),
                "geofenceRadiusMeters": branch.attendance_radius_meters or 250,
            }
        elif employee.office and employee.office.latitude is not None:
            office_payload = {
                "name": employee.office.name, "latitude": float(employee.office.latitude),
                "longitude": float(employee.office.longitude),
                "geofenceRadiusMeters": 250,
            }

        # Half-day threshold, as seconds - reuses the same office/shift
        # threshold config the web app's attendance calculations already use.
        try:
            from .shift_attendance_logic import get_shift_half_day_threshold
            half_day_hours = get_shift_half_day_threshold(shift, office=employee.office)
            half_day_seconds = int(float(half_day_hours) * 3600)
        except Exception:
            half_day_seconds = 14400

        return self.ok({
            "shiftName": shift.name,
            "start": shift.start_time.strftime('%H:%M'),
            "end": shift.end_time.strftime('%H:%M'),
            "graceMinutes": shift.grace_minutes,
            "halfDayThresholdSeconds": half_day_seconds,
            # Not yet a configurable per-shift field in this app - defaults
            # to Mon-Sat (Sunday off), same assumption used elsewhere in the
            # mobile API. See the shared API docs.
            "workingDays": ["MON", "TUE", "WED", "THU", "FRI", "SAT"],
            "office": office_payload,
        })


@extend_schema(responses=EnvelopeResponseSerializer, tags=[TAG_SHIFT], summary="On-time streak banner (optional)", description="'On time' here means a full PRESENT day - low priority, per the spec the client can hide this banner until it's populated.")
class AchievementsView(MobileAPIView):
    """GET /employees/me/achievements - on-time streak, computed from
    Attendance.final_status (this app doesn't persist per-day lateness -
    'on time' here means a full PRESENT day, not present-and-not-late)."""

    def get(self, request):
        employee = request.user.employee_profile
        today = timezone.localdate()
        streak = 0
        d = today
        for _ in range(14):
            record = Attendance.objects.filter(employee=employee, date=d).first()
            if record and record.final_status == 'present':
                streak += 1
            elif d.weekday() == 6:
                pass  # Sunday - doesn't break the streak
            else:
                break
            d -= timedelta(days=1)

        return self.ok({
            "onTimeStreakDays": streak,
            "period": "WEEK",
            "message": f"On-time streak: {streak} day{'s' if streak != 1 else ''}!" if streak else None,
        })


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG_SHIFT], summary="This employee's branch holiday calendar",
    parameters=[OpenApiParameter('year', OpenApiTypes.INT, description='Defaults to the current year')],
    description="Also used server-side to mark HOLIDAY days on the attendance calendar and to exclude holidays from leave day counts.",
)
class HolidaysView(MobileAPIView):
    """GET /holidays?year=2026"""

    def get(self, request):
        employee = request.user.employee_profile
        year_str = request.GET.get('year')
        try:
            year = int(year_str) if year_str else timezone.localdate().year
        except ValueError:
            raise MobileAPIException('VALIDATION_ERROR', 'year must be numeric.', 400, field='year')

        holidays = Holiday.objects.filter(
            office=employee.office, branch=employee.branch, date__year=year,
        ).order_by('date')

        return self.ok({
            "year": year,
            "holidays": [
                {"date": h.date.isoformat(), "name": h.name, "type": HOLIDAY_TYPE_MAP.get(h.type, 'COMPANY')}
                for h in holidays
            ],
        })


# --- Phase 2 (spec 14.1) - no client screens yet, minimal but functional ---

@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG_PHASE2], summary="Request a shift swap",
    description="Phase 2 per the spec - functional end-to-end, but there's no client screen for it yet.",
    request=ShiftSwapRequestSerializer,
)
class ShiftSwapRequestView(MobileAPIView):
    """POST /shift-swap-requests - phase 2"""

    def post(self, request):
        from .models import ShiftSwapRequest, Employee
        employee = request.user.employee_profile

        requested_date = parse_date(request.data.get('requestedDate') or '')
        swap_with_id = request.data.get('swapWithEmployeeId')
        if not requested_date or not swap_with_id:
            raise MobileAPIException('VALIDATION_ERROR', 'requestedDate and swapWithEmployeeId are required.', 400)

        from .mobile_common import resolve_employee_by_identifier
        swap_with = resolve_employee_by_identifier(swap_with_id, office=employee.office)
        if swap_with is None:
            raise MobileAPIException('VALIDATION_ERROR', 'swapWithEmployeeId not found in your office.', 400, field='swapWithEmployeeId')

        obj = ShiftSwapRequest.objects.create(
            office=employee.office, branch=employee.branch, employee=employee,
            swap_with_employee=swap_with, requested_date=requested_date,
            reason=request.data.get('reason', ''),
        )
        return self.ok({"id": obj.id, "status": obj.status.upper()}, message="Shift swap request submitted.", status_code=201)


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG_PHASE2], summary="Submit an expense claim",
    description="Phase 2 per the spec - functional end-to-end, but there's no client screen for it yet.",
    request=ExpenseClaimRequestSerializer,
)
class ExpenseClaimView(MobileAPIView):
    """POST /expense-claims - phase 2"""

    def post(self, request):
        from .models import ExpenseClaim
        employee = request.user.employee_profile

        category = request.data.get('category')
        amount = request.data.get('amount')
        claim_date = parse_date(request.data.get('date') or '')
        if not category or not amount or not claim_date:
            raise MobileAPIException('VALIDATION_ERROR', 'category, amount and date are required.', 400)

        receipt = request.FILES.get('receipt')
        if receipt:
            if receipt.content_type not in ('image/jpeg', 'image/png', 'application/pdf'):
                raise MobileAPIException('UNSUPPORTED_FILE_TYPE', 'Receipt must be JPEG, PNG or PDF.', 415)
            if receipt.size > 10 * 1024 * 1024:
                raise MobileAPIException('FILE_TOO_LARGE', 'Receipt must be 10 MB or smaller.', 413)

        try:
            amount_val = float(amount)
        except (TypeError, ValueError):
            raise MobileAPIException('VALIDATION_ERROR', 'amount must be numeric.', 400, field='amount')

        claim = ExpenseClaim.objects.create(
            office=employee.office, branch=employee.branch, employee=employee,
            category=category, amount=amount_val, date=claim_date,
            description=request.data.get('description', ''), receipt=receipt,
        )
        return self.ok({"id": claim.id, "status": claim.status.upper()}, message="Expense claim submitted.", status_code=201)


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG_PHASE2], summary="Open an HR helpdesk ticket",
    description="Phase 2 per the spec - functional end-to-end, but there's no client screen for it yet.",
    request=HRTicketRequestSerializer,
)
class HRTicketView(MobileAPIView):
    """POST /hr-tickets - phase 2"""

    def post(self, request):
        from .models import HRTicket
        employee = request.user.employee_profile

        subject = (request.data.get('subject') or '').strip()
        if not subject:
            raise MobileAPIException('VALIDATION_ERROR', 'subject is required.', 400, field='subject')

        ticket = HRTicket.objects.create(
            office=employee.office, branch=employee.branch, employee=employee,
            subject=subject, category=request.data.get('category', ''),
            description=request.data.get('description', ''),
        )
        return self.ok({"id": ticket.id, "status": ticket.status.upper()}, message="HR ticket created.", status_code=201)


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG_PHASE2], summary="List policy documents",
    description="Phase 2 per the spec - returns an empty list until an admin uploads policy PDFs (no upload UI exists yet either).",
)
class CompanyPoliciesView(MobileAPIView):
    """GET /company-policies - phase 2"""

    def get(self, request):
        from .models import CompanyPolicy
        employee = request.user.employee_profile
        policies = [
            p for p in CompanyPolicy.objects.filter(office=employee.office).order_by('title')
            if p.branch_id is None or p.branch_id == employee.branch_id
        ]
        return self.ok([
            {"id": p.id, "title": p.title, "category": p.category or None,
             "updatedAt": p.updated_at.isoformat(), "fileUrl": p.file.url if p.file else None}
            for p in policies
        ])
