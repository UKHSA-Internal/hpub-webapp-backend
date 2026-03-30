from django.urls import include, path
from rest_framework.routers import DefaultRouter

from core.addresses.views import v1
from core.addresses.views import v2

router = DefaultRouter()
router.register(
    r"api/v1/addresses",
    v1.AddressViewSet,
    basename='addresses-v1'
)
router.register(
    r"api/v2/users/(?P<user_id>[^/.]+)/addresses",
    v2.UserAddressesV2,
    basename='addresses-v2'
)

urlpatterns = [
    path("", include(router.urls)),
]
