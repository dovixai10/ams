"""
Geolocation utilities for attendance check-in/check-out
"""
import math

# Office coordinates (manually configured)
# OFFICE_LATITUDE = 26.875401
# OFFICE_LONGITUDE = 75.753071
# testing lat and long 
# OFFICE_LATITUDE = 26.9280397
# OFFICE_LONGITUDE = 75.7965632
# correct dovix loc 
OFFICE_LATITUDE = 26.929218452913393
OFFICE_LONGITUDE = 75.79914593083001
ALLOWED_RADIUS_METERS = 250 # 50 meters
# OFFICE_LATITUDE = 27.049444
# OFFICE_LONGITUDE = 76.575012
def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate the great circle distance between two points 
    on the earth (specified in decimal degrees) using the Haversine formula.
    
    Returns distance in meters.
    """
    # Convert decimal degrees to radians
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    
    # Haversine formula
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.asin(math.sqrt(a))
    
    # Radius of earth in meters
    earth_radius_meters = 6371000
    
    # Calculate the distance
    distance = earth_radius_meters * c
    
    return distance


def is_within_office_premises(user_latitude, user_longitude):
    """
    Check if the user's location is within the allowed radius of the office.
    
    Args:
        user_latitude (float): User's current latitude
        user_longitude (float): User's current longitude
    
    Returns:
        tuple: (is_valid, distance, message)
            - is_valid (bool): True if within allowed radius, False otherwise
            - distance (float): Distance from office in meters
            - message (str): Success or error message
    """
    try:
        # Calculate distance from office
        distance = haversine_distance(
            OFFICE_LATITUDE, 
            OFFICE_LONGITUDE, 
            user_latitude, 
            user_longitude
        )
        
        # Check if within allowed radius
        if distance <= ALLOWED_RADIUS_METERS:
            return True, distance, f"Location verified. You are {distance:.1f}m from office."
        else:
            return False, distance, f"You are not within office premises. You are {distance:.1f}m away from office (allowed: {ALLOWED_RADIUS_METERS}m)."
    
    except Exception as e:
        return False, None, f"Error validating location: {str(e)}"


def validate_coordinates(latitude, longitude):
    """
    Validate that latitude and longitude are valid values.
    
    Args:
        latitude (float): Latitude value
        longitude (float): Longitude value
    
    Returns:
        tuple: (is_valid, message)
    """
    try:
        lat = float(latitude)
        lon = float(longitude)
        
        # Check valid ranges
        if not (-90 <= lat <= 90):
            return False, "Invalid latitude. Must be between -90 and 90."
        
        if not (-180 <= lon <= 180):
            return False, "Invalid longitude. Must be between -180 and 180."
        
        return True, "Coordinates are valid."
    
    except (ValueError, TypeError):
        return False, "Invalid coordinate format. Must be numeric values."
