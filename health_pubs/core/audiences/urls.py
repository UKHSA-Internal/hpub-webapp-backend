from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AudienceBulkDeleteViewSet,
    AudienceBulkUploadViewSet,
    AudienceCreateViewSet,
    AudienceListViewSet,
    AudienceNameCheckViewSet,
)

router = DefaultRouter()
router.register(r"audiences/create", AudienceCreateViewSet, basename="audience-create")
router.register(r"audiences/list", AudienceListViewSet, basename="audience-list")
router.register(
    r"audiences/name", AudienceNameCheckViewSet, basename="audience-name-check"
)
router.register(
    r"audiences/bulk-upload", AudienceBulkUploadViewSet, basename="audience-bulk-upload"
)
router.register(
    r"audiences/bulk-delete", AudienceBulkDeleteViewSet, basename="audience-bulk-delete"
)

urlpatterns = [
    path("", include(router.urls)),
]
