import uuid

from core.addresses.models import Address
from core.products.models import Product
from core.users.models import User
from django.db import models
from wagtail.models import Page


class Order(Page):
    order_id = models.CharField(
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        editable=False,
        max_length=225,
    )
    user_ref = models.ForeignKey(
        User, null=True, on_delete=models.SET_NULL, related_name="orders"
    )

    full_external_key = models.CharField(
        max_length=25,
        null=False,
        blank=True,
        help_text="The full external key retrieved from the related establishment.",
    )
    order_confirmation_number = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    address_ref = models.ForeignKey(
        Address, null=True, on_delete=models.SET_NULL, related_name="orders"
    )
    order_origin = models.CharField(
        max_length=50,
        null=True,
        blank=False,
        choices=[("by_user", "BY_USER"), ("order_on_behalf", "ORDER_ON_BEHALF")],
    )

    order_date = models.DateTimeField(auto_now_add=True)
    tracking_number = models.CharField(max_length=50, null=True, blank=True)

    def __str__(self):
        return f"Order {self.order_id}"


class OrderItem(Page):
    order_item_id = models.CharField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        unique=True,
        max_length=225,
    )
    order_ref = models.ForeignKey(
        Order,
        related_name="order_items",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    product_ref = models.ForeignKey(
        Product,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="order_items",
    )
    product_code = models.CharField(max_length=255, default="UNKNOWN", editable=False)
    quantity = models.IntegerField()
    quantity_inprogress = models.IntegerField(default=0)
    quantity_shipped = models.IntegerField(default=0)
    quantity_cancelled = models.IntegerField(default=0)

    def save(self, *args, **kwargs):
        # Automatically set the product_code from the product_ref
        if self.product_ref:
            self.product_code = self.product_ref.product_code
        super().save(*args, **kwargs)

    def __str__(self):
        return f"OrderItem for {self.product_ref} in Order {self.order_ref}"
