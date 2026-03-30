from django.urls import path
from rest_framework.routers import DefaultRouter

from core.programs.views import v1
from core.programs.views import v2


router = DefaultRouter()

router.register(r"api/v1/programs", v1.ProgramListViewSet, basename="program")
router.register(
    r"api/v1/programs/name", v1.ProgramNameCheckViewSet, basename="program-name-check"
)
router.register(
    r"api/v1/programs/update", v1.ProgramUpdateViewSet, basename="program-update"
)
router.register(
    r"api/v1/programs/destroy", v1.ProgramDestroyViewSet, basename="program-destroy"
)
router.register(
    r"api/v1/programs/bulk-delete", v1.BulkProgramDeleteViewSet, basename="bulk-delete"
)

router.register(r"api/v2/programmes", v2.ProgrammesV2, basename="programmes-v2")

urlpatterns = [
    path(
        "api/v1/programs/create/", v1.ProgramCreateViewSet.as_view({"post": "create"})
    ),
    path(
        "api/v1/programs/featured/",
        v1.ProgramListViewSet.as_view({"get": "featured_programs"}),
    ),
    path(
        "api/v1/programs/filtered-programmes/",
        v1.ProgramListViewSet.as_view({"get": "programs_with_related"}),
    ),
    path("api/v1/programs/bulk-upload/", v1.BulkProgramUploadViewSet.as_view()),
]

urlpatterns += router.urls
