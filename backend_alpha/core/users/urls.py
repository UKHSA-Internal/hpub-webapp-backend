from django.urls import path

from .views import (
    LogoutView,
    TokenRefresh,
    UpdateUserView,
    UserDetailView,
    UserLoginView,
    UserSignUpView,
)

urlpatterns = [
    path("users/signup/", UserSignUpView.as_view(), name="signup"),
    path("users/update/", UpdateUserView.as_view(), name="update-user-view"),
    path("users/login/", UserLoginView.as_view(), name="login"),
    path("users/logout/", LogoutView().as_view(), name="logout"),
    path("users/refresh/", TokenRefresh.as_view(), name="token_refresh"),
    path("users/<uuid:user_id>/", UserDetailView.as_view(), name="user-detail"),
]
