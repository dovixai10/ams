"""
Manual Attendance Marker and Paid Leave Adjustment Views
Production-grade admin tools for attendance management
"""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db.models import Q
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal

from .models import Employee, Attendance, Shift, EmployeeNotification, LeaveAdjustment
from django.contrib.auth.models import User
from web_project import TemplateLayout
from web_project.template_helpers.theme import TemplateHelper


def is_admin(user):
    """Check if user is a superuser or admin"""
    return user.is_superuser or user.is_staff


@login_required
@user_passes_test(is_admin)
def manual_attendance(request):
    """Manual attendance marking page"""
    employees = Employee.objects.select_related('shift', 'user').order_by('full_name')
    
    if request.method == 'POST':
        employee_id = request.POST.get('employee')
        attendance_date = request.POST.get('date')
        status = request.POST.get('status')
        comment = request.POST.get('comment', '').strip()
        
        try:
            employee = Employee.objects.get(id=employee_id)
            att_date = datetime.strptime(attendance_date, '%Y-%m-%d').date()
            
            # Get or create attendance record
            attendance, created = Attendance.objects.get_or_create(
                employee=employee,
                branch=employee.branch,
                date=att_date
            )
            
            old_status = attendance.final_status
            
            # Handle paid leave deduction/refund
            if status == 'paid_leave' and old_status != 'paid_leave':
                if employee.paid_leaves <= 0:
                    messages.error(request, f"❌ {employee.full_name} has no paid leaves available!")
                    return redirect('employees:manual_attendance')
                employee.paid_leaves -= 1
                employee.save()
                
            elif status != 'paid_leave' and old_status == 'paid_leave':
                employee.paid_leaves += 1
                employee.save()
            
            # Update attendance with manual override fields
            attendance.final_status = status
            attendance.is_manually_marked = True
            attendance.manually_marked_by = request.user
            attendance.manually_marked_at = timezone.now()
            attendance.manual_comment = comment
            
            # Set status-specific fields
            if status == 'half_day':
                attendance.half_day = True
            else:
                attendance.half_day = False
            
            attendance.save()
            
            # Create audit log (model removed - commenting out)
            # ManualAttendanceChange.objects.create(
            #     employee=employee,
            #     date=att_date,
            #     old_status=old_status,
            #     new_status=status,
            #     comment=comment,
            #     changed_by=request.user
            # )
            
            # Create notification
            status_display = status.replace('_', ' ').title()
            EmployeeNotification.objects.create(
                employee=employee,
                branch=employee.branch,
                title='Attendance Updated',
                message=f'Your attendance for {att_date.strftime("%d-%m-%Y")} was marked as {status_display}. Reason: {comment}',
                notification_type='attendance_updated',
                is_read=False
            )
            
            messages.success(request, f"✓ Attendance marked for {employee.full_name}")
            return redirect('employees:manual_attendance')
            
        except Employee.DoesNotExist:
            messages.error(request, "❌ Employee not found!")
        except ValueError:
            messages.error(request, "❌ Invalid date format!")
        except Exception as e:
            messages.error(request, f"❌ Error: {str(e)}")
    
    # Initialize template layout with proper context
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'employees': employees,
        'today': timezone.now().date(),
        'page_title': 'Manual Attendance Marker',
        'page_description': 'Mark attendance manually for employees',
    })
    
    return render(request, 'employees/manual_attendance.html', context)


@login_required
@user_passes_test(is_admin)
@require_http_methods(["GET"])
def get_employee_details(request):
    """AJAX endpoint to get employee details"""
    employee_id = request.GET.get('employee_id')
    
    try:
        employee = Employee.objects.get(id=employee_id)
        
        # Get today's attendance
        today_attendance = Attendance.objects.filter(
            employee=employee,
            date=timezone.now().date()
        ).first()
        
        # Get last 5 attendance records
        last_attendance = Attendance.objects.filter(
            employee=employee
        ).order_by('-date')[:5]
        
        shift_info = {
            'name': employee.shift.name if employee.shift else 'No shift',
            'start_time': str(employee.shift.start_time) if employee.shift else '--',
            'end_time': str(employee.shift.end_time) if employee.shift else '--',
        }
        
        today_status = today_attendance.final_status if today_attendance else 'Not marked'
        worked_hours = '--'
        if today_attendance and today_attendance.check_in_time and today_attendance.check_out_time:
            delta = today_attendance.check_out_time - today_attendance.check_in_time
            worked_hours = f"{delta.seconds // 3600}h {(delta.seconds % 3600) // 60}m"
        
        last_attendance_list = [
            {
                'date': att.date.strftime('%d %b %Y'),
                'status': att.final_status or 'Absent',
                'check_in': att.check_in_time.strftime('%I:%M %p') if att.check_in_time else '--',
                'check_out': att.check_out_time.strftime('%I:%M %p') if att.check_out_time else '--',
            }
            for att in last_attendance
        ]
        
        return JsonResponse({
            'success': True,
            'shift': shift_info,
            'today_status': today_status,
            'worked_hours': worked_hours,
            'paid_leaves': float(employee.paid_leaves),
            'last_attendance': last_attendance_list,
        })
    except Employee.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Employee not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@user_passes_test(is_admin)
def adjust_paid_leave(request):
    """Paid leave adjustment page"""
    employees = Employee.objects.order_by('full_name')
    adjustment_reasons = []

    context = TemplateLayout.init(request, context={})

    if request.method == 'POST':
        employee_id = request.POST.get('employee')
        adjustment_amount = request.POST.get('adjustment_amount')
        reason = request.POST.get('reason')
        comment = request.POST.get('comment', '').strip()

        try:
            employee = Employee.objects.get(id=employee_id)
            adjustment = Decimal(adjustment_amount)

            if adjustment == 0:
                messages.warning(request, "⚠ Adjustment amount cannot be zero!")
                return redirect('employees:adjust_paid_leave')

            old_balance = employee.paid_leaves
            new_balance = old_balance + adjustment

            if new_balance < 0:
                messages.error(request, f"❌ Cannot reduce leaves below 0! Current: {old_balance}, Requested: {new_balance}")
                return redirect('employees:adjust_paid_leave')

            employee.paid_leaves = new_balance
            employee.save()

            LeaveAdjustment.objects.create(
                employee=employee,
                branch=employee.branch,
                old_balance=old_balance,
                new_balance=new_balance,
                change_amount=adjustment,
                reason=reason,
                comment=comment,
                adjusted_by=request.user,
            )

            action = "increased" if adjustment > 0 else "decreased"
            messages.success(request, f"✓ {employee.full_name}'s paid leaves {action} by {abs(adjustment)} (New balance: {new_balance})")
            return redirect('employees:adjust_paid_leave')

        except Employee.DoesNotExist:
            messages.error(request, "❌ Employee not found!")
        except ValueError:
            messages.error(request, "❌ Invalid adjustment amount!")
        except Exception as e:
            messages.error(request, f"❌ Error: {str(e)}")

    # History — was completely missing from context before
    adjustments = LeaveAdjustment.objects.select_related('employee', 'adjusted_by').order_by('-created_at')[:100]

    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'employees': employees,
        'adjustment_reasons': adjustment_reasons,
        'page_title': 'Adjust Paid Leave',
        'page_description': 'Increase or decrease employee paid leave balance',
        'adjustments': adjustments,
    })

    return render(request, 'employees/adjust_paid_leave.html', context)

@login_required
@require_http_methods(["GET"])
def attendance_calendar_data(request):
    """API endpoint returning calendar data with stats for employee"""
    try:
        employee = request.user.employee_profile
        month = int(request.GET.get('month', timezone.now().month))
        year = int(request.GET.get('year', timezone.now().year))
        
        # Get all attendance for the month
        from datetime import date
        first_day = date(year, month, 1)
        if month == 12:
            last_day = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = date(year, month + 1, 1) - timedelta(days=1)
        
        attendances = Attendance.objects.filter(
            employee=employee,
            date__gte=first_day,
            date__lte=last_day
        )
        
        # Calculate stats
        stats = {
            'present': 0,
            'half_day': 0,
            'absent': 0,
            'paid_leave': 0,
            'holiday': 0,
            'late': 0,
        }
        
        days = []
        status_colors = {
            'present': '#34C759',
            'half_day': '#FFCC00',
            'absent': '#FF3B30',
            'paid_leave': '#AF52DE',
            'holiday': '#FF9500',
            'late_penalty': '#FF6B6B',
            'sandwich_leave': '#5AC8FA',
            'checked_in': '#007AFF',
        }
        
        for att in attendances:
            status = att.final_status or 'absent'
            stats[status] = stats.get(status, 0) + 1
            
            days.append({
                'date': att.date.strftime('%Y-%m-%d'),
                'status': status,
                'color': status_colors.get(status, '#999999'),
                'check_in': att.check_in_time.strftime('%H:%M') if att.check_in_time else None,
                'check_out': att.check_out_time.strftime('%H:%M') if att.check_out_time else None,
            })
        
        return JsonResponse({
            'success': True,
            'month_stats': stats,
            'days': days,
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def checkin_dashboard_state(request):
    """API endpoint returning complete dashboard state"""
    try:
        employee = request.user.employee_profile
        today = timezone.now().date()
        
        # Get today's attendance
        today_attendance = Attendance.objects.filter(
            employee=employee,
            date=today
        ).first()
        
        # Determine state
        if not today_attendance:
            state = "pre_checkin"
        elif today_attendance.check_in_time and not today_attendance.check_out_time:
            state = "waiting_checkout"
        elif today_attendance.check_in_time and today_attendance.check_out_time:
            state = "post_checkout"
        else:
            state = "idle"
        
        # Format times
        check_in_time = today_attendance.check_in_time.strftime('%I:%M %p') if today_attendance and today_attendance.check_in_time else None
        check_out_time = today_attendance.check_out_time.strftime('%I:%M %p') if today_attendance and today_attendance.check_out_time else None
        
        # Get attendance status
        attendance_status = today_attendance.final_status if today_attendance else None
        
        # Get last 7 days
        last_7_days = []
        for i in range(7):
            date = today - timedelta(days=i)
            att = Attendance.objects.filter(employee=employee, date=date).first()
            if att:
                last_7_days.append({
                    'date': date.strftime('%Y-%m-%d'),
                    'date_display': date.strftime('%b %d'),
                    'status': att.final_status,
                    'in': att.check_in_time.strftime('%I:%M %p') if att.check_in_time else '--',
                    'out': att.check_out_time.strftime('%I:%M %p') if att.check_out_time else '--',
                })
            else:
                last_7_days.append({
                    'date': date.strftime('%Y-%m-%d'),
                    'date_display': date.strftime('%b %d'),
                    'status': 'no_record',
                    'in': '--',
                    'out': '--',
                })
        
        return JsonResponse({
            'success': True,
            'state': state,
            'check_in_time': check_in_time,
            'check_out_time': check_out_time,
            'attendance_status': attendance_status,
            'last_7_days': last_7_days,
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@user_passes_test(is_admin)
@require_http_methods(["GET"])
def get_leave_balance(request):
    """AJAX endpoint to get current leave balance"""
    employee_id = request.GET.get('employee_id')
    
    try:
        employee = Employee.objects.get(id=employee_id)
        
        # Get recent adjustments
        recent_adjustments = LeaveAdjustment.objects.filter(
            employee=employee
        ).order_by('-timestamp')[:5]
        
        adjustments_list = [
            {
                'date': adj.timestamp.strftime('%d %b %Y %H:%M'),
                'reason': adj.get_reason_display(),
                'amount': f"{adj.change_amount:+.1f}",
                'new_balance': f"{adj.new_balance:.1f}",
                'by': adj.adjusted_by.get_full_name() if adj.adjusted_by else 'System',
            }
            for adj in recent_adjustments
        ]
        
        return JsonResponse({
            'success': True,
            'current_balance': float(employee.paid_leaves),
            'recent_adjustments': adjustments_list,
        })
    except Employee.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Employee not found'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
