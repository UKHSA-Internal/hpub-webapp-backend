from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AdminProductFilterView,
    ProductAdminListView,
    ProductCreateView,
    ProductDeleteAll,
    ProductDetailDelete,
    ProductDetailView,
    ProductPatchView,
    ProductSearchAdminView,
    ProductSearchUserView,
    ProductStatusUpdateView,
    ProductUpdateView,
    ProductUsersListView,
    ProductViewSet,
    ProgramProductsView,
    UsersProductFilterView,
)

router = DefaultRouter()
router.register(r"products", ProductViewSet, basename="products")

urlpatterns = [
    path("create/", ProductCreateView.as_view(), name="create-product"),
    path("admin/all/", ProductAdminListView.as_view(), name="list-products-admin"),
    path("users/all/", ProductUsersListView.as_view(), name="list-products-user"),
    path("<str:product_code>/", ProductDetailView.as_view(), name="product-detail"),
    path(
        "put/<str:product_code>/",
        ProductUpdateView.as_view(),
        name="put-product-detail",
    ),
    path(
        "patch/<str:product_code>/",
        ProductPatchView.as_view(),
        name="update-product-detail",
    ),
    path(
        "delete/<str:product_code>/",
        ProductDetailDelete.as_view(),
        name="delete-product",
    ),
    path("bulk-delete/", ProductDeleteAll.as_view(), name="product_bulk_delete"),
    path(
        "<str:product_code>/status/",
        ProductStatusUpdateView.as_view(),
        name="product-status-update",
    ),
    path("search/admin", ProductSearchAdminView.as_view(), name="product-search-admin"),
    path("search/user", ProductSearchUserView.as_view(), name="product-search-user"),
    path("user_filter", UsersProductFilterView.as_view(), name="user-product-filter"),
    path("admin_filter", AdminProductFilterView.as_view(), name="admin-product-filter"),
    path(
        "<str:program_id>/products",
        ProgramProductsView.as_view(),
        name="program-products",
    ),
] + router.urls
