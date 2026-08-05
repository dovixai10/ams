"""
Shift Assignment Views
Handles admin shift assignment to employees with AJAX support
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.db.models import Q
from .models import Employee, Shift
import json
from .permissions import office_admin_required, is_platform_admin, get_request_office

def is_office_admin(user):
    """An HR user tied to a specific approved office."""
    return hasattr(user, 'office_admin_profile')

from django.core.exceptions import PermissionDenied


def tenant_queryset(request, queryset):
    """
    Scope a queryset to the current office.

    Platform admin:
        Can see all offices.

    Approved office admin:
        Can see only their own office.

    User with no office:
        Gets no tenant data.
    """
    if is_platform_admin(request.user):
        return queryset

    office = get_request_office(request)

    if office is None:
        return queryset.none()

    return queryset.filter(office=office)


def tenant_object_or_404(request, model, **lookup):
    """
    Fetch an object only if it belongs to the current office.

    Platform admin can access every office.
    Office admin can access only their own office.
    """
    queryset = tenant_queryset(
        request,
        model.objects.all()
    )

    return get_object_or_404(
        queryset,
        **lookup
    )


# def is_superadmin(user):
#     """Check if user is superadmin"""
#     return user.is_superuser


@login_required
@user_passes_test(office_admin_required)
def shift_assignment(request):
    """
    Display all employees with their current shifts
    Allow admin to assign/change shifts via dropdown
    """
    from web_project import TemplateLayout
    from web_project.template_helpers.theme import TemplateHelper
    
    try:
        # More robust query with proper error handling
        employees = tenant_queryset( request, Employee.objects.select_related('shift', 'user').order_by('full_name'))
        # shifts = Shift.objects.filter(is_active=True).order_by('name')
        shifts = ( tenant_queryset( request, Shift.objects.filter( is_active=True ) ) .order_by('name') )
        
        print(f"[DEBUG] Found {employees.count()} employees and {shifts.count()} shifts")
        
    except Exception as e:
        print(f"[ERROR] Error fetching data: {str(e)}")
        employees = Employee.objects.none()
        shifts = Shift.objects.none()
    
    context = TemplateLayout.init(request, context={})
    context.update({
        'layout_path': TemplateHelper.set_layout('layout_vertical.html', context),
        'employees': employees,
        'shifts': shifts,
        'page_title': 'Shift Assignment',
    })
    
    return render(request, 'employees/shifts/shift_assignment.html', context)


@login_required
@user_passes_test(office_admin_required)
@require_http_methods(["POST"])
def update_employee_shift(request):
    """
    AJAX endpoint to update employee shift
    Returns JSON response
    """
    try:
        data = json.loads(request.body)
        employee_id = data.get('employee_id')
        shift_id = data.get('shift_id')
        
        # Validate inputs
        if not employee_id or not shift_id:
            return JsonResponse({
                'success': False,
                'message': 'Employee ID and Shift ID are required'
            }, status=400)
        
        # Get employee
        try:
            # employee = Employee.objects.get(id=employee_id)
            employee = tenant_object_or_404( request, Employee, id=employee_id, )
        except Employee.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Employee not found'
            }, status=404)
        
        # Get shift
        try:
            # shift = Shift.objects.get(id=shift_id)
            shift = tenant_object_or_404( request, Shift, id=shift_id, is_active=True, )
        except Shift.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Shift not found'
            }, status=404)
        
        # Update employee shift
        old_shift = employee.shift
        employee.shift = shift
        employee.save()
        
        # Format shift display
        shift_display = f"{shift.start_time.strftime('%I:%M %p')} – {shift.end_time.strftime('%I:%M %p')}"
        
        return JsonResponse({
            'success': True,
            'message': f'Shift updated successfully for {employee.user.first_name}',
            'employee_id': employee_id,
            'shift_id': shift_id,
            'shift_display': shift_display,
            'shift_name': shift.name,
        })
    
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error updating shift: {str(e)}'
        }, status=500)


@login_required
@user_passes_test(office_admin_required)
@require_http_methods(["POST"])
def bulk_assign_shift(request):
    """
    AJAX endpoint for bulk shift assignment
    Assigns same shift to multiple employees
    """
    try:
        data = json.loads(request.body)
        employee_ids = data.get('employee_ids', [])
        shift_id = data.get('shift_id')
        
        # Validate inputs
        if not employee_ids or not shift_id:
            return JsonResponse({
                'success': False,
                'message': 'Employee IDs and Shift ID are required'
            }, status=400)
        
        if not isinstance(employee_ids, list):
            return JsonResponse({
                'success': False,
                'message': 'Employee IDs must be a list'
            }, status=400)
        
        # Get shift
        try:
            # shift = Shift.objects.get(id=shift_id)
            shift = tenant_object_or_404( request, Shift, id=shift_id, is_active=True, )
        except Shift.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Shift not found'
            }, status=404)

        employees = tenant_queryset( request, Employee.objects.filter( id__in=employee_ids ) )
        # Update employees
        # updated_count = 0
        # failed_count = 0
        updated_count = employees.update( shift=shift )
        failed_count = ( len( set( str( employee_id ) for employee_id in employee_ids ) ) - updated_count )

        # for employee_id in employee_ids:
        #     try:
        #         employee = Employee.objects.get(id=employee_id)
        #         employee.shift = shift
        #         employee.save()
        #         updated_count += 1
        #     except Employee.DoesNotExist:
        #         failed_count += 1
        #     except Exception as e:
        #         failed_count += 1
        
        # Format shift display
        shift_display = f"{shift.start_time.strftime('%I:%M %p')} – {shift.end_time.strftime('%I:%M %p')}"
        
        message = f'Shift assigned to {updated_count} employee{"s" if updated_count != 1 else ""}'
        if failed_count > 0:
            message += f' ({failed_count} failed)'
        
        return JsonResponse({
            'success': True,
            'message': message,
            'updated_count': updated_count,
            'failed_count': failed_count,
            'shift_id': shift_id,
            'shift_display': shift_display,
            'shift_name': shift.name,
        })
    
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error assigning shifts: {str(e)}'
        }, status=500)


@login_required
@user_passes_test(office_admin_required)
@require_http_methods(["POST"])
def remove_employee_shift(request):
    """
    AJAX endpoint to remove shift from employee
    Sets shift to NULL
    """
    try:
        data = json.loads(request.body)
        employee_id = data.get('employee_id')
        
        # Validate input
        if not employee_id:
            return JsonResponse({
                'success': False,
                'message': 'Employee ID is required'
            }, status=400)
        
        # Get employee
        try:
            # employee = Employee.objects.get(id=employee_id)
            employee = tenant_object_or_404( request, Employee, id=employee_id, )
        except Employee.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Employee not found'
            }, status=404)
        
        # Remove shift
        employee.shift = None
        employee.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Shift removed for {employee.user.first_name}',
            'employee_id': employee_id,
        })
    
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error removing shift: {str(e)}'
        }, status=500)


@login_required
@user_passes_test(office_admin_required)
def get_employee_shifts_data(request):
    """
    AJAX endpoint to get all employees with their shifts
    Used for dynamic table updates
    """
    try:
        # employees = Employee.objects.all().select_related('shift', 'user').order_by('user__first_name')
        employees = ( tenant_queryset( request, Employee.objects.select_related( 'shift', 'user', 'department', 'designation', ) ) .order_by( 'user__first_name' ) )
        
        employees_data = []
        for emp in employees:
            shift_info = {
                'id': emp.shift.id if emp.shift else None,
                'name': emp.shift.name if emp.shift else 'Not Assigned',
                'display': f"{emp.shift.start_time.strftime('%I:%M %p')} – {emp.shift.end_time.strftime('%I:%M %p')}" if emp.shift else 'Not Assigned',
            }
            
            employees_data.append({
                'id': emp.id,
                'employee_id': emp.employee_id,
                'name': f"{emp.user.first_name} {emp.user.last_name}",
                'department': emp.department.name if emp.department else 'N/A',
                'designation': emp.designation.name if emp.designation else 'N/A',
                'shift': shift_info,
                'status': 'Active' if emp.user.is_active else 'Inactive',
            })
        
        return JsonResponse({
            'success': True,
            'employees': employees_data,
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Error fetching employees: {str(e)}'
        }, status=500)
