from django.core.handlers.wsgi import WSGIHandler


class HealthCheckHostBypassWSGIHandler(WSGIHandler):
    def __init__(self):
        super().__init__()
        # Note: get_wsgi_application() calls load_middleware() for you,
        # so we’ll explicitly load it below.

    def get_response(self, request):
        # mark health-check paths to skip host validation
        if request.path.startswith("/api/v1/health/"):
            request._skip_host_validation = True
        return super().get_response(request)

    def validate_host(self, host, allowed_hosts):
        # skip ALLOWED_HOSTS check when flagged
        if getattr(self._current_request, "_skip_host_validation", False):
            return
        return super().validate_host(host, allowed_hosts)
