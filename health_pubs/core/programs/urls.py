from django.urls import path
from rest_framework.routers import DefaultRouter

from core.programs.views import v1


router = DefaultRouter()
router.register(r"api/v1/programs", v1.ProgramListViewSet, basename="program")
router.register(
    r"api/v1/programs/name", v1.ProgramNameCheckViewSet, basename="program-name-check"
)
router.register(r"api/v1/programs/update", v1.ProgramUpdateViewSet, basename="program-update")
router.register(r"api/v1/programs/destroy", v1.ProgramDestroyViewSet, basename="program-destroy")
router.register(
    r"api/v1/programs/bulk-delete", v1.BulkProgramDeleteViewSet, basename="bulk-delete"
)

urlpatterns = [
    # 1) your other custom endpoints
    path(
        "api/v1/programs/create/",
        v1.ProgramCreateViewSet.as_view({"post": "create"}),
        name="programs-create",
    ),
    path(
        "api/v1/programs/featured/",
        v1.ProgramListViewSet.as_view({"get": "featured_programs"}),
        name="programs-featured"
    ),
    path(
        "api/v1/programs/filtered-programmes/",
        v1.ProgramListViewSet.as_view({"get": "programs_with_related"}),
        name="programs-filtered",
    ),
    # 2) now your bulk-upload *before* the router’s catch‑alls
    path(
        "api/v1/programs/bulk-upload/",
        v1.BulkProgramUploadViewSet.as_view(),
        name="programs-bulk-upload",
    ),
    # 3) finally, drop in all of the router‑generated routes
    *router.urls,
]
