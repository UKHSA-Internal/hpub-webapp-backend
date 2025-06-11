from django.core.handlers.base import BaseHandler


class HealthCheckHostBypassWSGIHandler(BaseHandler):
    def __init__(self):
        super().__init__()

    def get_response(self, request):
        if request.path.startswith("/api/v1/health/"):
            request._skip_host_validation = True
        return super().get_response(request)

    def validate_host(self, host, allowed_hosts):
        request = self._current_request
        if getattr(request, "_skip_host_validation", False):
            return
        return super().validate_host(host, allowed_hosts)
