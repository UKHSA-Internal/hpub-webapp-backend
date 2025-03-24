from rest_framework.routers import DefaultRouter

from .views import (
    DiseaseCreateViewSet,
    DiseaseDeleteAllViewSet,
    DiseaseDeleteViewSet,
    DiseaseListViewSet,
)

router = DefaultRouter()
router.register(r"diseases/create", DiseaseCreateViewSet, basename="disease-create")
router.register(r"diseases", DiseaseListViewSet, basename="disease-list")
router.register(r"diseases/delete", DiseaseDeleteViewSet, basename="disease-delete")
router.register(
    r"diseases/delete-all", DiseaseDeleteAllViewSet, basename="disease-delete-all"
)

urlpatterns = router.urls
