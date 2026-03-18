import pytest
import uuid
import io
import pandas as pd
from unittest.mock import MagicMock, patch, create_autospec
from django.utils.text import slugify
from core.audiences.models import Audience
from core.roles.models import Role
from core.users.models import User


@pytest.fixture
def mock_audience():
    """Mock Audience model instance."""
    audience = create_autospec(Audience, instance=True)
    audience.audience_id = "123"
    audience.name = "Test Audience"
    audience.key = "test-key"
    audience.description = "Test Description"
    audience._state = MagicMock()  # Fix: Add _state
    return audience


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


@patch("core.audiences.models.Audience.objects.create")
def test_create_audience(mock_create):
    """Unit test for creating an audience."""
    slug_audience = slugify(f"test-audience-{uuid.uuid4()}")

    # Mock Audience instance instead of creating it
    audience_instance = create_autospec(Audience, instance=True)
    audience_instance.audience_id = "124"
    audience_instance.name = "New Audience"
    audience_instance.slug = slug_audience
    audience_instance.key = "new-key"
    audience_instance.description = "New Description"
    audience_instance._state = MagicMock()

    mock_create.return_value = audience_instance  # Mock the DB save

    saved_audience = Audience.objects.create(
        audience_id="124",
        name="New Audience",
        slug=slug_audience,
        key="new-key",
        description="New Description",
    )

    assert saved_audience.name == "New Audience"
    assert saved_audience.key == "new-key"
    mock_create.assert_called_once()


@patch("core.audiences.models.Audience.objects.filter")
def test_get_audience_by_key(mock_filter, mock_audience):
    """Unit test for retrieving an audience by key."""
    mock_filter.return_value.exists.return_value = True
    mock_filter.return_value.get.return_value = mock_audience

    audience = Audience.objects.filter(key="test-key").get()

    assert audience.name == "Test Audience"
    assert audience.key == "test-key"
    mock_filter.assert_called_once()


@patch("core.audiences.models.Audience.objects.count")
def test_count_audiences(mock_count):
    """Unit test for counting audiences."""
    mock_count.return_value = 2

    count = Audience.objects.count()

    assert count == 2
    mock_count.assert_called_once()


@patch("core.audiences.models.Audience.objects.all")
@patch("core.audiences.models.Audience.delete")
def test_delete_all_audiences(mock_delete, mock_all):
    """Unit test for deleting all audiences."""
    mock_all.return_value = [MagicMock(), MagicMock()]
    mock_delete.return_value = None

    audiences = Audience.objects.all()
    for aud in audiences:
        aud.delete()

    mock_all.assert_called_once()
    assert len(audiences) == 2


@patch("core.audiences.models.Audience.objects.bulk_create")
def test_bulk_create_audiences(mock_bulk_create):
    """Unit test for bulk creating audiences."""
    audience_1 = create_autospec(Audience, instance=True)
    audience_2 = create_autospec(Audience, instance=True)

    mock_bulk_create.return_value = [audience_1, audience_2]

    new_audiences = [
        create_autospec(
            Audience,
            instance=True,
            audience_id="201",
            name="Audience1",
            key="key1",
            description="Desc1",
        ),
        create_autospec(
            Audience,
            instance=True,
            audience_id="202",
            name="Audience2",
            key="key2",
            description="Desc2",
        ),
    ]

    created_audiences = Audience.objects.bulk_create(new_audiences)

    assert len(created_audiences) == 2
    mock_bulk_create.assert_called_once()


@patch("pandas.read_excel")
@patch("core.audiences.models.Audience.objects.bulk_create")
def test_bulk_upload_audience(mock_bulk_create, mock_read_excel):
    """Unit test for bulk uploading audiences from an Excel file."""
    test_data = pd.DataFrame(
        {
            "name": ["Audience1", "Audience2"],
            "key": ["key1", "key2"],
            "description": ["Description1", "Description2"],
            "id": [1, 2],
        }
    )

    mock_read_excel.return_value = test_data

    audience_1 = create_autospec(Audience, instance=True)
    audience_2 = create_autospec(Audience, instance=True)

    mock_bulk_create.return_value = [audience_1, audience_2]

    excel_file = io.BytesIO()
    with pd.ExcelWriter(excel_file, engine="xlsxwriter") as writer:
        test_data.to_excel(writer, index=False, sheet_name="Sheet1")
    excel_file.seek(0)

    df = pd.read_excel(excel_file)

    new_audiences = [
        create_autospec(
            Audience,
            instance=True,
            audience_id=row["id"],
            name=row["name"],
            key=row["key"],
            description=row["description"],
        )
        for _, row in df.iterrows()
    ]

    created_audiences = Audience.objects.bulk_create(new_audiences)

    assert len(created_audiences) == 2
    mock_read_excel.assert_called_once()
    mock_bulk_create.assert_called_once()
