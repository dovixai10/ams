class OfficeMiddleware:
    """Resolves the logged-in user's Office and attaches it to the request
    as request.office. Available in every view without changing any URL."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.office = None

        if request.user.is_authenticated:
            if hasattr(request.user, 'office_admin_profile'):
                request.office = request.user.office_admin_profile.office
            elif hasattr(request.user, 'employee_profile') and request.user.employee_profile.office_id:
                request.office = request.user.employee_profile.office

        response = self.get_response(request)
        return response