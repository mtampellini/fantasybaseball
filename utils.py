"""Common helpers shared across modules."""

import unicodedata
import re


def normalize_name(name):
    """
    Normalize player names for matching across data sources.
    - Lowercase
    - Strip accents
    - Handle 'Last, First' format from Savant
    - Strip Jr/Sr suffixes
    """
    if not name:
        return ""
    if "," in name:
        parts = [p.strip() for p in name.split(",")]
        if len(parts) == 2:
            name = f"{parts[1]} {parts[0]}"
    name = name.lower().strip()
    # Strip Jr./Sr.
    name = re.sub(r"\s+(jr|sr)\.?$", "", name)
    # Remove accents
    nfd = unicodedata.normalize("NFD", name)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def parse_float(val, default=None):
    """Parse a string/cell to float, return default if invalid."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    try:
        s = str(val).strip().replace(",", "")
        if not s or s == "-" or s == "--":
            return default
        return float(s)
    except (ValueError, TypeError):
        return default


def parse_int(val, default=None):
    """Parse to int."""
    f = parse_float(val, default)
    if f is None:
        return default
    return int(f)


def safe_get(d, *keys, default=None):
    """Nested dict get."""
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k)
        if d is None:
            return default
    return d
