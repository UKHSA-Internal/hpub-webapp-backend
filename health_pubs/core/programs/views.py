import logging
import string
import uuid

import pandas as pd
from core.users.permissions import IsAdminUser
from core.utils.custom_token_authentication import CustomTokenAuthentication
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError
from django.db.models import Max
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from wagtail.models import Page
from django.db.models import Q, Exists, OuterRef

from core.products.models import Product
from .models import Program
from .serializers import ProgramSerializer

logger = logging.getLogger(__name__)


class ProgramCreateViewSet(viewsets.ModelViewSet):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]
    queryset = Program.objects.all()
    serializer_class = ProgramSerializer

    def create(self, request, *args, **kwargs):
        data = request.data
        if isinstance(data, dict):
            data_list = [data]
        elif isinstance(data, list):
            data_list = data
        else:
            return Response(
                {"error": "Expected a list of programs or a single program object"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created_programs = []
        errors = []

        for data in data_list:
            program_name = data.get("programme_name", "")
            if not program_name:
                errors.append({"error": "Program Name is required", "data": data})
                continue

            slug = slugify(program_name)
            unique_slug = self.get_unique_slug(slug)
            data["title"] = program_name
            data["slug"] = unique_slug

            program_id = data.get("program_id")
            if not program_id:
                program_id = self.get_next_program_id()
            data["program_id"] = program_id

            is_featured = data.get("is_featured", False)
            data["is_featured"] = is_featured

            try:
                parent_page = Page.objects.get(slug="programs")
            except Page.DoesNotExist:
                root_page = Page.objects.first()
                parent_page = Page(
                    title="Programs",
                    slug="programs",
                    content_type=ContentType.objects.get_for_model(Page),
                )
                root_page.add_child(instance=parent_page)

            serializer = self.get_serializer(data=data)
            if serializer.is_valid():
                try:
                    program_instance = Program(
                        title=data["title"],
                        slug=data["slug"],
                        programme_name=data["programme_name"],
                        program_term=data.get("program_term"),
                        is_temporary=data.get("is_temporary"),
                        program_id=data["program_id"],
                        is_featured=data["is_featured"],
                        external_key=data.get("external_key", ""),
                    )
                    parent_page.add_child(instance=program_instance)
                    program_instance.save()
                    created_programs.append(ProgramSerializer(program_instance).data)
                except IntegrityError:
                    errors.append(
                        {
                            "error": f"Program with name '{data['programme_name']}' already exists",
                            "data": data,
                        }
                    )
            else:
                errors.append({"error": serializer.errors, "data": data})

        if created_programs:
            return Response(
                {"created_programs": created_programs, "errors": errors},
                status=(
                    status.HTTP_201_CREATED
                    if not errors
                    else status.HTTP_207_MULTI_STATUS
                ),
            )
        else:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)

    def get_unique_slug(self, base_slug):
        queryset = Program.objects.filter(slug__startswith=base_slug)
        if not queryset.exists():
            return base_slug

        num = queryset.count() + 1
        return f"{base_slug}-{num}"

    def get_next_program_id(self):
        last_program = Program.objects.aggregate(max_id=Max("program_id"))["max_id"]
        if not last_program:
            return "1"

        last_id = int(last_program, 36)
        next_id = last_id + 1
        return self.base36encode(next_id)

    def base36encode(self, number):
        alphabet = string.digits + string.ascii_uppercase
        base36 = []
        while number:
            number, i = divmod(number, 36)
            base36.append(alphabet[i])
        return "".join(reversed(base36)) or "1"


class ProgramListViewSet(viewsets.ReadOnlyModelViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    queryset = Program.objects.filter(is_temporary=False)
    serializer_class = ProgramSerializer

    def list(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def get_filtered_programs(self, is_featured=False):
        """
        Helper function to filter programs based on shared logic.
        """
        # Step 1: Filter Programs with Diseases or Vaccinations
        programs_with_diseases_or_vaccinations = Program.objects.filter(
            (Q(diseases__isnull=False) | Q(vaccinations__isnull=False)),
            is_temporary=False,
        ).distinct()

        if is_featured:
            programs_with_diseases_or_vaccinations = (
                programs_with_diseases_or_vaccinations.filter(is_featured=True)
            )

        # Step 2: Further filter Programs where associated Diseases or Vaccinations are tied to a Product
        products_qs_disease = Product.objects.filter(
            program_id=OuterRef("pk"),
            update_ref__diseases_ref__programs=OuterRef("pk"),
        )

        products_qs_vaccination = Product.objects.filter(
            program_id=OuterRef("pk"),
            update_ref__vaccination_ref__programs=OuterRef("pk"),
        )

        # Annotate Programs with boolean flags indicating the existence of related Products
        programs_final = (
            programs_with_diseases_or_vaccinations.annotate(
                has_related_product_disease=Exists(products_qs_disease),
                has_related_product_vaccination=Exists(products_qs_vaccination),
            )
            .filter(
                Q(has_related_product_disease=True)
                | Q(has_related_product_vaccination=True)
            )
            .distinct()
        )

        return programs_final

    @action(detail=False, methods=["get"], url_path="featured")
    def featured_programs(self, request):
        """
        List featured programs with the same filtering logic.
        """
        try:
            # Step 1: Filter Featured Programs with Diseases or Vaccinations
            featured_programs_with_diseases_or_vaccinations = Program.objects.filter(
                Q(diseases__isnull=False) | Q(vaccinations__isnull=False),
                is_featured=True,
            ).distinct()

            # Step 2: Further filter Programs where associated Diseases or Vaccinations are tied to a Product

            # Subquery to check existence of Products linked via Diseases
            products_qs_disease = Product.objects.filter(
                program_id=OuterRef("pk"),
                update_ref__diseases_ref__programs=OuterRef("pk"),
            )

            # Subquery to check existence of Products linked via Vaccinations
            products_qs_vaccination = Product.objects.filter(
                program_id=OuterRef("pk"),
                update_ref__vaccination_ref__programs=OuterRef("pk"),
            )

            # Annotate Programs with boolean flags indicating the existence of related Products
            featured_programs_final = (
                featured_programs_with_diseases_or_vaccinations.annotate(
                    has_related_product_disease=Exists(products_qs_disease),
                    has_related_product_vaccination=Exists(products_qs_vaccination),
                )
                .filter(
                    Q(has_related_product_disease=True)
                    | Q(has_related_product_vaccination=True)
                )
                .distinct()
            )

            # Serialize the filtered Programs
            serializer = self.get_serializer(featured_programs_final, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("Error fetching featured programs")
            return Response(
                {
                    "detail": "An unexpected error occurred. Please try again later.",
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"], url_path="filtered-programmes")
    def programs_with_related(self, request):
        """
        List programs that have diseases or vaccinations associated with them,
        and those diseases or vaccinations are tied to at least one product.
        """
        try:
            # Step 1: Filter Programs with Diseases or Vaccinations
            programs_with_diseases_or_vaccinations = Program.objects.filter(
                Q(diseases__isnull=False) | Q(vaccinations__isnull=False)
            ).distinct()

            # Step 2: Further filter Programs where associated Diseases or Vaccinations are tied to a Product

            # Subquery to check existence of Products linked via Diseases
            products_qs_disease = Product.objects.filter(
                program_id=OuterRef("pk"),
                update_ref__diseases_ref__programs=OuterRef("pk"),
            )

            # Subquery to check existence of Products linked via Vaccinations
            products_qs_vaccination = Product.objects.filter(
                program_id=OuterRef("pk"),
                update_ref__vaccination_ref__programs=OuterRef("pk"),
            )

            # Annotate Programs with boolean flags indicating the existence of related Products
            programs_final = (
                programs_with_diseases_or_vaccinations.annotate(
                    has_related_product_disease=Exists(products_qs_disease),
                    has_related_product_vaccination=Exists(products_qs_vaccination),
                )
                .filter(
                    Q(has_related_product_disease=True)
                    | Q(has_related_product_vaccination=True)
                )
                .distinct()
            )

            # Serialize the filtered Programs
            serializer = self.get_serializer(programs_final, many=True)

            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("Error fetching filtered programmes")

            return Response(
                {
                    "detail": "An unexpected error occurred. Please try again later.",
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ProgramUpdateViewSet(viewsets.ModelViewSet):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]
    queryset = Program.objects.all()
    serializer_class = ProgramSerializer

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProgramDestroyViewSet(viewsets.ModelViewSet):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]
    queryset = Program.objects.all()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def perform_destroy(self, instance):
        instance.delete()


class BulkProgramUploadViewSet(viewsets.ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        excel_file = request.FILES.get("excel_file")
        if not excel_file:
            return Response(
                {"error": "Excel file is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            df = pd.read_excel(excel_file)
        except Exception as e:
            return Response(
                {"error": f"Failed to read the Excel file: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created_programs = []
        errors = []
        parent_page = Page.objects.first()

        for _, row in df.iterrows():
            programme_name = row.get("programme_name")
            if not programme_name:
                errors.append({"error": "Missing programme_name"})
                continue

            if Program.objects.filter(programme_name=programme_name).exists():
                errors.append({"error": f'Program "{programme_name}" already exists'})
                continue

            program = Program(
                title=programme_name,
                slug=slugify(programme_name + str(timezone.now())),
                program_id=row.get("programme_id") or str(uuid.uuid4()),
                programme_name=programme_name,
                external_key=row.get("external_key", ""),
                is_featured=row.get("is_featured", False),
                is_temporary=row.get("is_temporary", False),
                program_term=row.get("program_term"),
            )
            try:
                parent_page.add_child(instance=program)
                program.save()
                created_programs.append(ProgramSerializer(program).data)
            except Exception as e:
                errors.append(
                    {"error": f'Failed to create program "{programme_name}": {str(e)}'}
                )

        if created_programs:
            return Response(
                {"created": created_programs, "errors": errors},
                status=status.HTTP_201_CREATED,
            )
        return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)


class BulkProgramDeleteViewSet(viewsets.ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def destroy(self, request, *args, **kwargs):
        try:
            entries = Program.objects.all()
            if not entries.exists():
                return Response(
                    {"message": "No entries found to delete."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            count = entries.count()
            entries.delete()
            return Response(
                {"message": f"Successfully deleted {count} entries."},
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            return Response(
                {"error": f"Failed to delete entries: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


#
