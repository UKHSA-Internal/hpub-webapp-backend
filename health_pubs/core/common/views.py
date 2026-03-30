from rest_framework import viewsets
from rest_framework import filters
from rest_framework import status
from rest_framework import permissions
from rest_framework import authentication
from rest_framework.response import Response


from django_filters.rest_framework import DjangoFilterBackend

from core.common.serializers import ListResponse
from core.utils import custom_token_authentication
from core.utils import logging_utils


logger = logging_utils.get_logger(__name__)


class CommonViewSet(viewsets.ModelViewSet):
    queryset = None
    serializer_class = None
    authentication_classes = [custom_token_authentication.CustomTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = []
    search_fields = []
    pagination_class = ListResponse


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
