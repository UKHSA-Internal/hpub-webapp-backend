from django.urls import include, path
from rest_framework.routers import DefaultRouter

from core.roles.views import v1
from core.roles.views import v2

router = DefaultRouter()

# v1 roles
router.register(r"api/v1/roles", v1.RoleViewSet, basename="roles-v1")

# v2 roles
router.register(r"api/v2/roles", v2.RolesV2, basename="roles-v2")

urlpatterns = [
    path("", include(router.urls)),
]
