from rest_framework.routers import DefaultRouter

from .views import DiseaseCreateViewSet, DiseaseDeleteAllViewSet, DiseaseListViewSet

router = DefaultRouter()
router.register(r"diseases/create", DiseaseCreateViewSet, basename="disease-create")
router.register(r"diseases", DiseaseListViewSet, basename="disease-list")
router.register(
    r"diseases/delete-all", DiseaseDeleteAllViewSet, basename="disease-delete-all"
)

urlpatterns = router.urls
