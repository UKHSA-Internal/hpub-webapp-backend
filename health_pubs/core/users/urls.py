from django.urls import path
from django.urls import include
from rest_framework.routers import DefaultRouter

from core.users import views


router = DefaultRouter()
router.register(r"api/v2/users", views.UsersV2, basename="users")


urlpatterns = [
    path(
        "api/v1/users/pre-registration/",
        views.PreRegistrationView.as_view(),
        name="users-pre-registration",
    ),
    path("api/v1/users/signup/", views.UserSignUpView.as_view(), name="users-signup"),
    path("api/v1/users/update/", views.UpdateUserView.as_view(), name="users-update"),
    path("api/v1/users/login/", views.UserLoginView.as_view(), name="auth-login"),
    path(
        "api/v1/users/auth/status/", views.AuthStatusView.as_view(), name="auth-status"
    ),
    path("api/v1/users/logout/", views.LogoutView().as_view(), name="auth-logout"),
    path(
        "api/v1/users/refresh/", views.TokenRefresh.as_view(), name="auth-token-refresh"
    ),
    path(
        "api/v1/users/delete-account/",
        views.DeleteAccountView.as_view(),
        name="users-delete",
    ),
    path(
        "api/v1/users/<str:user_id>/", views.UserDetailView.as_view(), name="users-get"
    ),
    path("api/v1/users/list/", views.UserListView.as_view(), name="users-list"),
    path(
        "api/v1/users/migrate-users/",
        views.MigrateUsersAPIView.as_view(),
        name="users-migrate",
    ),
    path(
        "api/v2/users/<str:user_id>/roles",
        views.UserRolesView.as_view(),
        name="users-roles",
    ),
    path(
        "api/v2/users/<str:user_id>/state",
        views.UserStateView.as_view(),
        name="users-state",
    ),
] + router.urls
