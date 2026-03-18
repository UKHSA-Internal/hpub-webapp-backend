import pytest
from unittest.mock import MagicMock, patch, create_autospec
from core.diseases.models import Disease
from core.programs.models import Program
from core.roles.models import Role
from core.users.models import User


@pytest.fixture
def mock_program():
    """Mock Program model instance."""
    program = create_autospec(Program, instance=True)
    program.program_id = "2"
    program.programme_name = "Test Program"
    program._state = MagicMock()
    return program


@pytest.fixture
def mock_disease(mock_program):
    """Mock Disease model instance."""
    disease = create_autospec(Disease, instance=True)
    disease.disease_id = "101"
    disease.name = "Test Disease"
    disease.key = "disease-key"
    disease.description = "A test disease for unit testing."
    disease.programs.all.return_value = [mock_program]  # Mock ManyToMany relationship
    disease._state = MagicMock()
    return disease


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


@patch("core.diseases.models.Disease.objects.create")
def test_create_disease(mock_create):
    """Unit test for creating a disease."""
    disease_instance = create_autospec(Disease, instance=True)
    disease_instance.disease_id = "102"
    disease_instance.name = "New Disease"
    disease_instance.key = "new-disease-key"
    disease_instance.description = "This is a new disease"
    disease_instance._state = MagicMock()

    mock_create.return_value = disease_instance

    new_disease = Disease.objects.create(
        disease_id="102",
        name="New Disease",
        key="new-disease-key",
        description="This is a new disease",
    )

    assert new_disease.name == "New Disease"
    assert new_disease.key == "new-disease-key"
    mock_create.assert_called_once()


@patch("core.diseases.models.Disease.objects.filter")
def test_get_disease_by_id(mock_filter, mock_disease):
    """Unit test for retrieving a disease by ID."""
    mock_filter.return_value.exists.return_value = True
    mock_filter.return_value.get.return_value = mock_disease

    disease = Disease.objects.filter(disease_id=mock_disease.disease_id).get()

    assert disease.name == "Test Disease"
    assert disease.key == "disease-key"
    mock_filter.assert_called_once()


@patch("core.diseases.models.Disease.objects.count")
def test_count_diseases(mock_count):
    """Unit test for counting diseases."""
    mock_count.return_value = 3

    count = Disease.objects.count()

    assert count == 3
    mock_count.assert_called_once()


@patch("core.diseases.models.Disease.objects.all")
@patch("core.diseases.models.Disease.delete")
def test_delete_all_diseases(mock_delete, mock_all):
    """Unit test for deleting all diseases."""
    mock_all.return_value = [MagicMock(), MagicMock()]
    mock_delete.return_value = None

    diseases = Disease.objects.all()
    for disease in diseases:
        disease.delete()

    mock_all.assert_called_once()
    assert len(diseases) == 2


@patch("core.diseases.models.Disease.objects.bulk_create")
def test_bulk_create_diseases(mock_bulk_create):
    """Unit test for bulk creating diseases."""
    disease_1 = create_autospec(Disease, instance=True)
    disease_2 = create_autospec(Disease, instance=True)

    mock_bulk_create.return_value = [disease_1, disease_2]

    new_diseases = [
        create_autospec(
            Disease, instance=True, disease_id="201", name="Disease1", key="key1"
        ),
        create_autospec(
            Disease, instance=True, disease_id="202", name="Disease2", key="key2"
        ),
    ]

    created_diseases = Disease.objects.bulk_create(new_diseases)

    assert len(created_diseases) == 2
    mock_bulk_create.assert_called_once()


@patch("core.diseases.models.Disease.objects.filter")
def test_bulk_delete_diseases(mock_filter):
    """Unit test for bulk deleting diseases."""
    mock_filter.return_value.exists.return_value = True
    mock_filter.return_value.delete.return_value = None

    Disease.objects.filter(key="disease-key").delete()

    mock_filter.assert_called_once()


@patch("core.diseases.models.Disease.objects.filter")
@patch("core.diseases.models.Disease.objects.update")
def test_update_disease(mock_update, mock_filter, mock_disease):
    """Unit test for updating a disease."""
    mock_filter.return_value.exists.return_value = True
    mock_filter.return_value.get.return_value = mock_disease
    mock_filter.return_value.update.return_value = 1  # Simulating one row update

    updated_data = {
        "name": "Updated Disease",
        "description": "Updated description",
        "key": "updated-key",
    }

    Disease.objects.filter(disease_id=mock_disease.disease_id).update(**updated_data)

    mock_filter.return_value.update.assert_called_once_with(**updated_data)
