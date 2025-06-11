"""
WSGI config for health_pubs project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/howto/deployment/wsgi/
"""

import os

from core.middleware.healthcheck_host_bypass import HealthCheckHostBypassWSGIHandler

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "health_pubs.settings")

application = HealthCheckHostBypassWSGIHandler()
application.load_middleware()
