from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    IncompleteProductsView,
    ProductAdminFilterView,
    ProductAdminListView,
    ProductCreateView,
    ProductDeleteAll,
    ProductDetailDelete,
    ProductDetailView,
    ProductDownloadUrlsView,
    ProductPatchView,
    ProductSearchAdminView,
    ProductSearchUserView,
    ProductStatusUpdateView,
    ProductUpdateView,
    ProductUsersListView,
    ProductUsersSearchFilterAPIView,
    ProductUsersFilterView,
    ProgramProductsView,
    ProductViewSet,
    ProductAutocompleteView,
    ProductCheckExistingView,
)

router = DefaultRouter()
router.register(r"products", ProductViewSet, basename="products")

urlpatterns = [
    path("", include(router.urls)),
    path(
        "incomplete-products/",
        IncompleteProductsView.as_view(),
        name="incomplete-products",
    ),
    path("create/", ProductCreateView.as_view(), name="create-product"),
    path("bulk-delete/", ProductDeleteAll.as_view(), name="product-bulk-delete"),
    path("admin/all/", ProductAdminListView.as_view(), name="list-products-admin"),
    path("users/all/", ProductUsersListView.as_view(), name="list-products-user"),
    path(
        "search/admin/check-existing/",
        ProductCheckExistingView.as_view(),
        name="check-existing",
    ),
    path(
        "search/admin/", ProductSearchAdminView.as_view(), name="product-search-admin"
    ),
    path("search/user/", ProductSearchUserView.as_view(), name="product-search-user"),
    path(
        "search/autocomplete/",
        ProductAutocompleteView.as_view(),
        name="product-autocomplete",
    ),
    path("user_filter/", ProductUsersFilterView.as_view(), name="user-product-filter"),
    path(
        "admin_filter/", ProductAdminFilterView.as_view(), name="admin-product-filter"
    ),
    path(
        "user/search/filter/",
        ProductUsersSearchFilterAPIView.as_view(),
        name="product-search",
    ),
    path(
        "<str:program_id>/products/",
        ProgramProductsView.as_view(),
        name="program-products",
    ),
    # 3) Legacy “catch-all” detail routes at the very end
    path(
        "<str:product_code>/",
        ProductDetailView.as_view({"get": "retrieve"}),
        name="product-detail",
    ),
    path(
        "<str:product_code>/download-urls/",
        ProductDownloadUrlsView.as_view({"get": "retrieve"}),
        name="product-download-urls",
    ),
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
    path(
        "<str:product_code>/status/",
        ProductStatusUpdateView.as_view(),
        name="product-status-update",
    ),
] + router.urls
