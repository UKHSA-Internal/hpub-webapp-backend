from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .view import CustomerSupportViewSet

router = DefaultRouter()
router.register(r"customer_support", CustomerSupportViewSet)


urlpatterns = [
    path("", include(router.urls)),
]
