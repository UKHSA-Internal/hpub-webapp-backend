from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    VaccinationCreateViewSet,
    VaccinationDeleteViewSet,
    VaccinationListViewSet,
)

router = DefaultRouter()
router.register(
    r"vaccinations/create", VaccinationCreateViewSet, basename="vaccination-create"
)
router.register(r"vaccinations", VaccinationListViewSet, basename="vaccination-list")
router.register(
    r"vaccinations/delete", VaccinationDeleteViewSet, basename="vaccination-delete"
)

urlpatterns = [
    path("", include(router.urls)),
]
