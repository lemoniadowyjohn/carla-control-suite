from __future__ import annotations

from typing import Optional, Dict, Any, Tuple


def _strip_cdata(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("<![CDATA[") and stripped.endswith("]]>"):
        return stripped[9:-3]
    return text


def normalize_georeference(text: Optional[str]) -> str:
    """
    Normalize geoReference whitespace for comparison purposes.
    Collapses all whitespace to single spaces, strips leading/trailing.
    Also strips CDATA wrappers for comparison.
    Does NOT change semantic meaning.
    """
    if text is None:
        return ""
    unwrapped = _strip_cdata(text)
    return " ".join(unwrapped.split())


def parse_georeference(text: Optional[str]) -> Tuple[bool, bool, str]:
    """
    Parse geoReference with a minimal completeness check.
    Treats "+proj=..." as valid but may be incomplete.
    Returns (valid, params_complete, normalized_string).
    """
    norm = normalize_georeference(text)
    valid = "+proj=" in norm if norm else False
    required = ("+lat_0=", "+lon_0=", "+k=", "+x_0=", "+y_0=", "+datum=", "+units=")
    params_complete = valid and all(r in norm for r in required)
    return valid, params_complete, norm


def parse_georeference_dict(text: Optional[str]) -> Dict[str, Any]:
    """Legacy helper for dict-style access."""
    valid, params_complete, norm = parse_georeference(text)
    return {"valid": valid, "params_complete": params_complete, "norm": norm}

# Canonical manual map CRS (used to make auto/manual maps comparable).
CANONICAL_MANUAL_GEOREFERENCE = (
    "+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 "
    "+datum=WGS84 +units=m +no_defs"
)


def canonical_manual_georeference() -> str:
    """Return canonical manual-map geoReference PROJ.4 string (normalized)."""
    return normalize_georeference(CANONICAL_MANUAL_GEOREFERENCE)
