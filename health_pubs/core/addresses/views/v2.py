from rest_framework import status, permissions, authentication, viewsets
from rest_framework.response import Response

from core.utils import logging_utils
from core.users.models import User
from core.addresses.serializers import AddressSerializer
from core.addresses.models import Address


logger = logging_utils.get_logger(__name__)


class UserAddressesV2(viewsets.ModelViewSet):
    authentication_classes = [authentication.TokenAuthentication]
    permission_classes = [permissions.AllowAny]
    serializer_class = AddressSerializer

    def get_queryset(self):
        user_id = self.kwargs.get("user_id")
        return User.objects.filter(user_id=user_id)

    def list(self, request, user_id=None):
        return Response(
            {"detail": "Not implemented"}, status=status.HTTP_501_NOT_IMPLEMENTED
        )

    def retrieve(self, request, user_id=None, pk=None):
        return Response(
            {"detail": "Not implemented"}, status=status.HTTP_501_NOT_IMPLEMENTED
        )

    def create(self, request, user_id=None):
        return Response(
            {"detail": "Not implemented"}, status=status.HTTP_501_NOT_IMPLEMENTED
        )

    def update(self, request, user_id=None, pk=None):
        return Response(
            {"detail": "Not implemented"}, status=status.HTTP_501_NOT_IMPLEMENTED
        )

    def partial_update(self, request, user_id=None, pk=None):
        return Response(
            {"detail": "Not implemented"}, status=status.HTTP_501_NOT_IMPLEMENTED
        )

    def destroy(self, request, user_id=None, pk=None):
        return Response(
            {"detail": "Not implemented"}, status=status.HTTP_501_NOT_IMPLEMENTED
        )
