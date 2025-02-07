import pytest
from unittest.mock import patch, MagicMock, create_autospec
from core.order_limits.models import OrderLimitPage
from core.products.models import Product
from core.organizations.models import Organization


def create_order_limit(order_limit_data):
    """
    Example function that your DRF viewset or service
    might call to create a new OrderLimitPage.
    We'll unit test this function directly.
    """
    product_id = order_limit_data.get("product_ref")
    org_id = order_limit_data.get("organization_ref")

    # Suppose your logic checks if product exists
    if not Product.objects.filter(product_id=product_id).exists():
        raise ValueError("Product does not exist")

    # Suppose your logic checks if organization exists
    if not Organization.objects.filter(organization_id=org_id).exists():
        raise ValueError("Organization does not exist")

    # Then create the OrderLimitPage
    return OrderLimitPage.objects.create(
        order_limit_id=order_limit_data.get("order_limit_id"),
        product_ref=product_id,
        organization_ref=org_id,
        order_limit=order_limit_data.get("order_limit"),
        title=order_limit_data.get("title", "Order Limit Title"),
    )


@patch("core.order_limits.models.OrderLimitPage.objects.create")
@patch("core.products.models.Product.objects.filter")
@patch("core.organizations.models.Organization.objects.filter")
def test_create_order_limit_success(mock_org_filter, mock_prod_filter, mock_create):
    """
    Positive test: create order limit with valid product & organization.
    """
    # Mock existence checks
    mock_prod_filter.return_value.exists.return_value = True
    mock_org_filter.return_value.exists.return_value = True

    # Mock create() to return a fake OrderLimitPage instance
    order_limit_instance = create_autospec(OrderLimitPage, instance=True)
    order_limit_instance.order_limit_id = "15"
    mock_create.return_value = order_limit_instance

    data = {
        "title": "New Order Limit",
        "order_limit_id": "15",
        "product_ref": "valid-product-id",
        "organization_ref": "valid-org-id",
        "order_limit": 15,
    }
    result = create_order_limit(data)

    assert result.order_limit_id == "15"
    mock_prod_filter.assert_called_once_with(product_id="valid-product-id")
    mock_org_filter.assert_called_once_with(organization_id="valid-org-id")
    mock_create.assert_called_once()


@patch("core.order_limits.models.OrderLimitPage.objects.create")
@patch("core.products.models.Product.objects.filter")
@patch("core.organizations.models.Organization.objects.filter")
def test_create_order_limit_invalid_product(
    mock_org_filter, mock_prod_filter, mock_create
):
    """
    Negative test: product does not exist => error
    """
    mock_prod_filter.return_value.exists.return_value = False
    mock_org_filter.return_value.exists.return_value = True

    data = {
        "order_limit_id": "1",
        "product_ref": "invalid-product-id",
        "organization_ref": "valid-org-id",
        "order_limit": 10,
    }
    with pytest.raises(ValueError, match="Product does not exist"):
        create_order_limit(data)

    mock_prod_filter.assert_called_once_with(product_id="invalid-product-id")
    mock_org_filter.assert_not_called()
    mock_create.assert_not_called()


@patch("core.order_limits.models.OrderLimitPage.objects.create")
@patch("core.products.models.Product.objects.filter")
@patch("core.organizations.models.Organization.objects.filter")
def test_create_order_limit_invalid_organization(
    mock_org_filter, mock_prod_filter, mock_create
):
    """
    Negative test: organization does not exist => error
    """
    mock_prod_filter.return_value.exists.return_value = True
    mock_org_filter.return_value.exists.return_value = False

    data = {
        "order_limit_id": "2",
        "product_ref": "valid-product-id",
        "organization_ref": "invalid-org-id",
        "order_limit": 10,
    }
    with pytest.raises(ValueError, match="Organization does not exist"):
        create_order_limit(data)

    # Called once for product check
    mock_prod_filter.assert_called_once_with(product_id="valid-product-id")
    # Called once for org check
    mock_org_filter.assert_called_once_with(organization_id="invalid-org-id")
    mock_create.assert_not_called()


def update_order_limit(order_limit_id, update_data):
    """
    Example function that updates an OrderLimitPage instance.
    """
    try:
        order_limit = OrderLimitPage.objects.get(order_limit_id=order_limit_id)
    except OrderLimitPage.DoesNotExist:
        raise ValueError("OrderLimitPage does not exist")

    product_id = update_data.get("product_ref")
    org_id = update_data.get("organization_ref")

    if product_id and not Product.objects.filter(product_id=product_id).exists():
        raise ValueError("Product does not exist")

    if org_id and not Organization.objects.filter(organization_id=org_id).exists():
        raise ValueError("Organization does not exist")

    order_limit.order_limit = update_data.get("order_limit", order_limit.order_limit)
    order_limit.product_ref = product_id or order_limit.product_ref
    order_limit.organization_ref = org_id or order_limit.organization_ref

    #  Mocked instance method `save()` is now correctly handled
    order_limit.save()

    return order_limit


@patch("core.order_limits.models.OrderLimitPage.objects.get")
@patch("core.products.models.Product.objects.filter")
@patch("core.organizations.models.Organization.objects.filter")
def test_update_order_limit_success(mock_org_filter, mock_prod_filter, mock_get):
    """
    Fixed: Successfully update an OrderLimitPage instance.
    """
    #  Mock the existing order limit and its `save()` method
    existing_order_limit = create_autospec(OrderLimitPage, instance=True)
    existing_order_limit.order_limit_id = "existing-limit"
    existing_order_limit.order_limit = 10
    existing_order_limit.save = MagicMock()  #  Add `save()` method on instance

    mock_get.return_value = existing_order_limit

    #  Mock existence checks
    mock_prod_filter.return_value.exists.return_value = True
    mock_org_filter.return_value.exists.return_value = True

    updated_data = {
        "product_ref": "new-product-id",
        "organization_ref": "new-org-id",
        "order_limit": 25,
    }
    result = update_order_limit("existing-limit", updated_data)

    #  Assertions
    assert result.order_limit == 25
    mock_get.assert_called_once_with(order_limit_id="existing-limit")
    mock_prod_filter.assert_called_once_with(product_id="new-product-id")
    mock_org_filter.assert_called_once_with(organization_id="new-org-id")
    existing_order_limit.save.assert_called_once()  #  Check if `save()` was called


@patch("core.order_limits.models.OrderLimitPage.objects.get")
@patch("core.products.models.Product.objects.filter")
def test_update_order_limit_invalid_product(mock_prod_filter, mock_get):
    """
    Negative test: update with invalid product => error
    """
    existing_order_limit = create_autospec(OrderLimitPage, instance=True)
    existing_order_limit.order_limit_id = "existing-limit"

    mock_get.return_value = existing_order_limit
    mock_prod_filter.return_value.exists.return_value = False

    updated_data = {
        "product_ref": "invalid-product-id",
        "order_limit": 30,
    }
    with pytest.raises(ValueError, match="Product does not exist"):
        update_order_limit("existing-limit", updated_data)

    mock_get.assert_called_once_with(order_limit_id="existing-limit")
    mock_prod_filter.assert_called_once_with(product_id="invalid-product-id")


@patch("core.order_limits.models.OrderLimitPage.objects.get")
@patch("core.organizations.models.Organization.objects.filter")
def test_update_order_limit_invalid_organization(mock_org_filter, mock_get):
    """
    Negative test: update with invalid organization => error
    """
    existing_order_limit = create_autospec(OrderLimitPage, instance=True)
    existing_order_limit.order_limit_id = "existing-limit"

    mock_get.return_value = existing_order_limit
    mock_org_filter.return_value.exists.return_value = False

    updated_data = {
        "organization_ref": "invalid-org-id",
        "order_limit": 40,
    }
    with pytest.raises(ValueError, match="Organization does not exist"):
        update_order_limit("existing-limit", updated_data)

    mock_get.assert_called_once_with(order_limit_id="existing-limit")
    mock_org_filter.assert_called_once_with(organization_id="invalid-org-id")
