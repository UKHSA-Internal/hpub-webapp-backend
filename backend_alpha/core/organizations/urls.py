from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    OrganizationBulkCreateViewSet,
    OrganizationBulkUploadViewSet,
    OrganizationCreateViewSet,
    OrganizationDeleteViewSet,
    OrganizationListViewSet,
    OrganizationUpdateViewSet,
)

router = DefaultRouter()
router.register(
    r"organizations/create", OrganizationCreateViewSet, basename="organization-create"
)
router.register(
    r"organizations/list", OrganizationListViewSet, basename="organization-list"
)
router.register(
    r"organizations/bulk-create",
    OrganizationBulkCreateViewSet,
    basename="organization-bulk-create",
)
router.register(
    r"organizations/delete", OrganizationDeleteViewSet, basename="organization-delete"
)
router.register(
    r"organizations/bulk-upload",
    OrganizationBulkUploadViewSet,
    basename="organization-bulk-upload",
)
router.register(
    r"organizations/update", OrganizationUpdateViewSet, basename="organization-update"
)

urlpatterns = [
    path("", include(router.urls)),
]
