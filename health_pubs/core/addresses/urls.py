from django.urls import include, path
from rest_framework.routers import DefaultRouter

from core.addresses.views import v1

router = DefaultRouter()
router.register(r"api/v1/addresses",v1.AddressViewSet)

urlpatterns = [
    path("", include(router.urls)),
]
