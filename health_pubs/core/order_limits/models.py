import uuid

from core.organizations.models import Organization
from core.products.models import Product
from django.contrib.postgres.fields import ArrayField
from django.db import models
from wagtail.admin.panels import FieldPanel, PageChooserPanel
from wagtail.models import Page


class OrderLimitPage(Page):
    order_limit_id = models.CharField(
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        editable=False,
        max_length=225,
    )
    order_limit = models.PositiveIntegerField()
    product_ref = models.ForeignKey(
        Product, null=True, on_delete=models.SET_NULL, related_name="order_limits"
    )

    organization_ref = models.ForeignKey(
        Organization, null=True, on_delete=models.SET_NULL, related_name="order_limits"
    )



    full_external_keys = ArrayField(
        models.CharField(max_length=255), blank=True, default=list
    )



    content_panels = Page.content_panels + [
        FieldPanel("order_limit"),
        PageChooserPanel("product_ref"),
        PageChooserPanel("organization_ref"),
    ]
