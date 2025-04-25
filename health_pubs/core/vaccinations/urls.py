from django.urls import include, path
from rest_framework.routers import DefaultRouter


from .views import (
    VaccinationCreateViewSet,
    VaccinationDeleteViewSet,
    VaccinationListViewSet,
    VaccinationNameCheckViewSet,
)

router = DefaultRouter()
router.register(
    r"vaccinations/create", VaccinationCreateViewSet, basename="vaccination-create"
)
router.register(r"vaccinations", VaccinationListViewSet, basename="vaccination-list")
router.register(
    r"vaccinations/delete", VaccinationDeleteViewSet, basename="vaccination-delete"
)
router.register(
    r"vaccinations/name", VaccinationNameCheckViewSet, basename="vaccination-check"
)

urlpatterns = [
    path("", include(router.urls)),
]
