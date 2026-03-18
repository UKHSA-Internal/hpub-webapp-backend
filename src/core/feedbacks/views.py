from datetime import datetime

from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.utils.text import slugify
from django.http import JsonResponse
from rest_framework.authentication import SessionAuthentication
from core.users.models import User
from wagtail.models import Page

from .models import Feedback
from .serializers import FeedbackSerializer


class FeedbackViewSet(viewsets.ModelViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    queryset = Feedback.objects.all().order_by("-submitted_at")
    serializer_class = FeedbackSerializer

    def create(self, request, *args, **kwargs):
        data = request.data
        user_instance = None

        # Get the authenticated user if available
        if request.user.is_authenticated:
            user_instance = request.user

        # If a user_ref is provided, override the user_instance
        user_ref_id = data.get("user_ref")
        if user_ref_id:
            try:
                user_instance = User.objects.get(user_id=user_ref_id)
            except User.DoesNotExist:
                return JsonResponse(
                    {"error": f"User with ID {user_ref_id} does not exist"}, status=400
                )

        # Prepare feedback data from request
        feedback_data = {
            "feedback_id": data.get("feedback_id"),
            "title": "feedback_title",
            "slug": slugify(
                f"feedback-{user_instance.id if user_instance else 'anonymous'}-"
                + str(datetime.now())
            ),
            "user_ref": user_instance,
            "how_satisfied": data.get("how_satisfied", ""),
            "would_recommend": data.get("would_recommend", ""),
            "where_did_you_hear": data.get("where_did_you_hear", ""),
            "why_did_you_come": data.get("why_did_you_come", ""),
            "did_you_get_what_you_wanted": data.get("did_you_get_what_you_wanted", ""),
            "improve_our_service": data.get("improve_our_service", ""),
        }

        parent_page = self._get_or_create_feedback_parent_page()
        feedback_instance = Feedback(**feedback_data)

        # If parent page has no children, set path/depth manually
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
        If `user_id` is provided as a query param, filter feedback by that user.
        Otherwise, return all feedback.
        """
        user_id = request.query_params.get("user_id")
        if user_id:
            feedbacks = self.queryset.filter(user_ref=user_id)
        else:
            feedbacks = self.get_queryset()

        serializer = self.get_serializer(feedbacks, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def _get_or_create_feedback_parent_page(self):
        """
        Helper method to ensure there's a parent page in Wagtail
        to attach Feedback pages under.
        """
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
