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

# 1) Explicitly pin the two custom list actions up front
featured_programs = ProgramListViewSet.as_view({"get": "featured_programs"})
filtered_programs = ProgramListViewSet.as_view({"get": "programs_with_related"})

router = DefaultRouter()
# 2) Register all of your ViewSets—order here doesn't matter now that the custom paths are first
router.register(r"programs", ProgramListViewSet, basename="program")
router.register(r"programs/create", ProgramCreateViewSet, basename="program-create")
router.register(
    r"programs/name", ProgramNameCheckViewSet, basename="program-name-check"
)
router.register(r"programs/update", ProgramUpdateViewSet, basename="program-update")
router.register(r"programs/destroy", ProgramDestroyViewSet, basename="program-destroy")
router.register(
    r"programs/bulk-delete", BulkProgramDeleteViewSet, basename="bulk-delete"
)

urlpatterns = [
    # these two will always be matched before any "/programs/<pk>/" catch-all
    path("programs/featured/", featured_programs, name="programs-featured"),
    path("programs/filtered-programmes/", filtered_programs, name="programs-filtered"),
    # now drop in the router’s automatically generated routes
    *router.urls,
    # plus your bulk-upload endpoint
    path(
        "programs/bulk-upload/",
        BulkProgramUploadViewSet.as_view(),
        name="programs-bulk-upload",
    ),
]
