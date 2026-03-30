import logging
import string
import uuid

import pandas as pd
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from django.db.models import Max
from django.db.models import Q, Exists, OuterRef
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError as DRFValidationError
from wagtail.models import Page

from core.products.models import Product
from core.programs.models import Program
from core.programs.serializers import ProgramSerializer
from core.users.permissions import IsAdminUser
from core.utils.custom_token_authentication import CustomTokenAuthentication


logger = logging.getLogger(__name__)

MAX_FEATURED_PROGRAMMES = getattr(settings, "MAX_FEATURED_PROGRAMMES", 6)


def _get_or_create_parent_programs_page() -> Page:
    try:
        return Page.objects.get(slug="programs")
    except Page.DoesNotExist:
        root_page = Page.objects.first()
        parent_page = Page(
            title="Programs",
            slug="programs",
            content_type=ContentType.objects.get_for_model(Page),
        )
        root_page.add_child(instance=parent_page)
        parent_page.save()
        return parent_page


def _assert_featured_capacity(exclude_program_id: str | None = None) -> None:
    """
    Must be called inside a transaction.atomic() block.
    Locks featured rows and ensures we don't exceed MAX_FEATURED_PROGRAMMES.
    """
    from rest_framework.exceptions import ValidationError

    # Lock currently featured rows to prevent concurrent oversubscription
    list(
        Program.objects.select_for_update()
        .filter(is_featured=True)
        .values("program_id")
    )

    q = Program.objects.filter(is_featured=True)
    if exclude_program_id:
        q = q.exclude(program_id=exclude_program_id)

    if q.count() >= MAX_FEATURED_PROGRAMMES:
        raise ValidationError(
            {
                "is_featured": [
                    f"Featured programmes must be {MAX_FEATURED_PROGRAMMES} or fewer. "
                    "Go back to ‘manage featured programmes’ to reduce the number, before you try again."
                ]
            }
        )


def _serialize_validation_error(exc):
    # DRF ValidationError
    if hasattr(exc, "detail"):
        return exc.detail
    # Django ValidationError
    if hasattr(exc, "message_dict"):
        return exc.message_dict
    if hasattr(exc, "messages"):
        return exc.messages
    return str(exc)


class ProgramCreateViewSet(viewsets.ViewSet):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    serializer_class = ProgramSerializer

    def get_serializer(self, *args, **kwargs):
        return self.serializer_class(*args, **kwargs)

    def create(self, request, *args, **kwargs):
        data = request.data

        # Extracted from: data_list = [data] if isinstance(data, dict) else data if isinstance(data, list) else None
        if isinstance(data, dict):
            data_list = [data]
        elif isinstance(data, list):
            data_list = data
        else:
            data_list = None

        if data_list is None:
            return Response(
                {"error": "Expected a list of programs or a single program object"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created_programs, errors = [], []
        parent_page = _get_or_create_parent_programs_page()

        for raw in data_list:
            entry = dict(raw or {})
            name = (entry.get("programme_name") or "").strip()
            if not name:
                errors.append({"error": "Program Name is required", "data": entry})
                continue

            # Build fields expected by serializer; slug/title handled here
            entry.setdefault("external_key", "")
            entry.setdefault("is_temporary", False)
            entry.setdefault("is_featured", False)
            entry.setdefault("program_term", None)

            serializer = self.get_serializer(data=entry)
            if not serializer.is_valid():
                errors.append({"error": serializer.errors, "data": entry})
                continue

            try:
                with transaction.atomic():
                    # Cap check if setting featured on create
                    if bool(entry.get("is_featured")):
                        _assert_featured_capacity()

                    #  use your unique slug helper
                    slug = self.get_unique_slug(slugify(name))

                    #  use your next base-36 ID helper (≤ 22 chars)
                    program_id = entry.get("program_id") or self.get_next_program_id()

                    program_instance = Program(
                        program_id=program_id,
                        title=name,
                        slug=slug,
                        programme_name=name,
                        is_featured=bool(entry.get("is_featured")),
                        is_temporary=bool(entry.get("is_temporary")),
                        program_term=entry.get("program_term") or None,
                        external_key=entry.get("external_key") or "",
                    )
                    parent_page.add_child(instance=program_instance)
                    program_instance.save()

                created_programs.append(self.serializer_class(program_instance).data)

            except IntegrityError as ie:
                errors.append(
                    {
                        "error": f"Program with name '{name}' already exists",
                        "data": entry,
                        "detail": str(ie),
                    }
                )
            except (DRFValidationError, DjangoValidationError) as ve:
                errors.append({"error": _serialize_validation_error(ve), "data": entry})
            except Exception as e:
                logger.exception("Unexpected error creating program")
                errors.append({"error": str(e), "data": entry})

        if created_programs:
            return Response(
                {"created_programs": created_programs, "errors": errors},
                status=(
                    status.HTTP_201_CREATED
                    if not errors
                    else status.HTTP_207_MULTI_STATUS
                ),
            )
        return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)

    def get_unique_slug(self, base_slug):
        queryset = Program.objects.filter(slug__startswith=base_slug)
        if not queryset.exists():
            return base_slug
        return f"{base_slug}-{queryset.count() + 1}"

    def get_next_program_id(self):
        last_id = Program.objects.aggregate(max_id=Max("program_id"))["max_id"]
        return self.base36encode(int(last_id, 36) + 1) if last_id else "1"

    def base36encode(self, number):
        alphabet = string.digits + string.ascii_uppercase
        base36 = []
        while number:
            number, i = divmod(number, 36)
            base36.append(alphabet[i])
        return "".join(reversed(base36)) or "1"


class ProgramListViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Public/read endpoints (list + special filtered lists).
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    serializer_class = ProgramSerializer
    queryset = Program.objects.all()

    def get_object(self):
        """
        Override default behaviour so retrieve() returns BOTH temporary and non-temporary programs.
        """
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        lookup_value = self.kwargs.get(lookup_url_kwarg)

        # Retrieve from full table — bypass get_queryset()
        obj = get_object_or_404(Program, **{self.lookup_field: lookup_value})
        self.check_object_permissions(self.request, obj)
        return obj

    def get_queryset(self):
        if self.action == "list":
            return Program.objects.all()
        return Program.objects.filter(is_temporary=False)

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        ser = self.get_serializer(qs, many=True)
        return Response(ser.data, status=status.HTTP_200_OK)

    def _filtered_programs(self, is_featured: bool = False):
        """
        Publishable programs: have diseases or vaccinations AND at least one live product.
        """
        base = Program.objects.filter(
            (Q(diseases__isnull=False) | Q(vaccinations__isnull=False)),
            is_temporary=False,
        ).distinct()

        if is_featured:
            base = base.filter(is_featured=True)

        # IMPORTANT: match on program_id explicitly (string PK per model)
        products_qs_disease = Product.objects.filter(
            program_id=OuterRef("program_id"),
            update_ref__diseases_ref__programs__program_id=OuterRef("program_id"),
            status="live",
            is_latest=True,
        )

        products_qs_vaccination = Product.objects.filter(
            program_id=OuterRef("program_id"),
            update_ref__vaccination_ref__programs__program_id=OuterRef("program_id"),
            status="live",
            is_latest=True,
        )

        return (
            base.annotate(
                has_related_product_disease=Exists(products_qs_disease),
                has_related_product_vaccination=Exists(products_qs_vaccination),
            )
            .filter(
                Q(has_related_product_disease=True)
                | Q(has_related_product_vaccination=True)
            )
            .distinct()
        )

    @action(detail=False, methods=["get"], url_path="featured")
    def featured_programs(self, request):
        """Featured + publishable (for homepage)."""
        try:
            qs = self._filtered_programs(is_featured=True)
            ser = self.get_serializer(qs, many=True)
            return Response(ser.data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.exception("Error fetching featured programs")
            return Response(
                {"detail": "Unexpected error.", "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"], url_path="featured-all")
    def featured_all(self, request):
        """ALL featured (counts towards cap), regardless of publishability."""
        qs = Program.objects.filter(is_featured=True, is_temporary=False).order_by(
            "programme_name"
        )
        ser = self.get_serializer(qs, many=True)
        return Response(ser.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="filtered-programmes")
    def programs_with_related(self, request):
        """All publishable programs (for listings)."""
        try:
            qs = self._filtered_programs()
            ser = self.get_serializer(qs, many=True)
            return Response(ser.data, status=status.HTTP_200_OK)
        except Exception as e:
            logger.exception("Error fetching filtered programmes")
            return Response(
                {"detail": "Unexpected error.", "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(
        detail=False,
        methods=["get"],
        url_path=r"list/(?P<program_id>[^/]+)",
        authentication_classes=[CustomTokenAuthentication],
        permission_classes=[IsAuthenticated, IsAdminUser],
    )
    def list_by_program_id(self, request, program_id=None):
        """
        Admin-only endpoint to fetch a program by program_id,
        returning BOTH temporary and non-temporary records.

        Example:
        GET /api/v1/programs/list/ABC123/
        """

        try:
            # IMPORTANT: bypass get_queryset() so temporary programmes are included
            qs = Program.objects.filter(program_id=program_id)

            if not qs.exists():
                return Response(
                    {"detail": f"No program found with program_id '{program_id}'."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            serializer = self.get_serializer(qs, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("Error fetching programs by program_id")
            return Response(
                {"detail": "Unexpected error occurred.", "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ProgramUpdateViewSet(viewsets.ModelViewSet):
    """
    Private/admin update + retrieve by program_id.
    Allows updating ANY editable field on Program via the serializer,
    with special handling to enforce capacity when toggling `is_featured` on.
    """

    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    queryset = Program.objects.all()
    serializer_class = ProgramSerializer
    lookup_field = "program_id"

    def _normalize_is_featured(self, data):
        """
        Normalise `is_featured` in incoming data to a real bool if present.
        Returns (normalized_value_or_None, mutated_data_dict).
        """
        if "is_featured" not in data:
            return None, data

        raw = data.get("is_featured")

        # If already a bool, just return it
        if isinstance(raw, bool):
            return raw, data

        # Handle common string / numeric representations
        if isinstance(raw, str):
            value = raw.strip().lower()
            if value in {"true", "1", "yes", "y"}:
                data["is_featured"] = True
                return True, data
            if value in {"false", "0", "no", "n"}:
                data["is_featured"] = False
                return False, data

        # Fallback: leave it as-is and let the serializer validate
        return raw, data

    def _update_instance(self, request, partial=False):
        instance: Program = self.get_object()
        data = request.data.copy()

        # Normalise is_featured if present, but allow all other fields through
        normalized_is_featured, data = self._normalize_is_featured(data)

        try:
            with transaction.atomic():
                # Enforce cap only when we are turning is_featured from False -> True
                if normalized_is_featured is True and instance.is_featured is False:
                    _assert_featured_capacity(exclude_program_id=instance.program_id)

                serializer = self.get_serializer(instance, data=data, partial=partial)
                serializer.is_valid(raise_exception=True)
                obj = serializer.save()  # save all updated fields
                obj.save()  # in case serializer does not call save() again

            return Response(serializer.data, status=status.HTTP_200_OK)

        except (DRFValidationError, DjangoValidationError) as ve:
            return Response(
                {"error": _serialize_validation_error(ve)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.exception("Error updating program")
            return Response(
                {"detail": "Unable to update program", "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def update(self, request, *args, **kwargs):
        """
        PUT – typically full update (but we still allow missing fields via serializer config).
        """
        return self._update_instance(request, partial=False)

    def partial_update(self, request, *args, **kwargs):
        """
        PATCH – partial update of any subset of fields.
        """
        return self._update_instance(request, partial=True)


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


class BulkProgramUploadViewSet(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
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


class ProgramNameCheckViewSet(viewsets.ViewSet):
    """
    API endpoint to check the uniqueness of a given programme name.
    The client sends a GET request with a query parameter `programme_name`,
    and the endpoint returns a JSON response indicating if the name is unique.
    """

    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    @action(detail=False, methods=["get"], url_path="check")
    def check_programme_name(self, request):
        programme_name = request.query_params.get("programme_name")
        if not programme_name:
            return Response(
                {"error": "The query parameter 'programme_name' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check case-insensitively if a program with the same name already exists.
        exists = Program.objects.filter(programme_name__iexact=programme_name).exists()
        return Response({"unique": not exists}, status=status.HTTP_200_OK)


#


#
