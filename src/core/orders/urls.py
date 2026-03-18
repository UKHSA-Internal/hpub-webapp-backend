from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    DeleteMigratedOrdersAPIView,
    MigrateOrdersAPIView,
    OrderItemViewSet,
    OrderViewSet,
)

router = DefaultRouter()
router.register(r"orders", OrderViewSet)
router.register(r"order-items", OrderItemViewSet)

urlpatterns = [
    path("", include(router.urls)),
    path("migrate-orders/", MigrateOrdersAPIView.as_view(), name="migrate_orders"),
    path("delete-all/", DeleteMigratedOrdersAPIView.as_view(), name="delete_all"),
]
