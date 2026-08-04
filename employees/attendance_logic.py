"""
Attendance Logic Module
Handles late coming, work duration, leave rules, and sandwich leave logic
"""

from datetime import datetime, date, timedelta
from decimal import Decimal
from django.utils import timezone
from django.db.models import Q
import logging

logger = logging.getLogger(__name__)

# Configuration
SHIFT_START_TIME = 9  # 9 AM
SHIFT_END_TIME = 18  # 6 PM
LATE_WINDOW_MIN = 30  # 30 minutes
LATE_WINDOW_MAX = 45  # 45 minutes
MAX_LATE_PER_MONTH = 3  # 3 times allowed
MIN_HOURS_PRESENT = 8  # 8 hours for full day
MIN_HOURS_HALF_DAY = 4  # 4 hours for half day


def get_shift_start_datetime(attendance_date: date) -> datetime:
    """Get shift start time for a given date"""
    return datetime.combine(attendance_date, datetime.min.time()).replace(hour=SHIFT_START_TIME)


def calculate_late_minutes(check_in_time: datetime, attendance_date: date) -> int:
    """Calculate how many minutes late the employee is"""
    shift_start = get_shift_start_datetime(attendance_date)
    if check_in_time <= shift_start:
        return 0
    
    delta = check_in_time - shift_start
    return int(delta.total_seconds() / 60)


def is_late(check_in_time: datetime, attendance_date: date) -> bool:
    """Check if employee is late (within 30-45 min window)"""
    late_minutes = calculate_late_minutes(check_in_time, attendance_date)
    return LATE_WINDOW_MIN <= late_minutes <= LATE_WINDOW_MAX


def get_monthly_late_count(employee, current_date: date) -> int:
    """Get late count for the current month"""
    from .models import Attendance
    
    first_day = current_date.replace(day=1)
    last_day = (first_day + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    
    late_count = Attendance.objects.filter(
        employee=employee,
        date__gte=first_day,
        date__lte=last_day,
        is_late=True
    ).count()
    
    return late_count


def reset_monthly_late_count(employee, current_date: date):
    """Reset late count on the 1st of every month"""
    if current_date.day == 1:
        from .models import Attendance
        Attendance.objects.filter(
            employee=employee,
            date__year=current_date.year,
            date__month=current_date.month
        ).update(late_count=0)


def calculate_work_hours(check_in_time: datetime, check_out_time: datetime, 
                        total_break_seconds: int = 0) -> Decimal:
    """Calculate total work hours (checkout - checkin - breaks)"""
    if not check_out_time:
        return Decimal('0.00')
    
    delta = check_out_time - check_in_time
    total_seconds = delta.total_seconds() - total_break_seconds
    
    if total_seconds < 0:
        return Decimal('0.00')
    
    hours = Decimal(str(total_seconds / 3600))
    return hours.quantize(Decimal('0.01'))


def determine_final_status(work_hours: Decimal, is_late: bool, 
                          late_count: int, has_leave_approval: bool = False) -> str:
    """
    Determine final attendance status based on work hours and late count
    
    Rules:
    - < 4 hours: Absent
    - 4-8 hours: Half Day
    - >= 8 hours: Present
    - 4th late or more: Half Day (forced) - ORANGE
    - Sandwich leave: Sandwich Leave - PURPLE
    """
    
    # 4th late coming forces half day
    if late_count >= MAX_LATE_PER_MONTH:
        return 'late_penalty'  # Half Day due to late penalty
    
    # Work duration based status
    if work_hours < MIN_HOURS_HALF_DAY:
        return 'absent'
    elif work_hours < MIN_HOURS_PRESENT:
        return 'half_day'
    else:
        return 'present'


def check_sandwich_leave(employee, current_date: date) -> bool:
    """
    Check if current day is a sandwich leave
    
    Scenario:
    - Employee absent on last working day of week (Saturday)
    - And absent/holiday on first working day (Monday)
    - Then Sunday should also be marked ABSENT (sandwich leave)
    """
    from .models import Attendance
    
    weekday = current_date.weekday()  # Monday=0, Sunday=6
    
    # Only check for Sunday (6)
    if weekday != 6:
        return False
    
    # Check if Saturday (before) was absent
    saturday = current_date - timedelta(days=1)
    saturday_absent = Attendance.objects.filter(
        employee=employee,
        date=saturday,
        final_status__in=['absent', 'sandwich_leave']
    ).exists()
    
    if not saturday_absent:
        return False
    
    # Check if Monday (after) is absent/holiday
    monday = current_date + timedelta(days=1)
    monday_absent = Attendance.objects.filter(
        employee=employee,
        date=monday,
        final_status__in=['absent', 'sandwich_leave']
    ).exists()
    
    return saturday_absent and monday_absent


def apply_leave_rules(employee, current_date: date) -> tuple:
    """
    Apply leave system logic
    
    Rules:
    1. If employee is absent without leave request:
       → Mark ABSENT for 2 consecutive days automatically
    2. If leave request exists AND admin approved:
       → Mark ABSENT only for the taken day(s)
    3. If leave request exists BUT not approved:
       → Apply rule 1 (auto 2-day absent)
    
    Returns: (should_mark_absent, auto_absent_days)
    """
    from .models import LeaveRequest, Attendance
    
    # Check if there's a leave request for this date
    leave_request = LeaveRequest.objects.filter(
        employee=employee,
        start_date__lte=current_date,
        end_date__gte=current_date
    ).first()
    
    if leave_request:
        if leave_request.status == LeaveRequest.Status.APPROVED:
            # Approved leave - mark absent only for this day
            return True, 1
        else:
            # Pending or rejected - apply auto 2-day rule
            return True, 2
    else:
        # No leave request - check if already marked absent
        attendance = Attendance.objects.filter(
            employee=employee,
            date=current_date
        ).first()
        
        if attendance and attendance.final_status == 'absent':
            # Already absent without leave - apply auto 2-day rule
            return True, 2
    
    return False, 0


def process_attendance_checkout(attendance_obj):
    """
    Process attendance record after check-out
    Updates all status fields based on business logic
    """
    from .models import Attendance
    
    try:
        if not attendance_obj.check_out_time:
            return
        
        # Calculate work hours
        total_break_seconds = attendance_obj.total_break_seconds or 0
        work_hours = calculate_work_hours(
            attendance_obj.check_in_time,
            attendance_obj.check_out_time,
            total_break_seconds
        )
        
        # Check if late
        is_late_flag = is_late(attendance_obj.check_in_time, attendance_obj.date)
        
        # Get monthly late count
        late_count = get_monthly_late_count(attendance_obj.employee, attendance_obj.date)
        
        # Determine final status
        final_status = determine_final_status(
            work_hours,
            is_late_flag,
            late_count
        )
        
        # Check for sandwich leave
        is_sandwich = check_sandwich_leave(attendance_obj.employee, attendance_obj.date)
        if is_sandwich:
            final_status = 'sandwich_leave'
        
        # Apply leave rules
        should_mark_absent, auto_days = apply_leave_rules(
            attendance_obj.employee,
            attendance_obj.date
        )
        
        # Update attendance record
        attendance_obj.total_work_hours = work_hours
        attendance_obj.is_late = is_late_flag
        attendance_obj.late_minutes = calculate_late_minutes(
            attendance_obj.check_in_time,
            attendance_obj.date
        )
        attendance_obj.late_count = late_count
        attendance_obj.final_status = final_status
        attendance_obj.forced_half_day_due_to_late = (late_count >= MAX_LATE_PER_MONTH)
        attendance_obj.sandwich_flag = is_sandwich
        attendance_obj.absent_days_auto = (final_status == 'absent' and should_mark_absent)
        
        # Update half_day flag for backward compatibility
        if final_status in ['half_day', 'late_penalty']:
            attendance_obj.half_day = True
        
        attendance_obj.save(update_fields=[
            'total_work_hours',
            'is_late',
            'late_minutes',
            'late_count',
            'final_status',
            'forced_half_day_due_to_late',
            'sandwich_flag',
            'absent_days_auto',
            'half_day'
        ])
        
        logger.info(f"Attendance processed: {attendance_obj.id}, Status: {final_status}")
    
    except Exception as e:
        logger.error(f"Error processing attendance: {str(e)}")
        raise


def get_status_color(final_status: str, forced_half_day: bool = False) -> str:
    """Get color code for status badge"""
    color_map = {
        'present': '#10b981',  # GREEN
        'absent': '#ef4444',   # RED
        'half_day': '#f59e0b', # YELLOW
        'late_penalty': '#f97316',  # ORANGE (4th late)
        'sandwich_leave': '#8b5cf6',  # PURPLE
        'checked_in': '#3b82f6',  # BLUE
    }
    return color_map.get(final_status, '#6b7280')  # GRAY as default


def get_status_display(final_status: str, forced_half_day: bool = False) -> str:
    """Get display text for status"""
    display_map = {
        'present': 'Present',
        'absent': 'Absent',
        'half_day': 'Half Day',
        'late_penalty': 'Late Penalty (Half Day)',
        'sandwich_leave': 'Sandwich Leave',
        'checked_in': 'Checked In',
    }
    return display_map.get(final_status, 'Unknown')
