from django.urls import include, path
from rest_framework.routers import DefaultRouter

from core.organizations.views import v1
from core.organizations.views import v2

router = DefaultRouter()
router.register(
    r"api/v1/organizations/create",
    v1.OrganizationCreateViewSet,
    basename="organization-create",
)
router.register(
    r"api/v1/organizations/list",
    v1.OrganizationListViewSet,
    basename="organization-list",
)
router.register(
    r"api/v1/organizations/bulk-create",
    v1.OrganizationBulkCreateViewSet,
    basename="organization-bulk-create",
)
router.register(
    r"api/v1/organizations/delete",
    v1.OrganizationDeleteViewSet,
    basename="organization-delete",
)
router.register(
    r"api/v1/organizations/bulk-upload",
    v1.OrganizationBulkUploadViewSet,
    basename="organization-bulk-upload",
)
router.register(
    r"api/v1/organizations/update",
    v1.OrganizationUpdateViewSet,
    basename="organization-update",
)
router.register(
    r"api/v2/organisations",
    v2.OrganisationV2,
    basename="organization-v2",
)

urlpatterns = [
    path("", include(router.urls)),
]
