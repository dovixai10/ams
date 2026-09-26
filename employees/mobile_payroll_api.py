"""
Mobile API - Payroll and salary slips (spec section 12, 5 endpoints).
GET /payroll/available-months, /payroll/slips/{yearMonth}, /payroll/slips,
GET /payroll/slips/{yearMonth}/pdf, POST /payroll/slips/{yearMonth}/email

Security note (spec section 12): never returns an unmasked account number
or full PAN - see _mask().
"""
import calendar
from datetime import datetime, date as date_cls

from django.core.mail import EmailMessage
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiParameter, OpenApiTypes

from .mobile_response import MobileAPIView, MobileAPIException, EnvelopeResponseSerializer
from .mobile_common import paginate
from .models import SalarySlip, Attendance

TAG = 'Payroll'
YEAR_MONTH_PARAM = OpenApiParameter('year_month', OpenApiTypes.STR, location=OpenApiParameter.PATH, description='YYYY-MM')


def _mask(value, keep=4):
    if not value:
        return None
    value = str(value)
    return ('•' * max(len(value) - keep, 0)) + value[-keep:] if len(value) > keep else '•' * len(value)


def _parse_year_month(year_month):
    try:
        year, month = (int(p) for p in year_month.split('-'))
        if not (1 <= month <= 12):
            raise ValueError
        return year, month
    except (ValueError, AttributeError):
        raise MobileAPIException('VALIDATION_ERROR', 'yearMonth must be in YYYY-MM format.', 400)


def _attendance_summary(employee, year, month):
    first = date_cls(year, month, 1)
    last = date_cls(year, month, calendar.monthrange(year, month)[1])
    total_days = (last - first).days + 1
    records = list(Attendance.objects.filter(employee=employee, date__gte=first, date__lte=last))
    present = sum(1 for r in records if r.final_status == 'present')
    half = sum(1 for r in records if r.final_status in ('half_day', 'late_penalty'))
    lop = sum(1 for r in records if r.final_status in ('absent', 'sandwich_leave'))
    paid_days = present + half * 0.5
    return {"paidDays": paid_days, "totalDays": total_days, "lossOfPayDays": lop}


def _slip_detail(slip):
    employee = slip.employee
    profile = slip.salary_profile  # EmployeeSalary snapshot, if the admin linked one when generating

    if profile:
        earnings = {
            "basicSalary": float(profile.basic_salary), "hra": float(profile.hra), "da": float(profile.da),
            "specialAllowance": float(profile.special_allowance),
            "performanceIncentive": float(profile.bonus),
            "conveyanceAllowance": float(profile.conveyance_allowance),
        }
        deductions = {
            "providentFund": float(profile.pf), "incomeTax": float(profile.tds),
            "healthInsurance": float(profile.esi), "professionalTax": float(profile.professional_tax),
        }
        gross = float(profile.gross_salary) if profile.gross_salary is not None else float(slip.basic_salary)
    else:
        # This slip was generated without a linked salary profile (the admin
        # payroll form only captures basic/deductions/net) - everything
        # collapses onto a single line each. See the shared API docs.
        earnings = {
            "basicSalary": float(slip.basic_salary), "hra": 0.0, "da": 0.0,
            "specialAllowance": 0.0, "performanceIncentive": 0.0, "conveyanceAllowance": 0.0,
        }
        deductions = {
            "providentFund": 0.0, "incomeTax": 0.0, "healthInsurance": 0.0,
            "professionalTax": float(slip.deductions),
        }
        gross = float(slip.basic_salary)

    year, month = slip.month.year, slip.month.month
    return {
        "month": f"{year:04d}-{month:02d}",
        "currency": "INR",
        "status": "PAID",  # this app has no separate payroll-processing pipeline yet - see API docs
        "netSalary": float(slip.net_salary),
        "grossEarnings": gross,
        "totalDeductions": float(slip.deductions),
        "disbursedOn": slip.updated_at.date().isoformat(),
        "disbursementMethod": "Direct Bank Transfer",
        "earnings": earnings,
        "deductions": deductions,
        "payrollDetails": {
            "employeeName": employee.full_name or employee.name,
            "employeeId": f"KI{employee.id:05d}",
            "department": employee.department.name if employee.department else None,
            "designation": employee.designation.name if employee.designation else None,
            "bankName": None,  # not captured in this app's Employee model yet
            "accountNumberMasked": _mask(employee.account_number),
            "panNumberMasked": _mask(employee.pan_card, keep=1) if employee.pan_card else None,
            "pfNumber": None,  # not captured in this app's Employee model yet
        },
        "attendance": _attendance_summary(employee, year, month),
    }


@extend_schema(responses=EnvelopeResponseSerializer, tags=[TAG], summary="Month dropdown options", description="Newest first.")
class AvailableMonthsView(MobileAPIView):
    """GET /payroll/available-months"""

    def get(self, request):
        employee = request.user.employee_profile
        months = list(
            SalarySlip.objects.filter(employee=employee).order_by('-month').values_list('month', flat=True)
        )
        return self.ok({"months": [f"{m.year:04d}-{m.month:02d}" for m in months]})


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="Full payslip breakdown", parameters=[YEAR_MONTH_PARAM],
    description=(
        "Account number and PAN are always masked before leaving the server. Earnings/deductions "
        "come from the linked salary profile when the admin set one; otherwise everything collapses "
        "onto basicSalary/professionalTax (see the docs' Decisions section)."
    ),
    examples=[OpenApiExample('200 response', value={
        "month": "2026-08", "currency": "INR", "status": "PAID", "netSalary": 78450.0,
        "grossEarnings": 92500.0, "totalDeductions": 14050.0, "disbursedOn": "2026-08-31",
        "disbursementMethod": "Direct Bank Transfer",
        "earnings": {"basicSalary": 46250.0, "hra": 18500.0, "da": 0.0, "specialAllowance": 18500.0, "performanceIncentive": 7650.0, "conveyanceAllowance": 1600.0},
        "deductions": {"providentFund": 5550.0, "incomeTax": 6200.0, "healthInsurance": 1500.0, "professionalTax": 800.0},
        "payrollDetails": {"employeeName": "Kamal", "employeeId": "KI00014", "department": None, "designation": None,
                            "bankName": None, "accountNumberMasked": "••••4821", "panNumberMasked": "•••••••••M", "pfNumber": None},
        "attendance": {"paidDays": 30, "totalDays": 31, "lossOfPayDays": 1},
    }, response_only=True)],
)
class SlipDetailView(MobileAPIView):
    """GET /payroll/slips/{yearMonth}"""

    def get(self, request, year_month):
        year, month = _parse_year_month(year_month)
        employee = request.user.employee_profile
        slip = SalarySlip.objects.filter(employee=employee, month__year=year, month__month=month).select_related('salary_profile').first()
        if slip is None:
            raise MobileAPIException('NOT_FOUND', 'No salary slip found for that month.', 404)
        return self.ok(_slip_detail(slip))


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="Past payslip summaries",
    parameters=[OpenApiParameter('page', OpenApiTypes.INT), OpenApiParameter('pageSize', OpenApiTypes.INT, description='default 12')],
)
class SlipListView(MobileAPIView):
    """GET /payroll/slips?page=1&pageSize=12"""

    def get(self, request):
        employee = request.user.employee_profile
        qs = SalarySlip.objects.filter(employee=employee).order_by('-month')
        items, pagination = paginate(list(qs), request.GET.get('page'), request.GET.get('pageSize', 12))
        slips = []
        for s in items:
            attendance = _attendance_summary(employee, s.month.year, s.month.month)
            slips.append({
                "month": f"{s.month.year:04d}-{s.month.month:02d}",
                "netSalary": float(s.net_salary),
                "grossEarnings": float(s.basic_salary),
                "paidOn": s.updated_at.date().isoformat(),
                "status": "PAID",
                "workingDays": f"{int(attendance['paidDays'])} / {attendance['totalDays']}",
            })
        return self.ok({"slips": slips, "pagination": pagination})


@extend_schema(
    tags=[TAG], summary="Download the payslip PDF", parameters=[YEAR_MONTH_PARAM],
    description="Returns `application/pdf` with Content-Disposition: attachment. Generated on first request if it doesn't exist yet, then cached on the record.",
    responses={200: OpenApiTypes.BINARY},
)
class SlipPdfView(MobileAPIView):
    """GET /payroll/slips/{yearMonth}/pdf"""

    def get(self, request, year_month):
        year, month = _parse_year_month(year_month)
        employee = request.user.employee_profile
        slip = SalarySlip.objects.filter(employee=employee, month__year=year, month__month=month).first()
        if slip is None:
            raise MobileAPIException('NOT_FOUND', 'No salary slip found for that month.', 404)

        if not slip.pdf_file:
            from .views import _build_salary_slip_pdf
            from django.core.files.base import ContentFile
            buf = _build_salary_slip_pdf(slip)
            slip.pdf_file.save(f"salary_slip_{employee.id}_{year}_{month:02d}.pdf", ContentFile(buf.getvalue()), save=True)

        from django.http import FileResponse
        return FileResponse(
            slip.pdf_file.open('rb'), as_attachment=True,
            filename=f"salary_slip_{slip.month.strftime('%b_%Y')}.pdf", content_type='application/pdf',
        )


@extend_schema(
    request=None,
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="Email the payslip", parameters=[YEAR_MONTH_PARAM],
    description="Sends only to the employee's registered work email - never an address supplied in the request. Rate-limited to 3 sends per slip per day. Response masks the address, e.g. `\"kam***@dovixai.com\"`.",
)
class SlipEmailView(MobileAPIView):
    """POST /payroll/slips/{yearMonth}/email"""

    def post(self, request, year_month):
        year, month = _parse_year_month(year_month)
        employee = request.user.employee_profile

        from django.core.cache import cache
        rate_key = f"mobile_payslip_email:{employee.id}:{year_month}"
        sends_today = cache.get(rate_key, 0)
        if sends_today >= 3:
            raise MobileAPIException('ACCOUNT_LOCKED', 'Too many email requests for this payslip today.', 429)

        slip = SalarySlip.objects.filter(employee=employee, month__year=year, month__month=month).first()
        if slip is None:
            raise MobileAPIException('NOT_FOUND', 'No salary slip found for that month.', 404)

        if not slip.pdf_file:
            from .views import _build_salary_slip_pdf
            from django.core.files.base import ContentFile
            buf = _build_salary_slip_pdf(slip)
            slip.pdf_file.save(f"salary_slip_{employee.id}_{year}_{month:02d}.pdf", ContentFile(buf.getvalue()), save=True)

        target_email = employee.email  # work email only - never an address supplied in the request
        try:
            email = EmailMessage(
                subject=f"Your salary slip - {slip.month.strftime('%B %Y')}",
                body="Please find your salary slip attached.",
                to=[target_email],
            )
            slip.pdf_file.open('rb')
            email.attach(f"salary_slip_{slip.month.strftime('%b_%Y')}.pdf", slip.pdf_file.read(), 'application/pdf')
            email.send(fail_silently=False)
        except Exception:
            raise MobileAPIException('SERVER_ERROR', 'Could not send the email. Please try again later.', 500)

        cache.set(rate_key, sends_today + 1, 24 * 3600)

        masked = target_email[:3] + '***@' + target_email.split('@')[-1] if '@' in target_email else '***'
        return self.ok({"sentTo": masked}, message="Salary slip emailed successfully.")
