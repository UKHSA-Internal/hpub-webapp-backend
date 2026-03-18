import logging

import pandas as pd
from core.users.permissions import IsAdminUser
from core.utils.custom_token_authentication import CustomTokenAuthentication
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from wagtail.models import Page
from django.shortcuts import get_object_or_404

from .models import WhereToUse
from .serializers import WhereToUseSerializer

logger = logging.getLogger(__name__)


class WhereToUseCreateViewSet(viewsets.ViewSet):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def create(self, request):
        # Retrieve or create the parent page for where-to-use
        try:
            parent_page = Page.objects.get(slug="where-to-use")
            logger.info("Parent page 'where-to-use' found.")
        except Page.DoesNotExist:
            try:
                root_page = Page.objects.first()
                parent_page = Page(
                    title="WhereToUse",
                    slug="where-to-use",
                    content_type=ContentType.objects.get_for_model(Page),
                )
                root_page.add_child(instance=parent_page)
                logger.info("Parent page 'where-to-use' created.")
            except Exception as ex:
                logger.error("Failed to create parent page: %s", str(ex))
                return Response(
                    {"error": "Failed to create parent page."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        # Handle single or multiple entries
        entries = request.data if isinstance(request.data, list) else [request.data]
        created_entries = []

        for entry in entries:
            # Extract title or use a default value
            title = "WhereToUse Title"
            slug = slugify(title + str(timezone.now()))

            # Validate the serializer for each entry
            serializer = WhereToUseSerializer(data=entry)
            if serializer.is_valid():
                # Extract validated data from serializer
                data = serializer.validated_data

                # Create the new WhereToUse page
                where_to_use_instance = WhereToUse(
                    title=title,
                    slug=slug,
                    name=data.get("name"),
                    key=data.get("key"),
                    description=data.get("description", ""),
                )

                # Use Wagtail's add_child method to create the page properly
                try:
                    parent_page.add_child(instance=where_to_use_instance)
                    where_to_use_instance.save()
                    logger.info(f"WhereToUse page '{title}' created successfully.")
                    created_entries.append(
                        WhereToUseSerializer(where_to_use_instance).data
                    )
                except Exception as e:
                    logger.error(
                        f"Error adding where-to-use '{title}' as child page: {str(e)}"
                    )
                    return Response(
                        {"error": f"Failed to create where-to-use page '{title}'."},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )
            else:
                logger.error(f"Invalid data for where-to-use: {serializer.errors}")
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return JsonResponse(created_entries, safe=False, status=201)


class WhereToUseListViewSet(viewsets.ViewSet):
    """
    Default = public list (Session + AllowAny)
    Admin-only retrieve is moved to a dedicated @action.
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    # PUBLIC LIST
    def list(self, request):
        objs = WhereToUse.objects.all()
        ser = WhereToUseSerializer(objs, many=True)
        return Response(ser.data)

    # ADMIN-ONLY RETRIEVE ACTION
    @action(
        detail=False,
        methods=["get"],
        url_path=r"retrieve/(?P<pk>[^/]+)",
        authentication_classes=[CustomTokenAuthentication],
        permission_classes=[IsAuthenticated, IsAdminUser],
    )
    def retrieve_item(self, request, pk=None):
        """
        Replaces the standard retrieve() method.
        Requires CustomToken + Admin.
        """
        try:
            obj = WhereToUse.objects.get(where_to_use_id=pk)
        except WhereToUse.DoesNotExist:
            return Response({"error": "Location not found"}, status=404)

        ser = WhereToUseSerializer(obj)
        return Response(ser.data)


class WhereToUseUpdateViewSet(viewsets.ViewSet):
    """
    Update or partially update a WhereToUse entry.
    Supports PUT and PATCH.
    """

    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def update(self, request, pk=None):
        instance = get_object_or_404(WhereToUse, pk=pk)
        serializer = WhereToUseSerializer(instance, data=request.data, partial=False)

        serializer.is_valid(raise_exception=True)

        # Update fields manually for Wagtail Page safe updating
        for attr, value in serializer.validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return Response(serializer.data)

    def partial_update(self, request, pk=None):
        instance = get_object_or_404(WhereToUse, pk=pk)
        serializer = WhereToUseSerializer(instance, data=request.data, partial=True)

        serializer.is_valid(raise_exception=True)

        for attr, value in serializer.validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return Response(serializer.data)


class WhereToUseBulkUploadViewSet(viewsets.ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    @action(detail=False, methods=["post"], url_path="bulk-upload")
    def bulk_upload(self, request, *args, **kwargs):
        # Retrieve or create the parent page
        try:
            parent_page = Page.objects.get(slug="where-to-use-bulk")
            logger.info("Parent page 'where-to-use-bulk' found.")
        except Page.DoesNotExist:
            try:
                root_page = Page.objects.first()
                parent_page = Page(
                    title="WhereToUseBulk",
                    slug="where-to-use-bulk",
                    content_type=ContentType.objects.get_for_model(Page),
                )
                root_page.add_child(instance=parent_page)
                parent_page.save_revision().publish()  # Ensure it's published
                logger.info("Parent page 'where-to-use-bulk' created.")
            except Exception as ex:
                logger.error("Failed to create parent page: %s", str(ex))
                return Response(
                    {"error": "Failed to create parent page."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        # Upload Excel file
        excel_file = request.FILES.get("excel_file")
        if not excel_file:
            logger.warning("Excel file is required.")
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

        for index, row in df.iterrows():
            name = row.get("name")
            key = row.get("key")
            description = row.get("description")
            where_to_use_id = row.get("id")

            logger.info(f"Processing WhereToUse entry ID: {where_to_use_id}")

            if pd.isna(name) or pd.isna(key):
                error_msg = f"Missing name or key for entry at row {index + 1}."
                errors.append({"error": error_msg})
                logger.warning(error_msg)
                return Response(
                    {"errors": errors}, status=status.HTTP_400_BAD_REQUEST
                )  # Stop processing

            # Check if the entry already exists
            if WhereToUse.objects.filter(key=key).exists():
                error_msg = f'Entry with key "{key}" already exists at row {index + 1}.'
                errors.append({"error": error_msg})
                logger.warning(error_msg)
                return Response(
                    {"errors": errors}, status=status.HTTP_400_BAD_REQUEST
                )  # Stop processing

            slug = slugify(name + str(timezone.now()))

            # Create the new WhereToUse page
            where_to_use_instance = WhereToUse(
                title=name,
                slug=slug,
                where_to_use_id=where_to_use_id,
                name=name,
                key=key,
                description=description or "",
            )

            try:
                # Add as child page under the parent page
                parent_page.add_child(instance=where_to_use_instance)
                where_to_use_instance.save()
                created_entries.append(WhereToUseSerializer(where_to_use_instance).data)
                logger.info(f"WhereToUse entry '{name}' created successfully.")
            except ValidationError as e:
                error_msg = (
                    f"Validation error for entry '{name}' at row {index + 1}: {str(e)}"
                )
                errors.append({"error": error_msg})
                logger.error(error_msg)
                return Response(
                    {"errors": errors}, status=status.HTTP_400_BAD_REQUEST
                )  # Stop processing
            except Exception as e:
                error_msg = (
                    f"Failed to create entry '{name}' at row {index + 1}: {str(e)}"
                )
                errors.append({"error": error_msg})
                logger.error(error_msg)
                return Response(
                    {"errors": errors}, status=status.HTTP_400_BAD_REQUEST
                )  # Stop processing

        if created_entries:
            return Response(
                {"created": created_entries, "errors": errors},
                status=status.HTTP_201_CREATED,
            )
        else:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)


class WhereToUseBulkDeleteViewSet(viewsets.ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    @action(detail=False, methods=["delete"], url_path="bulk_delete")
    def bulk_delete(self, request, *args, **kwargs):
        try:
            # Retrieve all WhereToUse entries
            entries = WhereToUse.objects.all()

            if not entries.exists():
                return Response(
                    {"message": "No entries found to delete."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Delete all entries
            count = entries.delete()

            logger.info(f"Deleted all WhereToUse entries successfully. Count: {count}")
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


class WhereToUseNameCheckViewSet(viewsets.ViewSet):
    """
    API endpoint to check the uniqueness of a given where_to_use name.
    The client sends a GET request with a query parameter `where_to_use_name`,
    and the endpoint returns a JSON response indicating if the name is unique.
    """

    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    @action(detail=False, methods=["get"], url_path="check")
    def check_where_to_use_name(self, request):
        where_to_use_name = request.query_params.get("where_to_use_name")
        if not where_to_use_name:
            return Response(
                {"error": "The query parameter 'where_to_use_name' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check case-insensitively if a where_to_use with the same name already exists.
        exists = WhereToUse.objects.filter(name__iexact=where_to_use_name).exists()
        return Response({"unique": not exists}, status=status.HTTP_200_OK)


#
