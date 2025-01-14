import uuid

from django.db import models
from wagtail.models import Page


class Role(Page):
    role_id = models.CharField(
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        editable=False,
        max_length=225,
    )
    name = models.CharField(max_length=50)
    # name = models.CharField(
    #     max_length=50, choices=[(tag.name, tag.name) for tag in PersonaPermission]
    # )
    permissions = models.JSONField(default=list, null=True, blank=True)

    # def save(self, *args, **kwargs):
    #     # Automatically assign permissions based on the name
    #     if not self.permissions:
    #         if self.name in PersonaPermission.__members__:
    #             self.permissions = PersonaPermission[self.name].value
    #         else:
    #             self.permissions = []
    #             logging.info(f"Warning: {self.name} is not a valid permission name. Assigning empty permissions.")
    #             # raise ValueError(f"{self.name} is not a valid permission name.")
    #     # super().save(*args, **kwargs)

    # def has_permission(self, permission):
    #     return permission in self.permissions
