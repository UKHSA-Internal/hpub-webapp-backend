from django.urls import path
from .views import GeneratePresignedUrlView

urlpatterns = [
    path(
        "get-presigned-url/",
        GeneratePresignedUrlView.as_view(),
        name="get_presigned_url",
    ),
]
