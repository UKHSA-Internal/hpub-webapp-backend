import io
import json
import logging

import pandas as pd
from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from unittest.mock import MagicMock, patch

# Import the views and serializers you want to test.
# (Adjust the import paths to match your project.)
from core.products.views import (
    ProductViewSet,
    ProductStatusUpdateView,
    AdminProductFilterView,
    ProductSearchUserView,
    ProductUpdateView,
    ProductDeleteAll,
    ProductDetailView,
)
from core.errors.enums import ErrorMessage

logger = logging.getLogger(__name__)

# --- Dummy Classes and Helpers for Unit Testing ---


class DummyProductUpdate:
    def __init__(self, downloads):
        self._downloads = downloads

    @property
    def product_downloads(self):
        return self._downloads


class DummyProduct:
    def __init__(self, product_code, product_title, update_ref=None):
        self.product_code = product_code
        self.product_title = product_title
        self.update_ref = update_ref


class DummyProductSerializer:
    def __init__(self, instance, many=False):
        self.instance = instance
        self.many = many

    @property
    def data(self):
        if self.many:
            return [self._serialize(item) for item in self.instance]
        else:
            return self._serialize(self.instance)

    def _serialize(self, obj):
        return {
            "product_code": obj.product_code,
            "product_title": obj.product_title,
            "update_ref": {
                "product_downloads": obj.update_ref.product_downloads
                if obj.update_ref
                else {}
            },
        }


# Dummy pagination that simply returns all items.
class DummyPagination:
    def paginate_queryset(self, queryset, request):
        return list(queryset)

    def get_paginated_response(self, data, status_code=status.HTTP_200_OK):
        return Response({"results": data, "count": len(data)}, status=status_code)


# Dummy URL constants
DUMMY_BULK_UPLOAD_URL = "/dummy/bulk-upload/"
DUMMY_PRODUCT_DETAIL_URL = "/dummy/product-detail/"
DUMMY_PRODUCT_DELETE_ALL_URL = "/dummy/product-delete-all/"
DUMMY_PRODUCT_STATUS_UPDATE_URL = "/dummy/product-status-update/P-001/"
DUMMY_ADMIN_PRODUCT_FILTER_URL = "/dummy/admin-product-filter/"
DUMMY_PRODUCT_SEARCH_USER_URL = "/dummy/product-search-user/"
DUMMY_PRODUCT_UPDATE_URL = "/dummy/update-product-detail/P-001/"
DUMMY_PRODUCT_CREATE_URL = "/dummy/create-product/"

# Dummy context manager to replace transaction.atomic
class DummyContextManager:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


def dummy_response(data, status_code):
    return Response(data, status=status_code)


def get_dummy_user(is_admin=False):
    dummy = MagicMock()
    dummy.is_authenticated = True
    dummy._state = MagicMock(db="default")
    if is_admin:
        dummy.user_id = "admin-1"
        dummy.email = "admin@example.com"
        dummy.is_staff = True
    else:
        dummy.user_id = "user-1"
        dummy.email = "user@example.com"
        dummy.is_staff = False
    dummy.establishment_ref = MagicMock(full_external_key="ext-key")
    return dummy


# A dummy renderer for DRF responses that provides the necessary attributes.
class DummyRenderer:
    media_type = "application/json"
    format = "json"
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return json.dumps(data)


# --- Unit Test Cases ---


# ----- Test: Bulk Upload Success -----
@patch("core.products.views.pd.read_excel")
@patch("core.products.views.Product.objects.filter")
@patch("core.products.views.Page.objects.get")
@patch(
    "core.products.views.generate_presigned_urls",
    side_effect=lambda urls: {url: f"{url}?sig=dummy" for url in urls},
)
@patch(
    "core.products.views.get_file_metadata",
    side_effect=lambda urls: [
        {"URL": url, "file_size": "dummy", "file_type": "dummy"} for url in urls
    ],
)
@patch(
    "core.products.views.ProductSerializer",
    new=lambda instance, many=False: DummyProductSerializer(instance, many=many),
)
@patch("django.db.transaction.atomic", return_value=DummyContextManager())
def test_bulk_upload_success(
    mock_atomic,
    mock_get_file_metadata,
    mock_generate_presigned,
    mock_page_get,
    mock_product_filter,
    mock_read_excel,
):
    factory = APIRequestFactory()
    url = DUMMY_BULK_UPLOAD_URL

    # Create a dummy DataFrame that the view will process.
    df = pd.DataFrame(
        {
            "product_id": ["101"],
            "title": ["Bulk Product"],
            "language_id": ["1"],
            "gov_related_article": ["https://example.com/article"],
            "status": ["draft"],
            "product_code": ["P-101"],
            "tag": ["download-only"],
            "created": ["01/01/2024 12:00:00"],
            "programme_id": ["2"],
        }
    )
    mock_read_excel.return_value = df

    dummy_parent = MagicMock()
    # Patch save_revision().publish() chain with a dummy that does nothing.
    dummy_publish = MagicMock(return_value=None)
    dummy_parent.save_revision.return_value.publish = dummy_publish
    mock_page_get.return_value = dummy_parent

    dummy_qs = MagicMock()
    dummy_qs.exists.return_value = False
    mock_product_filter.return_value = dummy_qs

    request = factory.post(
        url, {"product_excel": io.BytesIO(b"dummy excel")}, format="multipart"
    )
    force_authenticate(request, user=get_dummy_user(is_admin=True))
    with patch.object(ProductViewSet, "permission_classes", []):
        view = ProductViewSet.as_view({"post": "bulk_upload"})
        response = view(request)
    print("BULK UPLOAD RESPONSE:", response.data)
    assert response.status_code == status.HTTP_201_CREATED


# ----- Test: Product Detail View Success -----
@patch("core.products.views.Product.objects.filter")
@patch(
    "core.products.views.ProductSerializer",
    new=lambda instance, many=False: DummyProductSerializer(instance, many=many),
)
def test_product_detail_view_success(mock_filter):
    factory = APIRequestFactory()
    url = DUMMY_PRODUCT_DETAIL_URL

    # Create a dummy update with a downloads dictionary.
    dummy_update = DummyProductUpdate(
        downloads={
            "main_download_url": {"s3_bucket_url": "https://example.com/file.png"}
        }
    )
    # Create a dummy product with the dummy update.
    dummy_product = DummyProduct("P-001", "Test Product", update_ref=dummy_update)
    # Create a dummy QuerySet that returns our dummy product.
    dummy_qs = MagicMock()
    dummy_qs.first.return_value = dummy_product
    mock_filter.return_value = dummy_qs

    request = factory.get(url)
    force_authenticate(request, user=get_dummy_user())
    with patch.object(ProductDetailView, "permission_classes", []):
        view = ProductDetailView.as_view()
        response = view(request, product_code="P-001")
    data = json.loads(response.content.decode("utf-8"))
    print("PRODUCT DETAIL RESPONSE:", data)
    assert response.status_code == status.HTTP_200_OK


# ----- Test: Product Status Update Success -----
@patch("core.products.models.Product.objects.filter")
def test_product_status_update_success(mock_filter):
    factory = APIRequestFactory()
    url = DUMMY_PRODUCT_STATUS_UPDATE_URL
    payload = {"status": "live"}
    request = factory.put(
        url, data=json.dumps(payload), content_type="application/json"
    )

    dummy_product = MagicMock()
    dummy_product.product_code = "P-001"
    dummy_product.status = "draft"
    dummy_qs = MagicMock()
    dummy_qs.order_by.return_value.first.return_value = dummy_product
    mock_filter.return_value = dummy_qs

    force_authenticate(request, user=get_dummy_user(is_admin=True))
    with patch.object(ProductStatusUpdateView, "permission_classes", []), patch.object(
        ProductStatusUpdateView,
        "handle_error",
        side_effect=lambda err, msg, status_code: Response(
            {"error_message": msg}, status=status_code
        ),
    ):
        view = ProductStatusUpdateView.as_view()
        response = view(request, product_code="P-001")
    data = json.loads(response.content.decode("utf-8"))
    print("PRODUCT STATUS UPDATE RESPONSE:", data)
    assert response.status_code == status.HTTP_200_OK


# ----- Test: Admin Product Filter View Success -----
@patch("core.products.views.Product.objects.filter")
def test_admin_product_filter_success(mock_filter):
    factory = APIRequestFactory()
    url = DUMMY_ADMIN_PRODUCT_FILTER_URL

    dummy_product = MagicMock()
    dummy_product.product_id = "P-001"
    dummy_product.product_title = "Product 1"
    dummy_qs = MagicMock()
    dummy_qs.exists.return_value = True
    dummy_qs.order_by.return_value = [dummy_product]
    mock_filter.return_value = dummy_qs

    request = factory.get(url, {"product_title": "Product"})
    force_authenticate(request, user=get_dummy_user(is_admin=True))
    with patch.object(AdminProductFilterView, "permission_classes", []), patch.object(
        AdminProductFilterView,
        "_collect_download_urls",
        return_value=["https://example.com/file.png"],
    ), patch.object(
        AdminProductFilterView,
        "_update_product_downloads_with_presigned_urls",
        return_value=None,
    ), patch(
        "core.products.views.ProductSerializer",
        new=lambda instance, many=False: DummyProductSerializer(instance, many=many),
    ), patch.object(
        AdminProductFilterView, "pagination_class", DummyPagination
    ):
        view = AdminProductFilterView.as_view()
        response = view(request)
    print("ADMIN PRODUCT FILTER RESPONSE:", response.data)
    assert response.status_code == status.HTTP_200_OK


# ----- Test: Product Search User View Success -----
@patch("core.products.views.Product.objects.filter")
def test_product_search_user_success(mock_filter):
    factory = APIRequestFactory()
    url = DUMMY_PRODUCT_SEARCH_USER_URL

    dummy_product = MagicMock()
    dummy_product.product_id = "P-002"
    dummy_product.product_title = "Product 2"
    dummy_qs = MagicMock()
    dummy_qs.exists.return_value = True
    dummy_qs.order_by.return_value = [dummy_product]
    mock_filter.return_value = dummy_qs

    request = factory.get(url, {"product_code": "P-002"})
    force_authenticate(request, user=get_dummy_user())
    with patch.object(ProductSearchUserView, "permission_classes", []), patch.object(
        ProductSearchUserView,
        "_collect_download_urls",
        return_value=["https://example.com/file2.png"],
    ), patch.object(
        ProductSearchUserView,
        "_update_product_downloads_with_presigned_urls",
        return_value=None,
    ), patch(
        "core.products.views.ProductSerializer",
        new=lambda instance, many=False: DummyProductSerializer(instance, many=many),
    ), patch.object(
        ProductSearchUserView, "pagination_class", DummyPagination
    ):
        view = ProductSearchUserView.as_view()
        response = view(request)
    print("PRODUCT SEARCH USER RESPONSE:", response.data)
    assert response.status_code == status.HTTP_200_OK


# ----- Test: Product Update View Success -----
@patch("core.products.views.Product.objects.filter")
@patch("core.products.views.ProductSerializer")
def test_product_update_view_success(mock_serializer_class, mock_filter):
    factory = APIRequestFactory()
    url = DUMMY_PRODUCT_UPDATE_URL
    update_data = {"product_title": "Updated Product Title"}
    request = factory.put(
        url, data=json.dumps(update_data), content_type="application/json"
    )

    dummy_product = MagicMock()
    dummy_product.product_code = "P-001"
    dummy_product.product_title = "Old Title"
    dummy_qs = MagicMock()
    dummy_qs.order_by.return_value.first.return_value = dummy_product
    mock_filter.return_value = dummy_qs

    dummy_serializer = MagicMock()
    dummy_serializer.is_valid.return_value = True
    dummy_serializer.save.return_value = dummy_product
    dummy_serializer.data = {"product_title": "Updated Product Title"}
    mock_serializer_class.return_value = dummy_serializer

    force_authenticate(request, user=get_dummy_user(is_admin=True))
    with patch.object(ProductUpdateView, "permission_classes", []):
        view = ProductUpdateView.as_view()
        response = view(request, product_code="P-001")
    data = json.loads(response.content.decode("utf-8"))
    print("PRODUCT UPDATE VIEW RESPONSE:", data)
    assert response.status_code == status.HTTP_200_OK
    assert data["product_title"] == "Updated Product Title"


# ----- Test: Product Delete All Success -----
@patch("core.products.views.Product.objects.all")
@patch("core.products.views.ProductUpdate.objects.all")
def test_product_delete_all_success(mock_product_all, mock_productupdate_all):
    # Simulate that calling delete() returns a tuple (number_deleted, details)
    mock_product_all.return_value.delete.return_value = (1, {"core.Product": 1})
    mock_productupdate_all.return_value.delete.return_value = (
        1,
        {"core.ProductUpdate": 1},
    )
    factory = APIRequestFactory()
    url = DUMMY_PRODUCT_DELETE_ALL_URL
    request = factory.delete(url)
    view = ProductDeleteAll.as_view()
    response = view(request)
    data = json.loads(response.content.decode("utf-8"))
    print("PRODUCT DELETE ALL RESPONSE:", data)
    assert response.status_code == status.HTTP_204_NO_CONTENT


# ----- Test: Product Status Update Database Error -----
@patch("core.products.models.Product.objects.filter")
def test_product_status_update_database_error(mock_filter):
    # Simulate a database error during the product query.
    mock_filter.side_effect = Exception("Database error occurred.")
    factory = APIRequestFactory()
    url = DUMMY_PRODUCT_STATUS_UPDATE_URL
    payload = {"status": "live"}
    request = factory.put(
        url, data=json.dumps(payload), content_type="application/json"
    )
    force_authenticate(request, user=get_dummy_user(is_admin=True))

    with patch.object(ProductStatusUpdateView, "permission_classes", []), patch.object(
        ProductStatusUpdateView,
        "handle_error",
        side_effect=lambda err, msg, status_code: Response(
            {"error_message": str(msg)}, status=status_code
        ),
    ):
        view = ProductStatusUpdateView.as_view()
        response = view(request, product_code="P-001")
    response.accepted_renderer = DummyRenderer()
    response.accepted_media_type = "application/json"
    response.renderer_context = {}
    response.render()
    data = json.loads(response.content.decode("utf-8"))
    print("PRODUCT STATUS UPDATE DATABASE ERROR RESPONSE:", data)
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    expected_error = str(ErrorMessage.INTERNAL_SERVER_ERROR.value)
    assert data["error_message"] == expected_error
