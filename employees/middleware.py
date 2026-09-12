class OfficeMiddleware:
    """Resolves the logged-in user's Office and Branch, attaching them to
    the request as request.office / request.branch. Available in every
    view without changing any URL.

    - Employee: office/branch are just their own fixed assignment.
    - Office admin: office is fixed, but branch is whichever one is
      'active' in their session (SESSION_BRANCH_KEY, set by the branch
      switcher view). Falls back to the office's head-office branch (or
      its first branch) if nothing valid is selected yet.
    - Anyone else (platform admin, no profile): both stay None.
    """

    SESSION_BRANCH_KEY = 'active_branch_id'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.office = None
        request.branch = None

        if request.user.is_authenticated:
            if hasattr(request.user, 'office_admin_profile'):
                request.office = request.user.office_admin_profile.office
                request.branch = self._resolve_admin_branch(request, request.office)
            elif hasattr(request.user, 'employee_profile') and request.user.employee_profile.office_id:
                employee = request.user.employee_profile
                request.office = employee.office
                request.branch = employee.branch

        response = self.get_response(request)
        return response

    def _resolve_admin_branch(self, request, office):
        """Look up the office admin's session-selected branch, validating it
        still belongs to this office and is active. Falls back to the
        office's head-office/first branch, and remembers that choice in
        the session so it sticks across requests."""
        from .models import Branch

        branch_id = request.session.get(self.SESSION_BRANCH_KEY)
        branch = None

        if branch_id:
            branch = Branch.objects.filter(id=branch_id, office=office, is_active=True).first()

        if branch is None:
            branch = Branch.objects.filter(office=office, is_active=True).order_by('-is_head_office', 'name').first()
            if branch is not None:
                request.session[self.SESSION_BRANCH_KEY] = branch.id

        return branch
