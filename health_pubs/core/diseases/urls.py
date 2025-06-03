from rest_framework.routers import DefaultRouter

from .views import (
    DiseaseBulkUploadViewSet,
    DiseaseCreateViewSet,
    DiseaseDeleteViewSet,
    DiseaseListViewSet,
    DiseaseNameCheckViewSet,
)

router = DefaultRouter()
router.register(r"diseases/create", DiseaseCreateViewSet, basename="disease-create")
router.register(r"diseases", DiseaseListViewSet, basename="disease-list")
router.register(r"diseases/delete", DiseaseDeleteViewSet, basename="disease-delete")
router.register(r"diseases/name", DiseaseNameCheckViewSet, basename="disease-check")
router.register(
    r"diseases/bulk-upload", DiseaseBulkUploadViewSet, basename="disease-bulk-upload"
)

urlpatterns = router.urls
