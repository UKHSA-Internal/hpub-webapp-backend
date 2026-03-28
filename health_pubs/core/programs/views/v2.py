from core.common.views import CommonViewSet
from core.programs.serializers import ProgramSerializer
from core.programs.models import Program


class ProgrammesV2(CommonViewSet):
    queryset = Program.objects.all()
    serializer_class = ProgramSerializer
