from rest_framework.routers import DefaultRouter

from .views import (
    DiseaseCreateViewSet,
    DiseaseDeleteViewSet,
    DiseaseListViewSet,
)

router = DefaultRouter()
router.register(r"diseases/create", DiseaseCreateViewSet, basename="disease-create")
router.register(r"diseases", DiseaseListViewSet, basename="disease-list")
router.register(r"diseases/delete", DiseaseDeleteViewSet, basename="disease-delete")


urlpatterns = router.urls
