import uuid
import json
from unittest.mock import MagicMock, patch, DEFAULT
from django.urls import reverse
from rest_framework import status
import pandas as pd
from django.core.files.uploadedfile import SimpleUploadedFile
from core.users.models import User
from rest_framework.test import APIClient
from django.contrib.auth.models import User


# ========================
# Admin user test (create_for_admin)
# ========================
@patch("core.orders.views.Product.objects.get")
@patch(
    "core.orders.views.OrderSerializer",
    return_value=MagicMock(data={"order_id": "order-1"}),
)
@patch(
    "core.users.permissions.IsAdminOrRegisteredUser.has_permission",
    return_value=True,
)
@patch("rest_framework.permissions.IsAuthenticated.has_permission", return_value=True)
@patch("core.utils.custom_token_authentication.CustomTokenAuthentication.authenticate")
@patch("core.addresses.models.Address.objects.get")
@patch("django.db.transaction.atomic")
def test_create_for_admin_success(
    mock_transaction_atomic,
    mock_address_get,
    mock_authenticate,
    mock_is_authenticated,
    mock_is_admin_or_registered,
    mock_order_serializer,  # patched OrderSerializer
    mock_product_get,
    client,
):
    """
    Test the create_for_admin action of OrderViewSet for an admin user.
    All DB access and heavy operations are patched.
    """
    # Group a set of patches for methods on OrderViewSet into one context.
    with patch.multiple(
        "core.orders.views.OrderViewSet",
        get_unique_slug=DEFAULT,
        _validate_order_limits=DEFAULT,
        _get_or_create_user=DEFAULT,
        _get_existing_user=DEFAULT,
        _get_or_create_parent_page=DEFAULT,
        _create_order_instance=DEFAULT,
        _create_order_items=DEFAULT,
        _update_product_quantities=DEFAULT,
        _send_order_confirmation=DEFAULT,
    ) as mocks:
        # Assign the grouped mocks to local names for clarity.
        mock_get_unique_slug = mocks["get_unique_slug"]
        mock_validate_order_limits = mocks["_validate_order_limits"]
        mock_get_or_create_user = mocks["_get_or_create_user"]
        mock_get_existing_user = mocks["_get_existing_user"]
        mock_get_or_create_parent_page = mocks["_get_or_create_parent_page"]
        mock_create_order_instance = mocks["_create_order_instance"]
        mock_create_order_items = mocks["_create_order_items"]
        mock_update_product_quantities = mocks["_update_product_quantities"]
        mock_send_order_confirmation = mocks["_send_order_confirmation"]

        # --- Set up dummy objects simulating real instances ---
        dummy_parent_page = MagicMock(name="ParentPage")

        dummy_delivery_user = MagicMock(name="DeliveryUser")
        dummy_delivery_user.user_id = "67890"
        dummy_delivery_user.email = "delivery@test.com"
        dummy_delivery_user._state = MagicMock(db="default")

        dummy_admin_user = MagicMock(name="AdminUser")
        dummy_admin_user.user_id = "12345"
        dummy_admin_user.email = "admin@test.com"
        # Simulate an establishment with a full_external_key:
        dummy_establishment = MagicMock(full_external_key="ext-key")
        dummy_admin_user.establishment_ref = dummy_establishment
        dummy_admin_user._state = MagicMock(db="default")

        dummy_address = MagicMock(name="Address")
        dummy_address.address_id = "addr-1"
        dummy_address.city = "Test City"
        dummy_address._state = MagicMock(db="default")

        dummy_order = MagicMock(name="Order")
        dummy_order.order_id = "order-1"
        dummy_order._state = MagicMock(db="default")

        dummy_product = MagicMock(name="Product")
        dummy_product.product_code = "prod-1"
        dummy_product._state = MagicMock(db="default")

        # --- Configure grouped patch return values ---
        mock_get_or_create_parent_page.return_value = dummy_parent_page
        mock_get_or_create_user.return_value = dummy_delivery_user
        mock_get_existing_user.return_value = dummy_admin_user
        mock_get_unique_slug.return_value = "order-unique-slug"
        mock_validate_order_limits.return_value = True
        mock_transaction_atomic.return_value.__enter__.return_value = None
        mock_transaction_atomic.return_value.__exit__.return_value = None
        mock_create_order_instance.return_value = dummy_order

        # --- Configure remaining patched return values ---
        mock_address_get.return_value = dummy_address
        mock_authenticate.return_value = (dummy_admin_user, None)
        mock_product_get.return_value = dummy_product

        # --- Patch Order.save, refresh_from_db, and ContentType lookup to avoid DB access ---
        with (
            patch("core.orders.models.Order.save", lambda self: None),
            patch("core.orders.models.Order.refresh_from_db", lambda self: None),
            patch(
                "django.contrib.contenttypes.models.ContentType.objects.get_for_model",
                return_value=MagicMock(_state=MagicMock(db="default")),
            ),
        ):
            # --- Prepare payload ---
            payload = {
                "order_items": [{"product_code": "prod-1", "quantity": 1}],
                "user_ref": "12345",
                "user_info": {
                    "email": "testuser@example.com",
                    "first_name": "Test",
                    "last_name": "User",
                },
                "address_ref": "addr-1",
                "order_origin": "online",
            }

            url = reverse("order-create-for-admin")
            response = client.post(
                url,
                data=json.dumps(payload),
                content_type="application/json",
                HTTP_AUTHORIZATION="Token testtoken",
            )

            print("ADMIN RESPONSE:", response.json())
            assert response.status_code == status.HTTP_201_CREATED, response.json()
            assert response.json().get("order_id") == "order-1"

            # --- Verify that patched functions were called with expected arguments ---
            mock_authenticate.assert_called_once()
            mock_is_authenticated.assert_called_once()
            mock_is_admin_or_registered.assert_called_once()
            mock_address_get.assert_called_once_with(address_id="addr-1")
            mock_get_or_create_parent_page.assert_called_once()
            mock_get_or_create_user.assert_called_once_with(
                {
                    "email": "testuser@example.com",
                    "first_name": "Test",
                    "last_name": "User",
                },
                dummy_parent_page,
            )
            mock_get_existing_user.assert_called_once_with("12345")
            mock_validate_order_limits.assert_called_once_with(
                [{"product_code": "prod-1", "quantity": 1}], dummy_admin_user
            )
            # Note: get_unique_slug may not be called in this flow.
            mock_create_order_instance.assert_called_once()
            mock_create_order_items.assert_called_once_with(
                [{"product_code": "prod-1", "quantity": 1}],
                dummy_order,
                dummy_parent_page,
                dummy_delivery_user,
            )
            mock_update_product_quantities.assert_called_once_with(
                [{"product_code": "prod-1", "quantity": 1}]
            )
            mock_send_order_confirmation.assert_called_once_with(dummy_order)
            mock_transaction_atomic.assert_called_once()


@patch(
    "core.orders.views.OrderSerializer",
    return_value=MagicMock(data={"order_id": "order-2"}),
)
@patch("core.orders.views.OrderViewSet._is_product_live", return_value=True)
@patch("core.orders.views.OrderViewSet._get_or_create_parent_page_or_error")
@patch("core.orders.views.OrderViewSet._get_user_or_error")
@patch("core.orders.views.OrderViewSet._validate_order_limits", return_value=True)
@patch("core.addresses.models.Address.objects.get")
@patch("django.db.transaction.atomic")
@patch("core.orders.views.OrderViewSet._create_order_instance")
@patch("core.orders.views.OrderViewSet._create_order_items")
@patch("core.orders.views.OrderViewSet._update_product_quantities")
@patch("core.orders.views.OrderViewSet._send_order_confirmation")
def test_create_for_regular_user_success(
    mock_send_order_confirmation,
    mock_update_product_quantities,
    mock_create_order_items,
    mock_create_order_instance,
    mock_transaction_atomic,
    mock_address_get,
    mock_validate_order_limits,
    mock_get_user_or_error,
    mock_get_or_create_parent_page_or_error,
    mock_is_product_live,
    mock_order_serializer,
):
    """
    Test the normal create (non-admin) action of OrderViewSet.
    This test patches all DB operations so that no real DB access occurs.
    """

    # Create an APIClient instance and force authentication with a dummy user.
    client = APIClient()

    # --- Set up dummy objects simulating real instances ---
    dummy_parent_page = MagicMock(name="ParentPage")

    # Create a dummy user using Django's User model (or your custom user model)
    dummy_user = User(username="regular", email="user@test.com")
    dummy_user.id = 54321
    # Remove the line setting is_authenticated, since User instances already return True.
    # dummy_user.is_authenticated = True  # Remove or comment out this line.

    # Add a dummy role to satisfy permission requirements.
    dummy_role = MagicMock(name="Role")
    dummy_role.name = "User"
    dummy_user.role_ref = dummy_role

    # Simulate an establishment with full_external_key:
    dummy_establishment = MagicMock(full_external_key="ext-key-user")
    dummy_user.establishment_ref = dummy_establishment

    # Force authentication for the APIClient so that the request is treated as logged in.
    client.force_authenticate(user=dummy_user)

    dummy_address = MagicMock(name="Address")
    dummy_address.address_id = "addr-2"
    dummy_address.city = "User City"

    dummy_order = MagicMock(name="Order")
    dummy_order.order_id = "order-2"

    # --- Configure patched return values ---
    mock_get_or_create_parent_page_or_error.return_value = dummy_parent_page
    mock_get_user_or_error.return_value = dummy_user
    mock_validate_order_limits.return_value = True
    # Simulate entering and exiting the atomic block:
    mock_transaction_atomic.return_value.__enter__.return_value = None
    mock_transaction_atomic.return_value.__exit__.return_value = None
    mock_address_get.return_value = dummy_address
    mock_create_order_instance.return_value = dummy_order

    # --- Patch Order.save, Order.refresh_from_db, and ContentType lookup to avoid DB access ---
    with (
        patch("core.orders.models.Order.save", lambda self: None),
        patch("core.orders.models.Order.refresh_from_db", lambda self: None),
        patch(
            "django.contrib.contenttypes.models.ContentType.objects.get_for_model",
            return_value=MagicMock(),
        ),
    ):
        # --- Prepare payload ---
        payload = {
            "order_items": [{"product_code": "prod-2", "quantity": 2}],
            "user_ref": "54321",
            "user_info": {
                "email": "user@test.com",
                "first_name": "Regular",
                "last_name": "User",
            },
            "address_ref": "addr-2",
            "order_origin": "mobile",
        }

        url = reverse(
            "order-list"
        )  # Assuming the normal create is available at the list endpoint (POST)
        response = client.post(
            url, data=json.dumps(payload), content_type="application/json"
        )

        print("REGULAR USER RESPONSE:", response.json())
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json().get("order_id") == "order-2"

        # --- Verify that patched functions were called with expected arguments ---
        mock_is_product_live.assert_called_with("prod-2")
        mock_get_or_create_parent_page_or_error.assert_called_once()
        mock_get_user_or_error.assert_called_once_with("54321")
        mock_validate_order_limits.assert_called_once_with(
            [{"product_code": "prod-2", "quantity": 2}], dummy_user
        )
        mock_create_order_instance.assert_called_once()
        mock_create_order_items.assert_called_once_with(
            [{"product_code": "prod-2", "quantity": 2}],
            dummy_order,
            dummy_parent_page,
            dummy_user,
        )
        mock_update_product_quantities.assert_called_once_with(
            [{"product_code": "prod-2", "quantity": 2}]
        )
        mock_send_order_confirmation.assert_called_once_with(dummy_order)
        mock_transaction_atomic.assert_called_once()


# ============================================
# Test for get_all_orders action
# ============================================
@patch("core.orders.views.Order.objects.all")
@patch("core.orders.views.OrderViewSet.get_serializer")
def test_get_all_orders_success(mock_get_serializer, mock_orders_all):
    """
    Test the get_all_orders action returns all orders.
    """
    client = APIClient()

    # Set up dummy user and force authentication
    dummy_user = User(username="regular", email="user@test.com")
    dummy_user.id = 54321
    # Add a dummy role and establishment to satisfy permission & view requirements.
    dummy_role = MagicMock(name="Role")
    dummy_role.name = "User"
    dummy_user.role_ref = dummy_role
    dummy_establishment = MagicMock(full_external_key="ext-key-user")
    dummy_user.establishment_ref = dummy_establishment
    client.force_authenticate(user=dummy_user)

    # Prepare dummy orders and serializer return data.
    dummy_order = MagicMock()
    dummy_order.id = 1
    dummy_order.order_id = "order-1"
    dummy_orders = [dummy_order]
    mock_orders_all.return_value = dummy_orders

    dummy_serializer = MagicMock()
    dummy_serializer.data = [{"order_id": "order-1"}]
    mock_get_serializer.return_value = dummy_serializer

    # The URL name below should match what you have in your router for get-all-orders.
    url = reverse("order-get-all-orders")
    response = client.get(url)

    print("GET ALL ORDERS RESPONSE:", response.json())
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == [{"order_id": "order-1"}]


# ============================================
# Test for update endpoint
# ============================================
@patch("core.orders.views.OrderViewSet.get_queryset")
@patch("core.orders.views.OrderViewSet.get_serializer")
def test_update_order_success(mock_get_serializer, mock_get_queryset):
    """
    Test updating an order returns a 200 with the updated data.
    """
    client = APIClient()

    # Set up dummy user and force authentication
    dummy_user = User(username="regular", email="user@test.com")
    dummy_user.id = 54321
    dummy_role = MagicMock(name="Role")
    dummy_role.name = "User"
    dummy_user.role_ref = dummy_role
    dummy_establishment = MagicMock(full_external_key="ext-key-user")
    dummy_user.establishment_ref = dummy_establishment
    client.force_authenticate(user=dummy_user)

    # Create a dummy order instance that the view will find.
    dummy_order = MagicMock()
    dummy_order.order_id = "order-1"
    dummy_order.id = 1
    # Simulate get_queryset().filter(...).first() returning the dummy_order.
    queryset = MagicMock()
    queryset.filter.return_value.first.return_value = dummy_order
    mock_get_queryset.return_value = queryset

    # Prepare the serializer to simulate a successful update.
    dummy_serializer = MagicMock()
    dummy_serializer.data = {
        "order_id": "order-1",
        "order_origin": "web",
        "updated": True,
    }
    dummy_serializer.is_valid.return_value = True
    # When save() is called, nothing needs to happen (the dummy order is updated)
    dummy_serializer.save.return_value = None
    mock_get_serializer.return_value = dummy_serializer

    url = reverse(
        "order-detail", args=["order-1"]
    )  # URL should be configured with the detail view name.
    payload = {"order_origin": "web"}
    response = client.patch(
        url, data=json.dumps(payload), content_type="application/json"
    )

    print("UPDATE ORDER RESPONSE:", response.json())
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "order_id": "order-1",
        "order_origin": "web",
        "updated": True,
    }
    dummy_serializer.is_valid.assert_called_once()
    dummy_serializer.save.assert_called_once()


# ============================================
# Test for destroy endpoint
# ============================================
@patch("core.orders.views.OrderViewSet.get_object")
@patch("core.orders.views.OrderViewSet.perform_destroy")
def test_destroy_order_success(mock_perform_destroy, mock_get_object):
    """
    Test that destroying an order returns a 204 and calls perform_destroy.
    """
    client = APIClient()

    # Set up dummy user and force authentication
    dummy_user = User(username="regular", email="user@test.com")
    dummy_user.id = 54321
    dummy_role = MagicMock(name="Role")
    dummy_role.name = "User"
    dummy_user.role_ref = dummy_role
    dummy_establishment = MagicMock(full_external_key="ext-key-user")
    dummy_user.establishment_ref = dummy_establishment
    client.force_authenticate(user=dummy_user)

    # Set up a dummy order instance to be returned by get_object()
    dummy_order = MagicMock()
    dummy_order.id = 1
    dummy_order.order_id = "order-1"
    mock_get_object.return_value = dummy_order

    url = reverse("order-detail", args=["order-1"])  # Detail URL for deletion.
    response = client.delete(url)

    print("DESTROY ORDER RESPONSE STATUS:", response.status_code)
    assert response.status_code == status.HTTP_204_NO_CONTENT
    mock_perform_destroy.assert_called_once_with(dummy_order)


# Test for the MigrateOrdersAPIView
@patch("core.orders.views.pd.read_excel")
@patch("core.orders.views.MigrateOrdersAPIView.get_or_create_parent_page")
@patch("core.orders.views.MigrateOrdersAPIView._get_user_ref")
@patch("core.orders.views.MigrateOrdersAPIView._get_or_create_address_ref")
@patch("core.orders.views.MigrateOrdersAPIView._create_order_instance")
@patch("core.orders.views.MigrateOrdersAPIView._get_order_ref")
@patch("core.orders.views.MigrateOrdersAPIView._get_product_ref")
@patch("core.orders.views.MigrateOrdersAPIView._create_order_item_instance")
def test_migrate_orders_success(
    mock_create_order_item_instance,
    mock_get_product_ref,
    mock_get_order_ref,
    mock_create_order_instance,
    mock_get_or_create_address_ref,
    mock_get_user_ref,
    mock_get_or_create_parent_page,
    mock_read_excel,
):
    """
    Test that posting valid Excel files to the migration endpoint
    returns a 200 response with a success message.
    """
    # --- Prepare dummy DataFrames for orders and order items ---
    orders_data = {
        "order_id": ["orig_order_1"],
        "order_date": ["01/01/2021 12:00"],
        "user_id": [123],
        "order_origin": ["web"],
        "shipping_address_line_1": ["123 Street"],
        "shipping_address_line_2": [""],
        "shipping_address_line_3": [""],
        "shipping_address_city": ["City"],
        "shipping_address_postcode": ["12345"],
        "shipping_address_country": ["Country"],
        "shipping_address_county": ["County"],
        "tracking_number": [""],
    }
    orders_df = pd.DataFrame(orders_data)

    order_items_data = {
        "order_item_id": ["item1"],
        "order_id": ["orig_order_1"],
        "ProductCode": ["prod1"],
        "order_line_quantity": [2],
        "quantity_inprogress": [0],
        "quantity_shipped": [0],
        "quantity_cancelled": [0],
    }
    order_items_df = pd.DataFrame(order_items_data)

    # When pd.read_excel is called, first return orders_df then order_items_df.
    mock_read_excel.side_effect = [orders_df, order_items_df]

    # --- Patch view helper methods ---
    # Simulate get_or_create_parent_page returning different dummy parent pages based on slug.
    dummy_address_parent_page = MagicMock(name="AddressParentPage")
    dummy_order_parent_page = MagicMock(name="OrderParentPage")

    def side_effect_get_or_create_parent_page(slug, title):
        if slug == "addresses":
            return dummy_address_parent_page
        elif slug == "orders":
            return dummy_order_parent_page

    mock_get_or_create_parent_page.side_effect = side_effect_get_or_create_parent_page

    # _get_user_ref returns a dummy user (simulate user exists)
    dummy_user = User(username="dummy", email="dummy@example.com")
    # Assume your user model has a 'user_id' attribute.
    dummy_user.user_id = 123
    mock_get_user_ref.return_value = dummy_user

    # _get_or_create_address_ref returns a list containing a dummy address instance.
    dummy_address = MagicMock(name="AddressInstance")
    mock_get_or_create_address_ref.return_value = [dummy_address]

    # _create_order_instance: simulate order creation.
    dummy_order_instance = MagicMock(name="OrderInstance")
    # For example, assign a new order_id (simulate generated order)
    dummy_order_instance.order_id = str(uuid.uuid4())
    mock_create_order_instance.return_value = dummy_order_instance

    # _get_order_ref returns the same dummy order instance.
    mock_get_order_ref.return_value = dummy_order_instance

    # _get_product_ref returns a dummy product instance.
    dummy_product = MagicMock(name="ProductInstance")
    mock_get_product_ref.return_value = dummy_product

    # _create_order_item_instance returns a dummy order item.
    dummy_order_item = MagicMock(name="OrderItemInstance")
    mock_create_order_item_instance.return_value = dummy_order_item

    # --- Create dummy uploaded files ---
    orders_content = b"dummy orders excel content"
    order_items_content = b"dummy order items excel content"
    orders_file = SimpleUploadedFile(
        "orders.xlsx", orders_content, content_type="application/vnd.ms-excel"
    )
    order_items_file = SimpleUploadedFile(
        "order_items.xlsx",
        order_items_content,
        content_type="application/vnd.ms-excel",
    )

    # --- Set up APIClient with an authenticated user ---
    client = APIClient()
    dummy_api_user = User(username="apiuser", email="apiuser@example.com")

    # add a dummy role_ref attribute.
    dummy_role = MagicMock(name="Role")
    dummy_role.name = "User"
    dummy_api_user.role_ref = dummy_role
    client.force_authenticate(user=dummy_api_user)

    # --- Call the API endpoint ---
    url = reverse("migrate_orders")
    response = client.post(
        url,
        data={
            "orders_excel": orders_file,
            "order_items_excel": order_items_file,
        },
    )

    print("MIGRATE ORDERS RESPONSE:", response.json())
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"message": "Migration completed successfully."}


#
