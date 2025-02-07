from django.urls import reverse

from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from unittest.mock import MagicMock, patch


from core.vaccinations.views import (
    VaccinationCreateViewSet,
    VaccinationDeleteViewSet,
    VaccinationListViewSet,
)


import logging

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# Helper Functions
# -------------------------------------------------------------------
def dummy_response(data, status_code):
    """Helper that returns a DRF Response with given data and status code."""
    return Response(data, status=status_code)


def get_dummy_user(is_admin=False):
    """Return a dummy user with is_authenticated=True. For admin tests, set extra attributes."""
    dummy = MagicMock()
    if is_admin:
        dummy.user_id = "admin-1"
        dummy.email = "admin@example.com"
    else:
        dummy.user_id = "user-1"
        dummy.email = "user@example.com"
    dummy.is_authenticated = True
    dummy._state = MagicMock(db="default")
    # For admin tests, simulate an establishment with a full_external_key.
    dummy.establishment_ref = MagicMock(full_external_key="ext-key")
    return dummy


# -------------------------------------------------------------------
# Vaccination Create Tests
# -------------------------------------------------------------------


@patch(
    "core.vaccinations.views.VaccinationCreateViewSet.create",
    return_value=dummy_response(
        [{"vaccination_id": "100", "name": "New Vaccination", "programs": ["prog-1"]}],
        status.HTTP_201_CREATED,
    ),
)
def test_create_vaccination_with_program(mock_create, client):
    """
    Unit test for creating a vaccination with a valid program reference.
    The view's create method is patched to immediately return a dummy response.
    """
    factory = APIRequestFactory()
    url = reverse("vaccination-create-list")
    # In our dummy payload we assume that program reference is by program name.
    data = {
        "vaccinations": [
            {
                "vaccination_id": "100",
                "name": "New Vaccination",
                "key": "vaccination-key",
                "description": "This is a new vaccination",
                "program_names": ["Test Program"],
            }
        ]
    }
    request = factory.post(url, data=data, format="json")
    # Force authenticate the request with a dummy admin user.
    force_authenticate(request, user=get_dummy_user(is_admin=True))
    # Bypass permission checks.
    with patch.object(VaccinationCreateViewSet, "permission_classes", []):
        view = VaccinationCreateViewSet.as_view({"post": "create"})
        response = view(request)
    logger.info("CREATE VACCINATION RESPONSE: %s", response.data)
    assert response.status_code == status.HTTP_201_CREATED
    assert response.data[0]["name"] == "New Vaccination"
    assert response.data[0]["programs"] == ["prog-1"]


@patch(
    "core.vaccinations.views.VaccinationCreateViewSet.create",
    return_value=dummy_response(
        [{"error": "Program 'Non-Existent Program' does not exist."}],
        status.HTTP_404_NOT_FOUND,
    ),
)
def test_create_vaccination_with_invalid_program(mock_create, client):
    """
    Unit test for creating a vaccination with an invalid program.
    The view's create method is patched to immediately return a dummy error response.
    """
    factory = APIRequestFactory()
    url = reverse("vaccination-create-list")
    data = {
        "vaccinations": [
            {
                "vaccination_id": "101",
                "name": "Invalid Program Vaccination",
                "key": "invalid-key",
                "description": "This vaccination has an invalid program",
                "program_names": ["Non-Existent Program"],
            }
        ]
    }
    request = factory.post(url, data=data, format="json")
    force_authenticate(request, user=get_dummy_user(is_admin=True))
    with patch.object(VaccinationCreateViewSet, "permission_classes", []):
        view = VaccinationCreateViewSet.as_view({"post": "create"})
        response = view(request)
    logger.info("CREATE VACCINATION INVALID PROGRAM RESPONSE: %s", response.data)
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.data[0]["error"] == "Program 'Non-Existent Program' does not exist."


# -------------------------------------------------------------------
# Vaccination Delete Tests (Delete All)
# -------------------------------------------------------------------


@patch(
    "core.vaccinations.views.VaccinationDeleteViewSet.delete_all",
    return_value=dummy_response(
        {"message": "Successfully deleted 0 vaccination(s)."},
        status.HTTP_204_NO_CONTENT,
    ),
)
def test_delete_all_vaccinations_with_program(mock_delete_all, client):
    factory = APIRequestFactory()
    url = reverse("vaccination-delete-delete-all")
    request = factory.delete(url)
    force_authenticate(request, user=get_dummy_user(is_admin=True))
    with patch.object(VaccinationDeleteViewSet, "permission_classes", []):
        view = VaccinationDeleteViewSet.as_view({"delete": "delete_all"})
        response = view(request)
    logger.info("DELETE ALL VACCINATIONS RESPONSE: %s", response.data)
    assert response.status_code == status.HTTP_204_NO_CONTENT


@patch(
    "core.vaccinations.views.VaccinationDeleteViewSet.delete_all",
    return_value=dummy_response(
        {"message": "Successfully deleted 0 vaccination(s)."},
        status.HTTP_204_NO_CONTENT,
    ),
)
def test_delete_all_vaccinations_empty(mock_delete_all, client):
    factory = APIRequestFactory()
    url = reverse("vaccination-delete-delete-all")
    request = factory.delete(url)
    force_authenticate(request, user=get_dummy_user(is_admin=True))
    with patch.object(VaccinationDeleteViewSet, "permission_classes", []):
        view = VaccinationDeleteViewSet.as_view({"delete": "delete_all"})
        response = view(request)
    logger.info("DELETE ALL VACCINATIONS EMPTY RESPONSE: %s", response.data)
    assert response.status_code == status.HTTP_204_NO_CONTENT


# ----- Test: List Vaccinations with Program Details (Positive) -----
@patch(
    "core.vaccinations.views.VaccinationListViewSet.list",
    return_value=dummy_response(
        [
            {
                "vaccination_id": "1",
                "name": "Test Vaccination",
                "programs": ["prog-1", "prog-2"],
            }
        ],
        status.HTTP_200_OK,
    ),
)
def test_list_vaccinations_with_program(mock_list, client):
    factory = APIRequestFactory()
    url = reverse("vaccination-list-list")
    request = factory.get(url)
    force_authenticate(request, user=get_dummy_user())
    # Patch permission classes to bypass authentication/authorization.
    with patch.object(VaccinationListViewSet, "permission_classes", []):
        view = VaccinationListViewSet.as_view({"get": "list"})
        response = view(request)
    logger.info("LIST VACCINATIONS RESPONSE: %s", response.data)
    assert response.status_code == status.HTTP_200_OK
    assert len(response.data) > 0
    # For example, check that the first vaccination is linked to programs.
    assert "programs" in response.data[0]


# ----- Test: List Vaccinations When None Exist (Negative) -----
@patch(
    "core.vaccinations.views.VaccinationListViewSet.list",
    return_value=dummy_response([], status.HTTP_200_OK),
)
def test_list_vaccinations_empty(mock_list, client):
    factory = APIRequestFactory()
    url = reverse("vaccination-list-list")
    request = factory.get(url)
    force_authenticate(request, user=get_dummy_user())
    with patch.object(VaccinationListViewSet, "permission_classes", []):
        view = VaccinationListViewSet.as_view({"get": "list"})
        response = view(request)
    logger.info("LIST EMPTY VACCINATIONS RESPONSE: %s", response.data)
    assert response.status_code == status.HTTP_200_OK
    assert len(response.data) == 0
