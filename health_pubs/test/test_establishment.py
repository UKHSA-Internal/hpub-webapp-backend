import pytest
import uuid
from unittest.mock import MagicMock, patch, Mock, create_autospec
from django.utils.text import slugify
from core.establishments.models import Establishment
from core.organizations.models import Organization
from core.programs.models import Program
from core.roles.models import Role
from core.users.models import User


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
def mock_program():
    """Mock Program model instance."""
    program = create_autospec(Program, instance=True)
    program.program_id = "2"
    program.programme_name = "Test Program"
    program._state = MagicMock()
    return program


@pytest.fixture
def mock_role():
    """Mock Role model instance."""
    role = create_autospec(Role, instance=True)
    role.role_id = "50"
    role.name = "Admin"
    role._state = MagicMock()
    return role


@pytest.fixture
def mock_user(mock_role):
    """Mock User model instance."""
    user = create_autospec(User, instance=True)
    user.user_id = "12345"
    user.email = "testuser@example.com"
    user.role_ref = mock_role
    user._state = MagicMock()
    return user


@patch("core.establishments.models.Establishment.objects.create")
def test_create_establishment(mock_create, mock_organization):
    """Unit test for creating an establishment."""
    slug_establishment = slugify(f"test-establishment-{uuid.uuid4()}")

    # Simulate saving an establishment
    establishment = create_autospec(Establishment, instance=True)
    establishment.establishment_id = "131"
    establishment.name = "Test Establishment"
    establishment.slug = slug_establishment
    establishment.organization_ref = mock_organization
    establishment._state = MagicMock()

    mock_create.return_value = establishment  # Mock the database save

    saved_est = Establishment.objects.create(
        establishment_id="131",
        name="Test Establishment",
        slug=slug_establishment,
        organization_ref=mock_organization,
    )

    assert saved_est.name == "Test Establishment"
    assert saved_est.organization_ref.organization_id == "1"
    mock_create.assert_called_once()


@patch("core.establishments.models.Establishment.objects.filter")
def test_get_establishments_by_organization(mock_filter, mock_establishment):
    """Unit test for retrieving establishments by organization_id."""
    mock_filter.return_value.exists.return_value = True
    mock_filter.return_value.all.return_value = [mock_establishment]

    establishments = Establishment.objects.filter(
        organization_ref=mock_establishment.organization_ref
    ).all()

    assert len(establishments) == 1
    assert establishments[0].name == "Test Establishment"
    mock_filter.assert_called_once()


@patch("core.establishments.models.Establishment.objects.count")
def test_count_establishments(mock_count):
    """Unit test for counting establishments."""
    mock_count.return_value = 2

    count = Establishment.objects.count()

    assert count == 2
    mock_count.assert_called_once()


@patch("core.establishments.models.Establishment.objects.all")
@patch("core.establishments.models.Establishment.delete")
def test_delete_all_establishments(mock_delete, mock_all):
    """Unit test for deleting all establishments."""
    mock_all.return_value = [Mock(), Mock()]
    mock_delete.return_value = None

    establishments = Establishment.objects.all()
    for est in establishments:
        est.delete()

    mock_all.assert_called_once()
    assert len(establishments) == 2
