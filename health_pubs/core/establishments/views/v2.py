from core.establishments.serializers import EstablishmentSerializer
from core.establishments.models import Establishment


from rest_framework import status, permissions, authentication, viewsets
from rest_framework.response import Response

from core.utils import logging_utils

logger = logging_utils.get_logger(__name__)


class OrganisationEstablishmentsV2(viewsets.ModelViewSet):
    authentication_classes = [authentication.TokenAuthentication]
    permission_classes = [permissions.AllowAny]
    serializer_class = EstablishmentSerializer

    def get_queryset(self):
        organisation_id = self.kwargs.get("organisation_id")
        return Establishment.objects.filter(organisation_id=organisation_id)

    def list(self, request, organisation_id=None):
        return Response(
            {"detail": "Not implemented"}, status=status.HTTP_501_NOT_IMPLEMENTED
        )

    def retrieve(self, request, organisation_id=None, pk=None):
        return Response(
            {"detail": "Not implemented"}, status=status.HTTP_501_NOT_IMPLEMENTED
        )

    def create(self, request, organisation_id=None):
        return Response(
            {"detail": "Not implemented"}, status=status.HTTP_501_NOT_IMPLEMENTED
        )

    def update(self, request, organisation_id=None, pk=None):
        return Response(
            {"detail": "Not implemented"}, status=status.HTTP_501_NOT_IMPLEMENTED
        )

    def partial_update(self, request, organisation_id=None, pk=None):
        return Response(
            {"detail": "Not implemented"}, status=status.HTTP_501_NOT_IMPLEMENTED
        )

    def destroy(self, request, organisation_id=None, pk=None):
        return Response(
            {"detail": "Not implemented"}, status=status.HTTP_501_NOT_IMPLEMENTED
        )
