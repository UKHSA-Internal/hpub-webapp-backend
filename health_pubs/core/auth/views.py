from rest_framework.decorators import api_view
from rest_framework.decorators import permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from . import services

@api_view(['GET'])
@permission_classes([AllowAny])
def get_access_token(request: Request):
    response = services.get_access_token_from_browser()
    return Response({ 'access_token': response })