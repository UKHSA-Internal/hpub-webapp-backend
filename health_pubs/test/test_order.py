import pytest
from unittest import mock
from rest_framework import status
from rest_framework.test import APIClient
from django.urls import reverse
import logging
from core.products.models import Product

logger = logging.getLogger(__name__)

# Mock the Django models
@pytest.fixture
def mock_user():
    user = mock.MagicMock()
    user.user_id = 123
    user.email = "testuser@example.com"
    user.first_name = "Test"
    user.last_name = "User"
    return user


@pytest.fixture
def mock_product():
    product = mock.MagicMock()
    product.product_code = "prod-1"
    product.product_id = "4677686-678888"
    return product


@pytest.fixture
def mock_address():
    address = mock.MagicMock()
    address.address_id = "1"
    return address


@pytest.fixture
def mock_order_data(mock_product, mock_address, mock_user):
    return {
        "order_items": [
            {"product_code": mock_product.product_code, "quantity": 2},
        ],
        "user_info": {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@example.com",
            "mobile_number": "1234567890",
        },
        "address_ref": mock_address.address_id,
        "tracking_number": "TRACK12345",
    }


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_api_client_user(api_client, mock_user):
    # Simulating authentication
    api_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer mock_token_for_{mock_user.user_id}"
    )
    return api_client


# Test class for order-related APIs
@pytest.mark.django_db
class TestOrderViewSet:
    def test_create_order_for_admin_success(
        self, auth_api_client_user, mock_order_data, mock_user
    ):
        """Test creating order for admin (mocked success case)"""
        url = reverse("order-create-for-admin")
        payload = {
            "order_id": "12345",
            "order_items": mock_order_data["order_items"],
            "user_info": mock_order_data["user_info"],
            "user_ref": mock_user.user_id,
            "address_ref": mock_order_data["address_ref"],
            "order_confirmation_number": "CONFIRM123",
            "order_origin": "order_on_behalf",
        }

        with mock.patch("core.orders.views.Order.objects.create") as mock_create_order:
            mock_create_order.return_value.order_id = "12345"
            response = auth_api_client_user.post(url, payload, format="json")

        logger.info(f"Response Data: {response.json()}")
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["order_id"] == payload["order_id"]

    def test_create_order_for_admin_missing_user_data(
        self, auth_api_client_user, mock_order_data
    ):
        """Test creating order with missing user data (mocked failure case)"""
        url = reverse("order-create-for-admin")
        payload = {
            "order_id": "12345",
            "order_items": mock_order_data["order_items"],
            "address_ref": mock_order_data["address_ref"],
            "tracking_number": "TRACK12345",
        }

        response = auth_api_client_user.post(url, payload, format="json")

        logger.info(f"Response Data: {response.json()}")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error_code"] == "USER_REF_REQUIRED"
        assert (
            response.json()["error_message"]
            == "The logged-in user's reference is required."
        )

    def test_create_order_exceeds_limit(
        self, auth_api_client_user, mock_order_data, mock_product
    ):
        """Test order exceeds product limit (mocked failure case)"""
        url = reverse("order-list")

        # Mock the order limit check
        with mock.patch(
            "core.order_limits.views.OrderLimitPage.objects.filter"
        ) as mock_filter:
            mock_filter.return_value.exists.return_value = True
            mock_filter.return_value.first.return_value = mock.MagicMock(order_limit=10)

            payload = {
                "order_id": "12345",
                "order_items": [
                    {
                        "product_code": mock_product.product_code,
                        "quantity": 15,
                    },  # Exceeds limit
                ],
                "user_ref": mock_order_data["user_info"]["email"],
                "address_ref": mock_order_data["address_ref"],
                "tracking_number": "TRACK12345",
            }
            response = auth_api_client_user.post(url, payload, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            response.json()["error_message"] == "Order limit exceeded for this product."
        )

    def test_create_order_invalid_product(self, auth_api_client_user, mock_order_data):
        """Test order with invalid product code (mocked failure case)"""
        url = reverse("order-list")

        payload = {
            "order_id": "12345",
            "order_items": [{"product_code": "INVALID_CODE", "quantity": 2}],
            "user_ref": mock_order_data["user_info"]["email"],
            "address_ref": mock_order_data["address_ref"],
            "tracking_number": "TRACK12345",
            "order_confirmation_number": "CONFM123334",
            "order_origin": "by_user",
        }

        with mock.patch("core.products.views.Product.objects.get") as mock_get_product:
            mock_get_product.side_effect = Product.DoesNotExist
            response = auth_api_client_user.post(url, payload, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error_code"] == "PRODUCT_NOT_LIVE"
        assert (
            response.json()["error_message"]
            == "Product with code INVALID_CODE is not live yet."
        )

    # Further tests can be written in a similar manner...
