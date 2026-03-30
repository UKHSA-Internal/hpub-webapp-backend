from core.common.views import CommonViewSet
from core.roles.serializers import RoleSerializer
from core.roles.models import Role


class RolesV2(CommonViewSet):
    queryset = Role.objects.all()
    serializer_class = RoleSerializer
