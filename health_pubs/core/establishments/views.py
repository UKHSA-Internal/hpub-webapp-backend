import logging
import uuid

import pandas as pd
from core.errors.enums import ErrorCode, ErrorMessage
from core.errors.error_function import handle_error
from core.organizations.models import Organization
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
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet, ViewSet
from wagtail.models import Page

from .models import Establishment
from .serializers import EstablishmentSerializer

logger = logging.getLogger(__name__)


class EstablishmentCreateViewSet(ModelViewSet):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]
    queryset = Establishment.objects.all()
    serializer_class = EstablishmentSerializer

    def create(self, request, *args, **kwargs):
        if "bulk" in request.query_params:
            return EstablishmentBulkCreateViewSet().bulk_create(request)
        return super().create(request, *args, **kwargs)


class EstablishmentBulkCreateViewSet(ViewSet):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    queryset = Establishment.objects.all()
    serializer_class = EstablishmentSerializer

    @action(detail=False, methods=["post"], url_path="bulk-create")
    def bulk_create(self, request, *args, **kwargs):
        self.permission_classes = [IsAdminUser]
        data = request.data

        if not isinstance(data, list):
            return Response(
                {"error": "Data must be a list of establishment objects."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created_entries = []
        errors = []

        # Initialize or get the parent page
        try:
            parent_page = Page.objects.get(slug="establishments")
        except Page.DoesNotExist:
            root_page = (
                Page.objects.first()
            )  # Adjust this if your root page is different
            parent_page = Page(
                title="Establishments",
                slug="establishments",
                content_type=ContentType.objects.get_for_model(Page),
            )
            root_page.add_child(instance=parent_page)
            parent_page.save()
            logger.info("Parent page 'establishments' created.")

        for item in data:
            name = item.get("name")
            external_key = item.get("external_key", None)
            full_external_key = item.get("full_external_key", None)
            organization_id = item.get("organization_ref")
            establishment_id = item.get("establishment_id")

            if not name or not organization_id:
                errors.append(
                    {"error": f"Missing required fields for establishment: {item}"}
                )
                continue

            # Get the related Organization instance
            try:
                organization = Organization.objects.get(organization_id=organization_id)
            except Organization.DoesNotExist:
                errors.append(
                    {
                        "error": f"Organization with ID '{organization_id}' not found for establishment '{name}'."
                    }
                )
                continue

            # Check if the establishment already exists
            if Establishment.objects.filter(establishment_id=establishment_id).exists():
                errors.append(
                    {
                        "error": f'Entry with establishment_id "{establishment_id}" already exists.'
                    }
                )
                continue

            # Generate slug for the establishment
            slug = slugify(name)
            unique_slug = self.get_unique_slug(slug)

            # Create the establishment instance
            establishment_instance = Establishment(
                establishment_id=establishment_id,
                name=name,
                external_key=external_key or None,
                full_external_key=full_external_key or None,
                organization_ref=organization,
                slug=unique_slug,
                title=name,  # Using name as title for the page
            )

            try:
                # Create establishment as a child of the parent page
                parent_page.add_child(instance=establishment_instance)
                parent_page.save()

                created_entries.append(
                    EstablishmentSerializer(establishment_instance).data
                )
                logger.info(f"Establishment entry '{name}' created successfully.")
            except Exception as e:
                errors.append({"error": f"Failed to create entry '{name}': {str(e)}"})
                logger.error(f"Failed to create establishment entry '{name}': {str(e)}")

        if created_entries:
            return Response(
                {"created": created_entries, "errors": errors},
                status=status.HTTP_201_CREATED,
            )
        else:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)

    def get_unique_slug(self, base_slug):
        """Generate a unique slug for the Establishment."""
        queryset = Establishment.objects.filter(slug__startswith=base_slug)
        if not queryset.exists():
            return base_slug

        num = queryset.count() + 1
        return f"{base_slug}-{num}"


class EstablishmentListViewSet(ReadOnlyModelViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    queryset = Establishment.objects.all()
    serializer_class = EstablishmentSerializer

    def list(self, request, *args, **kwargs):
        """Retrieve all establishments."""
        try:
            establishments = Establishment.objects.all()

            if not establishments.exists():
                return Response(
                    {"message": "No establishments found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            serializer = self.get_serializer(establishments, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error fetching all establishments: {str(e)}")
            return Response(
                {"error": f"An error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class EstablishmentsByOrganizationViewSet(viewsets.ModelViewSet):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated]

    queryset = Establishment.objects.all()
    serializer_class = EstablishmentSerializer

    @action(detail=False, methods=["get"], url_path="by-organization")
    def get_by_organization(self, request):
        """Retrieve establishments by organization_id."""
        organization_id = request.query_params.get("organization_id")

        if not organization_id:
            return Response(
                {"error": "organization_id query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            establishments = Establishment.objects.filter(
                organization_ref__organization_id=organization_id
            )

            if not establishments.exists():
                return Response(
                    {"error": "No establishments found for this organization_id."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            serializer = self.get_serializer(establishments, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Organization.DoesNotExist:
            return Response(
                {"error": f"Organization with id {organization_id} does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            logger.error(
                f"Error fetching establishments for organization_id {organization_id}: {str(e)}"
            )
            return Response(
                {"error": f"An error occurred: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class EstablishmentBulkUploadViewSet(ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    @action(detail=False, methods=["post"], url_path="bulk-upload")
    def bulk_upload(self, request, *args, **kwargs):
        self.authentication_classes = [
            SessionAuthentication
        ]  # Optional: Use session-based auth for this endpoint.
        self.permission_classes = [AllowAny]
        # Retrieve or create the parent page
        try:
            parent_page = Page.objects.get(slug="establishment-bulk-upload")
            logger.info("Parent page 'establishment-bulk-upload' found.")
        except Page.DoesNotExist:
            try:
                root_page = Page.objects.first()
                parent_page = Page(
                    title="EstablishmentBulkUpload",
                    slug="establishment-bulk-upload",
                    content_type=ContentType.objects.get_for_model(Page),
                )
                root_page.add_child(instance=parent_page)
                logger.info("Parent page 'establishment-bulk-upload' created.")
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
            full_external_key = row.get("full_external_key")
            organization_id = row.get("organization_id")
            establishment_id = row.get("establishment_id")

            if pd.isna(name) or pd.isna(external_key):
                errors.append(
                    {"error": f"Missing name or external_key for entry: {name}"}
                )
                continue

            # Get the related Organization instance
            try:
                organization = Organization.objects.get(organization_id=organization_id)
            except Organization.DoesNotExist:
                errors.append(
                    {
                        "error": f"Organization with ID '{organization_id}' not found for establishment '{name}'."
                    }
                )
                continue

            # Check if the entry already exists
            if Establishment.objects.filter(establishment_id=establishment_id).exists():
                errors.append(
                    {
                        "error": f'Entry with establishment_id "{establishment_id}" already exists.'
                    }
                )
                continue

            # Create the new Establishment instance
            establishment_instance = Establishment(
                title=name,
                establishment_id=establishment_id
                or str(uuid.uuid4()),  # Generate UUID if not provided
                name=name,
                external_key=external_key,
                full_external_key=full_external_key,
                organization_ref=organization,
            )

            try:
                # Add as child page under the parent page
                parent_page.add_child(instance=establishment_instance)
                establishment_instance.save()
                created_entries.append(
                    EstablishmentSerializer(establishment_instance).data
                )
                logger.info(f"Establishment entry '{name}' created successfully.")
            except ValidationError as e:
                errors.append(
                    {"error": f"Validation error for entry '{name}': {str(e)}"}
                )
                logger.error(f"Validation error for entry '{name}': {str(e)}")
            except Exception as e:
                errors.append({"error": f"Failed to create entry '{name}': {str(e)}"})
                logger.error(f"Failed to create establishment entry '{name}': {str(e)}")

        if created_entries:
            return Response(
                {"created": created_entries, "errors": errors},
                status=status.HTTP_201_CREATED,
            )
        else:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)


class EstablishmentDeleteViewSet(ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def delete(self, request, *args, **kwargs):
        """Handle bulk deletion."""
        ids = request.data.get("ids", [])
        if not ids or not isinstance(ids, list):
            return handle_error(
                ErrorCode.MISSING_FIELD,
                ErrorMessage.MISSING_FIELD,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        establishments_to_delete = Establishment.objects.filter(
            establishment_id__in=ids
        )
        if not establishments_to_delete.exists():
            return handle_error(
                ErrorCode.NOT_FOUND,
                ErrorMessage.NOT_FOUND,
                status_code=status.HTTP_404_NOT_FOUND,
            )

        try:
            delete_counts = establishments_to_delete.delete()
            logging.info(f"Delete counts: {delete_counts}")
            # Retrieve the count of deleted Establishment objects
            count = delete_counts[1].get(
                f"{Establishment._meta.app_label}.{Establishment._meta.model_name}", 0
            )

            logger.info(f"Deleted {count} establishments with IDs: {ids}")

            return Response(
                {"message": f"Successfully deleted {count} establishments."},
                status=status.HTTP_200_OK,
            )

        except DatabaseError as e:
            logger.error(f"DatabaseError while deleting establishments: {e}")
            return handle_error(
                ErrorCode.DATABASE_ERROR,
                ErrorMessage.DATABASE_ERROR,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception:
            logger.exception("Unexpected error occurred while deleting establishments.")
            return handle_error(
                ErrorCode.INTERNAL_SERVER_ERROR,
                ErrorMessage.INTERNAL_SERVER_ERROR,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["delete"], url_path="delete-all")
    def delete_all(self, request, *args, **kwargs):
        self.authentication_classes = [
            SessionAuthentication
        ]  # Optional: Use session-based auth for this endpoint.
        self.permission_classes = [AllowAny]
        """Delete all establishments."""
        try:
            deleted_count = Establishment.objects.all().delete()

            logger.info(f"Deleted {deleted_count} establishments.")

            return Response(
                {"message": f"Successfully deleted {deleted_count} establishments."},
                status=status.HTTP_200_OK,
            )
        except DatabaseError:
            logger.exception("Database error while deleting all establishments.")
            return handle_error(
                ErrorCode.DATABASE_ERROR,
                ErrorMessage.DATABASE_ERROR,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception:
            logger.exception(
                "Unexpected error occurred while deleting all establishments."
            )
            return handle_error(
                ErrorCode.INTERNAL_SERVER_ERROR,
                ErrorMessage.INTERNAL_SERVER_ERROR,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


#
