"""
Mobile API - Attendance (spec sections 7 and 8, 7 endpoints total).
GET /attendance/today, POST /attendance/check-in, POST /attendance/check-out,
GET /attendance/summary, /attendance/calendar, /attendance/day/{date}, /attendance/history
"""
import calendar
from datetime import datetime, date as date_cls

from django.core.files.base import ContentFile
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import serializers
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiParameter, OpenApiTypes

from .mobile_response import MobileAPIView, MobileAPIException, EnvelopeResponseSerializer
from .mobile_common import (
    spec_day_status, duration_payload, paginate, FINAL_STATUS_TO_SPEC,
    approved_leave_weights, count_absent_days,
)
from .models import Attendance, Holiday, LeaveRequest
from .face_utils import compare_faces, get_strict_match_tolerance
from .geolocation_utils import is_within_office_premises

TAG = 'Attendance'

MONTH_PARAM = OpenApiParameter('month', OpenApiTypes.STR, description='YYYY-MM, defaults to the current month where optional')
PAGE_PARAMS = [
    OpenApiParameter('page', OpenApiTypes.INT, description='1-indexed, default 1'),
    OpenApiParameter('pageSize', OpenApiTypes.INT, description='default 20, max 100'),
]


class CheckInOutRequestSerializer(serializers.Serializer):
    photo = serializers.ImageField(help_text="Front-camera selfie, JPEG")
    capturedAt = serializers.DateTimeField(required=False, help_text="Device time - audit only, server clock is authoritative")
    latitude = serializers.FloatField(required=False, help_text="Omit to skip the geofence check")
    longitude = serializers.FloatField(required=False)
    deviceId = serializers.CharField(required=False)


def _parse_month(month_str):
    if not month_str:
        raise MobileAPIException('VALIDATION_ERROR', 'month is required, format YYYY-MM.', 400, field='month')
    try:
        year, month = (int(p) for p in month_str.split('-'))
        if not (1 <= month <= 12):
            raise ValueError
    except ValueError:
        raise MobileAPIException('VALIDATION_ERROR', 'month must be in YYYY-MM format.', 400, field='month')
    return year, month


def _month_bounds(year, month):
    first = date_cls(year, month, 1)
    last = date_cls(year, month, calendar.monthrange(year, month)[1])
    return first, last


def _holiday_and_leave_dates(employee, first, last):
    """(holiday_dates, full_leave_dates, half_leave_dates). Only a full day of
    approved leave makes the whole day PAID_LEAVE; a first/second-half leave
    covers half a day, so that day still shows the employee's real attendance
    (HALF_DAY if they never punched in - the leave covers the other half)."""
    holiday_dates = set(
        Holiday.objects.filter(office=employee.office, branch=employee.branch, date__gte=first, date__lte=last)
        .values_list('date', flat=True)
    )
    weights = approved_leave_weights(employee, first, last)
    full = {d for d, w in weights.items() if w >= 1}
    half = {d for d, w in weights.items() if w < 1}
    return holiday_dates, full, half


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="Today's check-in state",
    description=(
        "Polled when the dashboard opens and after each check-in/out. An employee can check in and out "
        "several times a day: `sessions` lists every check-in/check-out pair, `workingDurationSeconds` is the "
        "sum of the COMPLETED sessions (gaps between them aren't counted), `checkInTime` is the day's first "
        "check-in and `checkOutTime` the last check-out. While `isCheckedIn` is true, the client's live "
        "ticking duration = `workingDurationSeconds` + (now - `currentSessionStart`). Each calendar day "
        "starts empty - nothing carries over from a previous day."
    ),
)
class TodayView(MobileAPIView):
    """GET /attendance/today"""

    def get(self, request):
        employee = request.user.employee_profile
        today = timezone.localdate()
        attendance = Attendance.objects.filter(employee=employee, date=today).first()
        shift = employee.shift

        sessions = list(attendance.sessions.all()) if attendance else []
        open_session = next((x for x in reversed(sessions) if x.check_out_time is None), None)
        closed_sessions = [x for x in sessions if x.check_out_time]
        # Worked time so far = every completed session; a client showing a live
        # ticking duration adds (now - currentSessionStart) while checked in.
        worked_seconds = attendance.worked_seconds if attendance else 0
        first_in = sessions[0].check_in_time if sessions else (attendance.check_in_time if attendance and not sessions and attendance.check_out_time else None)
        last_out = closed_sessions[-1].check_out_time if closed_sessions else None

        data = {
            "date": today.isoformat(),
            "isCheckedIn": open_session is not None,
            # checkInTime = the day's first check-in; currentSessionStart = the
            # check-in the employee is in right now (null when checked out).
            "checkInTime": first_in.isoformat() if first_in else None,
            "checkOutTime": last_out.isoformat() if last_out else None,
            "currentSessionStart": open_session.check_in_time.isoformat() if open_session else None,
            "sessions": [
                {
                    "checkInTime": x.check_in_time.isoformat(),
                    "checkOutTime": x.check_out_time.isoformat() if x.check_out_time else None,
                    "durationSeconds": x.duration_seconds,
                }
                for x in sessions
            ],
            "checkInPhotoUrl": attendance.check_in_photo.url if attendance and attendance.check_in_photo else None,
            "checkOutPhotoUrl": attendance.check_out_photo.url if attendance and attendance.check_out_photo else None,
            "status": spec_day_status(employee, today, attendance=attendance) if attendance else None,
            "workingDurationSeconds": worked_seconds,
            "workingDurationDisplay": duration_payload(worked_seconds)["display"],
            "shift": (
                {"start": shift.start_time.strftime('%H:%M'), "end": shift.end_time.strftime('%H:%M'), "graceMinutes": shift.grace_minutes}
                if shift else None
            ),
            "expectedShiftEnd": (
                timezone.make_aware(datetime.combine(today, shift.end_time)).isoformat() if shift else None
            ),
            "officeName": employee.branch.name if employee.branch else (employee.office.name if employee.office else None),
            "locationVerified": bool(attendance and attendance.check_in_latitude is not None),
        }
        return self.ok(data)


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="Check in",
    description=(
        "Face match against the enrolled reference is mandatory and happens before the record "
        "is written - a failed match never creates a record. Late classification uses the "
        "employee's shift start + grace period, computed server-side. Sending latitude/longitude "
        "enforces the branch geofence (OUTSIDE_GEOFENCE on a miss); omitting them skips the check. "
        "Allowed again after a check-out (several check-in/check-out sessions per day); returns "
        "ALREADY_CHECKED_IN (409) only while a check-in is still open. Lateness applies to the day's first check-in only."
    ),
    request=CheckInOutRequestSerializer,
    examples=[OpenApiExample('201 response', value={
        "attendanceId": "att_20260914_14", "checkInTime": "2026-09-14T10:01:23+05:30",
        "status": "PRESENT", "isLate": False, "lateByMinutes": 0,
        "faceMatch": {"similarity": 0.93, "threshold": 0.4, "passed": True},
        "location": {"verified": True, "officeName": "Head Office", "distanceMeters": 42.0},
        "checkInPhotoUrl": "/media/checkin_photos/checkin_14_20260914.jpg",
    }, response_only=True)],
)
class CheckInView(MobileAPIView):
    """POST /attendance/check-in"""

    def post(self, request):
        employee = request.user.employee_profile
        today = timezone.localdate()

        if not employee.has_registered_face:
            raise MobileAPIException('FACE_NOT_REGISTERED', 'Please enrol Face ID before checking in.', 409)

        # An employee can check in and out several times a day. Only an OPEN
        # session (checked in, not yet checked out) blocks a new check-in.
        existing_today = Attendance.objects.filter(employee=employee, date=today).first()
        if existing_today and existing_today.open_session:
            raise MobileAPIException('ALREADY_CHECKED_IN', 'You are already checked in. Please check out first.', 409)

        photo = request.FILES.get('photo')
        if not photo:
            raise MobileAPIException('VALIDATION_ERROR', 'photo is required.', 400, field='photo')

        image_bytes = photo.read()
        from .mobile_face_api import _detect_faces
        face_locations, image_array = _detect_faces(image_bytes)
        if len(face_locations) == 0:
            raise MobileAPIException('NO_FACE_DETECTED', 'No face detected. Please retake the photo.', 422)
        if len(face_locations) > 1:
            raise MobileAPIException('MULTIPLE_FACES', 'Multiple faces detected in the photo.', 422)

        import face_recognition
        encodings = face_recognition.face_encodings(image_array, face_locations)
        if not encodings:
            raise MobileAPIException('NO_FACE_DETECTED', 'Could not extract a usable face from the photo.', 422)

        tolerance = get_strict_match_tolerance()
        result = compare_faces(employee.get_face_encoding(), encodings[0], tolerance=tolerance)
        similarity = round(result['confidence'] / 100, 4)
        threshold = round(1 - tolerance, 4)
        if not result['match']:
            raise MobileAPIException(
                'FACE_MISMATCH', 'Face does not match the registered reference.', 422,
                details={"similarity": similarity, "threshold": threshold},
            )

        latitude = request.data.get('latitude')
        longitude = request.data.get('longitude')
        location_info = {"verified": False, "officeName": None, "distanceMeters": None}
        if latitude is not None and longitude is not None:
            try:
                lat_f, lon_f = float(latitude), float(longitude)
            except (TypeError, ValueError):
                raise MobileAPIException('VALIDATION_ERROR', 'latitude/longitude must be numeric.', 400, field='latitude')
            is_within, distance, message = is_within_office_premises(
                employee.office, lat_f, lon_f, branch=employee.branch,
            )
            if not is_within:
                raise MobileAPIException('OUTSIDE_GEOFENCE', message, 422, details={"distanceMeters": distance})
            location_info = {
                "verified": True,
                "officeName": employee.branch.name if employee.branch else (employee.office.name if employee.office else None),
                "distanceMeters": round(distance, 1) if distance is not None else None,
            }

        # Record this check-in as a new session on today's row (shared with
        # the web portal - see attendance_sessions.py).
        from .attendance_sessions import get_or_create_today, start_session
        attendance = get_or_create_today(employee, today)
        first_of_day = not attendance.sessions.exists()
        file_name = f'checkin_{employee.id}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.jpg'
        session = start_session(
            attendance, employee,
            photo=ContentFile(image_bytes), photo_name=file_name,
            latitude=lat_f if latitude is not None and longitude is not None else None,
            longitude=lon_f if latitude is not None and longitude is not None else None,
        )
        attendance.refresh_from_db()

        shift = employee.shift
        is_late = False
        late_by_minutes = 0
        if shift and first_of_day:
            grace_cutoff = (
                datetime.combine(today, shift.start_time) + timezone.timedelta(minutes=shift.grace_minutes)
            ).time()
            check_in_local = timezone.localtime(session.check_in_time).time()
            if check_in_local > grace_cutoff:
                is_late = True
                shift_start_dt = datetime.combine(today, shift.start_time)
                checkin_dt = datetime.combine(today, check_in_local)
                late_by_minutes = max(int((checkin_dt - shift_start_dt).total_seconds() // 60), 0)

        from .models import AttendanceLog
        AttendanceLog.objects.create(
            office=employee.office, branch=employee.branch, employee=employee, attendance=attendance,
            action='check_in_success', success=True, confidence=result['confidence'],
            ip_address=request.META.get('REMOTE_ADDR'), user_agent=request.META.get('HTTP_USER_AGENT', ''),
            notes='Mobile app check-in',
        )

        return self.ok({
            "attendanceId": f"att_{today.strftime('%Y%m%d')}_{employee.id}",
            "checkInTime": session.check_in_time.isoformat(),
            "status": "LATE" if is_late else "PRESENT",
            "isLate": is_late,
            "lateByMinutes": late_by_minutes,
            "faceMatch": {"similarity": similarity, "threshold": threshold, "passed": True},
            "location": location_info,
            "checkInPhotoUrl": session.check_in_photo.url,
        }, message="Checked in successfully", status_code=201)


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="Check out",
    description=(
        "Same face-match requirement as check-in. Closes the open check-in (NOT_CHECKED_IN 409 if none is open, "
        "including right after a check-out - check in again first). The day's total (`workingDurationSeconds`) is the "
        "sum of all completed check-in/check-out sessions today, and the final day status (PRESENT/HALF_DAY) is computed "
        "server-side from that total, reusing the same shift-threshold logic the web app's attendance calculations use."
    ),
    request=CheckInOutRequestSerializer,
)
class CheckOutView(MobileAPIView):
    """POST /attendance/check-out"""

    def post(self, request):
        employee = request.user.employee_profile
        today = timezone.localdate()

        # Check-out closes today's OPEN session. Nothing open (never checked
        # in today, a leave placeholder, or already checked out) -> nothing to
        # check out of; after a check-out the next action is a new check-in.
        attendance = Attendance.objects.filter(employee=employee, date=today).first()
        open_session = attendance.open_session if attendance else None
        if open_session is None:
            raise MobileAPIException('NOT_CHECKED_IN', 'No open check-in exists for today.', 409)

        if not employee.has_registered_face:
            raise MobileAPIException('FACE_NOT_REGISTERED', 'Please enrol Face ID before checking out.', 409)

        photo = request.FILES.get('photo')
        if not photo:
            raise MobileAPIException('VALIDATION_ERROR', 'photo is required.', 400, field='photo')

        image_bytes = photo.read()
        from .mobile_face_api import _detect_faces
        face_locations, image_array = _detect_faces(image_bytes)
        if len(face_locations) == 0:
            raise MobileAPIException('NO_FACE_DETECTED', 'No face detected. Please retake the photo.', 422)
        if len(face_locations) > 1:
            raise MobileAPIException('MULTIPLE_FACES', 'Multiple faces detected in the photo.', 422)

        import face_recognition
        encodings = face_recognition.face_encodings(image_array, face_locations)
        if not encodings:
            raise MobileAPIException('NO_FACE_DETECTED', 'Could not extract a usable face from the photo.', 422)

        tolerance = get_strict_match_tolerance()
        result = compare_faces(employee.get_face_encoding(), encodings[0], tolerance=tolerance)
        similarity = round(result['confidence'] / 100, 4)
        threshold = round(1 - tolerance, 4)
        if not result['match']:
            raise MobileAPIException(
                'FACE_MISMATCH', 'Face does not match the registered reference.', 422,
                details={"similarity": similarity, "threshold": threshold},
            )

        latitude = request.data.get('latitude')
        longitude = request.data.get('longitude')
        try:
            lat_f = float(latitude) if latitude not in (None, '') else None
            lon_f = float(longitude) if longitude not in (None, '') else None
        except (TypeError, ValueError):
            raise MobileAPIException('VALIDATION_ERROR', 'latitude/longitude must be numeric.', 400, field='latitude')

        from .attendance_sessions import end_session
        file_name = f'checkout_{employee.id}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.jpg'
        end_session(
            attendance, open_session,
            photo=ContentFile(image_bytes), photo_name=file_name,
            latitude=lat_f, longitude=lon_f,
        )
        attendance.refresh_from_db()

        from .models import AttendanceLog
        AttendanceLog.objects.create(
            office=employee.office, branch=employee.branch, employee=employee, attendance=attendance,
            action='check_out_success', success=True,
            ip_address=request.META.get('REMOTE_ADDR'), user_agent=request.META.get('HTTP_USER_AGENT', ''),
            notes='Mobile app check-out',
        )

        working_seconds = attendance.worked_seconds
        return self.ok({
            "attendanceId": f"att_{today.strftime('%Y%m%d')}_{employee.id}",
            "checkOutTime": attendance.check_out_time.isoformat(),
            "workingDurationSeconds": working_seconds,
            "workingDurationDisplay": duration_payload(working_seconds)["display"],
            "status": FINAL_STATUS_TO_SPEC.get(attendance.final_status, 'PRESENT'),
            "faceMatch": {"similarity": similarity, "threshold": threshold, "passed": True},
            "checkOutPhotoUrl": attendance.check_out_photo.url,
        }, message="Checked out successfully")


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="Monthly statistic cards", parameters=[MONTH_PARAM],
    description="The six cards above the calendar. `absentDays` counts working days elapsed with no punch (same rule as /reports/monthly-summary). Note: `lateArrivals` currently always reports 0 - this app doesn't persist arrival-time lateness per past day, only at the moment of check-in (see `isLate` on POST /attendance/check-in).",
)
class SummaryView(MobileAPIView):
    """GET /attendance/summary?month=YYYY-MM"""

    def get(self, request):
        employee = request.user.employee_profile
        year, month = _parse_month(request.GET.get('month'))
        first, last = _month_bounds(year, month)
        today = timezone.localdate()
        end = min(last, today)

        records = list(Attendance.objects.filter(employee=employee, date__gte=first, date__lte=end))
        present_days = sum(1 for r in records if r.final_status == 'present')
        half_days = sum(1 for r in records if r.final_status in ('half_day', 'late_penalty'))
        working_seconds = sum(int(float(r.total_work_hours or 0) * 3600) for r in records)

        holiday_dates = set(
            Holiday.objects.filter(office=employee.office, branch=employee.branch, date__gte=first, date__lte=last)
            .values_list('date', flat=True)
        )
        leave_weights = approved_leave_weights(employee, first, last)
        # Same shared counting the reports screen uses, so the two can't disagree.
        absent_days = count_absent_days(employee, records, first, end, holiday_dates, leave_weights)
        total_calendar_days = (last - first).days + 1
        attendance_percent = round((present_days + half_days * 0.5) / total_calendar_days * 100) if total_calendar_days else 0

        return self.ok({
            "month": f"{year:04d}-{month:02d}",
            "presentDays": present_days,
            "absentDays": absent_days,
            "lateArrivals": 0,  # arrival-time lateness isn't persisted per-record in this schema; see API docs
            "halfDays": half_days,
            "workingHoursTotal": duration_payload(working_seconds),
            "attendancePercent": attendance_percent,
        })


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="Per-day status grid", parameters=[MONTH_PARAM],
    description="One entry per calendar day, drives the colour-coded grid. Every AttendanceStatus value can appear here. A day with a first/second-half approved leave and no punch shows HALF_DAY (the leave covers the other half).",
)
class CalendarView(MobileAPIView):
    """GET /attendance/calendar?month=YYYY-MM"""

    def get(self, request):
        employee = request.user.employee_profile
        year, month = _parse_month(request.GET.get('month'))
        first, last = _month_bounds(year, month)

        records = {r.date: r for r in Attendance.objects.filter(employee=employee, date__gte=first, date__lte=last)}
        holiday_dates, leave_dates, half_leave_dates = _holiday_and_leave_dates(employee, first, last)

        days = []
        for i in range((last - first).days + 1):
            d = first + timezone.timedelta(days=i)
            status = spec_day_status(
                employee, d, attendance=records.get(d), holiday_dates=holiday_dates,
                leave_dates=leave_dates, half_leave_dates=half_leave_dates,
            )
            days.append({"date": d.isoformat(), "status": status})

        return self.ok({"month": f"{year:04d}-{month:02d}", "days": days})


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="Single-day punch detail",
    parameters=[OpenApiParameter('date', OpenApiTypes.DATE, location=OpenApiParameter.PATH, description='YYYY-MM-DD')],
    description="For PAID_LEAVE/HOLIDAY days, both check times come back null and `totalHours.display` is a label ('On Leave' / 'Holiday') instead of a duration.",
)
class DayDetailView(MobileAPIView):
    """GET /attendance/day/{date}"""

    def get(self, request, date):
        employee = request.user.employee_profile
        day = parse_date(date)
        if day is None:
            raise MobileAPIException('VALIDATION_ERROR', 'date must be YYYY-MM-DD.', 400, field='date')

        attendance = Attendance.objects.filter(employee=employee, date=day).first()
        holiday_dates, leave_dates, half_leave_dates = _holiday_and_leave_dates(employee, day, day)
        status = spec_day_status(
            employee, day, attendance=attendance, holiday_dates=holiday_dates,
            leave_dates=leave_dates, half_leave_dates=half_leave_dates,
        )

        if status == 'PAID_LEAVE':
            total_hours = {"seconds": 0, "display": "On Leave"}
        elif status == 'HOLIDAY':
            total_hours = {"seconds": 0, "display": "Holiday"}
        elif attendance:
            total_hours = duration_payload(attendance.worked_seconds)
        else:
            total_hours = {"seconds": 0, "display": "-"}

        return self.ok({
            "date": day.isoformat(),
            "status": status,
            "checkIn": (
                {"time": timezone.localtime(attendance.check_in_time).strftime('%H:%M'),
                 "photoUrl": attendance.check_in_photo.url if attendance.check_in_photo else None}
                if attendance and attendance.check_in_time else {"time": None, "photoUrl": None}
            ),
            "checkOut": (
                {"time": timezone.localtime(attendance.check_out_time).strftime('%H:%M'),
                 "photoUrl": attendance.check_out_photo.url if attendance.check_out_photo else None}
                if attendance and attendance.check_out_time else {"time": None, "photoUrl": None}
            ),
            "totalHours": total_hours,
            "sessions": [
                {
                    "checkIn": timezone.localtime(x.check_in_time).strftime('%H:%M'),
                    "checkOut": timezone.localtime(x.check_out_time).strftime('%H:%M') if x.check_out_time else None,
                    "durationSeconds": x.duration_seconds,
                }
                for x in (attendance.sessions.all() if attendance else [])
            ],
            "note": None,
        })


@extend_schema(
    responses=EnvelopeResponseSerializer,
    tags=[TAG], summary="Paginated punch history", parameters=[MONTH_PARAM, *PAGE_PARAMS],
    description="`month` is optional here - omit it to page through the employee's entire history, newest first.",
)
class HistoryView(MobileAPIView):
    """GET /attendance/history?month=YYYY-MM&page=1&pageSize=20"""

    def get(self, request):
        employee = request.user.employee_profile
        month_str = request.GET.get('month')
        qs = Attendance.objects.filter(employee=employee).order_by('-date')
        if month_str:
            year, month = _parse_month(month_str)
            first, last = _month_bounds(year, month)
            qs = qs.filter(date__gte=first, date__lte=last)

        total_records = qs.count()
        records = list(qs)
        avg_seconds = int(sum(float(r.total_work_hours or 0) * 3600 for r in records) / len(records)) if records else 0

        page_items, pagination = paginate(records, request.GET.get('page'), request.GET.get('pageSize'))

        results = []
        for r in page_items:
            seconds = int(float(r.total_work_hours or 0) * 3600)
            results.append({
                "attendanceId": f"att_{r.date.strftime('%Y%m%d')}_{employee.id}",
                "date": r.date.isoformat(),
                "dayName": r.date.strftime('%a'),
                "checkInTime": timezone.localtime(r.check_in_time).strftime('%H:%M') if r.check_in_time else None,
                "checkOutTime": timezone.localtime(r.check_out_time).strftime('%H:%M') if r.check_out_time else None,
                "workingHours": duration_payload(seconds),
                "status": FINAL_STATUS_TO_SPEC.get(r.final_status, 'PRESENT'),
                "checkInPhotoUrl": r.check_in_photo.url if r.check_in_photo else None,
                "checkOutPhotoUrl": r.check_out_photo.url if r.check_out_photo else None,
            })

        return self.ok({
            "totalRecords": total_records,
            "averageWorkingHours": duration_payload(avg_seconds),
            "records": results,
            "pagination": pagination,
        })
