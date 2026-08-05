"""
Holiday Management Views
Admin can create, edit, delete holidays
Employees can view holidays in calendar
"""

from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from datetime import date, datetime
import logging
import json

from .models import Holiday
from web_project import TemplateLayout
from web_project.template_helpers.theme import TemplateHelper
from .permissions import office_admin_required, is_platform_admin, get_request_office

logger = logging.getLogger(__name__)


# def is_admin(user):
#     """Check if user is admin/superuser"""
#     return user.is_superuser or user.is_staff


@login_required
def holidays_calendar(request):
    """Render the holidays calendar page for employees and admins."""
    context = TemplateLayout.init(request, context={})
    context.update({
        "current_year": timezone.now().year,
        "layout_path": TemplateHelper.set_layout('layout_vertical.html', context),
    })
    return render(request, "employees/holidays_calendar.html", context)


@login_required
@require_http_methods(["GET"])
def get_holidays(request):
    """
    Get all holidays for a specific year
    GET /api/holidays?year=2025
    
    Returns JSON list of holidays
    """
    try:
        year = request.GET.get('year')
        
        if not year:
            year = date.today().year
        else:
            try:
                year = int(year)
            except ValueError:
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid year format'
                }, status=400)
        
        # Get all holidays for the year
        holidays = Holiday.objects.filter(
            date__year=year
        ).order_by('date').values(
            'id', 'date', 'name', 'description'
        )
        office = get_request_office(request)
        if office:
            holidays = holidays.filter(office=office)
        holidays = holidays.order_by('date').values('id', 'date', 'name', 'description')
  
        
        holidays_list = [
            {
                'id': h['id'],
                'date': h['date'].isoformat(),
                'name': h['name'],
                'description': h['description'] or ''
            }
            for h in holidays
        ]
        
        logger.info(f"Retrieved {len(holidays_list)} holidays for year {year}")
        
        return JsonResponse({
            'success': True,
            'holidays': holidays_list,
            'count': len(holidays_list),
            'year': year
        })
    
    except Exception as e:
        logger.error(f"Error fetching holidays: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'Server error'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def create_holiday(request):
    """
    Create a new holiday
    POST /api/holidays
    
    Expects:
        - date: YYYY-MM-DD format
        - name: Holiday name
        - description: (optional) Holiday description
    
    Admin only
    """
    try:
        if not office_admin_required(request.user):   # was: office_admin_required(request.user)
            return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

        office = get_request_office(request)
        
        # Parse request data
        try:
            data = json.loads(request.body)
        except:
            data = request.POST
        
        date_str = data.get('date')
        name = data.get('name')
        description = data.get('description', '')
        
        # Validate inputs
        if not date_str or not name:
            return JsonResponse({
                'success': False,
                'error': 'Date and name are required'
            }, status=400)
        
        # Parse date
        try:
            holiday_date = parse_date(date_str)
            if not holiday_date:
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid date format. Use YYYY-MM-DD'
                }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Date parsing error: {str(e)}'
            }, status=400)
        
        # Check if holiday already exists
        if Holiday.objects.filter(date=holiday_date, office=office).exists():
            return JsonResponse({
                'success': False,
                'error': 'Holiday already exists for this date'
            }, status=400)
        
        # Create holiday
        holiday = Holiday.objects.create(
            date=holiday_date,
            name=name,
            description=description,
            created_by=request.user,
            office=office
        )
        
        logger.info(f"Holiday created: {holiday.id} - {holiday.name} on {holiday.date}")
        
        return JsonResponse({
            'success': True,
            'message': 'Holiday created successfully',
            'holiday': {
                'id': holiday.id,
                'date': holiday.date.isoformat(),
                'name': holiday.name,
                'description': holiday.description
            }
        })
    
    except Exception as e:
        logger.error(f"Error creating holiday: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'Server error'
        }, status=500)


@login_required
@require_http_methods(["PUT", "PATCH"])
def update_holiday(request, holiday_id):
    """
    Update an existing holiday
    PUT /api/holidays/<id>
    
    Expects:
        - date: (optional) YYYY-MM-DD format
        - name: (optional) Holiday name
        - description: (optional) Holiday description
    
    Admin only
    """
    try:
        if not office_admin_required(request.user):
            return JsonResponse({
                'success': False,
                'error': 'Permission denied'
            }, status=403)
        
        holiday = get_object_or_404(Holiday, id=holiday_id)
        
        # Parse request data
        try:
            data = json.loads(request.body)
        except:
            data = request.POST
        
        # Update fields if provided
        if 'date' in data:
            try:
                new_date = parse_date(data['date'])
                if not new_date:
                    return JsonResponse({
                        'success': False,
                        'error': 'Invalid date format'
                    }, status=400)
                
                # Check if new date already exists
                if Holiday.objects.filter(date=new_date).exclude(id=holiday_id).exists():
                    return JsonResponse({
                        'success': False,
                        'error': 'Holiday already exists for this date'
                    }, status=400)
                
                holiday.date = new_date
            except Exception as e:
                return JsonResponse({
                    'success': False,
                    'error': f'Date error: {str(e)}'
                }, status=400)
        
        if 'name' in data:
            holiday.name = data['name']
        
        if 'description' in data:
            holiday.description = data['description']
        
        holiday.save()
        
        logger.info(f"Holiday updated: {holiday.id} - {holiday.name}")
        
        return JsonResponse({
            'success': True,
            'message': 'Holiday updated successfully',
            'holiday': {
                'id': holiday.id,
                'date': holiday.date.isoformat(),
                'name': holiday.name,
                'description': holiday.description
            }
        })
    
    except Exception as e:
        logger.error(f"Error updating holiday: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'Server error'
        }, status=500)


@login_required
@require_http_methods(["DELETE"])
def delete_holiday(request, holiday_id):
    """
    Delete a holiday
    DELETE /api/holidays/<id>
    
    Admin only
    """
    try:
        if not office_admin_required(request.user):
            return JsonResponse({
                'success': False,
                'error': 'Permission denied'
            }, status=403)
        
        holiday = get_object_or_404(Holiday, id=holiday_id)
        holiday_name = holiday.name
        holiday_date = holiday.date
        
        holiday.delete()
        
        logger.info(f"Holiday deleted: {holiday_name} on {holiday_date}")
        
        return JsonResponse({
            'success': True,
            'message': 'Holiday deleted successfully'
        })
    
    except Exception as e:
        logger.error(f"Error deleting holiday: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'Server error'
        }, status=500)


@login_required
@require_http_methods(["GET"])
def check_holiday(request):
    """
    Check if a specific date is a holiday
    GET /api/holidays/check?date=YYYY-MM-DD
    
    Returns holiday info if it's a holiday, null otherwise
    """
    try:
        date_str = request.GET.get('date')
        
        if not date_str:
            return JsonResponse({
                'success': False,
                'error': 'Date parameter required'
            }, status=400)
        
        try:
            check_date = parse_date(date_str)
            if not check_date:
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid date format'
                }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': f'Date error: {str(e)}'
            }, status=400)
        
        holiday = Holiday.objects.filter(date=check_date).first()
        
        if holiday:
            return JsonResponse({
                'success': True,
                'is_holiday': True,
                'holiday': {
                    'id': holiday.id,
                    'date': holiday.date.isoformat(),
                    'name': holiday.name,
                    'description': holiday.description
                }
            })
        else:
            return JsonResponse({
                'success': True,
                'is_holiday': False,
                'holiday': None
            })
    
    except Exception as e:
        logger.error(f"Error checking holiday: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'Server error'
        }, status=500)
