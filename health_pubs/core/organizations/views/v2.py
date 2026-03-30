from core.common.views import CommonViewSet
from core.organizations.serializers import OrganizationSerializer
from core.organizations.models import Organization


class OrganisationV2(CommonViewSet):
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer
