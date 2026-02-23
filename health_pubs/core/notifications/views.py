from core.users.permissions import IsAdminUser
from core.utils.custom_token_authentication import CustomTokenAuthentication
from django.db.models import Case, IntegerField, Q, When
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import Notification
from .serializers import NotificationEnabledSerializer, NotificationSerializer


class NotificationViewSet(viewsets.ModelViewSet):
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    authentication_classes = [SessionAuthentication, CustomTokenAuthentication]

    def get_queryset(self):
        queryset = super().get_queryset()

        # Admin list supports filtering by derived state via ?state=ENABLED|SCHEDULED|DISABLED.
        if getattr(self, "action", None) != "list":
            return queryset

        state = self.request.query_params.get("state")
        if not state:
            return queryset

        state = state.upper()
        now = timezone.now()

        if state == Notification.State.ENABLED:
            return (
                queryset.filter(is_enabled=True)
                .filter(Q(start_at__isnull=True) | Q(start_at__lte=now))
                .filter(Q(end_at__isnull=True) | Q(end_at__gte=now))
            )

        if state == Notification.State.SCHEDULED:
            return queryset.filter(is_enabled=True, start_at__gt=now)

        if state == Notification.State.DISABLED:
            return queryset.filter(Q(is_enabled=False) | Q(is_enabled=True, end_at__lt=now))

        allowed = ", ".join(Notification.State.values)
        raise ValidationError({"state": f"Invalid state. Use one of: {allowed}."})

    def get_permissions(self):
        # Only the public active banner endpoint is open; all other notification actions require admin access.
        if self.action in ["active"]:
            permission_classes = [AllowAny]
        else:
            permission_classes = [IsAuthenticated, IsAdminUser]
        return [permission() for permission in permission_classes]

    # Public endpoint for frontend banner check: returns latest active notification or DISABLED fallback.
    @action(detail=False, methods=["get"], url_path="active")
    def active(self, request):
        now = timezone.now()
        notification = (
            self.get_queryset()
            .filter(
                is_enabled=True,
            )
            .filter(Q(start_at__isnull=True) | Q(start_at__lte=now))
            .filter(Q(end_at__isnull=True) | Q(end_at__gte=now))
            # Priority among currently active banners:
            # 1) Does not have start date and does not have end date (unplanned emergency).
            # 2) Has end date, does not have start date (notify now until end date).
            # 3) Has start date (with or without end date), newest start date first.
            .annotate(
                display_priority=Case(
                    When(start_at__isnull=True, end_at__isnull=True, then=0),
                    When(start_at__isnull=True, end_at__isnull=False, then=1),
                    default=2,
                    output_field=IntegerField(),
                )
            )
            .order_by("display_priority", "-start_at", "-updated_at", "-created_at")
            .first()
        )

        if not notification:
            return Response(
                {
                    "notification_id": None,
                    "is_enabled": False,
                    "state": Notification.State.DISABLED,
                    "message": "",
                    "start_at": None,
                    "end_at": None,
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            NotificationSerializer(notification).data,
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="enabled")
    def set_enabled(self, request, pk=None):
        # POST /notifications/:id/enabled toggles only the is_enabled flag.
        notification = self.get_object()
        serializer = NotificationEnabledSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        notification.is_enabled = serializer.validated_data["is_enabled"]
        notification.save(update_fields=["is_enabled", "updated_at"])

        return Response(
            NotificationSerializer(notification).data,
            status=status.HTTP_200_OK,
        )
