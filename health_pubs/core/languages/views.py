import logging
import uuid

import langcodes
import pandas as pd
from core.users.permissions import IsAdminOrRegisteredUser, IsAdminUser
from core.utils.custom_token_authentication import CustomTokenAuthentication
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet, ViewSet
from wagtail.models import Page

from .models import LanguagePage
from .serializers import LanguageSerializer

logger = logging.getLogger(__name__)


def get_bcp47_language_code(language_name):
    try:
        if language_name == "Multiple":
            return "ml"

        # Retrieve the BCP 47 language code
        language_code = langcodes.find(language_name)

        if not language_code:
            return "UNKNOWN"

        logger.info(f"Final BCP 47 code: {language_code}")  # Log the final code
        return language_code
    except Exception as e:
        logger.error(f"Error retrieving BCP 47 language code: {str(e)}")
        return None


class LanguageCreateViewSet(ModelViewSet):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]
    queryset = LanguagePage.objects.all()
    serializer_class = LanguageSerializer

    def create(self, request, *args, **kwargs):
        self.permission_classes = [IsAdminUser]
        # Extract the list of languages from the request data
        languages_data = request.data.get("languages")
        # logger.info('TYPE',type(languages_data))

        # Check if the input is a list or a single object
        if not isinstance(languages_data, list):
            if isinstance(languages_data, dict):
                languages_data = [languages_data]
            else:
                logger.error(
                    "Language creation failed: Expected a list of languages or a single language object"
                )
                return Response(
                    {
                        "errors": [
                            {
                                "error": "Expected a list of languages or a single language object"
                            }
                        ]
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        created_languages = []
        errors = []
        parent_page = Page.objects.first()  # Adjust to get the appropriate parent page

        for language_data in languages_data:
            language_name = language_data.get("language_name")
            iso_language_code = language_data.get("iso_language_code")

            # Validate language name
            if not language_name:
                return Response(
                    {"errors": [{"error": "Missing language_name"}]},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Attempt to derive iso_language_code if not provided
            if not iso_language_code:
                iso_language_code = get_bcp47_language_code(language_name)
                if not iso_language_code:
                    errors.append(
                        {
                            "error": f"Invalid language name '{language_name}', cannot derive iso_language_code."
                        }
                    )
                    return Response(
                        {"errors": errors}, status=status.HTTP_400_BAD_REQUEST
                    )

            # Check if the language already exists (case-insensitive)
            if LanguagePage.objects.filter(
                language_names__iexact=language_name
            ).exists():
                return Response(
                    {
                        "errors": [
                            {"error": f'Language "{language_name}" already exists'}
                        ]
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Create the new language page
            page = LanguagePage(
                title=language_name,
                slug=slugify(f"{language_name}-{timezone.now().timestamp()}"),
                language_id=language_data.get("language_id", str(uuid.uuid4())),
                language_names=language_name,
                iso_language_code=iso_language_code,
            )

            try:
                parent_page.add_child(instance=page)
                page.save()
                created_languages.append(LanguageSerializer(page).data)
                logger.info("Language created successfully: %s", page.title)
            except Exception as e:
                errors.append(
                    {"error": f'Failed to create language "{language_name}": {str(e)}'}
                )
                logger.error(
                    'Failed to create language "%s": %s', language_name, str(e)
                )

        # Return results
        if created_languages or errors:
            return Response(
                {"created": created_languages, "errors": errors},
                status=(
                    status.HTTP_207_MULTIPLE_CHOICES
                    if created_languages and errors
                    else status.HTTP_201_CREATED
                ),
            )
        else:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)


class BulkLanguageUploadViewSet(ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    @action(detail=False, methods=["post"], url_path="bulk-language-upload")
    def bulk_language_upload(self, request, *args, **kwargs):
        # Assume Excel data is uploaded in the request
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

        created_languages = []
        errors = []

        # Retrieve the parent page (assumed as the first page in the database)
        parent_page = Page.objects.first()

        for _, row in df.iterrows():
            language_name = row.get("language_name")
            language_id = row.get("id")
            iso_language_code = row.get("iso_language_code")

            if not language_name:
                errors.append({"error": "Missing language_name"})
                continue

            # Generate iso_language_code if not provided
            if pd.isna(iso_language_code):
                iso_language_code = get_bcp47_language_code(language_name)

            # Check if the language already exists
            if LanguagePage.objects.filter(language_names=language_name).exists():
                errors.append({"error": f'Language "{language_name}" already exists'})
                continue

            # Create the new language page
            page = LanguagePage(
                title=language_name,
                slug=slugify(language_name + str(timezone.now())),
                language_id=language_id or uuid.uuid4(),
                language_names=language_name,
                iso_language_code=iso_language_code,
            )

            try:
                parent_page.add_child(instance=page)
                page.save()
                created_languages.append(LanguageSerializer(page).data)
                logger.info(f"Language created successfully: {page.title}")
            except Exception as e:
                errors.append(
                    {"error": f'Failed to create language "{language_name}": {str(e)}'}
                )
                logger.error(f'Failed to create language "{language_name}": {str(e)}')

        # Return results
        if created_languages:
            return Response(
                {"created": created_languages, "errors": errors},
                status=status.HTTP_201_CREATED,
            )
        else:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)


class LanguageListViewSet(ReadOnlyModelViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    queryset = LanguagePage.objects.all()
    serializer_class = LanguageSerializer


class DeleteAllLanguagesViewSet(ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    @action(detail=False, methods=["delete"], url_path="delete-all-languages")
    def delete_all_languages(self, request, *args, **kwargs):
        try:
            # Get all LanguagePage entries
            languages = LanguagePage.objects.all()

            if not languages.exists():
                return Response(
                    {"message": "No languages found to delete."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Delete all language entries
            count = languages.delete()

            logger.info("Deleted all languages successfully.")
            return Response(
                {"message": f"Successfully deleted {count} languages."},
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            logger.error(f"Error deleting languages: {str(e)}")
            return Response(
                {"error": f"Failed to delete languages: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


#
