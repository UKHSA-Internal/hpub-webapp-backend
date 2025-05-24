from django.urls import path

from .views import (
    LogoutView,
    MigrateUsersAPIView,
    TokenRefresh,
    UpdateUserView,
    UserDetailView,
    UserListView,
    UserLoginView,
    UserSignUpView,
    PreRegistrationView,
)

urlpatterns = [
    path("users/pre-registration/", PreRegistrationView, name="b2c-pre-registration"),
    path("users/signup/", UserSignUpView.as_view(), name="signup"),
    path("users/update/", UpdateUserView.as_view(), name="update-user-view"),
    path("users/login/", UserLoginView.as_view(), name="login"),
    path("users/logout/", LogoutView().as_view(), name="logout"),
    path("users/refresh/", TokenRefresh.as_view(), name="token_refresh"),
    path("users/<uuid:user_id>/", UserDetailView.as_view(), name="user-detail"),
    path("users/list/", UserListView.as_view(), name="user-list"),
    path("users/migrate-users/", MigrateUsersAPIView.as_view(), name="user-migrate"),
]
