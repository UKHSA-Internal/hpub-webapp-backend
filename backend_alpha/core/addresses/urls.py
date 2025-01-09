from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AddressViewSet

router = DefaultRouter()
router.register(r"addresses", AddressViewSet)

urlpatterns = [
    path("", include(router.urls)),
]
