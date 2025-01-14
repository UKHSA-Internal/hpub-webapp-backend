from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    WhereToUseBulkDeleteViewSet,
    WhereToUseBulkUploadViewSet,
    WhereToUseCreateViewSet,
    WhereToUseListViewSet,
)

router = DefaultRouter()
router.register(
    r"where-to-use/create", WhereToUseCreateViewSet, basename="where-to-use-create"
)
router.register(
    r"where-to-use/list", WhereToUseListViewSet, basename="where-to-use-list"
)
router.register(
    r"where-to-use/bulk-upload",
    WhereToUseBulkUploadViewSet,
    basename="where-to-use-bulk-upload",
)
router.register(
    r"where-to-use/bulk-delete",
    WhereToUseBulkDeleteViewSet,
    basename="where-to-use-bulk-delete",
)

urlpatterns = [
    path("", include(router.urls)),
]
