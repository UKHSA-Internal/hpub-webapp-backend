import pytest
import uuid
from unittest.mock import MagicMock, patch, create_autospec
from core.customer_support.models import CustomerSupport
from core.establishments.models import Establishment
from core.organizations.models import Organization
from core.roles.models import Role
from core.users.models import User


@pytest.fixture
def mock_customer_support():
    """Mock CustomerSupport model instance."""
    support = create_autospec(CustomerSupport, instance=True)
    support.customer_support_id = str(uuid.uuid4())
    support.message = "Test support message"
    support.summary = "Test Summary"
    support.contact_email = "test@example.com"
    support.contact_name = "Test User"
    support._state = MagicMock()
    return support


@pytest.fixture
def mock_organization():
    """Mock Organization model instance."""
    org = create_autospec(Organization, instance=True)
    org.organization_id = "1"
    org.name = "Test Organization"
    org._state = MagicMock()
    return org


@pytest.fixture
def mock_establishment(mock_organization):
    """Mock Establishment model instance."""
    est = create_autospec(Establishment, instance=True)
    est.establishment_id = "130"
    est.name = "Test Establishment"
    est.organization_ref = mock_organization
    est._state = MagicMock()
    return est


@pytest.fixture
def mock_role():
    """Mock Role model instance."""
    role = create_autospec(Role, instance=True)
    role.role_id = "50"
    role.name = "Admin"
    role._state = MagicMock()
    return role


@pytest.fixture
def mock_user(mock_role, mock_establishment):
    """Mock User model instance."""
    user = create_autospec(User, instance=True)
    user.user_id = "12345"
    user.email = "testuser@example.com"
    user.role_ref = mock_role
    user.establishment_ref = mock_establishment
    user.organization_ref = mock_establishment.organization_ref
    user._state = MagicMock()
    return user


@patch("core.customer_support.models.CustomerSupport.objects.create")
def test_create_customer_support(mock_create):
    """Unit test for creating a CustomerSupport entry."""
    support_instance = create_autospec(CustomerSupport, instance=True)
    support_instance.customer_support_id = str(uuid.uuid4())
    support_instance.message = "New support message"
    support_instance.summary = "General Inquiry"
    support_instance.contact_email = "support@example.com"
    support_instance.contact_name = "John Doe"
    support_instance._state = MagicMock()

    mock_create.return_value = support_instance

    new_support = CustomerSupport.objects.create(
        message="New support message",
        summary="General Inquiry",
        contact_email="support@example.com",
        contact_name="John Doe",
    )

    assert new_support.message == "New support message"
    assert new_support.contact_email == "support@example.com"
    mock_create.assert_called_once()


@patch("core.customer_support.models.CustomerSupport.objects.filter")
def test_get_customer_support_by_id(mock_filter, mock_customer_support):
    """Unit test for retrieving a CustomerSupport entry by ID."""
    mock_filter.return_value.exists.return_value = True
    mock_filter.return_value.get.return_value = mock_customer_support

    support = CustomerSupport.objects.filter(
        customer_support_id=mock_customer_support.customer_support_id
    ).get()

    assert support.message == "Test support message"
    assert support.contact_email == "test@example.com"
    mock_filter.assert_called_once()


@patch("core.customer_support.models.CustomerSupport.objects.count")
def test_count_customer_support_entries(mock_count):
    """Unit test for counting CustomerSupport entries."""
    mock_count.return_value = 5

    count = CustomerSupport.objects.count()

    assert count == 5
    mock_count.assert_called_once()


@patch("core.customer_support.models.CustomerSupport.objects.all")
@patch("core.customer_support.models.CustomerSupport.delete")
def test_delete_all_customer_support_entries(mock_delete, mock_all):
    """Unit test for deleting all CustomerSupport entries."""
    mock_all.return_value = [MagicMock(), MagicMock()]
    mock_delete.return_value = None

    supports = CustomerSupport.objects.all()
    for support in supports:
        support.delete()

    mock_all.assert_called_once()
    assert len(supports) == 2


@patch("core.customer_support.models.CustomerSupport.objects.bulk_create")
def test_bulk_create_customer_support(mock_bulk_create):
    """Unit test for bulk creating CustomerSupport entries."""
    support_1 = create_autospec(CustomerSupport, instance=True)
    support_2 = create_autospec(CustomerSupport, instance=True)

    mock_bulk_create.return_value = [support_1, support_2]

    new_supports = [
        create_autospec(
            CustomerSupport,
            instance=True,
            message="Support 1",
            contact_email="email1@example.com",
        ),
        create_autospec(
            CustomerSupport,
            instance=True,
            message="Support 2",
            contact_email="email2@example.com",
        ),
    ]

    created_supports = CustomerSupport.objects.bulk_create(new_supports)

    assert len(created_supports) == 2
    mock_bulk_create.assert_called_once()


@patch("core.customer_support.models.CustomerSupport.objects.filter")
def test_bulk_delete_customer_support(mock_filter):
    """Unit test for bulk deleting CustomerSupport entries."""
    mock_filter.return_value.exists.return_value = True
    mock_filter.return_value.delete.return_value = None

    CustomerSupport.objects.filter(contact_email="test@example.com").delete()

    mock_filter.assert_called_once()


@patch("core.customer_support.models.CustomerSupport.objects.filter")
def test_update_customer_support(mock_filter, mock_customer_support):
    """Unit test for updating a CustomerSupport entry."""
    mock_filter.return_value.exists.return_value = True
    mock_filter.return_value.get.return_value = mock_customer_support
    mock_filter.return_value.update.return_value = 1

    updated_data = {
        "message": "Updated message",
        "summary": "Updated summary",
        "contact_email": "updated@example.com",
        "contact_name": "Jane Doe",
    }

    CustomerSupport.objects.filter(
        customer_support_id=mock_customer_support.customer_support_id
    ).update(**updated_data)

    mock_filter.return_value.update.assert_called_once_with(**updated_data)
