from django.conf import settings
from django.http import HttpRequest
from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from core.users.permissions import IsAdminUser


@api_view(["GET"])
@permission_classes([AllowAny])
def get_health_check(request: HttpRequest):
    return JsonResponse({"status": "OK"}, status=200)


@api_view(["GET"])
@permission_classes([IsAdminUser])
def get_self_info(request: HttpRequest):
    response = {}
    response['name'] = 'hpub-backend'
    response['description'] = 'Backend for Find Public Health Resources.'
    response['version'] = 'TODO'
    return JsonResponse(response, status=200)


@api_view(["GET"])
@permission_classes([IsAdminUser])
def get_self_config(request: HttpRequest):
    response = {}

    # Pagination / limits
    response["MAX_FEATURED_PROGRAMMES"] = settings.MAX_FEATURED_PROGRAMMES
    response["PRODUCTS_PAGE_SIZE"] = settings.PRODUCTS_PAGE_SIZE
    response["USERS_LIST_PAGE_SIZE"] = settings.USERS_LIST_PAGE_SIZE
    response["ADDRESSES_LIST_PAGE_SIZE"] = settings.ADDRESSES_LIST_PAGE_SIZE
    response["ADMIN_PRODUCTS_PAGE_SIZE"] = settings.ADMIN_PRODUCTS_PAGE_SIZE
    response["ADMIN_PRE_LIST_LIMIT"] = settings.ADMIN_PRE_LIST_LIMIT

    # Cache TTLs
    response["CACHE_TTL"] = settings.CACHE_TTL
    response["CACHE_TTL_DETAIL"] = settings.CACHE_TTL_DETAIL
    response["CACHE_TTL_LIST"] = settings.CACHE_TTL_LIST

    # Presigned URLs
    response["PRESIGNED_URL_TTL"] = settings.PRESIGNED_URL_TTL
    response["MINIMUM_PRESIGNED_URL_TTL"] = settings.MINIMUM_PRESIGNED_URL_TTL
    response["PRESIGN_IN_LISTS"] = settings.PRESIGN_IN_LISTS

    # File metadata
    response["FILE_METADATA_ENABLED"] = settings.FILE_METADATA_ENABLED
    response["FILE_METADATA_DEEP_PROBE_DOCS"] = settings.FILE_METADATA_DEEP_PROBE_DOCS
    response["MAX_METADATA_BYTES"] = settings.MAX_METADATA_BYTES
    response["FILE_METADATA_TIME_BUDGET_MS"] = settings.FILE_METADATA_TIME_BUDGET_MS
    response["FILE_METADATA_SLOTS"] = settings.FILE_METADATA_SLOTS
    response["FILE_METADATA_CACHE_TTL"] = settings.FILE_METADATA_CACHE_TTL

    # Document settings
    response["DOC_FILE_TYPES"] = settings.DOC_FILE_TYPES
    response["DOC_DEEP_PROBE_EXTS"] = settings.DOC_DEEP_PROBE_EXTS
    response["DOCX_INCLUDE_PAGECOUNT"] = settings.DOCX_INCLUDE_PAGECOUNT
    response["DOC_PAGECOUNT_VIA_LIBREOFFICE"] = settings.DOC_PAGECOUNT_VIA_LIBREOFFICE
    response["LIBREOFFICE_TIMEOUT_SECS"] = settings.LIBREOFFICE_TIMEOUT_SECS
    response["STRICT_DOC_PAGE_META"] = settings.STRICT_DOC_PAGE_META

    return JsonResponse(response, status=200)