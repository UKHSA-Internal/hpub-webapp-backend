# core/authentication/views.py

from rest_framework.decorators import (
    api_view,
    permission_classes,
    authentication_classes,
)
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework import status

from core.auth import services
from core.utils import custom_token_authentication


@api_view(["GET"])
@authentication_classes([custom_token_authentication.CustomTokenAuthentication])
@permission_classes([permissions.IsAuthenticated, permissions.IsAdminUser])
def get_token(request):
    data = services.decode_access_token(request)
    return Response(data, status=status.HTTP_200_OK)


@api_view(["GET"])
@authentication_classes([custom_token_authentication.CustomTokenAuthentication])
@permission_classes([permissions.IsAuthenticated, permissions.IsAdminUser])
def get_user(request):
    data = services.get_user_from_access_token(request)
    return Response(data, status=status.HTTP_200_OK)


@api_view(["POST"])
@authentication_classes([custom_token_authentication.CustomTokenAuthentication])
@permission_classes([permissions.IsAuthenticated, permissions.IsAdminUser])
def create_access_token(request):
    data = services.create_access_token(request)
    return Response(data, status=status.HTTP_200_OK)


@api_view(["POST"])
@authentication_classes([custom_token_authentication.CustomTokenAuthentication])
@permission_classes([permissions.IsAuthenticated, permissions.IsAdminUser])
def refresh_access_token(request):
    data = services.refresh_access_token()
    return Response(data, status=status.HTTP_200_OK)


@api_view(["POST"])
@authentication_classes([custom_token_authentication.CustomTokenAuthentication])
@permission_classes([permissions.IsAuthenticated, permissions.IsAdminUser])
def revoke_access_token(request):
    data = services.revoke_access_token(request)
    return Response(data, status=status.HTTP_200_OK)