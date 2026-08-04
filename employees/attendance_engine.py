"""
Complete Shift-Based Attendance Engine
Handles all attendance calculation logic with shift rules, grace periods, and leave logic
Single source of truth for attendance status
"""

from datetime import datetime, timedelta, time
from decimal import Decimal
from django.utils import timezone
from django.db.models import Q
from employees.models import Attendance, LeaveRequest, Employee, Holiday


class AttendanceEngine:
    """
    Complete attendance calculation engine
    Applies shift logic, grace periods, working hours, leave rules, etc.
    """
    
    # Status constants
    STATUS_PRESENT = 'present'
    STATUS_HALF_DAY = 'half_day'
    STATUS_ABSENT = 'absent'
    STATUS_HOLIDAY = 'holiday'
    STATUS_PAID_LEAVE = 'paid_leave'
    STATUS_SANDWICH_LEAVE = 'sandwich_leave'
    STATUS_CHECKED_IN_ONLY = 'checked_in_only'
    STATUS_FUTURE = 'future'
    
    # Color codes
    COLOR_MAP = {
        STATUS_PRESENT: '#34C759',        # Green
        STATUS_HALF_DAY: '#FFCC00',       # Yellow
        STATUS_ABSENT: '#FF3B30',         # Red
        STATUS_HOLIDAY: '#9E9E9E',        # Grey
        STATUS_PAID_LEAVE: '#2196F3',     # Blue
        STATUS_SANDWICH_LEAVE: '#FF9800', # Orange
        STATUS_CHECKED_IN_ONLY: '#007AFF', # Light Blue
        STATUS_FUTURE: '#E0E0E0',         # Light Grey
    }
    
    def __init__(self, employee, date=None):
        """
        Initialize engine for an employee
        
        Args:
            employee: Employee instance
            date: Optional specific date to calculate for
        """
        self.employee = employee
        self.date = date or timezone.now().date()
        self.shift = employee.shift  # Employee's assigned shift
        
    def get_status(self, date=None):
        """
        Get final attendance status for a specific date
        
        Returns:
            {
                'status': 'present|half_day|absent|holiday|paid_leave|sandwich_leave|checked_in_only|future',
                'color': '#RRGGBB',
                'details': {...}
            }
        """
        date = date or self.date
        
        # Check if date is in future
        if date > timezone.now().date():
            return {
                'status': self.STATUS_FUTURE,
                'color': self.COLOR_MAP[self.STATUS_FUTURE],
                'details': {'reason': 'Future date'}
            }
        
        # Check if it's a holiday
        if self._is_holiday(date):
            return {
                'status': self.STATUS_HOLIDAY,
                'color': self.COLOR_MAP[self.STATUS_HOLIDAY],
                'details': {'reason': 'Holiday'}
            }
        
        # Check if employee has approved paid leave
        paid_leave_status = self._check_paid_leave(date)
        if paid_leave_status:
            return paid_leave_status
        
        # Check for sandwich leave
        sandwich_status = self._check_sandwich_leave(date)
        if sandwich_status:
            return sandwich_status
        
        # Check if employee has pending/rejected leave (mark as absent)
        if self._has_leave_request(date):
            leave = LeaveRequest.objects.filter(
                employee=self.employee,
                start_date__lte=date,
                end_date__gte=date
            ).first()
            
            if leave and leave.status == LeaveRequest.Status.REJECTED:
                return {
                    'status': self.STATUS_ABSENT,
                    'color': self.COLOR_MAP[self.STATUS_ABSENT],
                    'details': {'reason': 'Leave rejected'}
                }
        
        # Get attendance record
        attendance = Attendance.objects.filter(
            employee=self.employee,
            date=date
        ).first()
        
        if not attendance:
            # No attendance record = Absent
            return {
                'status': self.STATUS_ABSENT,
                'color': self.COLOR_MAP[self.STATUS_ABSENT],
                'details': {'reason': 'No check-in/check-out'}
            }
        
        # Calculate status based on punch times
        return self._calculate_punch_status(attendance)
    
    def _is_holiday(self, date):
        """Check if date is a holiday"""
        try:
            Holiday.objects.get(date=date, is_active=True)
            return True
        except:
            return False
    
    def _check_paid_leave(self, date):
        """Check if employee has approved paid leave"""
        leave = LeaveRequest.objects.filter(
            employee=self.employee,
            start_date__lte=date,
            end_date__gte=date,
            status=LeaveRequest.Status.APPROVED
        ).first()
        
        if leave and not leave.is_without_pay():
            return {
                'status': self.STATUS_PAID_LEAVE,
                'color': self.COLOR_MAP[self.STATUS_PAID_LEAVE],
                'details': {'reason': 'Paid leave approved'}
            }
        
        return None
    
    def _check_sandwich_leave(self, date):
        """
        Check for sandwich leave
        If employee takes leave on Sat+Mon → Sun = Absent
        If employee takes leave on Fri+Mon → Sat+Sun = Absent
        """
        weekday = date.weekday()  # 0=Mon, 6=Sun
        
        # Check Sunday (between Sat and Mon)
        if weekday == 6:  # Sunday
            sat = date - timedelta(days=1)
            mon = date + timedelta(days=1)
            
            sat_leave = LeaveRequest.objects.filter(
                employee=self.employee,
                start_date__lte=sat,
                end_date__gte=sat,
                status=LeaveRequest.Status.APPROVED
            ).exists()
            
            mon_leave = LeaveRequest.objects.filter(
                employee=self.employee,
                start_date__lte=mon,
                end_date__gte=mon,
                status=LeaveRequest.Status.APPROVED
            ).exists()
            
            if sat_leave and mon_leave:
                return {
                    'status': self.STATUS_SANDWICH_LEAVE,
                    'color': self.COLOR_MAP[self.STATUS_SANDWICH_LEAVE],
                    'details': {'reason': 'Sandwich leave (Sat+Mon)'}
                }
        
        # Check Saturday (between Fri and Sun)
        if weekday == 5:  # Saturday
            fri = date - timedelta(days=1)
            sun = date + timedelta(days=1)
            
            fri_leave = LeaveRequest.objects.filter(
                employee=self.employee,
                start_date__lte=fri,
                end_date__gte=fri,
                status=LeaveRequest.Status.APPROVED
            ).exists()
            
            sun_leave = LeaveRequest.objects.filter(
                employee=self.employee,
                start_date__lte=sun,
                end_date__gte=sun,
                status=LeaveRequest.Status.APPROVED
            ).exists()
            
            if fri_leave and sun_leave:
                return {
                    'status': self.STATUS_SANDWICH_LEAVE,
                    'color': self.COLOR_MAP[self.STATUS_SANDWICH_LEAVE],
                    'details': {'reason': 'Sandwich leave (Fri+Sun)'}
                }
        
        return None
    
    def _has_leave_request(self, date):
        """Check if employee has any leave request for this date"""
        return LeaveRequest.objects.filter(
            employee=self.employee,
            start_date__lte=date,
            end_date__gte=date
        ).exists()
    
    def _calculate_punch_status(self, attendance):
        """
        Calculate status based on punch times and shift
        
        Rules:
        1. Late Coming → if punch-in > grace → Half Day
        2. Early Going → if punch-out < shift end → Half Day
        3. Both Late + Early → Absent
        4. Missing Punch (only check-in or only check-out) → Absent
        5. Working Hours Logic:
           - Full shift = (end – start)
           - Half shift = full_shift / 2
           - If working_hours < half_shift → Half Day
           - If working_hours >= full_shift → Present
           - If punch > grace but working_hours > half_shift → Half Day
        """
        
        # Missing punch data
        if not attendance.check_in_time or not attendance.check_out_time:
            return {
                'status': self.STATUS_CHECKED_IN_ONLY if attendance.check_in_time else self.STATUS_ABSENT,
                'color': self.COLOR_MAP[self.STATUS_CHECKED_IN_ONLY if attendance.check_in_time else self.STATUS_ABSENT],
                'details': {'reason': 'Missing check-in or check-out'}
            }
        
        # Get shift details
        if not self.shift:
            # No shift assigned - use old logic
            return {
                'status': self.STATUS_ABSENT,
                'color': self.COLOR_MAP[self.STATUS_ABSENT],
                'details': {'reason': 'No shift assigned'}
            }
        
        shift_start = self._time_to_datetime(attendance.date, self.shift.start_time)
        shift_end = self._time_to_datetime(attendance.date, self.shift.end_time)
        
        # Handle overnight shifts
        if shift_end < shift_start:
            shift_end += timedelta(days=1)
        
        check_in = attendance.check_in_time
        check_out = attendance.check_out_time
        
        # Grace period
        grace_minutes = getattr(self.shift, 'grace_period_minutes', 10)
        grace_period = timedelta(minutes=grace_minutes)
        
        # Calculate working hours
        working_duration = check_out - check_in
        working_hours = working_duration.total_seconds() / 3600
        
        shift_duration = (shift_end - shift_start).total_seconds() / 3600
        half_shift_hours = shift_duration / 2
        
        # Check late coming
        is_late = check_in > (shift_start + grace_period)
        
        # Check early going
        is_early = check_out < shift_end
        
        # Both late and early = Absent
        if is_late and is_early:
            return {
                'status': self.STATUS_ABSENT,
                'color': self.COLOR_MAP[self.STATUS_ABSENT],
                'details': {
                    'reason': 'Late coming and early going',
                    'check_in': check_in.strftime('%H:%M'),
                    'check_out': check_out.strftime('%H:%M'),
                    'shift_start': shift_start.strftime('%H:%M'),
                    'shift_end': shift_end.strftime('%H:%M'),
                }
            }
        
        # Check working hours
        if working_hours < half_shift_hours:
            return {
                'status': self.STATUS_HALF_DAY,
                'color': self.COLOR_MAP[self.STATUS_HALF_DAY],
                'details': {
                    'reason': 'Insufficient working hours',
                    'working_hours': round(working_hours, 2),
                    'required_hours': round(shift_duration, 2),
                }
            }
        
        if working_hours >= shift_duration:
            return {
                'status': self.STATUS_PRESENT,
                'color': self.COLOR_MAP[self.STATUS_PRESENT],
                'details': {
                    'reason': 'Full shift completed',
                    'working_hours': round(working_hours, 2),
                    'shift_hours': round(shift_duration, 2),
                }
            }
        
        # Late but worked enough hours
        if is_late and working_hours > half_shift_hours:
            return {
                'status': self.STATUS_HALF_DAY,
                'color': self.COLOR_MAP[self.STATUS_HALF_DAY],
                'details': {
                    'reason': 'Late coming',
                    'check_in': check_in.strftime('%H:%M'),
                    'shift_start': shift_start.strftime('%H:%M'),
                }
            }
        
        # Early but worked enough hours
        if is_early and working_hours > half_shift_hours:
            return {
                'status': self.STATUS_HALF_DAY,
                'color': self.COLOR_MAP[self.STATUS_HALF_DAY],
                'details': {
                    'reason': 'Early going',
                    'check_out': check_out.strftime('%H:%M'),
                    'shift_end': shift_end.strftime('%H:%M'),
                }
            }
        
        # Default to present if all checks pass
        return {
            'status': self.STATUS_PRESENT,
            'color': self.COLOR_MAP[self.STATUS_PRESENT],
            'details': {
                'reason': 'Full shift completed',
                'working_hours': round(working_hours, 2),
            }
        }
    
    def _time_to_datetime(self, date, time_obj):
        """Convert time object to datetime on specific date"""
        if isinstance(time_obj, str):
            time_obj = datetime.strptime(time_obj, '%H:%M').time()
        
        return datetime.combine(date, time_obj)
    
    def get_month_stats(self, year, month):
        """
        Get attendance statistics for a month
        
        Returns:
            {
                'present': count,
                'half_day': count,
                'absent': count,
                'holidays': count,
                'paid_leave': count,
                'sandwich_leave': count,
                'total_working_days': count,
            }
        """
        from calendar import monthrange
        
        # Get all days in month
        days_in_month = monthrange(year, month)[1]
        
        stats = {
            'present': 0,
            'half_day': 0,
            'absent': 0,
            'holidays': 0,
            'paid_leave': 0,
            'sandwich_leave': 0,
            'total_working_days': 0,
        }
        
        for day in range(1, days_in_month + 1):
            date = datetime(year, month, day).date()
            status_info = self.get_status(date)
            status = status_info['status']
            
            # Count only past dates
            if date <= timezone.now().date():
                if status == self.STATUS_PRESENT:
                    stats['present'] += 1
                    stats['total_working_days'] += 1
                elif status == self.STATUS_HALF_DAY:
                    stats['half_day'] += 1
                    stats['total_working_days'] += 1
                elif status == self.STATUS_ABSENT:
                    stats['absent'] += 1
                    stats['total_working_days'] += 1
                elif status == self.STATUS_HOLIDAY:
                    stats['holidays'] += 1
                elif status == self.STATUS_PAID_LEAVE:
                    stats['paid_leave'] += 1
                elif status == self.STATUS_SANDWICH_LEAVE:
                    stats['sandwich_leave'] += 1
        
        return stats
    
    def get_month_calendar(self, year, month):
        """
        Get complete calendar data for a month
        
        Returns:
            {
                'days': {
                    '2024-12-01': {'status': 'present', 'color': '#34C759'},
                    '2024-12-02': {'status': 'absent', 'color': '#FF3B30'},
                    ...
                },
                'stats': {...},
                'success': True
            }
        """
        from calendar import monthrange
        
        days_in_month = monthrange(year, month)[1]
        days_data = {}
        
        for day in range(1, days_in_month + 1):
            date = datetime(year, month, day).date()
            status_info = self.get_status(date)
            
            date_str = date.strftime('%Y-%m-%d')
            days_data[date_str] = {
                'status': status_info['status'],
                'color': status_info['color'],
                'details': status_info.get('details', {}),
            }
        
        stats = self.get_month_stats(year, month)
        
        return {
            'days': days_data,
            'stats': stats,
            'success': True
        }
