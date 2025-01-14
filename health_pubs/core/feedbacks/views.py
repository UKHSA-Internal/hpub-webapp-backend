from datetime import datetime

from core.users.models import User
from core.users.permissions import IsRegisteredUser
from core.utils.custom_token_authentication import CustomTokenAuthentication
from django.http import JsonResponse
from django.utils.text import slugify
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from wagtail.models import Page

from .models import Feedback
from .serializers import FeedbackSerializer


class FeedbackViewSet(viewsets.ModelViewSet):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsRegisteredUser]
    queryset = Feedback.objects.all().order_by("-submitted_at")
    serializer_class = FeedbackSerializer

    def create(self, request, *args, **kwargs):
        data = request.data
        user_instance = None

        # Get authenticated user if available
        if request.user.is_authenticated:
            user_instance = request.user

        # Check for user_ref in data if provided explicitly
        user_ref_id = data.get("user_ref")
        if user_ref_id:
            try:
                user_instance = User.objects.get(user_id=user_ref_id)
            except User.DoesNotExist:
                return JsonResponse(
                    {"error": f"User with ID {user_ref_id} does not exist"}, status=400
                )

        if not user_instance:
            return Response(
                {"error": "User must be authenticated or user_ref must be provided"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Create Feedback instance
        feedback_data = {
            "feedback_id": data.get("feedback_id"),
            "title": "feedback_title",
            "slug": slugify(f"feedback-{user_instance.id}-" + str(datetime.now())),
            "message": data.get("message"),
            "user_ref": user_instance,
        }

        parent_page = self._get_or_create_feedback_parent_page()
        feedback_instance = Feedback(**feedback_data)

        # If parent has no children, manually handle depth and path settings
        if not parent_page.get_children().exists():
            feedback_instance.depth = parent_page.depth + 1
            feedback_instance.path = parent_page.path + "0001"
            feedback_instance.numchild = 0
            feedback_instance.save()
            parent_page.numchild += 1
            parent_page.save()
        else:
            parent_page.add_child(instance=feedback_instance)

        # Final save
        feedback_instance.save()

        serializer = self.get_serializer(feedback_instance)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def list(self, request, *args, **kwargs):
        """
        Retrieve all feedbacks in the system.
        """
        feedbacks = self.get_queryset()
        serializer = self.get_serializer(feedbacks, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def _get_or_create_feedback_parent_page(self):
        try:
            parent_page = Page.objects.get(slug="feedback")
        except Page.DoesNotExist:
            root_page = Page.objects.first()
            parent_page = Page(
                title="Feedback",
                slug="feedback",
            )
            root_page.add_child(instance=parent_page)
            root_page.save()
        return parent_page
