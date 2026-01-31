from django.urls import path

from .views import (
    AuthStatusView,
    LogoutView,
    MigrateUsersAPIView,
    TokenRefresh,
    UpdateUserView,
    UserDetailView,
    UserListView,
    UserLoginView,
    UserSignUpView,
    PreRegistrationView,
    DeleteAccountView,
)

urlpatterns = [
    path(
        "api/v1/users/pre-registration/",
        PreRegistrationView.as_view(),
        name="users-pre-registration",
    ),
    path("api/v1/users/signup/", UserSignUpView.as_view(), name="users-signup"),
    path("api/v1/users/update/", UpdateUserView.as_view(), name="users-update"),
    path("api/v1/users/login/", UserLoginView.as_view(), name="auth-login"),
    path("api/v1/users/auth/status/", AuthStatusView.as_view(), name="auth-status"),
    path("api/v1/users/logout/", LogoutView().as_view(), name="auth-logout"),
    path("api/v1/users/refresh/", TokenRefresh.as_view(), name="auth-token-refresh"),
    path("api/v1/users/delete-account/", DeleteAccountView.as_view(), name="users-delete"),
    path("api/v1/users/<str:user_id>/", UserDetailView.as_view(), name="users-get"),
    path("api/v1/users/list/", UserListView.as_view(), name="users-list"),
    path("api/v1/users/migrate-users/", MigrateUsersAPIView.as_view(), name="users-migrate"),
]
