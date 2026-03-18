from django.urls import include, path
from rest_framework.routers import DefaultRouter


from .views import (
    VaccinationBulkUploadViewSet,
    VaccinationCreateViewSet,
    VaccinationEditViewSet,
    VaccinationDeleteViewSet,
    VaccinationListViewSet,
    VaccinationNameCheckViewSet,
)

router = DefaultRouter()
router.register(
    r"vaccinations/create", VaccinationCreateViewSet, basename="vaccination-create"
)
router.register(
    r"vaccinations/edit", VaccinationEditViewSet, basename="vaccination-edit"
)
router.register(r"vaccinations", VaccinationListViewSet, basename="vaccination-list")
router.register(
    r"vaccinations/delete", VaccinationDeleteViewSet, basename="vaccination-delete"
)
router.register(
    r"vaccinations/name", VaccinationNameCheckViewSet, basename="vaccination-check"
)

router.register(
    r"vaccinations/bulk-upload",
    VaccinationBulkUploadViewSet,
    basename="vaccination-bulk-upload",
)

urlpatterns = [
    path("", include(router.urls)),
]
