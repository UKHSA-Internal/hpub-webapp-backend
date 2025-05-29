from django_filters import rest_framework as filters
from django.db.models import Q
from .models import Product


class ProductFilter(filters.FilterSet):
    q = filters.CharFilter(method="filter_search", label="Free-text search")
    recently_updated = filters.DateTimeFilter(
        field_name="updated_at", lookup_expr="gte"
    )
    audiences = filters.BaseInFilter(
        field_name="update_ref__audience_ref__name", lookup_expr="in"
    )
    diseases = filters.BaseInFilter(
        field_name="update_ref__diseases_ref__name", lookup_expr="in"
    )
    vaccinations = filters.BaseInFilter(
        field_name="update_ref__vaccination_ref__name", lookup_expr="in"
    )
    program_names = filters.BaseInFilter(field_name="program_name", lookup_expr="in")
    product_types = filters.BaseInFilter(
        field_name="update_ref__product_type", lookup_expr="in"
    )
    languages = filters.BaseInFilter(field_name="language_name", lookup_expr="in")
    where_to_use = filters.BaseInFilter(
        field_name="update_ref__where_to_use_ref__name", lookup_expr="in"
    )
    alternative_type = filters.BaseInFilter(
        field_name="update_ref__alternative_type", lookup_expr="in"
    )
    download_mode = filters.ChoiceFilter(
        method="filter_download_mode",
        choices=[
            ("download_only", "download_only"),
            ("order_only", "order_only"),
            ("download_and_order", "download_and_order"),
        ],
    )

    class Meta:
        model = Product
        fields = [
            "q",
            "recently_updated",
            "audiences",
            "diseases",
            "vaccinations",
            "program_names",
            "product_types",
            "languages",
            "where_to_use",
            "alternative_type",
            "download_mode",
        ]

    def filter_search(self, qs, name, value):
        return qs.filter(
            Q(product_title__icontains=value)
            | Q(product_code_no_dashes__icontains=value)
        )

    def filter_download_mode(self, qs, name, value):
        return qs.filter(tag__in=[value])
