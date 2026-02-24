from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import NotificationViewSet

router = DefaultRouter()
router.register(r"notifications", NotificationViewSet, basename="notifications")

urlpatterns = [
    path(
        "frontend/notifications",
        NotificationViewSet.as_view({"get": "frontend_notification"}),
        name="frontend-notifications",
    ),
    path("", include(router.urls)),
]
