# core/utils/address_normalizer.py

MAX_LINE = 53
MAX_CITY = 29
MAX_COUNTY = 40
MAX_POSTCODE = 8


def split_index_at_boundary(s: str, max_len: int) -> int:
    """Try to split at a natural boundary (comma or space) before hard cut."""
    comma = s.rfind(", ", 0, max_len)
    if comma > 0:
        return comma + 1
    space = s.rfind(" ", 0, max_len)
    if space > 0:
        return space
    return max_len


def enforce_length(input_str: str, max_len: int, spillover: str = ""):
    """Ensure string fits max_len, push remainder into spillover."""
    combined = ((spillover + " ") if spillover else "") + (input_str or "")
    trimmed = combined.strip()

    if len(trimmed) <= max_len:
        return trimmed, ""

    cut_at = split_index_at_boundary(trimmed, max_len)
    safe_part = trimmed[:cut_at].strip()
    remainder = trimmed[cut_at:].strip()
    return safe_part, remainder


def normalise_address_lines(line1: str, line2: str, line3: str):
    """Apply spillover logic across address_line1 → address_line2 → address_line3."""
    l1, overflow1 = enforce_length(line1 or "", MAX_LINE)
    l2, overflow2 = enforce_length(line2 or "", MAX_LINE, overflow1)
    l3, overflow3 = enforce_length(line3 or "", MAX_LINE, overflow2)

    # If still overflow → merge into line3 (truncate last line only)
    if overflow3:
        l3, _ = enforce_length((l3 + " " + overflow3).strip(), MAX_LINE)

    return l1, l2, l3


def normalize_address_instance(address_instance):
    """
    Takes a Django address instance and returns a dict
    with normalized fields that respect limits and spillover.
    """
    line1, line2, line3 = normalise_address_lines(
        getattr(address_instance, "address_line1", ""),
        getattr(address_instance, "address_line2", ""),
        getattr(address_instance, "address_line3", ""),
    )

    return {
        "address_lines": [line1, line2, line3],
        "city": (getattr(address_instance, "city", "") or "")[:MAX_CITY],
        "county": (getattr(address_instance, "county", "") or "")[:MAX_COUNTY],
        "postcode": (getattr(address_instance, "postcode", "") or "")[:MAX_POSTCODE],
        "country": getattr(address_instance, "country", "") or "England",
    }
