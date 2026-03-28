from django.urls import include, path
from rest_framework.routers import DefaultRouter

from core.establishments.views import v1

router = DefaultRouter()
router.register(
    r"api/v1/establishments/create",
    v1.EstablishmentCreateViewSet,
    basename="establishment-create",
)
router.register(
    r"api/v1/establishments",
    v1.EstablishmentBulkCreateViewSet,
    basename="establishment-bulk-create",
)
router.register(
    r"api/v1/establishments/list",
    v1.EstablishmentListViewSet,
    basename="establishment-list"
)
router.register(
    r"api/v1/establishments/by-organization",
    v1.EstablishmentsByOrganizationViewSet,
    basename="establishments-by-organization",
)
router.register(
    r"api/v1/establishments/bulk-upload",
    v1.EstablishmentBulkUploadViewSet,
    basename="establishment-bulk-upload",
)
router.register(
    r"api/v1/establishments/bulk-delete",
    v1.EstablishmentDeleteViewSet,
    basename="establishments-bulk-delete",
)

urlpatterns = [
    path("", include(router.urls)),
]
