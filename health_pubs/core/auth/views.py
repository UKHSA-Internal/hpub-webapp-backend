# core/authentication/views.py

from rest_framework.decorators import (
    api_view,
    permission_classes,
    authentication_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

from core.auth import services


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def get_token(request):
    data = services.decode_access_token(request)
    return Response(data, status=status.HTTP_200_OK)


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def get_user(request):
    data = services.get_user_from_access_token(request)
    return Response(data, status=status.HTTP_200_OK)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def create_access_token(request):
    data = services.create_access_token(request)
    return Response(data, status=status.HTTP_200_OK)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def refresh_access_token(request):
    data = services.refresh_access_token()
    return Response(data, status=status.HTTP_200_OK)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def revoke_access_token(request):
    data = services.revoke_access_token(request)
    return Response(data, status=status.HTTP_200_OK)