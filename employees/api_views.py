from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.http import require_http_methods
from .views import is_employee
from django.views.decorators.csrf import csrf_protect, csrf_exempt
from django.http import JsonResponse
from django.utils import timezone
from datetime import datetime as dt, timedelta
from calendar import monthrange
import json

from .models import Employee, Attendance, AttendanceDayComment, Holiday
from employees.shift_attendance_logic import calculate_attendance_status_for_record


def _get_status_display(attendance):
    """Convert Attendance status to frontend status display
    
    Returns: (status, status_label, status_color_class)
    - status: Internal status code
    - status_label: Display label
    - status_color_class: CSS class name for calendar cell styling
    
    Rules based on working duration:
    - Duration < 4 hours → ABSENT (Red #FF3B30)
    - Duration >= 4 hours and < 8 hours → HALF DAY (Yellow #FFCC00)
    - Duration >= 8 hours → PRESENT (Green #34C759)
    """
    status_map = {
        'present': ('present', 'Present', 'present'),
        'absent': ('absent', 'Absent', 'absent'),
        'half_day': ('halfday', 'Half Day', 'halfday'),
        'checked_in_only': ('checked_in', 'Checked In', 'checked_in'),
    }
    att_status, color_code = attendance.calculate_shift_based_status()  # was calculate_attendance_status
    if att_status in status_map:
        return status_map[att_status]
    
    # Fallback to absent if no attendance
    return ('absent', 'Absent', 'absent')


def _format_attendance_detail(attendance, employee, attendance_date, request=None):
    """Format a single attendance record for API response"""
    if not attendance:
        # No attendance record - return absent
        comments_qs = AttendanceDayComment.objects.filter(employee=employee, date=attendance_date).order_by('-created_at')
        comments = [
            {
                'id': c.pk,
                'comment': c.comment,
                'created_by': (c.created_by.get_username() if c.created_by else 'system'),
                'created_at': timezone.localtime(c.created_at).isoformat(),
                'is_admin_comment': c.is_admin_comment,
            }
            for c in comments_qs
        ]
        
        return {
            'date': attendance_date.isoformat(),
            'weekday': attendance_date.strftime('%A, %B %d, %Y'),
            'check_in_time': None,
            'check_out_time': None,
            'check_in_photo_url': None,
            'check_out_photo_url': None,
            'total_duration_seconds': None,
            'total_duration_display': '—',
            'status': 'absent',
            'status_label': 'Absent',
            'status_color_class': 'absent',
            'comments': comments,
            'paid_leave_balance': round(employee.calculate_paid_leave_balance(), 1),
        }
    
    # Format check-in/out times - CONVERT TO INDIA TIMEZONE (Asia/Kolkata)
    check_in_time = None
    check_in_time_display = None
    if attendance.check_in_time:
        # Convert to India timezone
        check_in_local = timezone.localtime(attendance.check_in_time)
        check_in_time = check_in_local.isoformat()
        check_in_time_display = check_in_local.strftime('%I:%M %p')
    
    check_out_time = None
    check_out_time_display = None
    if attendance.check_out_time:
        # Convert to India timezone
        check_out_local = timezone.localtime(attendance.check_out_time)
        check_out_time = check_out_local.isoformat()
        check_out_time_display = check_out_local.strftime('%I:%M %p')
    
    # Calculate duration
    total_duration_seconds = None
    total_duration_display = '—'
    if attendance.check_in_time and attendance.check_out_time:
        total_duration_seconds = attendance.worked_seconds
        hours = total_duration_seconds // 3600
        minutes = (total_duration_seconds % 3600) // 60
        total_duration_display = f"{hours}h {minutes}m"
    
    # Get status
    status, status_label, status_color = _get_status_display(attendance)
    
    # Get comments
    comments_qs = AttendanceDayComment.objects.filter(employee=employee, date=attendance_date).order_by('-created_at')
    comments = [
        {
            'id': c.pk,
            'comment': c.comment,
            'created_by': (c.created_by.get_username() if c.created_by else 'system'),
            'created_at': timezone.localtime(c.created_at).isoformat(),
            'is_admin_comment': c.is_admin_comment,
        }
        for c in comments_qs
    ]
    
    # Get photo URLs - ensure they're absolute URLs if request is available
    check_in_photo_url = None
    check_out_photo_url = None
    if attendance.check_in_photo:
        try:
            if request and hasattr(request, 'build_absolute_uri'):
                check_in_photo_url = request.build_absolute_uri(attendance.check_in_photo.url)
            else:
                check_in_photo_url = attendance.check_in_photo.url
        except Exception:
            check_in_photo_url = attendance.check_in_photo.url if attendance.check_in_photo else None
    if attendance.check_out_photo:
        try:
            if request and hasattr(request, 'build_absolute_uri'):
                check_out_photo_url = request.build_absolute_uri(attendance.check_out_photo.url)
            else:
                check_out_photo_url = attendance.check_out_photo.url
        except Exception:
            check_out_photo_url = attendance.check_out_photo.url if attendance.check_out_photo else None
    
    return {
        'date': attendance_date.isoformat(),
        'weekday': attendance_date.strftime('%A, %B %d, %Y'),
        'check_in_time': check_in_time,
        'check_in_time_display': check_in_time_display,
        'check_out_time': check_out_time,
        'check_out_time_display': check_out_time_display,
        'check_in_photo_url': check_in_photo_url,
        'check_out_photo_url': check_out_photo_url,
        'total_duration_seconds': total_duration_seconds,
        'total_duration_display': total_duration_display,
        'status': status,
        'status_label': status_label,
        'status_color_class': status_color,
        'comments': comments,
        'paid_leave_balance': round(employee.calculate_paid_leave_balance(), 1),
    }


@login_required
@require_http_methods(["GET"])
def attendance_month_api(request, employee_id):
    """GET /api/attendance/<employee_id>/month?year=2024&month=11
    
    Returns all attendance records for a given month with status mapping.
    """
    try:
        # Get year and month from query params
        current_date = timezone.now()
        year = int(request.GET.get('year', current_date.year))
        month = int(request.GET.get('month', current_date.month))
        
        # Validate month/year
        if month < 1 or month > 12:
            return JsonResponse({'error': 'Invalid month. Must be 1-12'}, status=400)
        if year < 1900 or year > 2100:
            return JsonResponse({'error': 'Invalid year'}, status=400)
        
        # Resolve employee and permissions
        employee = get_object_or_404(Employee, pk=employee_id)
        if not request.user.is_superuser:
            # Only allow the logged-in employee to fetch their own data
            if not hasattr(request.user, 'employee_profile') or request.user.employee_profile.id != employee.id:
                return JsonResponse({'error': 'Permission denied'}, status=403)
        
        # Get first and last day of month
        first_day = dt(year, month, 1).date()
        last_day = dt(year, month, monthrange(year, month)[1]).date()
        
        # Fetch all attendance records for this month
        attendance_records = Attendance.objects.filter(
            employee=employee,
            date__gte=first_day,
            date__lte=last_day
        ).order_by('date')
        
        # Create attendance lookup
        attendance_dict = {record.date: record for record in attendance_records}
        
        # Get holidays
        holidays = Holiday.objects.filter(date__gte=first_day, date__lte=last_day)
        holiday_dates = {h.date: h for h in holidays}
        
        def is_holiday(date_obj):
            """Check if date is a holiday"""
            if date_obj in holiday_dates:
                return True
            # Sunday
            if date_obj.weekday() == 6:
                return True
            # 1st, 3rd, 5th Saturday
            if date_obj.weekday() == 5:
                saturday_count = sum(1 for d in range(1, date_obj.day + 1)
                                   if dt(date_obj.year, date_obj.month, d).weekday() == 5)
                if saturday_count in [1, 3, 5]:
                    return True
            return False
        
        # Build response data
        days_data = {}
        stats = {
            'present': 0,
            'half_day': 0,
            'absent': 0,
            'holidays': 0,
            'paid_leave': 0,
            'late_penalty': 0,
            'sandwich_leave': 0,
            'checked_in': 0,
        }
        
        current_date_obj = current_date.date()
        for day in range(1, last_day.day + 1):
            date_obj = dt(year, month, day).date()
            attendance = attendance_dict.get(date_obj)
            
            # Check for approved paid leave first
            is_paid_leave = False
            if employee.joining_date:
                days_since_joining = (date_obj - employee.joining_date).days
                if days_since_joining >= 91:  # After 90 days
                    from .models import LeaveRequest
                    approved_leave = LeaveRequest.objects.filter(
                        employee=employee,
                        start_date__lte=date_obj,
                        end_date__gte=date_obj,
                        status=LeaveRequest.Status.APPROVED
                    ).exists()
                    if approved_leave:
                        is_paid_leave = True
            
            if is_holiday(date_obj):
                status = 'holiday'
                status_label = 'Holiday'
                status_color = 'holiday'
                stats['holidays'] += 1
            elif is_paid_leave:
                status = 'paid_leave'
                status_label = 'Paid Leave'
                status_color = 'paid_leave'
                stats['paid_leave'] += 1
            elif attendance:
                status, status_label, status_color = _get_status_display(attendance)
                # Ensure status_color matches CSS class names (am-calendar__cell--{status_color})
                # Map to valid CSS classes: present_full, present_half, absent, holiday, paid_leave, sandwich_leave, etc.
                if status_color not in ['present_full', 'present_half', 'absent', 'holiday', 'paid_leave', 'sandwich_leave', 'late_penalty', 'checked_in']:
                    if 'present' in status_color.lower() and 'full' in status_color.lower():
                        status_color = 'present_full'
                    elif 'present' in status_color.lower() and 'half' in status_color.lower():
                        status_color = 'present_half'
                    elif 'checked' in status_color.lower() or 'in' in status_color.lower():
                        status_color = 'checked_in'
                    elif 'late' in status_color.lower():
                        status_color = 'late_penalty'
                    elif 'sandwich' in status_color.lower():
                        status_color = 'sandwich_leave'
                    else:
                        status_color = 'absent'
                
                # Map status to stats keys
                if status == 'present':
                    stats['present'] = stats.get('present', 0) + 1
                elif status == 'half_day':
                    stats['half_day'] = stats.get('half_day', 0) + 1
                elif status == 'checked_in':
                    stats['checked_in'] = stats.get('checked_in', 0) + 1
                elif status == 'late_penalty':
                    stats['late_penalty'] = stats.get('late_penalty', 0) + 1
                elif status == 'sandwich_leave':
                    stats['sandwich_leave'] = stats.get('sandwich_leave', 0) + 1
                else:
                    # For any other status (including 'absent'), count in its category
                    stats[status] = stats.get(status, 0) + 1
            elif date_obj < current_date_obj:
                # Past date without attendance and not holiday/paid leave = absent
                status = 'absent'
                status_label = 'Absent'
                status_color = 'absent'
                stats['absent'] += 1
            else:
                # Future date
                status = 'future'
                status_label = 'Upcoming'
                status_color = 'future'
            
            days_data[str(date_obj)] = {
                'date': date_obj.isoformat(),
                'day': day,
                'status': status,
                'status_label': status_label,
                'status_color': status_color,
                'has_attendance': bool(attendance),
            }
        
        return JsonResponse({
            'success': True,
            'year': year,
            'month': month,
            'days': days_data,
            'stats': stats,
            'paid_leave_balance': round(employee.calculate_paid_leave_balance(), 1),
        }, status=200)
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def attendance_detail_api_v2(request, employee_id, date_str):
    """GET /api/attendance/<employee_id>/<YYYY-MM-DD>/

    Returns attendance details with photos, times, duration, status tokens,
    comments, and paid leave balance. Contract compliant for frontend usage.
    """
    try:
        # Parse date
        try:
            attendance_date = dt.strptime(date_str, '%Y-%m-%d').date()
        except Exception:
            return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=400)

        # Resolve employee and permissions
        employee = get_object_or_404(Employee, pk=employee_id)
        if not request.user.is_superuser:
            # Only allow the logged-in employee to fetch their own daily details
            if not hasattr(request.user, 'employee_profile') or request.user.employee_profile.id != employee.id:
                return JsonResponse({'error': 'Permission denied'}, status=403)

        # Attendance record (if any)
        attendance = Attendance.objects.filter(employee=employee, date=attendance_date).first()
        
        data = _format_attendance_detail(attendance, employee, attendance_date, request)
        return JsonResponse(data, status=200)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def attendance_comment_api_v2(request, employee_id, date_str):
    """POST /api/attendance/<employee_id>/<YYYY-MM-DD>/comments/

    Creates or updates a day comment. Returns the created/updated comment object (201/200).
    """
    try:
        # Parse date
        try:
            from datetime import datetime as dt
            attendance_date = dt.strptime(date_str, '%Y-%m-%d').date()
        except Exception:
            return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=400)

        # Resolve employee and permissions
        employee = get_object_or_404(Employee, pk=employee_id)
        if not request.user.is_superuser:
            # Only allow the logged-in employee to create/update their own comments
            if not hasattr(request.user, 'employee_profile') or request.user.employee_profile.id != employee.id:
                return JsonResponse({'error': 'Permission denied'}, status=403)

        # Read comment (JSON body or form-encoded)
        comment_text = ''
        if request.body:
            try:
                body = json.loads(request.body.decode('utf-8') or '{}')
                comment_text = (body.get('comment') or '').strip()
            except Exception:
                comment_text = ''
        if not comment_text:
            comment_text = (request.POST.get('comment') or '').strip()
        if not comment_text:
            return JsonResponse({'error': 'Comment cannot be empty'}, status=400)

        obj, created = AttendanceDayComment.objects.update_or_create(
            employee=employee,
            branch=employee.branch,
            date=attendance_date,
            is_admin_comment=bool(request.user.is_superuser),
            defaults={
                'comment': comment_text,
                'created_by': request.user,
            }
        )

        payload = {
            'id': obj.pk,
            'comment': obj.comment,
            'created_by': (obj.created_by.get_username() if obj.created_by else 'system'),
            'created_at': timezone.localtime(obj.created_at).isoformat(),
            'is_admin_comment': obj.is_admin_comment,
        }

        return JsonResponse(payload, status=201 if created else 200)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def paid_leave_balance_api(request, employee_id):
    """API endpoint to get paid leave balance for an employee"""
    try:
        employee = get_object_or_404(Employee, id=employee_id)
        
        # Permission check: employee can only see their own balance, admin can see any
        if not request.user.is_superuser:
            if not hasattr(request.user, 'employee_profile') or request.user.employee_profile.id != employee_id:
                return JsonResponse({'error': 'Permission denied'}, status=403)
        
        balance = employee.calculate_paid_leave_balance()
        
        return JsonResponse({
            'success': True,
            'employee_id': employee_id,
            'paid_leave_balance': float(balance),
            'paid_leave_balance_formatted': f"{float(balance):.1f}",
        }, status=200)
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)


# ============================================
# DASHBOARD API
# ============================================

def _calculate_shift_window(employee):
    """Calculate if employee is within check-in/out window
    
    Returns: {
        'can_check_in': bool,
        'can_check_out': bool,
        'next_checkin_time': str,
        'next_checkout_time': str,
        'shift_start': str,
        'shift_end': str,
        'is_night_shift': bool,
        'message': str
    }
    """
    from datetime import time as dt_time
    
    if not employee.shift:
        return {
            'can_check_in': False,
            'can_check_out': False,
            'shift_start': 'N/A',
            'shift_end': 'N/A',
            'is_night_shift': False,
            'message': 'No shift assigned'
        }
    
    now = timezone.now()
    current_time = now.time()
    shift_start = employee.shift.start_time
    shift_end = employee.shift.end_time
    
    # Calculate window times (30 minutes before/after)
    window_before = timedelta(minutes=30)
    window_after = timedelta(minutes=30)
    
    # Convert times to datetime for calculation
    shift_start_dt = dt.combine(now.date(), shift_start)
    shift_end_dt = dt.combine(now.date(), shift_end)
    
    # Handle night shifts (end time < start time)
    is_night_shift = shift_end < shift_start
    if is_night_shift:
        # If current time is after shift start, it's today's shift
        # If current time is before shift end, it's yesterday's shift
        if current_time >= shift_start:
            shift_end_dt = dt.combine(now.date() + timedelta(days=1), shift_end)
    
    checkin_window_start = shift_start_dt - window_before
    checkin_window_end = shift_start_dt + window_after
    checkout_window_start = shift_end_dt - window_before
    checkout_window_end = shift_end_dt + window_after
    
    current_dt = now.replace(second=0, microsecond=0)
    
    can_check_in = checkin_window_start <= current_dt <= checkin_window_end
    can_check_out = checkout_window_start <= current_dt <= checkout_window_end
    
    # Format times for display
    shift_start_str = shift_start.strftime('%I:%M %p')
    shift_end_str = shift_end.strftime('%I:%M %p')
    
    message = ''
    if can_check_in:
        message = f'Check-in window open (until {checkin_window_end.strftime("%I:%M %p")})'
    elif can_check_out:
        message = f'Check-out window open (until {checkout_window_end.strftime("%I:%M %p")})'
    else:
        if current_dt < checkin_window_start:
            message = f'Next check-in window opens at {checkin_window_start.strftime("%I:%M %p")}'
        elif current_dt > checkout_window_end:
            message = 'Shift ended. You\'re off duty.'
        else:
            message = f'Next check-out window opens at {checkout_window_start.strftime("%I:%M %p")}'
    
    return {
        'can_check_in': can_check_in,
        'can_check_out': can_check_out,
        'shift_start': shift_start_str,
        'shift_end': shift_end_str,
        'is_night_shift': is_night_shift,
        'message': message,
        'next_checkin_time': checkin_window_start.strftime('%I:%M %p'),
        'next_checkout_time': checkout_window_start.strftime('%I:%M %p'),
    }


@login_required
@require_http_methods(["GET"])
def dashboard_api(request):
    """API endpoint for employee dashboard data"""
    try:
        from .models import EmployeePoints, EmployeeTask, EmployeeNotification
        from .weather_service import WeatherService
        from datetime import date
        
        employee = request.user.employee_profile
        now = timezone.now()
        current_date = now.date()
        current_month = now.month
        current_year = now.year
        
        # Get shift window info
        shift_window = _calculate_shift_window(employee)
        
        # Get today's attendance
        today_attendance = Attendance.objects.filter(
            employee=employee,
            date=current_date
        ).first()
        
        # Get current month points
        points_obj = EmployeePoints.objects.filter(
            employee=employee,
            month=current_month,
            year=current_year
        ).first()
        
        current_points = points_obj.points if points_obj else 0
        
        # Get today's tasks
        today_tasks = EmployeeTask.objects.filter(
            employee=employee,
            due_date=current_date
        ).values('id', 'title', 'status', 'priority')
        
        # Get unread notifications count
        unread_notifications = EmployeeNotification.objects.filter(
            employee=employee,
            is_read=False
        ).count()
        
        # Get top 3 performers this month
        top_performers = EmployeePoints.objects.filter(
            month=current_month,
            year=current_year
        ).select_related('employee').order_by('-points')[:3]
        
        top_performers_data = [
            {
                'rank': idx + 1,
                'name': perf.employee.full_name,
                'points': perf.points,
                'photo': perf.employee.profile_picture.url if perf.employee.profile_picture else None
            }
            for idx, perf in enumerate(top_performers)
        ]
        
        # Check profile completion
        profile_complete = all([
            employee.full_name,
            employee.email,
            employee.contact,
            employee.joining_date,
        ])
        
        # Get current time for greeting
        hour = now.hour
        if 6 <= hour < 12:
            greeting = 'Good Morning'
            time_period = 'morning'
        elif 12 <= hour < 17:
            greeting = 'Good Afternoon'
            time_period = 'afternoon'
        elif 17 <= hour < 21:
            greeting = 'Good Evening'
            time_period = 'evening'
        else:
            greeting = 'Good Night'
            time_period = 'night'
        
        # Get weather data
        weather_data = WeatherService.get_weather(city='Bangalore')
        weather_theme = WeatherService.get_weather_theme(
            weather_data.get('condition', 'Clear'),
            weather_data.get('temperature', 25)
        )
        weather_icon = WeatherService.get_weather_icon(weather_data.get('icon', '01d'))
        weather_recommendation = WeatherService.get_weather_recommendation(
            weather_data.get('condition', 'Clear'),
            weather_data.get('temperature', 25)
        )
        
        return JsonResponse({
            'success': True,
            'employee': {
                'id': employee.id,
                'name': employee.full_name,
                'email': employee.email,
                'photo': employee.profile_picture.url if employee.profile_picture else None,
            },
            'greeting': greeting,
            'time_period': time_period,
            'shift_window': shift_window,
            'attendance': {
                'checked_in': bool(today_attendance and today_attendance.open_session),
                'checked_out': bool(today_attendance and not today_attendance.open_session and today_attendance.check_out_time is not None),
                'check_in_time': today_attendance.check_in_time.strftime('%I:%M %p') if today_attendance and today_attendance.check_in_time else None,
                'check_out_time': today_attendance.check_out_time.strftime('%I:%M %p') if today_attendance and today_attendance.check_out_time else None,
                'status': today_attendance.final_status if today_attendance else None,
            },
            'points': {
                'current': current_points,
                'month': current_month,
                'year': current_year,
            },
            'tasks': {
                'today': list(today_tasks),
                'count': today_tasks.count(),
            },
            'notifications': {
                'unread_count': unread_notifications,
            },
            'top_performers': top_performers_data,
            'profile': {
                'complete': profile_complete,
            },
            'weather': {
                'success': weather_data.get('success', False),
                'city': weather_data.get('city', 'Unknown'),
                'temperature': weather_data.get('temperature', 0),
                'condition': weather_data.get('condition', 'Unknown'),
                'description': weather_data.get('description', ''),
                'humidity': weather_data.get('humidity', 0),
                'wind_speed': weather_data.get('wind_speed', 0),
                'icon': weather_icon,
                'recommendation': weather_recommendation,
            },
            'theme': {
                'name': weather_theme.get('name', 'default'),
                'gradient': weather_theme.get('gradient', ''),
                'text_color': weather_theme.get('text_color', '#ffffff'),
                'accent': weather_theme.get('accent', '#667eea'),
            },
        }, status=200)
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)


# ============================================
# NOTIFICATION API ENDPOINTS
# ============================================

@login_required
@require_http_methods(["POST"])
def mark_notification_as_read(request, notification_id):
    """Mark a notification as read"""
    try:
        from .models import EmployeeNotification
        
        notification = EmployeeNotification.objects.get(id=notification_id)
        
        # Check permission
        if notification.employee != request.user.employee_profile:
            return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
        
        notification.is_read = True
        notification.save()
        
        return JsonResponse({'success': True})
    except EmployeeNotification.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Notification not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def mark_all_notifications_as_read(request):
    """Mark all notifications as read"""
    try:
        from .models import EmployeeNotification
        
        employee = request.user.employee_profile
        EmployeeNotification.objects.filter(
            employee=employee,
            is_read=False
        ).update(is_read=True)
        
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def delete_notification(request, notification_id):
    """Delete a notification"""
    try:
        from .models import EmployeeNotification
        
        notification = EmployeeNotification.objects.get(id=notification_id)
        
        # Check permission
        if notification.employee != request.user.employee_profile:
            return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
        
        notification.delete()
        
        return JsonResponse({'success': True})
    except EmployeeNotification.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Notification not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def clear_all_notifications(request):
    """Delete all notifications"""
    try:
        from .models import EmployeeNotification
        
        employee = request.user.employee_profile
        EmployeeNotification.objects.filter(employee=employee).delete()
        
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def update_notification_preferences(request):
    """Update notification preferences"""
    try:
        from .models import NotificationPreference
        import json
        
        employee = request.user.employee_profile
        data = json.loads(request.body)
        
        preference_name = data.get('preference')
        preference_value = data.get('value')
        
        prefs, created = NotificationPreference.objects.get_or_create(employee=employee)
        
        # Update preference
        if hasattr(prefs, preference_name):
            setattr(prefs, preference_name, preference_value)
            prefs.save()
            return JsonResponse({'success': True})
        else:
            return JsonResponse({'success': False, 'error': 'Invalid preference'}, status=400)
    
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@require_http_methods(["GET"])
@csrf_exempt  # Allow without CSRF token for simplicity
def holidays_api(request, employee_id):
    """API endpoint to get holidays for a specific month and year"""
    try:
        # Holidays are company-wide information, no authentication needed
        # This allows the holiday table to work for all users

        # Get year and month from query params
        year = int(request.GET.get('year', timezone.now().year))
        month = int(request.GET.get('month', timezone.now().month))
        
        # Get holidays for this month
        from employees.models import Holiday
        month_start = dt(year, month, 1).date()
        if month == 12:
            month_end = dt(year + 1, 1, 1).date() - timedelta(days=1)
        else:
            month_end = dt(year, month + 1, 1).date() - timedelta(days=1)
        
        holidays = Holiday.objects.filter(
            date__gte=month_start,
            date__lte=month_end
        ).order_by('date')
        
        # Debug: Log the query and results
        print(f"[DEBUG] Holiday API: Looking for holidays between {month_start} and {month_end}")
        print(f"[DEBUG] Holiday API: Found {holidays.count()} holidays")
        
        # Build holiday list
        holiday_list = []
        for holiday in holidays:
            print(f"[DEBUG] Holiday API: Found holiday - {holiday.date}: {holiday.name}")
            holiday_list.append({
                'date': holiday.date.strftime('%Y-%m-%d'),
                'day': holiday.date.strftime('%A'),
                'reason': holiday.name
            })
        
        return JsonResponse({
            'success': True,
            'year': year,
            'month': month,
            'holidays': holiday_list
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@require_http_methods(["GET"])
def attendance_month_api_legacy(request, employee_id):
    """Legacy API endpoint to get attendance data for a month.

    Kept for backward-compatibility; new calendar uses the enhanced
    `attendance_month_api` defined earlier in this module.
    """
    try:
        # Check if user is viewing their own data or is admin
        user_employee = request.user.employee_profile
        if user_employee.id != employee_id and not request.user.is_superuser:
            return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)

        employee = Employee.objects.get(id=employee_id)
        
        # Get year and month from query params
        year = int(request.GET.get('year', timezone.now().year))
        month = int(request.GET.get('month', timezone.now().month))
        
        # Get all attendance records for this month
        month_start = dt(year, month, 1).date()
        if month == 12:
            month_end = dt(year + 1, 1, 1).date() - timedelta(days=1)
        else:
            month_end = dt(year, month + 1, 1).date() - timedelta(days=1)
        
        attendance_records = Attendance.objects.filter(
            employee=employee,
            date__gte=month_start,
            date__lte=month_end
        )
        
        # Build days dictionary
        days = {}
        for day in range(1, 32):
            try:
                date = dt(year, month, day).date()
                if date > month_end:
                    break
                    
                attendance = attendance_records.filter(date=date).first()
                
                if attendance:
                    status, status_label, status_color = _get_status_display(attendance)
                    days[str(date)] = {
                        'date': str(date),
                        'day': day,
                        'status': status,
                        'status_label': status_label,
                        'status_color': status_color,
                        'has_attendance': True
                    }
                else:
                    # Check if it's a holiday or weekend
                    is_weekend = date.weekday() >= 5
                    is_holiday = Holiday.objects.filter(date=date).exists()
                    
                    if is_holiday:
                        days[str(date)] = {
                            'date': str(date),
                            'day': day,
                            'status': 'holiday',
                            'status_label': 'Holiday',
                            'status_color': 'holiday',
                            'has_attendance': False
                        }
                    elif is_weekend:
                        days[str(date)] = {
                            'date': str(date),
                            'day': day,
                            'status': 'weekend',
                            'status_label': 'Weekend',
                            'status_color': 'holiday',
                            'has_attendance': False
                        }
                    else:
                        days[str(date)] = {
                            'date': str(date),
                            'day': day,
                            'status': 'absent',
                            'status_label': 'Absent',
                            'status_color': 'absent',
                            'has_attendance': False
                        }
            except ValueError:
                break
        
        # Calculate stats
        stats = {
            'present': attendance_records.filter(is_late=False, half_day=False).exclude(check_out_time__isnull=True).count(),
            'half_day': attendance_records.filter(half_day=True).count(),
            'absent': (month_end.day - len([d for d in days.values() if d['has_attendance']])),
            'holidays': len([d for d in days.values() if d['status'] == 'holiday']),
        }
        
        return JsonResponse({
            'success': True,
            'year': year,
            'month': month,
            'days': days,
            'stats': stats,
        })
        
    except Employee.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Employee not found'}, status=404)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def checkin_dashboard_api(request):
    """API endpoint for check-in/check-out dashboard with all required data"""
    try:
        from .models import EmployeeNotification, EmployeePoints
        
        employee = request.user.employee_profile
        today = timezone.now().date()
        
        # Get today's attendance
        today_attendance = Attendance.objects.filter(
            employee=employee,
            date=today
        ).first()
        
        # Get shift info - MUST come from employee.shift
        shift_data = None
        shift_start_display = None
        shift_end_display = None
        shift_window = None
        if employee.shift:
            # Raw shift data for frontend logic
            shift_data = {
                'id': employee.shift.id,
                'name': employee.shift.name,
                'start_time': str(employee.shift.start_time),
                'end_time': str(employee.shift.end_time),
                'shift_type': employee.shift.shift_type,
            }
            # Human-readable display times (12-hour format)
            shift_start_display = employee.shift.start_time.strftime('%I:%M %p')
            shift_end_display = employee.shift.end_time.strftime('%I:%M %p')

            # Calculate check-in/check-out windows (handles night shifts)
            shift_window = _calculate_shift_window(employee)
        
        # Get today's attendance data
        attendance_data = None
        today_attendance_status = None
        today_check_in_display = None
        today_check_out_display = None
        if today_attendance:
            attendance_data = {
                'id': today_attendance.id,
                'check_in_time': today_attendance.check_in_time.isoformat() if today_attendance.check_in_time else None,
                'check_out_time': today_attendance.check_out_time.isoformat() if today_attendance.check_out_time else None,
                'half_day': today_attendance.half_day,
                'is_late': today_attendance.is_late,
            }
            # Status summary for dashboard JSON
            if today_attendance.final_status:
                today_attendance_status = today_attendance.final_status
            elif today_attendance.check_in_time and today_attendance.check_out_time:
                today_attendance_status = 'present'
            elif today_attendance.check_in_time and not today_attendance.check_out_time:
                today_attendance_status = 'checked_in'
            else:
                today_attendance_status = 'absent'

            if today_attendance.check_in_time:
                today_check_in_display = timezone.localtime(today_attendance.check_in_time).strftime('%I:%M %p')
            if today_attendance.check_out_time:
                today_check_out_display = timezone.localtime(today_attendance.check_out_time).strftime('%I:%M %p')
        
        # Get pending tasks count (safe fallback if Task model doesn't exist)
        pending_tasks = 0
        try:
            from .models import Task
            pending_tasks = Task.objects.filter(
                assigned_to=employee,
                status__in=['pending', 'in_progress']
            ).count()
        except:
            pending_tasks = 0
        
        # Get alerts (notifications)
        alerts = EmployeeNotification.objects.filter(
            employee=employee,
            is_read=False
        ).count()
        
        # Get top performers list (for display) - keep lightweight
        top_performers = []
        
        # Get month points
        month_points = 0
        try:
            points_obj = EmployeePoints.objects.filter(
                employee=employee,
                month=today.month,
                year=today.year
            ).first()
            if points_obj:
                month_points = points_obj.points
        except:
            month_points = 0
        
        # Get notifications
        notifications = EmployeeNotification.objects.filter(
            employee=employee
        ).order_by('-created_at')[:10]
        
        notifications_data = [
            {
                'id': n.id,
                'notification_type': n.notification_type,
                'title': n.title,
                'message': n.message,
                'is_read': n.is_read,
                'created_at': n.created_at.isoformat(),
                'action_url': n.action_url,
            }
            for n in notifications
        ]
        
        # Dashboard JSON structure (backwards compatible with existing frontend)
        payload = {
            'success': True,
            # New top-level summary fields
            'employee_name': employee.full_name,
            'employee_code': f"KI{employee.id:05d}",
            'shift_start': shift_start_display,
            'shift_end': shift_end_display,
            'month_points': month_points,
            'today_attendance_summary': {
                'status': today_attendance_status,
                'checkin': today_check_in_display,
                'checkout': today_check_out_display,
            },
            'tasks': pending_tasks,
            'alerts': alerts,
            'top_performers': top_performers,
            # Legacy keys used by existing JS
            'employee': {
                'id': employee.id,
                'full_name': employee.full_name,
                'month_points': month_points,
            },
            'shift': shift_data,
            'shift_window': shift_window,
            'today_attendance': attendance_data,
            'pending_tasks': pending_tasks,
            'alerts': alerts,
            'top_performers': len(top_performers),
            'notifications': notifications_data,
        }

        return JsonResponse(payload)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@user_passes_test(is_employee)
def dashboard_ui_state_api(request):
    """API endpoint that returns single UI state object for dashboard
    Returns state, check-in/out times, attendance status, and last 7 days data
    """
    try:
        from datetime import timedelta
        from django.db.models import Q
        
        employee = request.user.employee_profile
        today = timezone.now().date()
        
        # Get today's attendance
        today_attendance = Attendance.objects.filter(
            employee=employee,
            date=today
        ).first()
        
        # Determine UI state
        state = 'pre_checkin'
        check_in_time = None
        check_out_time = None
        attendance_status = None
        
        if today_attendance:
            if today_attendance.open_session:
                state = 'waiting_checkout'
                check_in_time = timezone.localtime(today_attendance.open_session.check_in_time).strftime('%I:%M %p')
                attendance_status = 'checked_in'
            elif today_attendance.check_in_time and today_attendance.check_out_time:
                # Checked out - the next action is a new check-in (several per day are allowed).
                check_in_time = timezone.localtime(today_attendance.check_in_time).strftime('%I:%M %p')
                check_out_time = timezone.localtime(today_attendance.check_out_time).strftime('%I:%M %p')
                attendance_status = today_attendance.final_status or 'present'
        
        # Get last 7 days attendance data
        last_7_days = []
        for i in range(7):
            date = today - timedelta(days=i)
            attendance = Attendance.objects.filter(
                employee=employee,
                date=date
            ).first()
            
            day_data = {
                'date': date.strftime('%Y-%m-%d'),
                'day_name': date.strftime('%A'),
                'status': 'absent',
                'check_in_time': None,
                'check_out_time': None,
                'icon': 'bx-x-circle'
            }
            
            if attendance:
                if attendance.check_in_time:
                    day_data['check_in_time'] = timezone.localtime(attendance.check_in_time).strftime('%I:%M %p')
                if attendance.check_out_time:
                    day_data['check_out_time'] = timezone.localtime(attendance.check_out_time).strftime('%I:%M %p')
                
                # Determine status and icon
                if attendance.final_status:
                    status = attendance.final_status.lower()
                elif attendance.check_in_time and attendance.check_out_time:
                    status = 'present'
                elif attendance.check_in_time:
                    status = 'checked_in'
                else:
                    status = 'absent'
                
                day_data['status'] = status
                
                # Set icon based on status
                if status == 'present':
                    day_data['icon'] = 'bx-check-circle'
                elif status == 'half_day' or status == 'half':
                    day_data['icon'] = 'bx-time-five'
                elif status == 'checked_in':
                    day_data['icon'] = 'bx-log-in-circle'
                elif status == 'holiday':
                    day_data['icon'] = 'bx-calendar'
                elif status == 'paid_leave':
                    day_data['icon'] = 'bx-file'
                else:
                    day_data['icon'] = 'bx-x-circle'
            
            last_7_days.append(day_data)
        
        # Return single UI state object
        return JsonResponse({
            'state': state,
            'check_in_time': check_in_time,
            'check_out_time': check_out_time,
            'attendance_status': attendance_status,
            'last_7_days': last_7_days
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'error': str(e)
        }, status=500)


@login_required
@require_http_methods(["GET"])
def attendance_calendar_ajax(request):
    """AJAX endpoint for attendance calendar with unified status logic
    
    GET /api/attendance/calendar/?month=11&year=2025
    
    Returns:
    {
        "success": true,
        "stats": {
            "present": 10,
            "half": 2,
            "absent": 3,
            "holidays": 15,
            "paid_leave": 1
        },
        "dates": [
            {"date": "2025-11-01", "status": "holiday"},
            {"date": "2025-11-26", "status": "half"},
            ...
        ]
    }
    """
    try:
        employee = request.user.employee_profile
        
        # Get month and year from query params
        current_date = timezone.now()
        year = int(request.GET.get('year', current_date.year))
        month = int(request.GET.get('month', current_date.month))
        
        # Validate month/year
        if month < 1 or month > 12:
            return JsonResponse({'error': 'Invalid month'}, status=400)
        if year < 1900 or year > 2100:
            return JsonResponse({'error': 'Invalid year'}, status=400)
        
        # Get first and last day of month
        first_day = dt(year, month, 1).date()
        last_day = dt(year, month, monthrange(year, month)[1]).date()
        
        # Fetch all attendance records for this month
        attendance_records = Attendance.objects.filter(
            employee=employee,
            date__gte=first_day,
            date__lte=last_day
        ).order_by('date')
        
        # Create attendance lookup
        attendance_dict = {record.date: record for record in attendance_records}
        
        # Get holidays
        holidays = Holiday.objects.filter(date__gte=first_day, date__lte=last_day)
        holiday_dates = {h.date: h for h in holidays}
        
        # Get approved leave requests
        from .models import LeaveRequest
        leave_requests = LeaveRequest.objects.filter(
            employee=employee,
            start_date__lte=last_day,
            end_date__gte=first_day,
            status=LeaveRequest.Status.APPROVED
        )
        
        def is_holiday(date_obj):
            """Check if date is a holiday"""
            if date_obj in holiday_dates:
                return True
            # Sunday
            if date_obj.weekday() == 6:
                return True
            # 1st, 3rd, 5th Saturday
            if date_obj.weekday() == 5:
                saturday_count = sum(1 for d in range(1, date_obj.day + 1)
                                   if dt(date_obj.year, date_obj.month, d).weekday() == 5)
                if saturday_count in [1, 3, 5]:
                    return True
            return False
        
        # api_views.py — top of file, with your other imports


        # inside attendance_calendar_ajax(), replace the whole get_attendance_status() with:

        def get_attendance_status(date_obj, attendance_record):
            """Unified status calculation

            Returns: "present", "half", "absent", "holiday", or "paid_leave"

            CRITICAL FIX: LWP/Without Paid leaves should show as ABSENT (red), not PAID_LEAVE (blue)
            """
            # Check if holiday
            if is_holiday(date_obj):
                return "holiday"

            # Check if approved leave (PAID or LWP)
            for leave in leave_requests:
                if leave.start_date <= date_obj <= leave.end_date:
                    # CRITICAL: Distinguish between PAID and LWP/WITHOUT_PAID leaves
                    if leave.is_without_pay():
                        # LWP/Without Paid → Show as ABSENT (red color)
                        return "absent"
                    else:
                        # Paid Leave → Show as PAID_LEAVE (blue color)
                        if employee.joining_date:
                            days_since_joining = (date_obj - employee.joining_date).days
                            if days_since_joining >= 91:
                                return "paid_leave"

            # If no attendance record and past date, mark as absent
            if not attendance_record:
                if date_obj < current_date.date():
                    return "absent"
                return None  # Future date with no record

            # Calculate status using the office-configurable shift-based logic
            # (replaces the old manual 4h/8h duration math)
            status, _ = calculate_attendance_status_for_record(attendance_record)

            status_map = {
                'present': 'present',
                'half_day': 'half',
                'absent': 'absent',
                'checked_in_only': 'absent',
            }
            return status_map.get(status, 'absent')
        
        # Build response data
        dates_data = []
        stats = {
            'present': 0,
            'half': 0,
            'absent': 0,
            'holidays': 0,
            'paid_leave': 0,
        }
        
        for day in range(1, last_day.day + 1):
            date_obj = dt(year, month, day).date()
            attendance = attendance_dict.get(date_obj)
            status = get_attendance_status(date_obj, attendance)
            
            if status:
                dates_data.append({
                    'date': date_obj.isoformat(),
                    'status': status
                })
                stats[status] += 1
        
        return JsonResponse({
            'success': True,
            'stats': stats,
            'dates': dates_data,
        }, status=200)
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)


# ============================================================================
# CRITICAL FIX: Clean Attendance Status API - NO FRONTEND RECALCULATION
# ============================================================================

@login_required
@require_http_methods(["GET"])
def attendance_status_api(request):
    """
    API endpoint that returns ONLY backend-computed attendance status.
    
    This endpoint is designed to prevent frontend recalculation and flickering.
    It returns the final_status directly from the database without any
    JavaScript-side computation.
    
    Query params:
    - date: YYYY-MM-DD (optional, defaults to today)
    
    Response:
    {
        "success": true,
        "date": "2025-12-03",
        "status": "present",
        "status_label": "Present",
        "color": "#34C759",
        "check_in_time": "09:35 AM",
        "check_out_time": "06:12 PM",
        "duration_hours": 8.62,
        "shift_hours": 9.0,
        "has_checkout": true
    }
    """
    try:
        employee = request.user.employee_profile
        
        # Get date from query params or use today
        date_str = request.GET.get('date')
        if date_str:
            try:
                attendance_date = dt.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=400)
        else:
            attendance_date = timezone.now().date()
        
        # Fetch attendance record
        attendance = Attendance.objects.filter(
            employee=employee,
            date=attendance_date
        ).first()
        
        # Status mapping
        status_map = {
            'present': {'label': 'Present', 'color': '#34C759'},
            'half_day': {'label': 'Half Day', 'color': '#FFCC00'},
            'absent': {'label': 'Absent', 'color': '#FF3B30'},
            'checked_in': {'label': 'Checked In', 'color': '#007AFF'},
            'holiday': {'label': 'Holiday', 'color': '#9E9E9E'},
            'paid_leave': {'label': 'Paid Leave', 'color': '#2196F3'},
            'sandwich_leave': {'label': 'Sandwich Leave', 'color': '#FF9800'},
            'late_penalty': {'label': 'Late Penalty', 'color': '#FF5722'},
        }
        
        if not attendance:
            # No attendance record
            return JsonResponse({
                'success': True,
                'date': attendance_date.isoformat(),
                'status': 'absent',
                'status_label': 'Absent',
                'color': '#FF3B30',
                'check_in_time': None,
                'check_out_time': None,
                'duration_hours': 0,
                'shift_hours': 0,
                'has_checkout': False,
            })
        
        # Get final_status from database (NO recalculation)
        final_status = attendance.final_status or 'absent'
        status_info = status_map.get(final_status, {'label': 'Unknown', 'color': '#999999'})
        
        # Format times
        check_in_time_str = None
        check_out_time_str = None
        if attendance.check_in_time:
            check_in_time_str = timezone.localtime(attendance.check_in_time).strftime('%I:%M %p')
        if attendance.check_out_time:
            check_out_time_str = timezone.localtime(attendance.check_out_time).strftime('%I:%M %p')
        
        # Get shift hours
        shift_hours = 0
        if employee.shift:
            from datetime import time
            start = employee.shift.start_time
            end = employee.shift.end_time
            if isinstance(start, str):
                start = dt.strptime(start, '%H:%M').time()
            if isinstance(end, str):
                end = dt.strptime(end, '%H:%M').time()
            
            start_dt = dt.combine(attendance_date, start)
            end_dt = dt.combine(attendance_date, end)
            if end_dt < start_dt:
                end_dt = dt.combine(attendance_date + timedelta(days=1), end)
            shift_hours = (end_dt - start_dt).total_seconds() / 3600
        
        return JsonResponse({
            'success': True,
            'date': attendance_date.isoformat(),
            'status': final_status,
            'status_label': status_info['label'],
            'color': status_info['color'],
            'check_in_time': check_in_time_str,
            'check_out_time': check_out_time_str,
            'duration_hours': float(attendance.duration_hours),
            'shift_hours': shift_hours,
            'has_checkout': attendance.check_out_time is not None,
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)


# ===========================
# NOTIFICATION API ENDPOINTS
# ===========================

@login_required
@require_http_methods(["GET"])
def notifications_list_api(request):
    """
    Fetch all notifications for logged-in employee
    GET /api/notifications/list/
    """
    try:
        from .models import EmployeeNotification
        
        employee = request.user.employee_profile
        limit = int(request.GET.get('limit', 20))
        
        notifications = EmployeeNotification.objects.filter(
            employee=employee
        ).order_by('-created_at')[:limit]
        
        unread_count = EmployeeNotification.objects.filter(
            employee=employee,
            is_read=False
        ).count()
        
        notifications_data = []
        for notif in notifications:
            notifications_data.append({
                'id': notif.id,
                'title': notif.title,
                'message': notif.message,
                'notification_type': notif.notification_type,
                'is_read': notif.is_read,
                'created_at': notif.created_at.isoformat(),
                'action_url': notif.action_url or '',
                'type_display': notif.get_notification_type_display(),
            })
        
        return JsonResponse({
            'success': True,
            'notifications': notifications_data,
            'unread_count': unread_count,
            'total_count': EmployeeNotification.objects.filter(employee=employee).count(),
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def notification_count_api(request):
    """Get unread notification count"""
    try:
        from .models import EmployeeNotification
        
        employee = request.user.employee_profile
        
        unread_count = EmployeeNotification.objects.filter(
            employee=employee,
            is_read=False
        ).count()
        
        total_count = EmployeeNotification.objects.filter(
            employee=employee
        ).count()
        
        return JsonResponse({
            'success': True,
            'unread_count': unread_count,
            'total_count': total_count,
        })
    
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
@csrf_protect
def mark_notification_as_read(request, notification_id):
    """Mark a notification as read"""
    try:
        from .models import EmployeeNotification
        
        employee = request.user.employee_profile
        
        notification = EmployeeNotification.objects.get(
            id=notification_id,
            employee=employee
        )
        
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save(update_fields=['is_read', 'read_at'])
        
        unread_count = EmployeeNotification.objects.filter(
            employee=employee,
            is_read=False
        ).count()
        
        return JsonResponse({
            'success': True,
            'message': 'Notification marked as read',
            'unread_count': unread_count,
        })
    
    except EmployeeNotification.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Notification not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
@csrf_protect
def mark_all_notifications_as_read(request):
    """Mark all notifications as read"""
    try:
        from .models import EmployeeNotification
        
        employee = request.user.employee_profile
        
        count = EmployeeNotification.objects.filter(
            employee=employee,
            is_read=False
        ).update(
            is_read=True,
            read_at=timezone.now()
        )
        
        return JsonResponse({
            'success': True,
            'message': 'All notifications marked as read',
            'count': count,
        })
    
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
@csrf_protect
def delete_notification(request, notification_id):
    """Delete a notification"""
    try:
        from .models import EmployeeNotification
        
        employee = request.user.employee_profile
        
        notification = EmployeeNotification.objects.get(
            id=notification_id,
            employee=employee
        )
        notification.delete()
        
        return JsonResponse({
            'success': True,
            'message': 'Notification deleted',
        })
    
    except EmployeeNotification.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Notification not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ===========================
# ATTENDANCE CALENDAR API
# ===========================

@login_required
@require_http_methods(["GET"])
def attendance_calendar_api(request):
    """
    Get complete attendance calendar data for a month
    Uses AttendanceEngine for unified status calculation
    
    Query params:
    - month: Month (1-12), default = current month
    - year: Year, default = current year
    
    Returns:
    {
        "success": true,
        "days": {
            "2024-12-01": {"status": "present", "color": "#34C759", "details": {...}},
            "2024-12-02": {"status": "absent", "color": "#FF3B30", "details": {...}},
            ...
        },
        "stats": {
            "present": 15,
            "half_day": 2,
            "absent": 5,
            "holidays": 4,
            "paid_leave": 3,
            "sandwich_leave": 1,
            "total_working_days": 22
        }
    }
    """
    try:
        from employees.attendance_engine import AttendanceEngine
        
        employee = request.user.employee_profile
        
        # Get month and year from query params
        month = int(request.GET.get('month', timezone.now().month))
        year = int(request.GET.get('year', timezone.now().year))
        
        # Validate month/year
        if month < 1 or month > 12:
            month = timezone.now().month
        if year < 2000 or year > 2100:
            year = timezone.now().year
        
        # Use AttendanceEngine to get complete calendar
        engine = AttendanceEngine(employee)
        calendar_data = engine.get_month_calendar(year, month)
        
        return JsonResponse(calendar_data)
    
    except Exception as e:
        import traceback
        print(f"[ERROR] Attendance calendar API: {traceback.format_exc()}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
