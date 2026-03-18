import pytest
import uuid
from unittest.mock import MagicMock, patch, create_autospec
from core.establishments.models import Establishment
from core.feedbacks.models import Feedback
from core.organizations.models import Organization
from core.roles.models import Role
from core.users.models import User


@pytest.fixture
def mock_feedback():
    """Mock Feedback model instance."""
    feedback = create_autospec(Feedback, instance=True)
    feedback.feedback_id = str(uuid.uuid4())
    feedback.message = "This is a test feedback message."
    feedback.user_ref = None
    feedback._state = MagicMock()
    return feedback


@pytest.fixture
def mock_user():
    """Mock User model instance."""
    user = create_autospec(User, instance=True)
    user.user_id = str(uuid.uuid4())
    user.email = "testuser@example.com"
    user._state = MagicMock()
    return user


@pytest.fixture
def mock_role():
    """Mock Role model instance."""
    role = create_autospec(Role, instance=True)
    role.role_id = "50"
    role.name = "Admin"
    role._state = MagicMock()
    return role


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


@patch("core.feedbacks.models.Feedback.objects.create")
def test_create_feedback(mock_create):
    """Unit test for creating a feedback entry."""
    feedback_instance = create_autospec(Feedback, instance=True)
    feedback_instance.feedback_id = str(uuid.uuid4())
    feedback_instance.message = "New feedback message"
    feedback_instance._state = MagicMock()

    mock_create.return_value = feedback_instance

    new_feedback = Feedback.objects.create(
        feedback_id=str(uuid.uuid4()), message="New feedback message"
    )

    assert new_feedback.message == "New feedback message"
    mock_create.assert_called_once()


@patch("core.feedbacks.models.Feedback.objects.filter")
def test_get_feedback_by_id(mock_filter, mock_feedback):
    """Unit test for retrieving a feedback entry by ID."""
    mock_filter.return_value.exists.return_value = True
    mock_filter.return_value.get.return_value = mock_feedback

    feedback = Feedback.objects.filter(feedback_id=mock_feedback.feedback_id).get()

    assert feedback.message == "This is a test feedback message."
    mock_filter.assert_called_once()


@patch("core.feedbacks.models.Feedback.objects.count")
def test_count_feedback(mock_count):
    """Unit test for counting feedback entries."""
    mock_count.return_value = 5

    count = Feedback.objects.count()

    assert count == 5
    mock_count.assert_called_once()


@patch("core.feedbacks.models.Feedback.objects.all")
@patch("core.feedbacks.models.Feedback.delete")
def test_delete_all_feedback(mock_delete, mock_all):
    """Unit test for deleting all feedback entries."""
    mock_all.return_value = [MagicMock(), MagicMock()]
    mock_delete.return_value = None

    feedbacks = Feedback.objects.all()
    for feedback in feedbacks:
        feedback.delete()

    mock_all.assert_called_once()
    assert len(feedbacks) == 2


@patch("core.feedbacks.models.Feedback.objects.bulk_create")
def test_bulk_create_feedback(mock_bulk_create):
    """Unit test for bulk creating feedback entries."""
    feedback_1 = create_autospec(Feedback, instance=True)
    feedback_2 = create_autospec(Feedback, instance=True)

    mock_bulk_create.return_value = [feedback_1, feedback_2]

    new_feedbacks = [
        create_autospec(
            Feedback, instance=True, feedback_id=str(uuid.uuid4()), message="Feedback 1"
        ),
        create_autospec(
            Feedback, instance=True, feedback_id=str(uuid.uuid4()), message="Feedback 2"
        ),
    ]

    created_feedbacks = Feedback.objects.bulk_create(new_feedbacks)

    assert len(created_feedbacks) == 2
    mock_bulk_create.assert_called_once()


@patch("core.feedbacks.models.Feedback.objects.filter")
def test_bulk_delete_feedback(mock_filter):
    """Unit test for bulk deleting feedback entries."""
    mock_filter.return_value.exists.return_value = True
    mock_filter.return_value.delete.return_value = None

    Feedback.objects.filter(message="This is a test feedback message.").delete()

    mock_filter.assert_called_once()


@patch("core.feedbacks.models.Feedback.objects.filter")
@patch("core.feedbacks.models.Feedback.objects.update")
def test_update_feedback(mock_update, mock_filter, mock_feedback):
    """Unit test for updating a feedback entry."""
    mock_filter.return_value.exists.return_value = True
    mock_filter.return_value.get.return_value = mock_feedback
    mock_filter.return_value.update.return_value = 1  # Simulating one row update

    updated_data = {
        "message": "Updated feedback message",
    }

    Feedback.objects.filter(feedback_id=mock_feedback.feedback_id).update(
        **updated_data
    )

    mock_filter.return_value.update.assert_called_once_with(**updated_data)
