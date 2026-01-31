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
        name="b2c-pre-registration",
    ),
    path("api/v1/users/signup/", UserSignUpView.as_view(), name="signup"),
    path("api/v1/users/update/", UpdateUserView.as_view(), name="update-user-view"),
    path("api/v1/users/login/", UserLoginView.as_view(), name="login"),
    path("api/v1/users/auth/status/", AuthStatusView.as_view(), name="auth-status"),
    path("api/v1/users/logout/", LogoutView().as_view(), name="logout"),
    path("api/v1/users/refresh/", TokenRefresh.as_view(), name="token_refresh"),
    path("api/v1/users/delete-account/", DeleteAccountView.as_view(), name="user-delete-account"),
    path("api/v1/users/<str:user_id>/", UserDetailView.as_view(), name="user-detail"),
    path("api/v1/users/list/", UserListView.as_view(), name="user-list"),
    path("api/v1/users/migrate-users/", MigrateUsersAPIView.as_view(), name="user-migrate"),
]
