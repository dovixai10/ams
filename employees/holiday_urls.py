"""
Holiday Management URLs
"""

from django.urls import path
from . import holiday_views

app_name = 'holidays'

urlpatterns = [
    # Get holidays for a year
    path('api/holidays/', holiday_views.get_holidays, name='get_holidays'),
    
    # Create holiday
    path('api/holidays/create/', holiday_views.create_holiday, name='create_holiday'),
    
    # Check if date is holiday
    path('api/holidays/check/', holiday_views.check_holiday, name='check_holiday'),
    
    # Update holiday
    path('api/holidays/<int:holiday_id>/update/', holiday_views.update_holiday, name='update_holiday'),
    
    # Delete holiday
    path('api/holidays/<int:holiday_id>/delete/', holiday_views.delete_holiday, name='delete_holiday'),
]
