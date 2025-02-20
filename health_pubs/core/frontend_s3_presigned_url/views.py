# views.py
import time
import boto3
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.decorators import authentication_classes, permission_classes


@authentication_classes([SessionAuthentication])
@permission_classes([AllowAny])
class GeneratePresignedUrlView(APIView):
    def post(self, request):
        file_name = request.data.get("fileName")
        content_type = request.data.get("contentType")

        if not file_name or not content_type:
            return Response(
                {"error": "Missing fileName or contentType"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        bucket_name = settings.AWS_BUCKET_NAME
        region = settings.AWS_REGION

        # Generate a unique key for the file using the current timestamp.
        key = f"{int(time.time())}_{file_name}"

        # Initialize the S3 client
        s3_client = boto3.client("s3", region_name=region)
        try:
            # Create a pre-signed URL valid for 1 hour (3600 seconds)
            presigned_url = s3_client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": bucket_name,
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
                "bucketName": bucket_name,
                "region": region,
            }
        )
