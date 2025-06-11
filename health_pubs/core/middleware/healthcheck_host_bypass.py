from django.core.handlers.base import BaseHandler
from django.http import HttpRequest


class HealthCheckHostBypassWSGIHandler(BaseHandler):
    """
    Custom WSGI request handler that skips host validation for /health/
    """

    def __init__(self):
        super().__init__()

    def get_response(self, request: HttpRequest):
        if request.path == "/api/v1/health/" or request.path.startswith(
            "/api/v1/health/"
        ):
            # Disable host validation dynamically
            request._skip_host_validation = True
        return super().get_response(request)

    def validate_host(self, host: str, allowed_hosts: list[str]):
        request = self._current_request
        # Skip host validation only for health check
        if hasattr(request, "_skip_host_validation") and request._skip_host_validation:
            return
        return super().validate_host(host, allowed_hosts)
