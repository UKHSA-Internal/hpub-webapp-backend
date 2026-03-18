import logging
from unittest import mock
import pytest
from rest_framework import status
from rest_framework.test import APIClient
from django.urls import reverse
from core.orders.models import Order, OrderItem
from core.products.models import Product
from core.users.models import User
from core.addresses.models import Address


logger = logging.getLogger(__name__)

# Mocked Fixtures


@pytest.fixture
def mock_data(product, address):
    return {
        "order_items": [
            {"product_code": product[0].product_code, "quantity": 2},
            {"product_code": product[1].product_code, "quantity": 1},
        ],
        "user_info": {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@example.com",
            "mobile_number": "1234567890",
        },
        "address_ref": address.address_id,
        "tracking_number": "TRACK12345",
    }


@pytest.fixture
def auth_api_client_user():
    client = APIClient()
    return client


@pytest.fixture
def auth_api_client_admin():
    client = APIClient()
    return client


@pytest.fixture
def mock_user():
    return mock.MagicMock(
        spec=User, user_id=23, email="testuser@example.com", is_authorized=True
    )


@pytest.fixture
def mock_order():
    return mock.MagicMock(spec=Order, order_id="12345", user_ref=mock_user())


@pytest.fixture
def mock_order_item():
    return mock.MagicMock(
        spec=OrderItem, order_item_id="1", product_ref=mock.MagicMock(spec=Product)
    )


@pytest.fixture
def mock_address():
    return mock.MagicMock(spec=Address, address_id="1", user_ref=mock_user())


@pytest.fixture
def mock_product():
    return mock.MagicMock(spec=Product, product_code="prod-1")


# Unit Tests

from unittest import mock


@mock.patch("core.orders.models.Order.objects.create")
def test_create_order(mock_create_order, mock_data):
    # Mock the return value of create
    mock_create_order.return_value = mock.MagicMock(spec=Order, order_id="12345")
    payload = {
        "order_id": "12345",
        "user_ref": mock_data["user_ref"],
        "order_items": mock_data["order_items"],
    }

    response = auth_api_client_user.post(reverse("order-list"), payload, format="json")
    assert response.status_code == status.HTTP_201_CREATED
    mock_create_order.assert_called_once()


@pytest.mark.parametrize(
    "product_code, quantity, expected_status",
    [
        ("prod-1", 2, status.HTTP_201_CREATED),
        ("prod-2", 1, status.HTTP_201_CREATED),
    ],
)
def test_create_order_success(
    mock_data, mock_user, auth_api_client_user, product_code, quantity, expected_status
):
    url = reverse("order-list")

    payload = {
        "order_id": "12345",
        "order_items": [{"product_code": product_code, "quantity": quantity}],
        "user_ref": mock_user.user_id,
        "address_ref": mock_data["address_ref"],
        "tracking_number": "TRACK12345",
        "order_confirmation_number": "CONFM123334",
        "order_origin": "by_user",
    }

    # Mock the creation of order and its items
    with mock.patch("core.orders.models.Order.objects.create") as mock_create_order:
        with mock.patch(
            "core.orders.models.OrderItem.objects.create"
        ) as mock_create_order_item:
            mock_create_order.return_value = mock_order()
            mock_create_order_item.return_value = mock_order_item()

            response = auth_api_client_user.post(url, payload, format="json")

    assert response.status_code == expected_status
    mock_create_order.assert_called_once_with(
        order_id="12345", user_ref=mock_user.user_id
    )
    mock_create_order_item.assert_called()


def test_create_order_with_missing_data(auth_api_client_user, mock_data, mock_user):
    url = reverse("order-list")

    # Missing user_ref
    payload = {
        "order_id": "12345",
        "order_items": [{"product_code": "prod-1", "quantity": 2}],
        "address_ref": mock_data["address_ref"],
        "tracking_number": "TRACK12345",
        "order_origin": "by_user",
    }

    with mock.patch("core.orders.models.Order.objects.create") as mock_create_order:
        response = auth_api_client_user.post(url, payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    mock_create_order.assert_not_called()


def test_create_order_invalid_product(mock_data, mock_user, auth_api_client_user):
    url = reverse("order-list")

    payload = {
        "order_id": "12345",
        "order_items": [{"product_code": "INVALID_CODE", "quantity": 2}],
        "user_ref": mock_user.user_id,
        "address_ref": mock_data["address_ref"],
        "tracking_number": "TRACK12345",
        "order_origin": "by_user",
    }

    with mock.patch("core.orders.models.Product.objects.get") as mock_get_product:
        mock_get_product.side_effect = Product.DoesNotExist
        response = auth_api_client_user.post(url, payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert (
        response.json()["error_message"]
        == "Product with code INVALID_CODE is not live yet."
    )


def test_migrate_orders_success(
    auth_api_client_user,
    mock_order,
    mock_order_item,
    orders_excel_file,
    order_items_excel_file,
):
    url = reverse("migrate_orders")

    with mock.patch("core.orders.models.Order.objects.create") as mock_create_order:
        with mock.patch(
            "core.orders.models.OrderItem.objects.create"
        ) as mock_create_order_item:
            mock_create_order.return_value = mock_order
            mock_create_order_item.return_value = mock_order_item

            response = auth_api_client_user.post(
                url,
                data={
                    "orders_excel": orders_excel_file,
                    "order_items_excel": order_items_excel_file,
                },
            )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["message"] == "Migration completed successfully."
    mock_create_order.assert_called()
    mock_create_order_item.assert_called()


def test_migrate_orders_missing_files(auth_api_client_user):
    url = reverse("migrate_orders")
    response = auth_api_client_user.post(url, data={})

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["error"] == "Both orders and order items files are required."
