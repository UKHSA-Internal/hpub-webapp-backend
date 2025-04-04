import datetime
import json
import logging
from django.http import JsonResponse
from django.utils.text import slugify
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Count
from rest_framework.views import APIView
from rest_framework.response import Response
from wagtail.models import Page
from core.users.models import User
from core.errors.error_function import handle_error
from core.errors.enums import ErrorCode, ErrorMessage
from rest_framework.authentication import SessionAuthentication
from core.utils.custom_token_authentication import CustomTokenAuthentication
from rest_framework.permissions import IsAuthenticated, AllowAny
from collections import defaultdict
from core.users.permissions import (
    IsAdminUser,
)
from .models import EventAnalytics
from .serializers import AnalyticsEventSerializer

logger = logging.getLogger(__name__)


class EventAnalyticsCreateView(APIView):
    """
    Optimized view to handle EventAnalytics creation via POST requests.
    Uses the user_id from the request to fetch the user_ref and stores the event
    as a Wagtail Page under a parent page with slug "events".
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        logger.info("EventAnalyticsCreateView POST method called")
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON: %s", str(e))
            return handle_error(
                ErrorCode.INVALID_DATA, ErrorMessage.INVALID_DATA, status_code=400
            )
        logger.info("Data received: %s", data)

        required_fields = ["event_type", "metadata", "session_id"]
        missing_fields = [field for field in required_fields if not data.get(field)]
        if missing_fields:
            logger.warning("Missing required fields: %s", missing_fields)
            return handle_error(
                ErrorCode.MISSING_FIELD, ErrorMessage.MISSING_FIELD, status_code=400
            )

        event_type = data["event_type"]
        metadata = data["metadata"]
        session_id = data["session_id"]

        # Optional: if a user_id is passed, fetch the corresponding user.
        user_id = data.get("user_id")
        user_instance = self.get_user_instance(user_id) if user_id else None

        # Generate a title and slug if not provided in data
        title = data.get("title", f"{event_type} Event - {session_id}")
        slug = data.get(
            "slug", slugify(f"{event_type}-{session_id}-{datetime.datetime.now()}")
        )

        data.update(
            {
                "title": title,
                "slug": slug,
            }
        )

        parent_page = self.get_or_create_parent_page()
        user_instance = self.get_user_instance(user_id)
        if isinstance(user_instance, JsonResponse):
            # If get_user_instance returned an error response, propagate it.
            return user_instance

        # Create the new event instance (as a Wagtail Page)
        event_instance = EventAnalytics(
            title=title,
            slug=slug,
            event_type=event_type,
            metadata=metadata,
            session_id=session_id,
            user_ref=user_instance,
        )

        # Save the event as a child page of the parent
        parent_page.add_child(instance=event_instance)
        logger.info("EventAnalytics instance created successfully.")
        return JsonResponse(AnalyticsEventSerializer(event_instance).data, status=201)

    def get_or_create_parent_page(self):
        """
        Retrieve the parent page with slug "events". If it does not exist,
        fallback to the first root page.
        """
        try:
            parent_page = Page.objects.get(slug="events")
            logger.info("Parent page 'events' found.")
        except ObjectDoesNotExist:
            logger.warning("Parent page 'events' not found; using the first root page.")
            parent_page = Page.get_first_root_node()
        return parent_page

    def get_user_instance(self, user_ref_id):
        """
        Retrieve the User instance based on the provided user_id.
        """
        if user_ref_id:
            try:
                return User.objects.get(user_id=user_ref_id)
            except User.DoesNotExist as e:
                logger.warning("User %s not found: %s", user_ref_id, str(e))
                return handle_error(
                    ErrorCode.USER_NOT_FOUND,
                    ErrorMessage.USER_NOT_FOUND,
                    status_code=404,
                )
        return None


class EventAnalyticsAdminListView(APIView):
    """
    View to list all EventAnalytics records.
    Restricted to admin users via authentication and permission classes.
    """

    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request, *args, **kwargs):
        # Retrieve events under the "events" parent page (or all events)
        try:
            parent_page = Page.objects.get(slug="events")
            # Get all descendant pages that are EventAnalytics
            events = (
                parent_page.get_descendants()
                .specific()
                .filter(id__in=EventAnalytics.objects.values("id"))
            )
        except Page.DoesNotExist:
            events = EventAnalytics.objects.all()
        serializer = AnalyticsEventSerializer(events, many=True)
        return Response(serializer.data)


class EventAnalyticsStatsViewPerSessionId(APIView):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request, *args, **kwargs):
        events = EventAnalytics.objects.all()

        # Nested structure: session_id → product_code → counts
        stats = defaultdict(
            lambda: defaultdict(lambda: {"basket_add": 0, "order_completion": 0})
        )

        for event in events:
            session_id = event.session_id
            product_code = event.metadata.get("productCode")
            if not product_code:
                continue

            if event.event_type in ["basket_add", "order_completion"]:
                stats[session_id][product_code][event.event_type] += 1

        # Add completion_rate to each nested group
        for session_id, session_data in stats.items():
            for product_code, counts in session_data.items():
                adds = counts["basket_add"]
                completes = counts["order_completion"]
                counts["completion_rate"] = (
                    round((completes / adds) * 100, 2) if adds else 0.0
                )

        return Response(stats)


class EventAnalyticsStatsView(APIView):
    """
    Aggregates basket_add and order_completion events per product_code and/or session.
    Used to calculate order completion rates.
    """

    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request, *args, **kwargs):
        # Optional query filters (e.g., by date range)
        start_date = request.query_params.get("start_date")  # format: YYYY-MM-DD
        end_date = request.query_params.get("end_date")  # format: YYYY-MM-DD

        filters = {}
        if start_date and end_date:
            filters["timestamp__range"] = [start_date, end_date]

        # Get all events matching filter
        events = EventAnalytics.objects.filter(**filters)

        # Group and count events by product_code + event_type
        grouped_counts = events.values("metadata__product_code", "event_type").annotate(
            count=Count("id")
        )

        # Structure the result
        stats = {}
        for entry in grouped_counts:
            product_code = entry["metadata__product_code"]
            event_type = entry["event_type"]
            count = entry["count"]

            if product_code not in stats:
                stats[product_code] = {
                    "basket_add": 0,
                    "order_completion": 0,
                }

            if event_type == "basket_add":
                stats[product_code]["basket_add"] = count
            elif event_type == "order_completion":
                stats[product_code]["order_completion"] = count

        # Add calculated completion rate per product
        for product_code, data in stats.items():
            added = data["basket_add"]
            completed = data["order_completion"]
            data["completion_rate"] = (
                round((completed / added) * 100, 2) if added > 0 else 0.0
            )

        return Response(stats)
