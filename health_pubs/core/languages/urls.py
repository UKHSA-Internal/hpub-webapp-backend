from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    BulkLanguageUploadViewSet,
    DeleteAllLanguagesViewSet,
    LanguageCreateViewSet,
    LanguageListViewSet,
    LanguageFilteredListViewSet,
)

router = DefaultRouter()
router.register(r"languages/create", LanguageCreateViewSet, basename="language-create")
router.register(r"languages/list", LanguageListViewSet, basename="language-list")
router.register(
    r"languages/filtered-list",
    LanguageFilteredListViewSet,
    basename="language-filted-list",
)
router.register(
    r"languages/bulk-upload", BulkLanguageUploadViewSet, basename="language-bulk-upload"
)
router.register(
    r"languages/delete-all", DeleteAllLanguagesViewSet, basename="language-delete-all"
)

urlpatterns = [
    path("", include(router.urls)),
]
