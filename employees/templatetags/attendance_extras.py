from django import template
from datetime import datetime, timedelta

register = template.Library()

@register.filter
def duration(check_out_time, check_in_time):
    """Calculate duration between check-in and check-out times"""
    if not check_out_time or not check_in_time:
        return "-"
    
    # Calculate the difference
    delta = check_out_time - check_in_time
    
    # Get total seconds
    total_seconds = int(delta.total_seconds())
    
    # Calculate hours and minutes
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    
    # Format the output
    if hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"

@register.filter
def duration_hours(check_out_time, check_in_time):
    """Calculate duration in decimal hours"""
    if not check_out_time or not check_in_time:
        return 0
    
    delta = check_out_time - check_in_time
    hours = delta.total_seconds() / 3600
    return round(hours, 2)
