# core/utils/search.py
import re
from typing import Tuple

from django.db.models import Q, F, Value, FloatField
from django.db.models.functions import Lower
from django.db.models import Case, When
from django.db.models.expressions import Func
from django.contrib.postgres.search import TrigramSimilarity

# ---- NEW: immutable unaccent wrapper ----
class UnaccentImm(Func):
    function = "unaccent_imm"
    arity = 1


# Normalise: drop dashes/underscores in codes, collapse spaces
CODE_STRIP = re.compile(r"[-_\s]+")


def normalize_code(s: str) -> str:
    return CODE_STRIP.sub("", s or "").strip()


def normalize_text(s: str) -> str:
    return (s or "").strip()


def build_search_filters(q: str) -> Tuple[Q, str, str]:
    """
    Fast prefix matches (autocomplete path). Accent-insensitive prefix would
    need shadow cols; we keep prefix on raw lower() which is indexed.
    """
    q_norm = normalize_text(q)
    q_code_norm = normalize_code(q_norm)

    filters = Q(product_title__istartswith=q_norm) | Q(
        product_code_no_dashes__istartswith=q_code_norm
    )
    return filters, q_norm, q_code_norm


def annotate_similarity(queryset, q_norm: str, q_code_norm: str):
    """
    Adds trigram similarity scores using unaccent_imm(lower(...)),
    plus a composite rank.
    """
    # Wrap fields with UnaccentImm(Lower(...))
    title_expr = UnaccentImm(Lower(F("product_title")))
    code_expr = UnaccentImm(Lower(F("product_code_no_dashes")))

    # Wrap search terms the same way
    q_title = UnaccentImm(Lower(Value(q_norm)))
    q_code = UnaccentImm(Lower(Value(q_code_norm)))

    qs = queryset.annotate(
        title_sim=TrigramSimilarity(title_expr, q_title),
        code_sim=TrigramSimilarity(code_expr, q_code),
        exact_title_boost=Case(
            When(product_title__iexact=q_norm, then=1.0),
            When(product_title__istartswith=q_norm, then=0.3),
            default=0.0,
            output_field=FloatField(),
        ),
        exact_code_boost=Case(
            When(product_code_no_dashes__iexact=q_code_norm, then=1.0),
            When(product_code_no_dashes__istartswith=q_code_norm, then=0.4),
            default=0.0,
            output_field=FloatField(),
        ),
    ).annotate(
        rank=(
            F("code_sim") * 1.2
            + F("title_sim") * 1.0
            + F("exact_title_boost")
            + F("exact_code_boost")
        )
    )
    return qs


def fuzzy_threshold_filter(
    queryset, q_norm: str, q_code_norm: str, min_sim: float = 0.15
):
    """
    Keep typo-close rows using the annotated sims.
    IMPORTANT: call this ONLY after annotate_similarity(), so title_sim/code_sim exist.
    """
    return queryset.filter(Q(title_sim__gte=min_sim) | Q(code_sim__gte=min_sim))
