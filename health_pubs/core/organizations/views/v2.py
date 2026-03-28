from rest_framework import viewsets
from rest_framework import filters
from rest_framework import status
from rest_framework import permissions
from rest_framework import authentication
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from django_filters.rest_framework import DjangoFilterBackend

from core.organizations.serializers import OrganizationSerializer
from core.organizations.models import Organization
from core.utils import logging_utils


logger = logging_utils.get_logger(__name__)

class CustomPagination(PageNumberPagination):
    from django.conf import settings

    page_size = getattr(
        settings, "USERS_LIST_PAGE_SIZE", 10
    )  # Set pagination to 10 items per page

    def get_paginated_response(self, data, status_code=200):
        response = Response(
            {
                "metadata": {
                    "total_count": self.page.paginator.count,
                    "page_size": self.page_size,
                    "page_number": self.page.number,
                    "next_page": self.get_next_link(),
                    "previous_page": self.get_previous_link(),
                },
                "data": data,
            },
            status=status_code,
        )
        return response


class OrganisationV2(viewsets.ModelViewSet):
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer
    authentication_classes = [authentication.TokenAuthentication]
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = [
        "name"
    ]
    search_fields = [
        "name"
    ]
    pagination_class = CustomPagination


    def list(self, request):
        return Response({"detail": "Not implemented"}, status=status.HTTP_501_NOT_IMPLEMENTED)

    def retrieve(self, request, pk=None):
        return Response({"detail": "Not implemented"}, status=status.HTTP_501_NOT_IMPLEMENTED)

    def create(self, request):
        return Response({"detail": "Not implemented"}, status=status.HTTP_501_NOT_IMPLEMENTED)

    def update(self, request, pk=None):
        return Response({"detail": "Not implemented"}, status=status.HTTP_501_NOT_IMPLEMENTED)

    def partial_update(self, request, pk=None):
        return Response({"detail": "Not implemented"}, status=status.HTTP_501_NOT_IMPLEMENTED)

    def destroy(self, request, pk=None):
        return Response({"detail": "Not implemented"}, status=status.HTTP_501_NOT_IMPLEMENTED)
