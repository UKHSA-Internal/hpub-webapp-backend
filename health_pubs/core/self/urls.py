from django.urls import path

from core.self import views

urlpatterns = [
    path("api/v1/health/", views.get_health_check, name="health_check"),
    path("api/v2/self/health/", views.get_health_check, name="v2_self_health"),
    path("api/v2/self/info/", views.get_self_info, name="v2_self_info"),
    path("api/v2/self/config/", views.get_self_config, name="v2_self_config"),
]
