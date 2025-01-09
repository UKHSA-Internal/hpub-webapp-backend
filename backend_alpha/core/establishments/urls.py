from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    EstablishmentBulkCreateViewSet,
    EstablishmentBulkUploadViewSet,
    EstablishmentCreateViewSet,
    EstablishmentDeleteViewSet,
    EstablishmentListViewSet,
    EstablishmentsByOrganizationViewSet,
)

router = DefaultRouter()
router.register(
    r"establishments/create",
    EstablishmentCreateViewSet,
    basename="establishment-create",
)
router.register(
    r"establishments",
    EstablishmentBulkCreateViewSet,
    basename="establishment-bulk-create",
)
router.register(
    r"establishments/list", EstablishmentListViewSet, basename="establishment-list"
)
router.register(
    r"establishments/by-organization",
    EstablishmentsByOrganizationViewSet,
    basename="establishments-by-organization",
)
router.register(
    r"establishments/bulk-upload",
    EstablishmentBulkUploadViewSet,
    basename="establishment-bulk-upload",
)
router.register(
    r"establishments/bulk-delete",
    EstablishmentDeleteViewSet,
    basename="establishments-bulk-delete",
)

urlpatterns = [
    path("", include(router.urls)),
]
