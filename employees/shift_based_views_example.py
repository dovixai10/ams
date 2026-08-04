"""
SHIFT-BASED ATTENDANCE INTEGRATION EXAMPLES
============================================

This file shows how to integrate shift-based attendance logic into your
existing check-in/check-out views.

Copy and adapt these code snippets into your employees/views.py file.

Author: EMS System
Date: 2024
"""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# 1. ON LOGIN - FETCH EMPLOYEE'S SHIFT INFORMATION
# ============================================================================

def employee_login_view(request):
    """
    Example: When employee logs in, fetch their assigned shift.
    
    This can be integrated into your existing login view or called
    from a dashboard initialization function.
    """
    from employees.shift_attendance_logic import get_employee_shift_info
    
    employee = request.user.employee_profile
    
    try:
        # Fetch shift information
        shift_info = get_employee_shift_info(employee)
        
        # Store in session for quick access
        request.session['shift_info'] = {
            'shift_name': shift_info['shift_name'],
            'start_time': str(shift_info['start_time']),
            'end_time': str(shift_info['end_time']),
            'total_hours': str(shift_info['total_hours']),
            'half_day_threshold': str(shift_info['half_day_threshold']),
        }
        
        logger.info(
            f"Employee {employee.id} logged in. "
            f"Shift: {shift_info['shift_name']}, "
            f"Hours: {shift_info['total_hours']}"
        )
        
        # Pass to template context
        context = {
            'shift_info': shift_info,
            'employee': employee,
        }
        
        return render(request, 'employees/dashboard.html', context)
    
    except ValueError as e:
        logger.error(f"Error fetching shift info: {str(e)}")
        messages.error(request, 'Your shift information is not configured. Contact admin.')
        return redirect('employees:employee_dashboard')


# ============================================================================
# 2. CHECK-OUT VIEW - UPDATE ATTENDANCE WITH SHIFT-BASED LOGIC
# ============================================================================

@login_required
@require_http_methods(["POST"])
def check_out_with_shift_logic(request):
    """
    Example: Updated check-out view that uses shift-based attendance calculation.
    
    This replaces the hardcoded 4.5 hour threshold with dynamic shift-based logic.
    
    INTEGRATION STEPS:
    1. Replace the hardcoded HALF_DAY_THRESHOLD_SECONDS with shift-based calculation
    2. Call update_attendance_on_checkout() to update the record
    3. Return the calculated status to the frontend
    """
    from employees.models import Attendance, AttendanceLog
    from employees.shift_attendance_logic import update_attendance_on_checkout
    
    employee = request.user.employee_profile
    today = timezone.now().date()
    ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
    
    try:
        # Get today's attendance record
        attendance = Attendance.objects.filter(employee=employee, date=today).first()
        
        if not attendance:
            if ajax:
                return JsonResponse(
                    {'success': False, 'message': 'No check-in found for today'},
                    status=400
                )
            messages.error(request, 'No check-in found for today.')
            return redirect('employees:check_in')
        
        if attendance.check_out_time:
            if ajax:
                return JsonResponse(
                    {'success': True, 'message': 'Already checked out'},
                    status=200
                )
            messages.success(request, 'Already checked out today.')
            return redirect('employees:check_in')
        
        # ===== SHIFT-BASED LOGIC =====
        # Record check-out time
        check_out_time = timezone.now()
        attendance.check_out_time = check_out_time
        attendance.check_out_photo.save(
            request.FILES.get('check_out_photo').name,
            request.FILES.get('check_out_photo'),
            save=False
        )
        
        # Update attendance with shift-based calculations
        result = update_attendance_on_checkout(attendance)
        
        if not result['updated']:
            logger.error(f"Failed to update attendance: {result.get('error')}")
            if ajax:
                return JsonResponse(
                    {'success': False, 'message': 'Error updating attendance'},
                    status=500
                )
            messages.error(request, 'Error updating attendance.')
            return redirect('employees:check_in')
        
        # Log successful check-out
        AttendanceLog.objects.create(
            employee=employee,
            action='check_out_success',
            success=True,
            attendance=attendance,
            notes=f"Check-out successful. Status: {result['status']}, "
                  f"Hours: {result['duration_hours']}, "
                  f"Shift: {result['shift_hours']}"
        )
        
        # Return response
        if ajax:
            return JsonResponse({
                'success': True,
                'message': f"Check-out successful! Status: {result['status'].upper()}",
                'check_out_time': check_out_time.strftime('%d %b %Y, %I:%M %p'),
                'status': result['status'],
                'color': result['color'],
                'duration_hours': float(result['duration_hours']),
                'shift_hours': float(result['shift_hours']),
                'half_day_threshold': float(result['half_day_threshold']),
            })
        
        messages.success(
            request,
            f"✓ Check-out successful! Status: {result['status'].upper()}"
        )
        request.session['check_out_success'] = True
        request.session['check_out_success_time'] = check_out_time.strftime('%d %b %Y, %I:%M %p')
        return redirect('employees:modern_dashboard')
    
    except Exception as e:
        logger.error(f"Error during check-out: {str(e)}")
        AttendanceLog.objects.create(
            employee=employee,
            action='check_out_failed',
            success=False,
            failure_reason='other',
            notes=f'Exception: {str(e)}'
        )
        if ajax:
            return JsonResponse(
                {'success': False, 'message': f'Error: {str(e)}'},
                status=500
            )
        messages.error(request, f'Error: {str(e)}')
        return redirect('employees:check_in')


# ============================================================================
# 3. ATTENDANCE CALENDAR API - RETURN SHIFT-BASED STATUS
# ============================================================================

@login_required
def attendance_calendar_api(request):
    """
    Example: Updated API endpoint that returns shift-based attendance status.
    
    This can replace or supplement your existing attendance API.
    """
    from employees.models import Attendance
    from employees.shift_attendance_logic import calculate_attendance_status_for_record
    
    employee = request.user.employee_profile
    date_str = request.GET.get('date')
    
    if not date_str:
        return JsonResponse({'error': 'Date parameter required'}, status=400)
    
    try:
        from datetime import datetime
        selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        # Get attendance record
        attendance = Attendance.objects.filter(
            employee=employee,
            date=selected_date
        ).first()
        
        if not attendance:
            return JsonResponse({
                'date': date_str,
                'status': 'absent',
                'color': '#FF3B30',
                'message': 'No attendance recorded',
            })
        
        # Calculate shift-based status
        status, color = calculate_attendance_status_for_record(attendance)
        
        return JsonResponse({
            'date': date_str,
            'status': status,
            'color': color,
            'checkin': {
                'time': attendance.check_in_time.strftime('%I:%M %p') if attendance.check_in_time else None,
                'image': attendance.check_in_photo.url if attendance.check_in_photo else None,
            },
            'checkout': {
                'time': attendance.check_out_time.strftime('%I:%M %p') if attendance.check_out_time else None,
                'image': attendance.check_out_photo.url if attendance.check_out_photo else None,
            },
            'duration': attendance.duration or '-',
            'hours': float(attendance.total_work_hours),
            'shift_hours': float(attendance.employee.shift.total_hours) if attendance.employee.shift else 0,
        })
    
    except Exception as e:
        logger.error(f"Error in attendance API: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


# ============================================================================
# 4. ATTENDANCE SUMMARY VIEW - SHIFT-BASED STATISTICS
# ============================================================================

@login_required
def attendance_summary_view(request):
    """
    Example: Attendance summary view using shift-based logic.
    
    Shows Present, Half-Day, Absent counts for a date range.
    """
    from employees.shift_attendance_logic import get_attendance_summary
    from datetime import datetime, timedelta
    
    employee = request.user.employee_profile
    
    # Get date range from request or use current month
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    if start_date_str and end_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    else:
        # Default to current month
        today = timezone.now().date()
        start_date = today.replace(day=1)
        end_date = (start_date + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    
    try:
        # Get summary
        summary = get_attendance_summary(employee, start_date, end_date)
        
        if not summary['success']:
            messages.error(request, f"Error: {summary.get('error')}")
            return redirect('employees:attendance_calendar')
        
        context = {
            'summary': summary,
            'employee': employee,
            'start_date': start_date,
            'end_date': end_date,
        }
        
        return render(request, 'employees/attendance_summary.html', context)
    
    except Exception as e:
        logger.error(f"Error in attendance summary: {str(e)}")
        messages.error(request, f'Error: {str(e)}')
        return redirect('employees:attendance_calendar')


# ============================================================================
# 5. ADMIN VIEW - MANAGE SHIFTS AND EMPLOYEE ASSIGNMENTS
# ============================================================================

@login_required
def admin_employee_shift_assignment(request, employee_id):
    """
    Example: Admin view to assign/change employee shift.
    
    When admin creates or edits an employee, they select a shift.
    This shift becomes the employee's assigned shift.
    """
    from employees.models import Employee, Shift
    
    try:
        employee = Employee.objects.get(id=employee_id)
        shifts = Shift.objects.filter(is_active=True)
        
        if request.method == 'POST':
            shift_id = request.POST.get('shift_id')
            
            if not shift_id:
                messages.error(request, 'Please select a shift.')
                return redirect('employees:admin_employee_detail', pk=employee_id)
            
            try:
                shift = Shift.objects.get(id=shift_id)
                employee.shift = shift
                employee.save(update_fields=['shift'])
                
                logger.info(
                    f"Employee {employee.id} assigned to shift {shift.id} ({shift.name})"
                )
                messages.success(
                    request,
                    f"Employee assigned to shift: {shift.name} ({shift.total_hours} hours)"
                )
                return redirect('employees:admin_employee_detail', pk=employee_id)
            
            except Shift.DoesNotExist:
                messages.error(request, 'Shift not found.')
                return redirect('employees:admin_employee_detail', pk=employee_id)
        
        context = {
            'employee': employee,
            'shifts': shifts,
            'current_shift': employee.shift,
        }
        
        return render(request, 'employees/admin_assign_shift.html', context)
    
    except Employee.DoesNotExist:
        messages.error(request, 'Employee not found.')
        return redirect('employees:admin_employees')


# ============================================================================
# 6. TEMPLATE CONTEXT HELPER - PASS SHIFT INFO TO TEMPLATES
# ============================================================================

def get_shift_context_for_employee(employee):
    """
    Helper function to get shift information for template context.
    
    Usage in views:
        context = get_shift_context_for_employee(employee)
        return render(request, 'template.html', context)
    """
    from employees.shift_attendance_logic import get_employee_shift_info
    
    try:
        shift_info = get_employee_shift_info(employee)
        return {
            'shift_info': shift_info,
            'shift_name': shift_info['shift_name'],
            'shift_start': shift_info['start_time'],
            'shift_end': shift_info['end_time'],
            'shift_hours': shift_info['total_hours'],
            'half_day_threshold': shift_info['half_day_threshold'],
        }
    except ValueError:
        return {
            'shift_info': None,
            'error': 'No shift assigned',
        }


# ============================================================================
# 7. BATCH PROCESSING - UPDATE ALL ATTENDANCE RECORDS (ADMIN)
# ============================================================================

@login_required
def admin_recalculate_attendance(request):
    """
    Example: Admin function to recalculate all attendance records.
    
    Useful when:
    - Shift hours change
    - Need to update old records with new logic
    - Fixing calculation errors
    """
    from employees.models import Attendance
    from employees.shift_attendance_logic import update_attendance_on_checkout
    
    if request.method == 'POST':
        try:
            # Get all attendance records with checkout
            records = Attendance.objects.filter(check_out_time__isnull=False)
            
            updated_count = 0
            error_count = 0
            
            for attendance in records:
                try:
                    result = update_attendance_on_checkout(attendance)
                    if result['updated']:
                        updated_count += 1
                    else:
                        error_count += 1
                except Exception as e:
                    logger.error(f"Error updating attendance {attendance.id}: {str(e)}")
                    error_count += 1
            
            message = f"Recalculation complete: {updated_count} updated, {error_count} errors"
            logger.info(message)
            messages.success(request, message)
            
            return redirect('employees:admin_attendance_list')
        
        except Exception as e:
            logger.error(f"Error in batch recalculation: {str(e)}")
            messages.error(request, f'Error: {str(e)}')
            return redirect('employees:admin_attendance_list')
    
    return render(request, 'employees/admin_recalculate_attendance.html')


# ============================================================================
# 8. INTEGRATION CHECKLIST
# ============================================================================

"""
INTEGRATION CHECKLIST:

1. ✓ Models Updated:
   - Shift model has total_hours and half_day_threshold properties
   - Employee model has shift ForeignKey
   - Attendance model has calculate_shift_based_status() method

2. ✓ Utility Module Created:
   - shift_attendance_logic.py with all calculation functions

3. TODO: Update Views:
   - Replace hardcoded thresholds in check_out view
   - Call update_attendance_on_checkout() after checkout
   - Update attendance calendar API to use shift-based status

4. TODO: Update Templates:
   - Display shift information on employee dashboard
   - Show shift hours in attendance calendar
   - Display status with shift-based colors

5. TODO: Admin Interface:
   - Add shift selection when creating/editing employees
   - Show shift assignments in employee list
   - Allow shift changes with recalculation option

6. TODO: Testing:
   - Test with different shift hours (8h, 9h, 4h, etc.)
   - Test overnight shifts (10 PM - 6 AM)
   - Test edge cases (missing checkout, multiple check-ins)
   - Test calendar display with shift-based colors

7. TODO: Migration (if needed):
   - Run: python manage.py makemigrations
   - Run: python manage.py migrate
   - Update existing attendance records if needed
"""
