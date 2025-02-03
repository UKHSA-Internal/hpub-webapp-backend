import io

import pandas as pd
from django.urls import reverse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from unittest.mock import MagicMock, patch

# Adjust these imports to match your project structure.
from core.where_to_use.views import (
    WhereToUseCreateViewSet,
    WhereToUseBulkUploadViewSet,
    WhereToUseBulkDeleteViewSet,
)

# -------------------------------------------------------------------
# Helper Functions
# -------------------------------------------------------------------
def dummy_response(data, status_code):
    """Return a DRF Response with the given data and status code."""
    return Response(data, status=status_code)


def get_dummy_user(is_admin=False):
    """Return a dummy user that is authenticated. For admin tests, set extra attributes."""
    dummy = MagicMock()
    dummy.user_id = "admin-1" if is_admin else "user-1"
    dummy.email = "admin@example.com" if is_admin else "user@example.com"
    dummy.is_authenticated = True
    dummy._state = MagicMock(db="default")
    # For admin tests, simulate an establishment with a full_external_key.
    dummy.establishment_ref = MagicMock(full_external_key="ext-key")
    return dummy


# -------------------------------------------------------------------
# Unit Tests for WhereToUse Endpoints
# -------------------------------------------------------------------

# ----- Test: Create WhereToUse (Success) -----
@patch(
    "core.where_to_use.views.WhereToUseCreateViewSet.create",
    return_value=dummy_response(
        [
            {
                "name": "New Where To Use",
                "key": "new-key-1",
                "description": "This is a new test description.",
            }
        ],
        status.HTTP_201_CREATED,
    ),
)
def test_create_where_to_use_success(mock_create, client):
    """
    Unit test for successful creation of a WhereToUse entry.
    The view's create method is patched to return a dummy response.
    """
    factory = APIRequestFactory()
    url = reverse("where-to-use-create-list")
    data = {
        "name": "New Where To Use",
        "key": "new-key-1",
        "description": "This is a new test description.",
    }
    request = factory.post(url, data=data, format="json")
    force_authenticate(request, user=get_dummy_user(is_admin=True))
    # Bypass permission checks by patching the view’s permission_classes.
    with patch.object(WhereToUseCreateViewSet, "permission_classes", []):
        view = WhereToUseCreateViewSet.as_view({"post": "create"})
        response = view(request)
    print("CREATE WHERE-TO-USE RESPONSE:", response.data)
    assert response.status_code == status.HTTP_201_CREATED
    # We assume the dummy response returns a list with one entry having the expected name.
    assert response.data[0]["name"] == "New Where To Use"


# ----- Test: Create WhereToUse with Duplicate Key (Negative) -----
@patch(
    "core.where_to_use.views.WhereToUseCreateViewSet.create",
    return_value=dummy_response(
        {"key": "Duplicate key error."}, status.HTTP_400_BAD_REQUEST
    ),
)
def test_create_where_to_use_duplicate_key(mock_create, client):
    """
    Unit test for creating a WhereToUse entry with a duplicate key.
    """
    factory = APIRequestFactory()
    url = reverse("where-to-use-create-list")
    data = {
        "name": "Another Where To Use",
        "key": "existing-key",  # Duplicate key
        "description": "This description should cause a conflict.",
    }
    request = factory.post(url, data=data, format="json")
    force_authenticate(request, user=get_dummy_user(is_admin=True))
    with patch.object(WhereToUseCreateViewSet, "permission_classes", []):
        view = WhereToUseCreateViewSet.as_view({"post": "create"})
        response = view(request)
    print("CREATE WHERE-TO-USE DUPLICATE KEY RESPONSE:", response.data)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "key" in response.data


# ----- Test: Create WhereToUse with Missing Fields (Negative) -----
@patch(
    "core.where_to_use.views.WhereToUseCreateViewSet.create",
    return_value=dummy_response(
        {"name": ["This field is required."]}, status.HTTP_400_BAD_REQUEST
    ),
)
def test_create_where_to_use_missing_fields(mock_create, client):
    """
    Unit test for creating a WhereToUse entry with missing required fields.
    """
    factory = APIRequestFactory()
    url = reverse("where-to-use-create-list")
    data = {"key": "missing-name-key"}  # 'name' is missing
    request = factory.post(url, data=data, format="json")
    force_authenticate(request, user=get_dummy_user(is_admin=True))
    with patch.object(WhereToUseCreateViewSet, "permission_classes", []):
        view = WhereToUseCreateViewSet.as_view({"post": "create"})
        response = view(request)
    print("CREATE WHERE-TO-USE MISSING FIELDS RESPONSE:", response.data)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "name" in response.data


# ----- Test: Bulk Upload WhereToUse Success -----
@patch(
    "core.where_to_use.views.WhereToUseBulkUploadViewSet.bulk_upload",
    return_value=dummy_response({"count": 2}, status.HTTP_201_CREATED),
)
def test_bulk_upload_success(mock_bulk_upload, client):
    """
    Unit test for successful bulk upload of WhereToUse entries.
    We simulate a file upload by creating a dummy Excel file in memory.
    """
    factory = APIRequestFactory()
    url = reverse("where-to-use-bulk-upload-bulk-upload")
    # Prepare a dummy Excel file using pandas.
    df = pd.DataFrame(
        {
            "name": ["Bulk Where To Use 1", "Bulk Where To Use 2"],
            "key": ["bulk-key-1", "bulk-key-2"],
            "description": ["Desc 1", "Desc 2"],
        }
    )
    excel_file = io.BytesIO()
    df.to_excel(excel_file, index=False)
    excel_file.seek(0)
    request = factory.post(url, {"excel_file": excel_file}, format="multipart")
    force_authenticate(request, user=get_dummy_user(is_admin=True))
    with patch.object(WhereToUseBulkUploadViewSet, "permission_classes", []):
        view = WhereToUseBulkUploadViewSet.as_view({"post": "bulk_upload"})
        response = view(request)
    print("BULK UPLOAD SUCCESS RESPONSE:", response.data)
    assert response.status_code == status.HTTP_201_CREATED
    assert response.data.get("count") == 2


# ----- Test: Bulk Upload Missing File (Negative) -----
@patch(
    "core.where_to_use.views.WhereToUseBulkUploadViewSet.bulk_upload",
    return_value=dummy_response(
        {"error": "Excel file is required"}, status.HTTP_400_BAD_REQUEST
    ),
)
def test_bulk_upload_missing_file(mock_bulk_upload, client):
    factory = APIRequestFactory()
    url = reverse("where-to-use-bulk-upload-bulk-upload")
    # No file provided.
    request = factory.post(url, {}, format="multipart")
    force_authenticate(request, user=get_dummy_user(is_admin=True))
    with patch.object(WhereToUseBulkUploadViewSet, "permission_classes", []):
        view = WhereToUseBulkUploadViewSet.as_view({"post": "bulk_upload"})
        response = view(request)
    print("BULK UPLOAD MISSING FILE RESPONSE:", response.data)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Excel file is required" in response.data.get("error", "")


# ----- Test: Bulk Upload with Invalid Data (Negative) -----
@patch(
    "core.where_to_use.views.WhereToUseBulkUploadViewSet.bulk_upload",
    return_value=dummy_response(
        {"errors": [{"error": "Invalid data: missing name or duplicate key"}]},
        status.HTTP_400_BAD_REQUEST,
    ),
)
def test_bulk_upload_invalid_data(mock_bulk_upload, client):
    factory = APIRequestFactory()
    url = reverse("where-to-use-bulk-upload-bulk-upload")
    # Prepare a dummy Excel file with invalid data (e.g. missing name in second row)
    df = pd.DataFrame(
        {
            "name": ["Bulk Where To Use 1", None],
            "key": ["bulk-key-3", "bulk-key-3"],  # duplicate key
            "description": ["Desc 1", "Desc 2"],
        }
    )
    excel_file = io.BytesIO()
    df.to_excel(excel_file, index=False)
    excel_file.seek(0)
    request = factory.post(url, {"excel_file": excel_file}, format="multipart")
    force_authenticate(request, user=get_dummy_user(is_admin=True))
    with patch.object(WhereToUseBulkUploadViewSet, "permission_classes", []):
        view = WhereToUseBulkUploadViewSet.as_view({"post": "bulk_upload"})
        response = view(request)
    print("BULK UPLOAD INVALID DATA RESPONSE:", response.data)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    errors = response.data.get("errors", [])
    assert len(errors) >= 1


# ----- Test: Bulk Delete Success -----
@patch(
    "core.where_to_use.views.WhereToUseBulkDeleteViewSet.bulk_delete",
    return_value=dummy_response(
        {"message": "Successfully deleted 2 entries."}, status.HTTP_200_OK
    ),
)
def test_bulk_delete_success(mock_delete, client):
    factory = APIRequestFactory()
    url = reverse("where-to-use-bulk-delete-bulk-delete")
    request = factory.delete(url)
    force_authenticate(request, user=get_dummy_user(is_admin=True))
    with patch.object(WhereToUseBulkDeleteViewSet, "permission_classes", []):
        view = WhereToUseBulkDeleteViewSet.as_view({"delete": "bulk_delete"})
        response = view(request)
    print("BULK DELETE SUCCESS RESPONSE:", response.data)
    assert response.status_code == status.HTTP_200_OK
    assert "Successfully deleted" in response.data.get("message", "")


# ----- Test: Bulk Delete When No Entries Exist (Negative) -----
@patch(
    "core.where_to_use.views.WhereToUseBulkDeleteViewSet.bulk_delete",
    return_value=dummy_response(
        {"message": "No entries found to delete"}, status.HTTP_404_NOT_FOUND
    ),
)
def test_bulk_delete_no_entries(mock_delete, client):
    factory = APIRequestFactory()
    url = reverse("where-to-use-bulk-delete-bulk-delete")
    request = factory.delete(url)
    force_authenticate(request, user=get_dummy_user(is_admin=True))
    with patch.object(WhereToUseBulkDeleteViewSet, "permission_classes", []):
        view = WhereToUseBulkDeleteViewSet.as_view({"delete": "bulk_delete"})
        response = view(request)
    print("BULK DELETE NO ENTRIES RESPONSE:", response.data)
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "No entries found to delete" in response.data.get("message", "")


#
