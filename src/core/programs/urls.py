# your_app/urls.py

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ProgramListViewSet,
    ProgramCreateViewSet,
    ProgramUpdateViewSet,
    ProgramDestroyViewSet,
    ProgramNameCheckViewSet,
    BulkProgramDeleteViewSet,
    BulkProgramUploadViewSet,
)

featured_programs = ProgramListViewSet.as_view({"get": "featured_programs"})
filtered_programs = ProgramListViewSet.as_view({"get": "programs_with_related"})

router = DefaultRouter()
router.register(r"programs", ProgramListViewSet, basename="program")
router.register(
    r"programs/name", ProgramNameCheckViewSet, basename="program-name-check"
)
router.register(r"programs/update", ProgramUpdateViewSet, basename="program-update")
router.register(r"programs/destroy", ProgramDestroyViewSet, basename="program-destroy")
router.register(
    r"programs/bulk-delete", BulkProgramDeleteViewSet, basename="bulk-delete"
)

urlpatterns = [
    # 1) your other custom endpoints
    path(
        "programs/create/",
        ProgramCreateViewSet.as_view({"post": "create"}),
        name="programs-create",
    ),
    path("programs/featured/", featured_programs, name="programs-featured"),
    path(
        "programs/filtered-programmes/",
        filtered_programs,
        name="programs-filtered",
    ),
    # 2) now your bulk-upload *before* the router’s catch‑alls
    path(
        "programs/bulk-upload/",
        BulkProgramUploadViewSet.as_view(),
        name="programs-bulk-upload",
    ),
    # 3) finally, drop in all of the router‑generated routes
    *router.urls,
]
