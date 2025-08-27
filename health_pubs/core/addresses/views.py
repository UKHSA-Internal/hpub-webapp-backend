import logging
import uuid
import os, re
import sys
import uuid
from django.utils.timezone import now
import pandas as pd
import requests
from configs.get_secret_config import Config
from core.users.models import User
from core.utils.address_verification import get_oauth_token, verify_address

from django.contrib.contenttypes.models import ContentType
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from core.utils.custom_token_authentication import CustomTokenAuthentication
from core.users.permissions import IsAdminOrRegisteredUser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from wagtail.models import Page

from .models import Address
from .serializers import AddressSerializer

sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

logger = logging.getLogger(__name__)


class CustomPagination(PageNumberPagination):
    page_size = 10  # Set pagination to 10 items per page

    def get_paginated_response(self, data):
        response = Response(
            {
                "links": {
                    "next": self.get_next_link(),
                    "previous": self.get_previous_link(),
                },
                "count": self.page.paginator.count,
                "results": data,
            }
        )
        response.status_code = 200
        return response


class AddressViewSet(viewsets.ModelViewSet):
    lookup_field = "address_id"
    authentication_classes = [CustomTokenAuthentication]

    permission_classes = [IsAuthenticated, IsAdminOrRegisteredUser]
    queryset = Address.objects.all()
    serializer_class = AddressSerializer
    pagination_class = CustomPagination

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.base_url = Config().get_address_verify_base_url()

    def _normalize_address_fields(self, data):
        return {
            "address_line1": data["address_line1"].strip(),
            "address_line2": data.get("address_line2", "").strip(),
            "address_line3": data.get("address_line3", "").strip(),
            "city": data["city"].strip(),
            "county": data.get("county", "").strip(),
            "postcode": data["postcode"].strip().upper(),
            "country": data["country"].strip(),
        }

    def _build_address_instance(self, normalized, slug, user_ref):
        return Address(
            title=normalized["address_line1"],
            slug=slug,
            address_line1=normalized["address_line1"],
            address_line2=normalized["address_line2"],
            address_line3=normalized["address_line3"],
            city=normalized["city"],
            county=normalized["county"],
            postcode=normalized["postcode"],
            country=normalized["country"],
            is_default=False,
            verified=False,
            user_ref=user_ref,
        )

    def create(self, request, *args, **kwargs):
        data = request.data

        # resolve user_ref
        user_ref = None
        if data.get("user_ref"):
            user_ref = get_object_or_404(User, user_id=data["user_ref"])

        # normalize and dedupe
        normalized = self._normalize_address_fields(data)
        dup = Address.objects.filter(
            address_line1__iexact=normalized["address_line1"],
            address_line2__iexact=normalized["address_line2"],
            address_line3__iexact=normalized["address_line3"],
            city__iexact=normalized["city"],
            county__iexact=normalized["county"],
            postcode__iexact=normalized["postcode"],
            country__iexact=normalized["country"],
            user_ref=user_ref,
        ).first()
        if dup:
            return Response(
                {
                    "message": "Address already exists.",
                    "address": AddressSerializer(dup).data,
                    "action": "confirm_existing_or_create_new",
                },
                status=status.HTTP_409_CONFLICT,
            )

        # ensure parent
        parent = self._get_or_create_parent_page("addresses")

        # slug/title
        base = slugify(normalized["address_line1"])
        slug = self._get_unique_slug(base, parent)

        # build instance
        addr = self._build_address_instance(normalized, slug, user_ref)

        # first address = default
        if not Address.objects.filter(user_ref=user_ref).exists():
            addr.is_default = True

        # external verify (now returns details on failure)
        try:
            ok = verify_address(addr)
        except Exception as e:
            logger.exception(f"Unexpected error verifying address, {e}")
            return Response(
                {"error": "Address verification service error"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if not ok:
            return Response(
                {"error": "Address verification failed"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # always add_child() so Wagtail sets parent, path, depth
        parent.add_child(instance=addr)

        serializer = AddressSerializer(addr)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def _get_unique_slug(self, base_slug: str, parent_page: Page) -> str:
        existing = set(
            parent_page.get_children()
            .filter(slug__startswith=base_slug)
            .values_list("slug", flat=True)
        )
        if base_slug not in existing:
            return base_slug
        i = 1
        while True:
            candidate = f"{base_slug}-{i}"
            if candidate not in existing:
                return candidate
            i += 1

    def _get_or_create_parent_page(self, slug: str) -> Page:
        try:
            return Page.objects.get(slug=slug)
        except Page.DoesNotExist:
            root = Page.objects.first()
            parent = Page(
                title=slug.capitalize(),
                slug=slug,
                content_type=ContentType.objects.get_for_model(Page),
            )
            root.add_child(instance=parent)
            return parent

    def _normalize_postcode(self, postcode: str) -> str:
        """
        Clean up postcode:
        - Remove leading/trailing spaces
        - Collapse multiple spaces inside
        - Convert to uppercase
        """
        if not postcode:
            return ""
        return re.sub(r"\s+", " ", postcode.strip()).upper()

    @action(detail=False, methods=["post"], url_path="verify-address")
    def verify_address(self, request):
        postcode = self._normalize_postcode(request.data.get("postcode", ""))
        building = request.data.get("building_number", "")
        if not postcode or not building:
            return Response(
                {"error": "Postcode and building number are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload = {
            "operationId": "matchAddress",
            "callingApplication": "HPUB",
            "address": f"{building} {postcode}".strip(),
            "maxResults": 100,
            "fuzzy": True,
        }
        token = get_oauth_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "PythonDevApplication",
        }
        resp = requests.post(
            f"{self.base_url}/matchAddress", json=payload, headers=headers
        )
        data = resp.json()
        logger.info("Match Address Response: %s", data.get("matchedAddresses", []))

        if resp.status_code != 200:
            return Response(
                {"error": "Failed to verify address", "details": data},
                status=status.HTTP_400_BAD_REQUEST,
            )

        matches = [
            a
            for a in data.get("matchedAddresses", [])
            if a.get("countryCode") in ("E", "England")
            and a.get("postcode", "").strip().lower() == postcode.lower()
            and building.lower() in a.get("addressString", "").lower()
        ]
        if not matches:
            return Response(
                {"error": "No addresses found in England with that postcode."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"matchedAddresses": matches}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="geo-code-address")
    def geo_code_address(self, request):
        addr_str = request.data.get("address_string", "")
        postcode = request.data.get("postcode", "")
        uprn = request.data.get("uprn", "")
        if not addr_str and not postcode:
            return Response(
                {"error": "Either address_string or postcode is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload = {
            "operationId": "geoCodeAddresses",
            "callingApplication": "HPUB",
            "addressString": addr_str,
            "uprn": uprn,
            "postcode": postcode,
        }
        try:
            token = get_oauth_token()
        except Exception as e:
            return Response(
                {"error": "Failed to obtain token", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "PythonDevApplication",
        }
        try:
            resp = requests.post(
                f"{self.base_url}/geoCodeAddresses", json=payload, headers=headers
            )
            resp.raise_for_status()
        except requests.HTTPError as e:
            return Response(
                {"error": "HTTP error", "details": str(e)},
                status=resp.status_code,
            )
        except Exception as e:
            return Response(
                {"error": "Unexpected error", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        results = resp.json().get("matchedAddresses", [])
        filtered = [
            {
                "addressString": r["addressString"],
                "postcode": r["postcode"],
                "uprn": r.get("uprn", ""),
                "parentUprn": r.get("parentUprn", ""),
                "blpuCode": r.get("blpuCode", ""),
                "locationX": r.get("locationX", ""),
                "locationY": r.get("locationY", ""),
                "latitude": r.get("latitude", ""),
                "longitude": r.get("longitude", ""),
            }
            for r in results
            if r.get("postcode") == postcode
            and r.get("countryCode") in ("E", "England")
        ]
        if not filtered:
            return Response(
                {"error": "No geocoded addresses in England found"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"matchedAddresses": filtered}, status=status.HTTP_200_OK)

    def _duplicate_exists(self, data, current_id):
        return (
            Address.objects.exclude(address_id=current_id)
            .filter(
                address_line1__iexact=data["address_line1"],
                city__iexact=data["city"],
                postcode__iexact=data["postcode"].upper(),
                country__iexact=data["country"],
                user_ref=data["user_ref"],
            )
            .exists()
        )

    @action(detail=True, methods=["put"], url_path="update")
    def update_address(self, request, address_id=None):
        addr = get_object_or_404(Address, address_id=address_id)
        serializer = AddressSerializer(addr, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        changes = serializer.validated_data

        dupe_check = {
            "address_line1": changes.get("address_line1", addr.address_line1).strip(),
            "city": changes.get("city", addr.city).strip(),
            "postcode": changes.get("postcode", addr.postcode).strip(),
            "country": changes.get("country", addr.country).strip(),
            "user_ref": changes.get("user_ref", addr.user_ref),
        }
        if self._duplicate_exists(dupe_check, address_id):
            return Response(
                {"error": "ADDRESS_ALREADY_EXISTS"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        update_fields = []
        for f, v in changes.items():
            setattr(addr, f, v)
            update_fields.append(f)
        addr.modified_at = now()
        update_fields.append("modified_at")

        addr.save(update_fields=update_fields)
        return Response(AddressSerializer(addr).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path=r"user/(?P<user_id>[\w-]+)")
    def list_by_user(self, request, user_id=None):
        user = get_object_or_404(User, user_id=user_id)
        qs = Address.objects.filter(user_ref__user_id=user.user_id)
        if not qs.exists():
            return Response(
                {
                    "error": "NO_ADDRESSES_FOUND",
                    "message": "No addresses for that user.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = AddressSerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        inst = self.get_object()
        inst.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"], url_path="bulk-upload")
    def bulk_upload(self, request):
        f = request.FILES.get("addresses_excel")
        if not f:
            return JsonResponse(
                {"error": "File required"}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            df = pd.read_excel(f)
        except Exception as e:
            logger.error("Excel read error: %s", e)
            return JsonResponse(
                {"error": "Invalid Excel"}, status=status.HTTP_400_BAD_REQUEST
            )

        for col in ("address_line1", "city", "postcode", "country", "user_id"):
            if col not in df.columns:
                return JsonResponse(
                    {"error": f"Missing column {col}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        parent = self._get_or_create_parent_page("addresses")
        for row in df.to_dict(orient="records"):
            uid = row.get("user_id")
            try:
                usr = User.objects.get(user_id=uid)
            except User.DoesNotExist:
                logger.error("User %s missing", uid)
                continue

            existing = Address.objects.filter(
                address_line1=row["address_line1"],
                city=row["city"],
                postcode=row["postcode"],
                user_ref=usr,
            ).first()
            if existing:
                # you might update fields here if desired
                continue

            base = slugify(f"{row['city']}-{row['postcode']}-{uuid.uuid4()}")
            slug = self._get_unique_slug(base, parent)
            inst = Address(
                title=f"{row['address_line1']}, {row['city']}",
                slug=slug,
                address_line1=row["address_line1"],
                address_line2=row.get("address_line2", ""),
                address_line3=row.get("address_line3", ""),
                city=row["city"],
                county=row.get("county", ""),
                postcode=row["postcode"],
                country=row["country"],
                is_default=row.get("is_default", False),
                verified=row.get("verified", False),
                user_ref=usr,
            )
            parent.add_child(instance=inst)
        return JsonResponse({"message": "Bulk upload done"}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["delete"], url_path="bulk-delete")
    def bulk_delete(self, request):
        cnt, _ = Address.objects.all().delete()
        if cnt == 0:
            return Response(
                {"message": "No entries to delete"}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(
            {"message": f"Deleted {cnt} entries"}, status=status.HTTP_200_OK
        )

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        page = self.paginate_queryset(qs)
        if page is not None:
            ser = self.get_serializer(page, many=True)
            return self.get_paginated_response(ser.data)
        ser = self.get_serializer(qs, many=True)
        return Response(ser.data, status=status.HTTP_200_OK)
