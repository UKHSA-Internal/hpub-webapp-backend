from core.programs.models import Program
from django.core.exceptions import ValidationError
from rest_framework import serializers

from .models import Disease


class DiseaseSerializer(serializers.ModelSerializer):
    program_names = serializers.ListField(
        child=serializers.CharField(),
        write_only=True,
        required=False,  # allow omitted for PATCH
    )

    programs = serializers.SerializerMethodField()

    class Meta:
        model = Disease
        fields = [
            "disease_id",
            "name",
            "key",
            "description",
            "program_names",  # used for creating OR adding
            "programs",  # read-only list shown in UI
        ]

    def get_programs(self, obj):
        # Display readable names
        return [p.programme_name for p in obj.programs.all()]

    # ------------------------
    # CREATE
    # ------------------------
    def create(self, validated_data):
        program_names = validated_data.pop("program_names", [])
        programs = []

        for name in program_names:
            try:
                programs.append(Program.objects.get(programme_name=name))
            except Program.DoesNotExist:
                raise ValidationError({"error": f"Programme '{name}' does not exist."})

        disease = Disease.objects.create(**validated_data)
        disease.programs.set(programs)
        return disease

    # ------------------------
    # UPDATE (NO REMOVAL — ONLY ADDING)
    # ------------------------
    def update(self, instance, validated_data):
        # Basic editable fields
        instance.name = validated_data.get("name", instance.name)
        instance.key = validated_data.get("key", instance.key)
        instance.description = validated_data.get("description", instance.description)
        instance.save()

        #  Preserve all existing programmes (they are read-only)
        existing_programs = set(instance.programs.all())

        #  Only allow ADDING new ones
        new_program_names = validated_data.get("program_names", [])
        new_programs = set()

        for name in new_program_names:
            try:
                p = Program.objects.get(programme_name=name)
                new_programs.add(p)
            except Program.DoesNotExist:
                raise ValidationError({"error": f"Programme '{name}' does not exist."})

        #  Merge existing + new (no deletions)
        instance.programs.set(existing_programs.union(new_programs))
        return instance


class DiseaseListSerializer(serializers.Serializer):
    diseases = DiseaseSerializer(many=True)
