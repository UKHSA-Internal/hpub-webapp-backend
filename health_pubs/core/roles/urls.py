from django.urls import include, path
from rest_framework.routers import DefaultRouter

from core.roles.views import v1

router = DefaultRouter()
router.register("api/v1/roles", v1.RoleViewSet)

urlpatterns = [
    path("", include(router.urls)),
]
