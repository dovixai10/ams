"""
Shift-Based Attendance Calculation Logic
==========================================

This module handles all shift-based attendance calculations including:
- Duration calculation (check-in to check-out)
- Shift comparison (worked hours vs assigned shift hours)
- Attendance status determination (Present, Half-Day, Absent)
- Edge case handling (missing checkout, overnight shifts, etc.)
- Per-office configurable thresholds via AttendanceRule (falls back to
  system default of 100% shift hours = Present, 50% = Half Day if the
  office hasn't configured a rule, or has disabled it).

Author: EMS System
Date: 2024
"""

from datetime import datetime, timedelta, time, date
from decimal import Decimal
from django.utils import timezone
from typing import Tuple, Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS
# ============================================================================

# Attendance Status Constants
STATUS_PRESENT = 'present'
STATUS_HALF_DAY = 'half_day'
STATUS_ABSENT = 'absent'
STATUS_CHECKED_IN_ONLY = 'checked_in_only'

# Color codes for UI display
COLOR_PRESENT = '#34C759'      # Green
COLOR_HALF_DAY = '#FFCC00'     # Yellow
COLOR_ABSENT = '#FF3B30'       # Red
COLOR_CHECKED_IN = '#007AFF'   # Blue

# System defaults used when an office has no active AttendanceRule.
# NOTE: these replace the old hardcoded HALF_DAY_THRESHOLD_MULTIPLIER = 0.5.
# Full day now defaults to 100% of shift hours (was: duration >= shift_total_hours,
# which is mathematically the same thing, just now expressed as a percentage
# so it can be overridden per office).
DEFAULT_FULL_DAY_PERCENTAGE = Decimal('100.00')
DEFAULT_HALF_DAY_PERCENTAGE = Decimal('50.00')

# Kept for backward compatibility in case anything else imports this constant.
HALF_DAY_THRESHOLD_MULTIPLIER = 0.5


# ============================================================================
# OFFICE ATTENDANCE RULE HELPERS
# ============================================================================

def get_office_attendance_rule(office):
    """
    Fetch the active AttendanceRule for an office, if any.

    Args:
        office: Office model instance (or None)

    Returns:
        AttendanceRule instance if one exists and is active, else None.
        None is the signal to callers: "use system default thresholds."
    """
    if not office:
        return None

    from .models import AttendanceRule

    try:
        rule = office.attendance_rule
    except AttendanceRule.DoesNotExist:
        return None

    return rule if rule.is_active else None


def get_shift_thresholds(shift, office=None) -> Dict[str, Decimal]:
    """
    Calculate full-day and half-day thresholds (in hours) for a shift,
    using the office's AttendanceRule if one is configured and active,
    otherwise falling back to the system default (100% / 50% of shift hours).

    Args:
        shift: Shift model instance
        office: Office model instance. If not provided, falls back to
                shift.office.

    Returns:
        Dict with keys:
            - total_hours: Decimal
            - full_day_threshold: Decimal (hours needed to be marked Present)
            - half_day_threshold: Decimal (hours needed to be marked Half Day)
    """
    total_hours = get_shift_total_hours(shift)
    office = office or getattr(shift, 'office', None)
    rule = get_office_attendance_rule(office)

    if rule:
        full_day_threshold, half_day_threshold = rule.get_thresholds(total_hours)
    else:
        full_day_threshold = (
            total_hours * DEFAULT_FULL_DAY_PERCENTAGE / Decimal('100')
        ).quantize(Decimal('0.01'))
        half_day_threshold = (
            total_hours * DEFAULT_HALF_DAY_PERCENTAGE / Decimal('100')
        ).quantize(Decimal('0.01'))

    return {
        'total_hours': total_hours,
        'full_day_threshold': full_day_threshold,
        'half_day_threshold': half_day_threshold,
    }


# ============================================================================
# SHIFT UTILITY FUNCTIONS
# ============================================================================

def get_shift_total_hours(shift) -> Decimal:
    """
    Calculate total hours for a shift.

    Args:
        shift: Shift model instance

    Returns:
        Decimal: Total hours in the shift (e.g., 8.5, 4.0)

    Raises:
        ValueError: If shift is None or times are invalid
    """
    if not shift:
        raise ValueError("Shift cannot be None")

    if not shift.start_time or not shift.end_time:
        raise ValueError(f"Shift {shift.id} has invalid times")

    # Create datetime objects for calculation (use same date to handle overnight shifts)
    start_dt = datetime.combine(date.today(), shift.start_time)
    end_dt = datetime.combine(date.today(), shift.end_time)

    # Handle overnight shifts (e.g., 10 PM to 6 AM)
    if end_dt <= start_dt:
        end_dt = end_dt + timedelta(days=1)

    # Calculate duration in hours
    duration = end_dt - start_dt
    hours = Decimal(str(duration.total_seconds() / 3600))

    return hours.quantize(Decimal('0.01'))


def get_shift_half_day_threshold(shift, office=None) -> Decimal:
    """
    Calculate half-day threshold for a shift.

    Uses the office's AttendanceRule if configured, otherwise defaults
    to 50% of total shift hours (same behavior as before).

    Args:
        shift: Shift model instance
        office: Office model instance (optional, falls back to shift.office)

    Returns:
        Decimal: Half-day threshold in hours
    """
    thresholds = get_shift_thresholds(shift, office=office)
    return thresholds['half_day_threshold']


def get_employee_shift_info(employee) -> Dict[str, Any]:
    """
    Fetch employee's assigned shift information, including office-specific
    (or default) attendance thresholds.

    Called when employee logs in / whenever a status needs to be computed.

    Args:
        employee: Employee model instance

    Returns:
        Dict with keys:
            - shift: Shift object
            - shift_name: str
            - start_time: time object
            - end_time: time object
            - total_hours: Decimal
            - full_day_threshold: Decimal
            - half_day_threshold: Decimal

    Raises:
        ValueError: If employee has no assigned shift
    """
    if not employee.shift:
        raise ValueError(f"Employee {employee.id} has no assigned shift")

    shift = employee.shift
    office = getattr(employee, 'office', None) or getattr(shift, 'office', None)
    thresholds = get_shift_thresholds(shift, office=office)

    return {
        'shift': shift,
        'shift_name': shift.name,
        'start_time': shift.start_time,
        'end_time': shift.end_time,
        'total_hours': thresholds['total_hours'],
        'full_day_threshold': thresholds['full_day_threshold'],
        'half_day_threshold': thresholds['half_day_threshold'],
    }


# ============================================================================
# DURATION CALCULATION FUNCTIONS
# ============================================================================

def calculate_duration_hours(check_in_time: datetime, check_out_time: Optional[datetime]) -> Decimal:
    """
    Calculate duration between check-in and check-out in hours.

    Args:
        check_in_time: Check-in datetime (timezone-aware)
        check_out_time: Check-out datetime (timezone-aware) or None

    Returns:
        Decimal: Duration in hours (e.g., 8.5, 4.25)

    Raises:
        ValueError: If check_in_time is None
    """
    if not check_in_time:
        raise ValueError("check_in_time cannot be None")

    if not check_out_time:
        return Decimal('0.00')

    # Ensure both times are timezone-aware
    if timezone.is_naive(check_in_time):
        check_in_time = timezone.make_aware(check_in_time)
    if timezone.is_naive(check_out_time):
        check_out_time = timezone.make_aware(check_out_time)

    # Validate check_out is after check_in
    if check_out_time <= check_in_time:
        logger.warning(
            f"Check-out time ({check_out_time}) is not after check-in time ({check_in_time})"
        )
        return Decimal('0.00')

    # Calculate duration
    duration = check_out_time - check_in_time
    hours = Decimal(str(duration.total_seconds() / 3600))

    return hours.quantize(Decimal('0.01'))


def calculate_duration_display(check_in_time: datetime, check_out_time: Optional[datetime]) -> str:
    """
    Get human-readable duration display (HH:MM:SS format).

    Args:
        check_in_time: Check-in datetime
        check_out_time: Check-out datetime or None

    Returns:
        str: Duration in "HH:MM:SS" format or "-" if no checkout
    """
    if not check_out_time:
        return "-"

    try:
        hours = calculate_duration_hours(check_in_time, check_out_time)
        total_seconds = int(float(hours) * 3600)

        h = total_seconds // 3600
        m = (total_seconds % 3600) // 60
        s = total_seconds % 60

        return f"{h:02d}:{m:02d}:{s:02d}"
    except Exception as e:
        logger.error(f"Error calculating duration display: {str(e)}")
        return "-"


# ============================================================================
# ATTENDANCE STATUS DETERMINATION
# ============================================================================

def determine_attendance_status(
    duration_hours: Decimal,
    full_day_threshold: Decimal,
    half_day_threshold: Decimal,
    has_checkout: bool = True
) -> Tuple[str, str]:
    """
    Determine attendance status based on shift-based logic.

    RULES:
    1. If no checkout: STATUS_CHECKED_IN_ONLY (Blue)
    2. If duration >= full_day_threshold: STATUS_PRESENT (Green)
    3. If half_day_threshold <= duration < full_day_threshold: STATUS_HALF_DAY (Yellow)
    4. If duration < half_day_threshold: STATUS_ABSENT (Red)

    NOTE: `full_day_threshold` replaces the old `shift_total_hours` parameter.
    By default full_day_threshold == 100% of shift_total_hours (identical
    behavior to before), but an office can now configure a different
    percentage (or a fixed-hours value) via AttendanceRule.

    Args:
        duration_hours: Decimal - worked hours
        full_day_threshold: Decimal - hours required for Present
        half_day_threshold: Decimal - hours required for Half Day
        has_checkout: bool - whether checkout was recorded

    Returns:
        Tuple[str, str]: (status, color_code)
            - status: 'present', 'half_day', 'absent', 'checked_in_only'
            - color_code: CSS color code for UI
    """
    # Rule 1: No checkout recorded
    if not has_checkout:
        return (STATUS_CHECKED_IN_ONLY, COLOR_CHECKED_IN)

    # Rule 2: Full day present
    if duration_hours >= full_day_threshold:
        return (STATUS_PRESENT, COLOR_PRESENT)

    # Rule 3: Half day
    if duration_hours >= half_day_threshold:
        return (STATUS_HALF_DAY, COLOR_HALF_DAY)

    # Rule 4: Absent
    return (STATUS_ABSENT, COLOR_ABSENT)


def calculate_attendance_status_for_record(attendance) -> Tuple[str, str]:
    """
    Calculate attendance status for an Attendance record.

    This is a convenience function that extracts data from the Attendance model
    and calls determine_attendance_status(), using the employee's office
    AttendanceRule (if configured) to determine thresholds.

    Args:
        attendance: Attendance model instance

    Returns:
        Tuple[str, str]: (status, color_code)
    """
    # Check if employee has a shift
    if not attendance.employee.shift:
        logger.warning(f"Employee {attendance.employee.id} has no assigned shift")
        return (STATUS_ABSENT, COLOR_ABSENT)

    try:
        # Get shift information (thresholds resolved per-office here)
        shift_info = get_employee_shift_info(attendance.employee)
        full_day_threshold = shift_info['full_day_threshold']
        half_day_threshold = shift_info['half_day_threshold']

        # Calculate duration
        duration_hours = calculate_duration_hours(
            attendance.check_in_time,
            attendance.check_out_time
        )

        # Determine status
        has_checkout = attendance.check_out_time is not None
        status, color = determine_attendance_status(
            duration_hours,
            full_day_threshold,
            half_day_threshold,
            has_checkout
        )

        return (status, color)

    except Exception as e:
        logger.error(f"Error calculating attendance status: {str(e)}")
        return (STATUS_ABSENT, COLOR_ABSENT)


# ============================================================================
# ATTENDANCE UPDATE FUNCTIONS
# ============================================================================

def update_attendance_on_checkout(attendance) -> Dict[str, Any]:
    """
    Update attendance record after checkout with shift-based calculations.

    This function should be called when an employee checks out.
    It updates:
    - total_work_hours
    - half_day flag
    - final_status

    Args:
        attendance: Attendance model instance

    Returns:
        Dict with keys:
            - status: str (present, half_day, absent, checked_in_only)
            - color: str (CSS color code)
            - duration_hours: Decimal
            - shift_hours: Decimal
            - full_day_threshold: Decimal
            - half_day_threshold: Decimal
            - updated: bool (whether record was updated)
    """
    try:
        # Validate attendance has checkout
        if not attendance.check_out_time:
            logger.warning(f"Attendance {attendance.id} has no checkout time")
            return {
                'status': STATUS_CHECKED_IN_ONLY,
                'color': COLOR_CHECKED_IN,
                'duration_hours': Decimal('0.00'),
                'shift_hours': Decimal('0.00'),
                'full_day_threshold': Decimal('0.00'),
                'half_day_threshold': Decimal('0.00'),
                'updated': False,
            }

        # Get shift information (thresholds resolved per-office here)
        shift_info = get_employee_shift_info(attendance.employee)
        shift_total_hours = shift_info['total_hours']
        full_day_threshold = shift_info['full_day_threshold']
        half_day_threshold = shift_info['half_day_threshold']

        # Calculate duration
        duration_hours = calculate_duration_hours(
            attendance.check_in_time,
            attendance.check_out_time
        )

        # Determine status
        status, color = determine_attendance_status(
            duration_hours,
            full_day_threshold,
            half_day_threshold,
            has_checkout=True
        )

        # Update attendance record
        attendance.total_work_hours = duration_hours
        attendance.half_day = (status == STATUS_HALF_DAY)
        attendance.final_status = status

        # Save changes
        attendance.save(
            update_fields=['total_work_hours', 'half_day', 'final_status']
        )

        logger.info(
            f"Attendance {attendance.id} updated: "
            f"Status={status}, Hours={duration_hours}, Shift={shift_total_hours}, "
            f"FullDayThreshold={full_day_threshold}, HalfDayThreshold={half_day_threshold}"
        )

        return {
            'status': status,
            'color': color,
            'duration_hours': duration_hours,
            'shift_hours': shift_total_hours,
            'full_day_threshold': full_day_threshold,
            'half_day_threshold': half_day_threshold,
            'updated': True,
        }

    except Exception as e:
        logger.error(f"Error updating attendance on checkout: {str(e)}")
        return {
            'status': STATUS_ABSENT,
            'color': COLOR_ABSENT,
            'duration_hours': Decimal('0.00'),
            'shift_hours': Decimal('0.00'),
            'full_day_threshold': Decimal('0.00'),
            'half_day_threshold': Decimal('0.00'),
            'updated': False,
            'error': str(e),
        }


# ============================================================================
# EDGE CASE HANDLING
# ============================================================================

def handle_missing_checkout(attendance) -> Dict[str, Any]:
    """
    Handle case where employee checked in but didn't check out.

    This can happen if:
    - Employee forgot to check out
    - System crashed during shift
    - Employee left without checkout

    Args:
        attendance: Attendance model instance

    Returns:
        Dict with status and action taken
    """
    if attendance.check_out_time:
        return {
            'handled': False,
            'message': 'Attendance already has checkout time',
        }

    try:
        # Mark as absent (no checkout = no work recorded)
        attendance.final_status = STATUS_ABSENT
        attendance.half_day = False
        attendance.total_work_hours = Decimal('0.00')
        attendance.save(
            update_fields=['final_status', 'half_day', 'total_work_hours']
        )

        logger.warning(
            f"Attendance {attendance.id} marked absent due to missing checkout"
        )

        return {
            'handled': True,
            'message': 'Marked as absent due to missing checkout',
            'status': STATUS_ABSENT,
        }

    except Exception as e:
        logger.error(f"Error handling missing checkout: {str(e)}")
        return {
            'handled': False,
            'message': f'Error: {str(e)}',
        }


def handle_multiple_checkins(employee, attendance_date: date) -> Dict[str, Any]:
    """
    Handle case where employee checked in multiple times on same day.

    Current logic: Keep first check-in, ignore subsequent ones.

    Args:
        employee: Employee model instance
        attendance_date: Date of attendance

    Returns:
        Dict with action taken
    """
    from .models import Attendance

    try:
        # Get all attendance records for this employee on this date
        records = Attendance.objects.filter(
            employee=employee,
            date=attendance_date
        ).order_by('check_in_time')

        if records.count() <= 1:
            return {
                'handled': False,
                'message': 'Only one check-in found',
            }

        # Keep first record, mark others as duplicates
        first_record = records.first()
        duplicate_records = records.exclude(id=first_record.id)

        logger.warning(
            f"Found {duplicate_records.count()} duplicate check-ins for "
            f"employee {employee.id} on {attendance_date}"
        )

        return {
            'handled': True,
            'message': f'Found {duplicate_records.count()} duplicate check-ins',
            'kept_record_id': first_record.id,
            'duplicate_count': duplicate_records.count(),
        }

    except Exception as e:
        logger.error(f"Error handling multiple check-ins: {str(e)}")
        return {
            'handled': False,
            'message': f'Error: {str(e)}',
        }


def handle_overnight_shift(shift) -> Dict[str, Any]:
    """
    Handle overnight shifts (e.g., 10 PM to 6 AM).

    Args:
        shift: Shift model instance

    Returns:
        Dict with shift information
    """
    start_time = shift.start_time
    end_time = shift.end_time

    is_overnight = end_time < start_time

    if is_overnight:
        logger.info(
            f"Shift {shift.id} is overnight: {start_time} to {end_time} (next day)"
        )

    return {
        'is_overnight': is_overnight,
        'start_time': start_time,
        'end_time': end_time,
        'message': 'Overnight shift detected' if is_overnight else 'Regular shift',
    }


# ============================================================================
# CALENDAR & SUMMARY FUNCTIONS
# ============================================================================

def get_attendance_calendar_data(employee, year: int, month: int) -> Dict[str, Any]:
    """
    Get attendance data for calendar display.

    Args:
        employee: Employee model instance
        year: Year (e.g., 2024)
        month: Month (1-12)

    Returns:
        Dict with calendar data for each day
    """
    from .models import Attendance

    try:
        # Get all attendance records for this month
        records = Attendance.objects.filter(
            employee=employee,
            date__year=year,
            date__month=month
        )

        # Build calendar data
        calendar_data = {}
        for record in records:
            day = record.date.day
            status, color = calculate_attendance_status_for_record(record)

            calendar_data[day] = {
                'status': status,
                'color': color,
                'date': record.date.isoformat(),
                'check_in': record.check_in_time.isoformat() if record.check_in_time else None,
                'check_out': record.check_out_time.isoformat() if record.check_out_time else None,
                'duration': record.duration or '-',
                'hours': float(record.total_work_hours),
            }

        return {
            'success': True,
            'year': year,
            'month': month,
            'data': calendar_data,
        }

    except Exception as e:
        logger.error(f"Error getting calendar data: {str(e)}")
        return {
            'success': False,
            'error': str(e),
        }


def get_attendance_summary(employee, start_date: date, end_date: date) -> Dict[str, Any]:
    """
    Get attendance summary for a date range.

    Args:
        employee: Employee model instance
        start_date: Start date
        end_date: End date

    Returns:
        Dict with summary statistics
    """
    from .models import Attendance

    try:
        records = Attendance.objects.filter(
            employee=employee,
            date__gte=start_date,
            date__lte=end_date
        )

        # Count by status
        present_count = sum(1 for r in records if r.final_status == STATUS_PRESENT)
        half_day_count = sum(1 for r in records if r.final_status == STATUS_HALF_DAY)
        absent_count = sum(1 for r in records if r.final_status == STATUS_ABSENT)
        checked_in_only = sum(1 for r in records if r.final_status == STATUS_CHECKED_IN_ONLY)

        # Calculate total hours
        total_hours = sum(r.total_work_hours for r in records)

        # Calculate attendance percentage
        total_days = (end_date - start_date).days + 1
        attendance_percentage = (present_count + (half_day_count * 0.5)) / total_days * 100 if total_days > 0 else 0

        return {
            'success': True,
            'period': f"{start_date} to {end_date}",
            'total_days': total_days,
            'present': present_count,
            'half_day': half_day_count,
            'absent': absent_count,
            'checked_in_only': checked_in_only,
            'total_hours': float(total_hours),
            'attendance_percentage': round(attendance_percentage, 2),
        }

    except Exception as e:
        logger.error(f"Error getting attendance summary: {str(e)}")
        return {
            'success': False,
            'error': str(e),
        }