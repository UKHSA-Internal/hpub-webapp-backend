from core.programs.models import Program
from django.core.exceptions import ValidationError
from rest_framework import serializers

from .models import Vaccination


class VaccinationSerializer(serializers.ModelSerializer):
    program_names = serializers.ListField(
        child=serializers.CharField(),
        write_only=True,
        required=False,  # allow partial updates
    )
    programs = serializers.SerializerMethodField()

    class Meta:
        model = Vaccination
        fields = [
            "vaccination_id",
            "name",
            "description",
            "key",
            "program_names",  # used for create OR adding
            "programs",  # read-only list for UI
        ]

    def get_programs(self, obj):
        # Return readable programme names for frontend display
        return [p.programme_name for p in obj.programs.all()]

    # -------------------------
    # CREATE (existing logic)
    # -------------------------
    def create(self, validated_data):
        program_names = validated_data.pop("program_names", [])
        programs = []

        for program_name in program_names:
            try:
                program = Program.objects.get(programme_name=program_name)
                programs.append(program)
            except Program.DoesNotExist:
                raise ValidationError(
                    {"error": f"Programme '{program_name}' does not exist."}
                )

        vaccination = Vaccination.objects.create(**validated_data)
        vaccination.programs.set(programs)
        return vaccination

    # -------------------------
    # UPDATE (NEW LOGIC)
    # Only ADD new programmes; existing remain untouched
    # -------------------------
    def update(self, instance, validated_data):
        # Update editable fields
        instance.name = validated_data.get("name", instance.name)
        instance.description = validated_data.get("description", instance.description)
        instance.key = validated_data.get("key", instance.key)
        instance.save()

        # Existing programmes remain unchanged (AC rule)
        existing_programs = set(instance.programs.all())

        # New programmes to add
        new_program_names = validated_data.get("program_names", [])
        new_programs = set()

        for name in new_program_names:
            try:
                p = Program.objects.get(programme_name=name)
                new_programs.add(p)
            except Program.DoesNotExist:
                raise ValidationError({"error": f"Programme '{name}' does not exist."})

        # Merge existing + new
        final_programs = existing_programs.union(new_programs)
        instance.programs.set(final_programs)

        return instance


class VaccinationListSerializer(serializers.Serializer):
    vaccinations = VaccinationSerializer(many=True)
