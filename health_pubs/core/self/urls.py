from django.urls import path

from .views import health_check

urlpatterns = [
    path("api/v1/health/", health_check, name="health_check"),
]
