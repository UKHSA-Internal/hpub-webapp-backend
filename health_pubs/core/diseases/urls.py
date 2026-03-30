from rest_framework.routers import DefaultRouter

from core.diseases.views import v1

router = DefaultRouter()
router.register(
    r"api/v1/diseases/create", v1.DiseaseCreateViewSet, basename="disease-create"
)
router.register(r"api/v1/diseases/edit", v1.DiseaseEditViewSet, basename="disease-edit")
router.register(r"api/v1/diseases", v1.DiseaseListViewSet, basename="disease-list")
router.register(
    r"api/v1/diseases/delete", v1.DiseaseDeleteViewSet, basename="disease-delete"
)
router.register(
    r"api/v1/diseases/name", v1.DiseaseNameCheckViewSet, basename="disease-check"
)
router.register(
    r"api/v1/diseases/bulk-upload",
    v1.DiseaseBulkUploadViewSet,
    basename="disease-bulk-upload",
)

urlpatterns = router.urls
