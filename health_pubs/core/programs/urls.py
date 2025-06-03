from rest_framework.routers import DefaultRouter
from django.urls import path
from .views import (
    BulkProgramDeleteViewSet,
    BulkProgramUploadViewSet,
    ProgramCreateViewSet,
    ProgramDestroyViewSet,
    ProgramListViewSet,
    ProgramNameCheckViewSet,
    ProgramUpdateViewSet,
)

router = DefaultRouter()
router.register(r"programs/create", ProgramCreateViewSet, basename="program-create")
router.register(r"programs", ProgramListViewSet, basename="program")
router.register(
    r"programs/name", ProgramNameCheckViewSet, basename="programme-name-check"
)
router.register(r"programs/update", ProgramUpdateViewSet, basename="program-update")
router.register(r"programs/destroy", ProgramDestroyViewSet, basename="program-destroy")
router.register(
    r"programs/bulk-delete", BulkProgramDeleteViewSet, basename="bulk-delete"
)

# Combine router-generated URLs with your extra upload endpoint
urlpatterns = [
    *router.urls,
    path(
        "programs/bulk-upload/",
        BulkProgramUploadViewSet.as_view(),
        name="program-bulk-upload",
    ),
]
