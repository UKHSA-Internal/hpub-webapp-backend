# views.py
import uuid
import boto3
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from core.utils.custom_token_authentication import CustomTokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import authentication_classes, permission_classes
from core.users.permissions import IsAdminUser


@authentication_classes([CustomTokenAuthentication])
@permission_classes([IsAuthenticated, IsAdminUser])
class GeneratePresignedUrlView(APIView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bucket_name = settings.AWS_BUCKET_NAME
        self.region = settings.AWS_REGION
        self.s3_client = boto3.client("s3", region_name=self.region)

    def post(self, request):
        file_name = request.data.get("fileName")
        content_type = request.data.get("contentType")

        if not file_name or not content_type:
            return Response(
                {"error": "Missing fileName or contentType"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Generate a unique key for the file using a UUID.
        key = f"{uuid.uuid4()}_{file_name}"

        try:
            presigned_url = self.s3_client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self.bucket_name,
                    "Key": key,
                    "ContentType": content_type,
                },
                ExpiresIn=3600,
            )
        except Exception as e:
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response(
            {
                "url": presigned_url,
                "key": key,
                "bucketName": self.bucket_name,
                "region": self.region,
            }
        )
