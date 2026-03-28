from .v1 import (
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
    DeleteAccountView
)
from .v2 import UsersV2
from core.users.views.v2 import UserRolesView
from core.users.views.v2 import UserStateView