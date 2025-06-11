class HealthCheckHostBypassMiddleware:
    """
    Bypass ALLOWED_HOSTS validation for /api/v1/health requests.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Check if it's the health check URL
        if request.path == "/api/v1/health":
            # Force host validation to always succeed for this path
            request._dont_enforce_csrf_checks = True
            return self.get_response(request)

        # Proceed normally
        return self.get_response(request)
