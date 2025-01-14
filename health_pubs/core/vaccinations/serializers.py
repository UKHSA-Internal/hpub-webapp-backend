from core.programs.models import Program
from django.core.exceptions import ValidationError
from rest_framework import serializers

from .models import Vaccination


class VaccinationSerializer(serializers.ModelSerializer):
    program_names = serializers.ListField(
        child=serializers.CharField(),
        write_only=True,
        required=True,
    )
    programs = serializers.SerializerMethodField()  # Read-only field

    class Meta:
        model = Vaccination
        fields = [
            "vaccination_id",
            "name",
            "description",
            "key",
            "program_names",
            "programs",
        ]

    def get_programs(self, obj):
        # This method provides the output for the programs field
        return [program.program_id for program in obj.programs.all()]

    def create(self, validated_data):
        # Handle creation logic, linking programs through program_names
        program_names = validated_data.pop("program_names")
        programs = []
        for program_name in program_names:
            try:
                program = Program.objects.get(programme_name=program_name)
                programs.append(program)
            except Program.DoesNotExist:
                raise ValidationError(
                    {"error": f"Program '{program_name}' does not exist."}
                )

        vaccination_instance = Vaccination.objects.create(**validated_data)
        # Set many-to-many relationship
        vaccination_instance.programs.set(programs)
        return vaccination_instance


class VaccinationListSerializer(serializers.Serializer):
    vaccinations = VaccinationSerializer(many=True)
