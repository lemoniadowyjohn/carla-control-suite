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


# ============================================================================
# P0-E: absolute OpenDRIVE georeference authority
# ============================================================================
#
# The map-of-record family stores plan-view coordinates in a LOCAL frame:
#     local = native_tmerc(lat_0=0 lon_0=0 k=1) - (offset.x, offset.y)
# with the rebase declared only as a header <offset x="832671.676"
# y="5458671.104"> and a bare `<geoReference>+proj=tmerc</geoReference>`.
# A bare tmerc has NO absolute origin, so WGS84 -> projected CRS -> local →
# OpenDRIVE geoReference → CARLA GNSS is not invertible: geodetic operations
# cannot produce truthful coordinates.
#
# The truthful single-CRS encoding re-expresses the SAME rebase (no second
# offset, no coordinate mutation) directly in the projection's false
# easting/northing, because proj's x_0/y_0 are pure post-translations:
#
#   proj(lat_0=0 lon_0=0 k=1 x_0=-offset.x y_0=-offset.y) == local
#
# The offsets are supplied as arguments by the frame-contract caller so this
# module stays dependency-free (core layer) and duplicated frame math is
# impossible.


def build_local_rebased_georeference(offset_x: float, offset_y: float) -> str:
    """Absolute <geoReference> for a map whose plan-view coordinates are
    ``native_tmerc(0,0,1) - (offset_x, offset_y)``.

    The rebase is embedded as ``+x_0=-offset_x `` ``+y_0=-offset_y`` on the
    native (lat_0=0, lon_0=0, k=1) transverse Mercator definition, so the
    resulting projection is exactly invertible against the file coordinates:
    forward(WGS84 anchor) == anchor_native - (offset_x, offset_y).
    """
    return normalize_georeference(
        "+proj=tmerc +lat_0=0 +lon_0=0 +k=1 "
        f"+x_0={float(-offset_x):.3f} +y_0={float(-offset_y):.3f} "
        "+datum=WGS84 +units=m +no_defs"
    )


def _parse_proj_param(proj4: str, key: str) -> Optional[float]:
    """Extract one ``+key=`` value from a PROJ.4-ish geoReference string."""
    prefix = f"{key}="
    for token in normalize_georeference(proj4).split():
        if token.startswith(prefix):
            try:
                return float(token[len(prefix):])
            except (TypeError, ValueError):
                return None
    return None


def has_embedded_georef_origin(proj4: str) -> bool:
    """True when the geoReference itself declares non-zero ``+x_0``/``+y_0``
    (an absolute origin embedded in the projection, not only in <offset>)."""
    x0 = _parse_proj_param(proj4, "+x_0")
    y0 = _parse_proj_param(proj4, "+y_0")
    return x0 is not None and y0 is not None and (x0 != 0.0 or y0 != 0.0)


def georef_describes_local_coords(
    proj4: str, offset_x: float, offset_y: float
) -> bool:
    """True when the geoReference maps plan-view (local) coordinates directly.

    Heavy-handed heuristic replaced by an exact rule: the projection embeds
    ``+x_0``/``+y_0`` values equal (within 1e-3 m) to minus the map's header
    offset, i.e. it re-expresses the same single rebase the header declares.
    Consumers must then NOT apply the header <offset> again on top of the
    geoReference transform.
    """
    x0 = _parse_proj_param(proj4, "+x_0")
    y0 = _parse_proj_param(proj4, "+y_0")
    if x0 is None or y0 is None:
        return False
    return (
        abs(x0 + float(offset_x)) <= 1e-3
        and abs(y0 + float(offset_y)) <= 1e-3
    )
