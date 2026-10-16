"""
Geolocation utilities for attendance check-in/check-out
"""
import math

DEFAULT_ALLOWED_RADIUS_METERS = 250


def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate the great circle distance between two points
    on the earth (specified in decimal degrees) using the Haversine formula.

    Returns distance in meters.
    """
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))

    earth_radius_meters = 6371000

    return earth_radius_meters * c


def is_within_office_premises(office, user_latitude, user_longitude, radius_meters=None, branch=None):
    """
    Check if the user's location is within the allowed radius of their
    workplace - their branch if it has coordinates set, otherwise falling
    back to the office's own coordinates (e.g. a single-branch office that
    hasn't filled in its branch's location separately yet).

    Args:
        office (Office): The employee's office. Used as a location fallback.
        user_latitude (float): User's current latitude
        user_longitude (float): User's current longitude
        radius_meters (float, optional): Override radius. Defaults to the
            branch's/office's own attendance_radius_meters if set, else
            DEFAULT_ALLOWED_RADIUS_METERS.
        branch (Branch, optional): The employee's branch. Its own
            latitude/longitude/attendance_radius_meters take priority over
            the office's when both are present.

    Returns:
        tuple: (is_valid, distance, message)
            - is_valid (bool): True if within allowed radius, False otherwise
            - distance (float | None): Distance from the workplace in meters
            - message (str): Success or error message
    """
    if office is None and branch is None:
        return False, None, "No office is associated with your account. Contact your admin."

    # Prefer the branch's own location; fall back to the office's.
    location_source = None
    if branch is not None and branch.latitude is not None and branch.longitude is not None:
        location_source = branch
    elif office is not None and office.latitude is not None and office.longitude is not None:
        location_source = office

    if location_source is None:
        where = "branch" if branch is not None else "office"
        return False, None, f"Your {where} hasn't set its location yet. Contact your admin to configure it."

    # Priority: an explicit override > the branch's own radius (if it set
    # one) > the office's own default radius (if it set one) > the hardcoded
    # fallback. location_source may already BE the office (branch had no
    # coordinates of its own), in which case the second and third lookups
    # here are the same value - harmless, just redundant.
    allowed_radius = (
        radius_meters
        or getattr(location_source, 'attendance_radius_meters', None)
        or getattr(office, 'attendance_radius_meters', None)
        or DEFAULT_ALLOWED_RADIUS_METERS
    )

    try:
        distance = haversine_distance(
            float(location_source.latitude),
            float(location_source.longitude),
            user_latitude,
            user_longitude
        )

        if distance <= allowed_radius:
            return True, distance, f"Location verified. You are {distance:.1f}m from office."
        else:
            return False, distance, f"You are not within office premises. You are {distance:.1f}m away from office (allowed: {allowed_radius}m)."

    except Exception as e:
        return False, None, f"Error validating location: {str(e)}"


def validate_coordinates(latitude, longitude):
    """
    Validate that latitude and longitude are valid values.
    """
    try:
        lat = float(latitude)
        lon = float(longitude)

        if not (-90 <= lat <= 90):
            return False, "Invalid latitude. Must be between -90 and 90."

        if not (-180 <= lon <= 180):
            return False, "Invalid longitude. Must be between -180 and 180."

        return True, "Coordinates are valid."

    except (ValueError, TypeError):
        return False, "Invalid coordinate format. Must be numeric values."