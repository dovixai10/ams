"""
drf-spectacular preprocessing hook - keeps the generated OpenAPI schema
(served at /api/docs/) scoped to the mobile attendance app API
(employees/mobile_*.py) only. The three pre-existing /api/v1/ endpoints
(token-auth, profile, salary-slips) serve a different integration - other
platforms, not this Flutter app - and stay undocumented here rather than
mixed into a schema meant for the mobile team.
"""

EXCLUDED_PATHS = {
    '/api/v1/token-auth/',
    '/api/v1/profile/',
    '/api/v1/salary-slips/',
}


def mobile_api_only(endpoints):
    return [
        (path, path_regex, method, callback)
        for path, path_regex, method, callback in endpoints
        if path not in EXCLUDED_PATHS
    ]
