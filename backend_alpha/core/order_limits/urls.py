from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import OrderLimitPageViewSet

router = DefaultRouter()
router.register(r"order-limits", OrderLimitPageViewSet)

urlpatterns = [
    path("", include(router.urls)),
]
