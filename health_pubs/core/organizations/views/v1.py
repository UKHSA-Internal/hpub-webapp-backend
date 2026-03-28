import logging
import uuid

import pandas as pd
from core.errors.enums import ErrorCode, ErrorMessage
from core.errors.error_function import handle_error
from core.users.permissions import IsAdminOrRegisteredUser, IsAdminUser
from core.utils.custom_token_authentication import CustomTokenAuthentication
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.utils.text import slugify
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from wagtail.models import Page

from core.organizations.models import Organization
from core.organizations.serializers import OrganizationSerializer

logger = logging.getLogger(__name__)


class OrganizationCreateViewSet(viewsets.ModelViewSet):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminOrRegisteredUser]
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer


class OrganizationUpdateViewSet(viewsets.ModelViewSet):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer

    @action(detail=True, methods=["patch"], url_path="update")
    def update_organization(self, request, pk=None):
        """
        Update an existing organization's details.
        """
        try:
            organization = self.get_object()
        except Organization.DoesNotExist:
            return Response(
                {"error": f"Organization with id {pk} does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = self.get_serializer(organization, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            logger.info(f"Organization '{organization.name}' updated successfully.")
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            logger.error(
                f"Validation failed for updating organization: {serializer.errors}"
            )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class OrganizationListViewSet(viewsets.ReadOnlyModelViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer


class OrganizationBulkCreateViewSet(viewsets.ModelViewSet):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer

    @action(detail=False, methods=["post"], url_path="bulk-create")
    def bulk_create(self, request, *args, **kwargs):
        data = request.data
        if not isinstance(data, list):
            return Response(
                {"error": "Data must be a list of organizations."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Initialize or get the parent page
        try:
            parent_page = Page.objects.get(slug="organizations")
        except Page.DoesNotExist:
            root_page = (
                Page.objects.first()
            )  # Adjust this if your root page is different
            parent_page = Page(
                title="Organizations",
                slug="organizations",
                content_type=ContentType.objects.get_for_model(Page),
            )
            root_page.add_child(instance=parent_page)
            root_page.save()  # Ensure the parent page is saved
            logger.info("Parent page 'organizations' created.")

        # Prepare data for bulk upload
        organizations = []
        errors = []

        for index, item in enumerate(data, start=1):
            # Validate required fields
            organization_id = item.get("organization_id")
            name = item.get("name")

            if not organization_id or not isinstance(organization_id, str):
                errors.append(
                    {
                        "organization_id": f"Organization ID is required and must be a string at index {index}."
                    }
                )
            if not name or not isinstance(name, str):
                errors.append(
                    {"name": f"Name is required and must be a string at index {index}."}
                )

            if errors:
                continue  # Skip to the next item if there are validation errors

            # Assign a default title if not provided
            title = "organization_title"
            slug = slugify(title + str(index))
            unique_slug = self.get_unique_slug(slug)

            external_key = item.get("external_key", None)

            # Create the Organization instance
            organization = Organization(
                organization_id=organization_id,
                name=name,
                external_key=external_key or None,
                title=title,
                slug=unique_slug,
                content_type=ContentType.objects.get_for_model(Organization),
            )
            organizations.append(organization)

        # If there are any errors, return them
        if errors:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)

        # Add each organization to the parent page
        for organization in organizations:
            if not parent_page.get_children().exists():
                organization.depth = parent_page.depth + 1
                organization.path = parent_page.path + "0001"
                organization.numchild = 0
                organization.save()
                parent_page.numchild += 1
                parent_page.save()
            else:
                parent_page.add_child(instance=organization)

            logger.info(
                f"Organization '{organization.title}' added under page '{parent_page.title}'."
            )

        return Response(
            {
                "message": "Organizations successfully uploaded.",
                "count": len(organizations),
            },
            status=status.HTTP_201_CREATED,
        )

    def get_unique_slug(self, base_slug):
        """Generate a unique slug for the Organization."""
        queryset = Organization.objects.filter(slug__startswith=base_slug)
        if not queryset.exists():
            return base_slug

        num = queryset.count() + 1
        return f"{base_slug}-{num}"


class OrganizationDeleteViewSet(viewsets.ModelViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer

    @action(detail=False, methods=["delete"], url_path="bulk-delete")
    def bulk_delete(self, request, *args, **kwargs):
        try:
            # Retrieve all Organization entries
            entries = Organization.objects.all()

            if not entries.exists():
                return Response(
                    {"message": "No entries found to delete."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Delete all entries
            count = entries.delete()

            logger.info(
                f"Deleted all Organization entries successfully. Count: {count}"
            )
            return Response(
                {"message": f"Successfully deleted {count} entries."},
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            logger.error(f"Error deleting entries: {str(e)}")
            return Response(
                {"error": f"Failed to delete entries: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def delete(self, request, *args, **kwargs):
        ids = request.data.get("ids", [])
        if not ids or not isinstance(ids, list):
            return handle_error(
                ErrorCode.MISSING_FIELD,
                ErrorMessage.MISSING_FIELD,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        organizations_to_delete = Organization.objects.filter(organization_id__in=ids)

        if not organizations_to_delete.exists():
            return handle_error(
                ErrorCode.NOT_FOUND,
                ErrorMessage.NOT_FOUND,
                status_code=status.HTTP_404_NOT_FOUND,
            )

        try:
            count = organizations_to_delete.delete()[
                0
            ]  # delete() returns a tuple, where the first item is the count of deleted objects
            logger.info(f"Deleted {count} organizations with IDs: {ids}")
            return Response(
                {"message": f"Successfully deleted {count} organizations."},
                status=status.HTTP_200_OK,
            )
        except DatabaseError as e:
            logger.error(f"DatabaseError while deleting organizations: {e}")
            return handle_error(
                ErrorCode.DATABASE_ERROR,
                ErrorMessage.DATABASE_ERROR,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception:
            logger.exception("Unexpected error occurred while deleting organizations.")
            return handle_error(
                ErrorCode.INTERNAL_SERVER_ERROR,
                ErrorMessage.INTERNAL_SERVER_ERROR,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class OrganizationBulkUploadViewSet(viewsets.ModelViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer

    @action(detail=False, methods=["post"], url_path="bulk-upload")
    def bulk_upload(self, request, *args, **kwargs):
        # Retrieve or create the parent page
        try:
            parent_page = Page.objects.get(slug="organization-bulk-upload")
            logger.info("Parent page 'organization-bulk-upload' found.")
        except Page.DoesNotExist:
            try:
                root_page = Page.objects.first()
                parent_page = Page(
                    title="OrganizationBulkUpload",
                    slug="organization-bulk-upload",
                    content_type=ContentType.objects.get_for_model(Page),
                )
                root_page.add_child(instance=parent_page)
                logger.info("Parent page 'organization-bulk-upload' created.")
            except Exception as ex:
                logger.error("Failed to create parent page: %s", str(ex))
                return Response(
                    {"error": "Failed to create parent page."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        # Check if parent page is valid
        if not isinstance(parent_page, Page):
            return Response(
                {"error": "Parent page could not be retrieved or created."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Upload Excel file
        excel_file = request.FILES.get("excel_file")
        if not excel_file:
            return Response(
                {"error": "Excel file is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Read Excel file using pandas
        try:
            df = pd.read_excel(excel_file)
        except Exception as e:
            logger.error(f"Error reading Excel file: {str(e)}")
            return Response(
                {"error": f"Failed to read the Excel file: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created_entries = []
        errors = []

        for _, row in df.iterrows():
            name = row.get("name")
            external_key = row.get("external_key")
            organization_id = row.get("id")

            if pd.isna(name) or pd.isna(external_key):
                errors.append(
                    {"error": f"Missing name or external_key for entry: {name}"}
                )
                continue

            # Check if the entry already exists
            if Organization.objects.filter(external_key=external_key).exists():
                errors.append(
                    {
                        "error": f'Entry with external_key "{external_key}" already exists.'
                    }
                )
                continue

            # Create the new Organization instance
            organization_instance = Organization(
                title=name,
                organization_id=organization_id
                or str(uuid.uuid4()),  # Generate UUID if not provided
                name=name,
                external_key=external_key,
            )

            try:
                # Add as child page under the parent page
                parent_page.add_child(instance=organization_instance)
                organization_instance.save()
                created_entries.append(
                    OrganizationSerializer(organization_instance).data
                )
                logger.info(f"Organization entry '{name}' created successfully.")
            except ValidationError as e:
                errors.append(
                    {"error": f"Validation error for entry '{name}': {str(e)}"}
                )
                logger.error(f"Validation error for entry '{name}': {str(e)}")
            except Exception as e:
                errors.append({"error": f"Failed to create entry '{name}': {str(e)}"})
                logger.error(f"Failed to create organization entry '{name}': {str(e)}")

        if created_entries:
            return Response(
                {"created": created_entries, "errors": errors},
                status=status.HTTP_201_CREATED,
            )
        else:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)


#
