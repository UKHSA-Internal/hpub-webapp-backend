"""
WSGI config for health_pubs project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application
from core.middleware.healthcheck_host_bypass import HealthCheckHostBypassWSGIHandler

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "health_pubs.settings")

application = get_wsgi_application()
application = HealthCheckHostBypassWSGIHandler()
application.load_middleware()
