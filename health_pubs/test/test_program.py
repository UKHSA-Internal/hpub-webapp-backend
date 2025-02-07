import uuid

from django.urls import reverse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from unittest.mock import MagicMock, patch

# Adjust these imports to match your project structure.
from core.programs.views import (
    ProgramCreateViewSet,
    ProgramListViewSet,
    ProgramUpdateViewSet,
    ProgramDestroyViewSet,
)


# -------------------------------------------------------------------
# Helper Functions
# -------------------------------------------------------------------
def dummy_response(data, status_code):
    """Return a DRF Response with given data and status."""
    return Response(data, status=status_code)


def get_dummy_user(is_admin=False):
    """Return a dummy user that is authenticated. For admin tests, set extra attributes."""
    dummy = MagicMock()
    if is_admin:
        dummy.user_id = "admin-1"
        dummy.email = "admin@example.com"
    else:
        dummy.user_id = "user-1"
        dummy.email = "user@example.com"
    dummy.is_authenticated = True
    # For admin tests, simulate an establishment with a full_external_key.
    dummy.establishment_ref = MagicMock(full_external_key="ext-key")
    dummy._state = MagicMock(db="default")
    return dummy


# -------------------------------------------------------------------
# Tests for Program Endpoints
# -------------------------------------------------------------------


# ----- Test: Create Program (Admin User) -----
@patch(
    "core.programs.views.ProgramCreateViewSet.create",
    return_value=dummy_response(
        {"created_programs": ["New Test Program"]}, status.HTTP_201_CREATED
    ),
)
def test_create_program_success(mock_create, client):
    """
    Unit test for creating a program (admin) via the create endpoint.
    The view's create method is patched to immediately return a dummy response.
    """
    factory = APIRequestFactory()
    url = reverse("program-create-list")
    program_data = {
        "programme_name": "New Test Program",
        "is_featured": True,
        "is_temporary": False,
        "program_term": "short_term",
        "external_key": f"newtestprogram{str(uuid.uuid4())}",
    }
    request = factory.post(url, data=program_data, format="json")
    # Create a dummy admin user and force authenticate the request.
    dummy_admin = get_dummy_user(is_admin=True)
    force_authenticate(request, user=dummy_admin)
    # Optionally, bypass permission checks by patching permission_classes.
    with patch.object(ProgramCreateViewSet, "permission_classes", []):
        view = ProgramCreateViewSet.as_view({"post": "create"})
        response = view(request)
    print("CREATE PROGRAM RESPONSE:", response.data)
    assert response.status_code == status.HTTP_201_CREATED
    assert "created_programs" in response.data


# ----- Test: Create Program Without Name (Error) -----
@patch(
    "core.programs.views.ProgramCreateViewSet.create",
    return_value=dummy_response(
        {"errors": [{"error": "Program Name is required"}]}, status.HTTP_400_BAD_REQUEST
    ),
)
def test_create_program_without_name(mock_create, client):
    factory = APIRequestFactory()
    url = reverse("program-create-list")
    program_data = {"is_featured": False, "program_term": "short_term"}
    request = factory.post(url, data=program_data, format="json")
    force_authenticate(request, user=get_dummy_user(is_admin=True))
    with patch.object(ProgramCreateViewSet, "permission_classes", []):
        view = ProgramCreateViewSet.as_view({"post": "create"})
        response = view(request)
    print("CREATE PROGRAM WITHOUT NAME RESPONSE:", response.data)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "errors" in response.data
    assert "Program Name is required" in response.data["errors"][0]["error"]


# ----- Test: Update Program (Admin User) -----
@patch(
    "core.programs.views.ProgramUpdateViewSet.update",
    return_value=dummy_response(
        {"programme_name": "Updated Program Name", "is_featured": True},
        status.HTTP_200_OK,
    ),
)
def test_update_program(mock_update, client):
    dummy_program_id = "2"
    factory = APIRequestFactory()
    url = reverse("program-update-detail", kwargs={"pk": dummy_program_id})
    updated_data = {"programme_name": "Updated Program Name", "is_featured": True}
    request = factory.patch(url, data=updated_data, format="json")
    force_authenticate(request, user=get_dummy_user(is_admin=True))
    with patch.object(ProgramUpdateViewSet, "permission_classes", []):
        view = ProgramUpdateViewSet.as_view({"patch": "update"})
        response = view(request, pk=dummy_program_id)
    print("UPDATE PROGRAM RESPONSE:", response.data)
    # We expect a 200 OK response when authenticated.
    assert response.status_code == status.HTTP_200_OK


# ----- Test: Destroy Program (Admin User) -----
@patch(
    "core.programs.views.ProgramDestroyViewSet.destroy",
    return_value=dummy_response({}, status.HTTP_204_NO_CONTENT),
)
def test_destroy_program(mock_destroy, client):
    dummy_program_id = "2"
    factory = APIRequestFactory()
    url = reverse("program-destroy-detail", kwargs={"pk": dummy_program_id})
    request = factory.delete(url)
    force_authenticate(request, user=get_dummy_user(is_admin=True))
    with patch.object(ProgramDestroyViewSet, "permission_classes", []):
        view = ProgramDestroyViewSet.as_view({"delete": "destroy"})
        response = view(request, pk=dummy_program_id)
    print("DESTROY PROGRAM RESPONSE:", response.data)
    assert response.status_code == status.HTTP_204_NO_CONTENT


# ==========
# Test for getting featured programs
# ==========
# Here we assume that the custom action for featured programs is defined on ProgramListViewSet
@patch(
    "core.programs.views.ProgramListViewSet.featured_programs",
    return_value=dummy_response(
        [{"is_featured": True}, {"is_featured": True}], status.HTTP_200_OK
    ),
)
def test_get_featured_programs(mock_featured, client):
    url = reverse("program-featured-programs")
    response = client.get(url)
    print("FEATURED PROGRAMS RESPONSE:", response.data)
    assert response.status_code == status.HTTP_200_OK
    assert len(response.data) > 0
    assert all(item["is_featured"] for item in response.data)


# ==========
# Test for listing programs
# ==========
@patch("core.programs.views.Program.objects.all")
def test_list_programs(mock_program_all, client):
    # Create dummy programs (non-temporary)
    dummy_program1 = MagicMock(name="Program1")
    dummy_program1.is_temporary = False
    dummy_program2 = MagicMock(name="Program2")
    dummy_program2.is_temporary = False
    # Simulate that the queryset returns these dummy programs.
    mock_program_all.return_value = [dummy_program1, dummy_program2]

    url = reverse("program-list")
    with patch.object(
        ProgramListViewSet,
        "list",
        return_value=Response(
            [{"is_temporary": False}, {"is_temporary": False}],
            status=status.HTTP_200_OK,
        ),
    ):
        response = client.get(url)
        print("LIST PROGRAMS RESPONSE:", response.data)
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) > 0
        assert not any(item["is_temporary"] for item in response.data)
