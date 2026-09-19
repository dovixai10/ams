"""
Check-in / check-out sessions for the employee portal (web) and the mobile
API - the one place both go through, so they can't drift apart.

An employee can check in and out several times a day. Each pair is an
AttendanceSession; the day's Attendance row keeps the FIRST check-in and the
LAST check-out, and total_work_hours is the sum of the closed sessions. Each
calendar day has its own Attendance row, so an unclosed session from an
earlier day never carries into today (the missed check-out is fixed through an
attendance regularization request instead).
"""
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Attendance, AttendanceSession


def get_or_create_today(employee, day):
    """Today's Attendance row for this employee, created if it doesn't exist.
    Keyed on (employee, date) only, matching the model's unique_together."""
    try:
        attendance, _ = Attendance.objects.get_or_create(
            employee=employee, date=day,
            defaults={
                'office': employee.office,
                'branch': employee.branch,
                'check_in_time': timezone.now(),
            },
        )
    except IntegrityError:
        # A double-tapped submit created the row between our lookup and insert.
        attendance = Attendance.objects.get(employee=employee, date=day)
    return attendance


def start_session(attendance, employee, *, photo, photo_name, latitude=None, longitude=None):
    """Record a check-in. Returns the new AttendanceSession."""
    with transaction.atomic():
        now = timezone.now()
        first_of_day = not attendance.sessions.exists()

        session = AttendanceSession(
            attendance=attendance, check_in_time=now,
            check_in_latitude=latitude, check_in_longitude=longitude,
        )
        session.check_in_photo.save(photo_name, photo, save=False)
        session.save()

        if first_of_day:
            # First check-in of the day claims the row fresh - overwriting any
            # placeholder (e.g. an approved-leave marker with a stale
            # timestamp) rather than inheriting its data.
            attendance.office = employee.office
            attendance.branch = employee.branch
            attendance.check_in_time = now
            attendance.check_in_photo = session.check_in_photo.name
            attendance.check_in_latitude = latitude
            attendance.check_in_longitude = longitude
            attendance.check_out_photo = None
            attendance.check_out_latitude = None
            attendance.check_out_longitude = None
            attendance.total_work_hours = Decimal('0.00')
            attendance.half_day = False
            attendance.final_status = 'present'

        # Checked in again -> not checked out right now.
        attendance.check_out_time = None
        attendance.save()
        return session


def end_session(attendance, session, *, photo, photo_name, latitude=None, longitude=None, auto_end_context=None):
    """Record a check-out against the open session and recompute the day's
    total and status from all of its sessions. Returns the status result."""
    from .shift_attendance_logic import update_attendance_on_checkout

    with transaction.atomic():
        now = timezone.now()
        session.check_out_time = now
        session.check_out_latitude = latitude
        session.check_out_longitude = longitude
        session.check_out_photo.save(photo_name, photo, save=False)
        session.save()

        attendance.check_out_time = now
        attendance.check_out_photo = session.check_out_photo.name
        attendance.check_out_latitude = latitude
        attendance.check_out_longitude = longitude
        if auto_end_context:
            attendance._auto_end_context = auto_end_context
        attendance.save()

        return update_attendance_on_checkout(attendance)


def today_sessions_summary(attendance):
    """Everything the check-in screen needs to describe today."""
    if attendance is None:
        return {'sessions': [], 'open_session': None, 'worked_seconds': 0}
    sessions = list(attendance.sessions.all())
    open_session = next((s for s in reversed(sessions) if s.check_out_time is None), None)
    return {
        'sessions': sessions,
        'open_session': open_session,
        'worked_seconds': attendance.worked_seconds,
    }
