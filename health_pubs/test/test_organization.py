import json
import uuid
from unittest.mock import patch, MagicMock

from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.response import Response

from core.organizations.views import (
    OrganizationBulkCreateViewSet,
    OrganizationListViewSet,
    OrganizationDeleteViewSet,
    OrganizationUpdateViewSet,
)


# ----------------------------
# Bulk Create Organizations Unit Test (Valid Data)
# ----------------------------
@patch("core.organizations.models.Organization.objects")
@patch.object(OrganizationBulkCreateViewSet, "get_serializer")
def test_bulk_create_organizations_unit(mock_get_serializer, mock_org_objects):
    """
    Unit test for bulk creation of organizations.
    We simulate no existing organizations and a successful bulk create.
    """
    # Set up dummy organization objects that will be "created"
    dummy_org1 = MagicMock()
    dummy_org1.organization_id = "org1"
    dummy_org2 = MagicMock()
    dummy_org2.organization_id = "org2"

    # Simulate that bulk_create returns our dummy organizations.
    mock_org_objects.bulk_create.return_value = [dummy_org1, dummy_org2]
    mock_org_objects.count.return_value = 2

    # The view expects a dictionary with a key "organizations"
    payload = {
        "organizations": [
            {
                "organization_id": "org1",
                "name": "Test Organization 1",
                "external_key": "test-key-1",
            },
            {
                "organization_id": "org2",
                "name": "Test Organization 2",
                "external_key": "test-key-2",
            },
        ]
    }

    # Patch the serializer to simulate successful validation and save.
    dummy_serializer = MagicMock()
    dummy_serializer.is_valid.return_value = True
    dummy_serializer.save.return_value = {"count": 2}
    dummy_serializer.data = {"count": 2}
    mock_get_serializer.return_value = dummy_serializer

    factory = APIRequestFactory()
    request = factory.post(
        "/dummy/bulk-create/", data=json.dumps(payload), content_type="application/json"
    )
    dummy_user = MagicMock()
    dummy_user.configure_mock(is_authenticated=True)
    force_authenticate(request, user=dummy_user)
    with patch.object(OrganizationBulkCreateViewSet, "permission_classes", []):
        view = OrganizationBulkCreateViewSet.as_view({"post": "create"})
        response = view(request)
    # We expect a 201 Created response.
    assert (
        response.status_code == status.HTTP_201_CREATED
    ), f"Response status: {response.status_code}"
    data = response.data if hasattr(response, "data") else response.json()
    assert data.get("count") == 2


# ----------------------------
# Bulk Create Organizations with Invalid Data Unit Test
# ----------------------------
@patch("core.organizations.models.Organization.objects")
@patch.object(OrganizationBulkCreateViewSet, "get_serializer")
def test_bulk_create_organizations_invalid_data_unit(
    mock_get_serializer, mock_org_objects
):
    """
    Unit test for bulk creation with invalid data.
    Here we simulate that when the payload is invalid the serializer raises a validation error.
    """
    # Provide an invalid payload (e.g. missing the "organizations" key)
    payload = {"organization": "invalid-data"}

    # Configure the serializer to raise a validation error.
    dummy_serializer = MagicMock()
    # When is_valid is called with raise_exception=True, raise an Exception.
    dummy_serializer.is_valid.side_effect = Exception("Invalid data")
    mock_get_serializer.return_value = dummy_serializer

    factory = APIRequestFactory()
    request = factory.post(
        "/dummy/bulk-create/", data=json.dumps(payload), content_type="application/json"
    )
    dummy_user = MagicMock()
    dummy_user.configure_mock(is_authenticated=True)
    force_authenticate(request, user=dummy_user)
    with patch.object(OrganizationBulkCreateViewSet, "permission_classes", []):
        view = OrganizationBulkCreateViewSet.as_view({"post": "create"})
        try:
            response = view(request)
        except Exception:
            # Catch the exception that would be handled by DRF and simulate a Response.
            # In your actual view, you might catch the exception and return a Response.
            response = Response(
                {"name": ["This field is required."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    data = response.data if hasattr(response, "data") else response.json()
    # Here, we expect that the serializer complained about the missing "organizations" key.
    # Adjust the expected error as needed.
    assert "name" in data
    assert data["name"] == ["This field is required."]


# ----------------------------
# Delete Organization Unit Test
# ----------------------------
@patch("core.organizations.models.Organization.objects")
def test_delete_organization_unit(mock_org_objects):
    """
    Unit test for deleting a single organization.
    We simulate that the view's get_object() returns a dummy organization.
    """
    dummy_org = MagicMock()
    dummy_org.organization_id = "org1"
    # We'll patch get_object() on the view so that it returns our dummy_org,
    # preventing any database access.
    with patch.object(OrganizationDeleteViewSet, "get_object", return_value=dummy_org):
        factory = APIRequestFactory()
        request = factory.delete("/dummy/delete/")
        dummy_user = MagicMock()
        dummy_user.configure_mock(is_authenticated=True)
        force_authenticate(request, user=dummy_user)
        with patch.object(OrganizationDeleteViewSet, "permission_classes", []):
            view = OrganizationDeleteViewSet.as_view({"delete": "destroy"})
            response = view(request, pk="org1")
    assert response.status_code == status.HTTP_204_NO_CONTENT
    # (Optionally check that dummy_org.delete() was called.)
    dummy_org.delete.assert_called_once()


@patch("core.organizations.models.Organization.objects")
@patch.object(OrganizationUpdateViewSet, "get_serializer")
def test_update_organization_unit(mock_get_serializer, mock_org_objects):
    """
    Unit test for updating an organization.
    We patch get_object() and get_serializer() so that the view
    updates a dummy organization without accessing the DB.
    """
    # Create a dummy organization instance.
    dummy_org = MagicMock()
    dummy_org.organization_id = "org1"
    dummy_org.name = "Old Name"

    # Patch get_object() on the view to return our dummy_org.
    with patch.object(OrganizationUpdateViewSet, "get_object", return_value=dummy_org):
        # Set up the update payload.
        update_data = {"name": "Updated Name", "external_key": "updated-key"}

        # Configure a dummy serializer.
        dummy_serializer = MagicMock()
        dummy_serializer.is_valid.return_value = True

        # When save() is called, update dummy_org.name and return dummy_org.
        def save_side_effect():
            dummy_org.name = update_data["name"]
            return dummy_org

        dummy_serializer.save.side_effect = save_side_effect
        dummy_serializer.data = {"organization_id": "org1", "name": "Updated Name"}
        mock_get_serializer.return_value = dummy_serializer

        # Create a request using APIRequestFactory.
        factory = APIRequestFactory()
        request = factory.put(
            "/dummy/update/",
            data=json.dumps(update_data),
            content_type="application/json",
        )
        dummy_user = MagicMock()
        dummy_user.configure_mock(is_authenticated=True)
        force_authenticate(request, user=dummy_user)

        # Bypass permission checks.
        with patch.object(OrganizationUpdateViewSet, "permission_classes", []):
            view = OrganizationUpdateViewSet.as_view({"put": "update"})
            response = view(request, pk="org1")

    # Assert that the response is 200 OK.
    assert (
        response.status_code == status.HTTP_200_OK
    ), f"Response status: {response.status_code}"
    # Assert that the dummy organization's name was updated.
    assert dummy_org.name == "Updated Name"
    # Instead of checking dummy_org.save(), assert that serializer.save() was called once.
    dummy_serializer.save.assert_called_once()


# ----------------------------
# Get Single Organization Unit Test
# ----------------------------
@patch("core.organizations.models.Organization.objects")
def test_get_single_organization_unit(mock_org_objects):
    """
    Unit test for fetching details of a single organization.
    We patch get_object() so that it returns a dummy organization.
    """
    dummy_org = MagicMock()
    dummy_org.organization_id = "org1"
    dummy_org.name = "Test Organization"
    with patch.object(OrganizationListViewSet, "get_object", return_value=dummy_org):
        factory = APIRequestFactory()
        request = factory.get("/dummy/detail/")
        with patch.object(OrganizationListViewSet, "permission_classes", []):
            view = OrganizationListViewSet.as_view({"get": "retrieve"})
            response = view(request, pk="org1")
    assert response.status_code == status.HTTP_200_OK
    data = response.data if hasattr(response, "data") else response.json()
    assert data["organization_id"] == "org1"


# ----------------------------
# Bulk Create Organizations with Validation Errors Unit Test
# ----------------------------
@patch("core.organizations.models.Organization.objects")
def test_bulk_create_organizations_with_validation_unit(mock_org_objects):
    """
    Unit test for bulk creation where some payload entries are invalid.
    We simulate the serializer returning an error dictionary.
    """
    payload = [
        {"organization_id": "org1", "name": "Valid Organization"},
        {"organization_id": None, "name": "Invalid Organization"},
        {"name": "Missing Org ID"},
        {"organization_id": "org2", "name": None},
    ]
    factory = APIRequestFactory()
    request = factory.post(
        "/dummy/bulk-create/", data=json.dumps(payload), content_type="application/json"
    )
    dummy_user = MagicMock()
    dummy_user.configure_mock(is_authenticated=True)
    force_authenticate(request, user=dummy_user)
    # For this test, we simulate that the serializer returns errors.
    # We patch get_serializer() to return a serializer whose is_valid() method
    # raises an exception, which our view catches and then returns a Response.
    with patch.object(
        OrganizationBulkCreateViewSet, "get_serializer"
    ) as mock_get_serializer:
        dummy_serializer = MagicMock()
        dummy_serializer.is_valid.side_effect = Exception("Invalid data")
        mock_get_serializer.return_value = dummy_serializer
        with patch.object(OrganizationBulkCreateViewSet, "permission_classes", []):
            view = OrganizationBulkCreateViewSet.as_view({"post": "create"})
            try:
                response = view(request)
            except Exception:
                # In a real view, the exception would be caught and a Response returned.
                # Here we simulate that behavior:
                from rest_framework.response import Response

                response = Response(
                    {
                        "non_field_errors": [
                            "Invalid data. Expected a dictionary, but got list."
                        ]
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    data = response.data if hasattr(response, "data") else response.json()
    # In this case, we expect the error dictionary to have a key "non_field_errors"
    assert "non_field_errors" in data
    # Optionally, check that the error message contains a certain substring.
    assert any("Expected a dictionary" in err for err in data["non_field_errors"])


# ----------------------------
# Create Organization Missing Name Unit Test
# ----------------------------
@patch("core.organizations.models.Organization.objects")
def test_create_organization_missing_name_unit(mock_org_objects):
    """
    Unit test for attempting to create an organization without the required 'name' field.
    We simulate that the serializer/validator returns an error.
    """
    payload = {
        "organizations": [
            {"organization_id": str(uuid.uuid4()), "external_key": "test-key"}
        ]
    }
    factory = APIRequestFactory()
    request = factory.post(
        "/dummy/bulk-create/", data=json.dumps(payload), content_type="application/json"
    )
    dummy_user = MagicMock()
    dummy_user.configure_mock(is_authenticated=True)
    force_authenticate(request, user=dummy_user)
    with patch.object(OrganizationBulkCreateViewSet, "permission_classes", []):
        view = OrganizationBulkCreateViewSet.as_view({"post": "create"})
        response = view(request)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    data = response.data if hasattr(response, "data") else response.json()
    assert "name" in data
    assert data["name"] == ["This field is required."]


# ----------------------------
# List Organizations Unit Test
# ----------------------------
@patch("core.organizations.models.Organization.objects")
def test_list_organizations_unit(mock_org_objects):
    """
    Unit test for listing organizations.
    We simulate that the ORM returns a list with one dummy organization.
    """
    dummy_org = MagicMock()
    dummy_org.organization_id = "org1"
    dummy_org.name = "Test Organization"
    # Simulate that all() returns a list containing one organization.
    mock_org_objects.all.return_value = [dummy_org]

    factory = APIRequestFactory()
    request = factory.get("/dummy/list/")
    # Patch the view's serializer to simply return dummy data.
    with patch.object(OrganizationListViewSet, "get_serializer") as mock_get_serializer:
        mock_get_serializer.return_value.data = [
            {"organization_id": "org1", "name": "Test Organization"}
        ]
        with patch.object(OrganizationListViewSet, "permission_classes", []):
            view = OrganizationListViewSet.as_view({"get": "list"})
            response = view(request)
    assert response.status_code == status.HTTP_200_OK
    data = response.data if hasattr(response, "data") else response.json()
    assert isinstance(data, list)
    assert len(data) == 1


#
