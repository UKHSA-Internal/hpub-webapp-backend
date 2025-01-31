from unittest.mock import patch, MagicMock
from django.urls import reverse
from rest_framework import status


class TestOrderViewSet:
    @patch("rest_framework.permissions.IsAuthenticated.has_permission")
    @patch("core.users.permissions.IsAdminOrRegisteredUser.has_permission")
    @patch(
        "core.utils.custom_token_authentication.CustomTokenAuthentication.authenticate"
    )
    @patch("core.users.models.User.objects.get")
    @patch("core.addresses.models.Address.objects.get")
    @patch("core.orders.models.Order.objects.create")
    @patch("core.orders.serializers.OrderSerializer")
    def test_create_for_admin_success(
        self,
        mock_order_serializer,
        mock_order_create,
        mock_address_get,
        mock_user_get,
        mock_authenticate,
        mock_is_admin_or_registered,
        mock_is_authenticated,
        client,
    ):
        """Test creating an order for admin successfully with authentication and permission mocks"""

        url = reverse("order-create-for-admin")

        # ✅ Mock authentication to return a valid user
        mock_user = MagicMock(
            user_id="12345", email="admin@test.com", is_staff=True, is_superuser=True
        )
        mock_authenticate.return_value = (
            mock_user,
            None,
        )  # Simulate successful authentication

        # ✅ Mock user retrieval
        mock_user_get.return_value = mock_user

        # ✅ Mock address retrieval
        mock_address = MagicMock(address_id="addr-1", city="Test City")
        mock_address_get.return_value = mock_address

        # ✅ Mock Order creation
        mock_order = MagicMock(order_id="order-1")
        mock_order_create.return_value = mock_order

        # ✅ Mock Serializer
        mock_serializer = MagicMock()
        mock_serializer.data = {"order_id": "order-1"}
        mock_serializer.is_valid.return_value = True
        mock_serializer.save.return_value = mock_order
        mock_order_serializer.return_value = mock_serializer

        # ✅ Mock Permissions (return True to grant access)
        mock_is_authenticated.return_value = True  # Mock IsAuthenticated
        mock_is_admin_or_registered.return_value = True  # Mock IsAdminOrRegisteredUser

        # ✅ Fix: Send JSON Data as a Dictionary
        payload = {
            "order_items": [{"product_code": "prod-1", "quantity": 1}],
            "user_ref": "12345",
            "user_info": {"email": "testuser@example.com"},
            "address_ref": "addr-1",
        }

        # ✅ Use `json=` instead of `data=` to properly pass JSON
        response = client.post(url, json=payload, HTTP_AUTHORIZATION="Token testtoken")
        print("RES", response.json())

        # ✅ Assertions
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["order_id"] == "order-1"

        # ✅ Ensure mock methods were called
        mock_authenticate.assert_called_once()  # Verify authentication was called
        mock_is_authenticated.assert_called_once()  # Verify authentication check was performed
        mock_is_admin_or_registered.assert_called_once()  # Verify role-based access was checked
        mock_user_get.assert_called_once_with(user_id="12345")
        mock_address_get.assert_called_once_with(address_id="addr-1")
        mock_order_create.assert_called_once()
        mock_order_serializer.assert_called_once()

    # def test_create_for_admin_missing_user_ref(client, mocker):
    #     """Test order creation fails when user_ref is missing"""

    #     url = reverse("order-create-for-admin")

    #     payload = {
    #         "order_items": [{"product_code": "prod-1", "quantity": 1}],
    #         "user_info": {"email": "testuser@example.com"},
    #         "address_ref": "addr-1"
    #     }

    #     response = client.post(url, data=payload, format="json")
    #     assert response.status_code == status.HTTP_400_BAD_REQUEST
    #     assert response.json()["error_code"] == "USER_REF_REQUIRED"

    # def test_get_all_orders(client, mocker):
    #     """Test fetching all orders"""

    #     url = reverse("order-get-all-orders")

    #     # Mock Orders Queryset
    #     mock_order1 = MagicMock(order_id="order-1")
    #     mock_order2 = MagicMock(order_id="order-2")
    #     mocker.patch("core.order.models.Order.objects.all", return_value=[mock_order1, mock_order2])

    #     response = client.get(url)
    #     assert response.status_code == status.HTTP_200_OK
    #     assert len(response.json()) == 2

    #
