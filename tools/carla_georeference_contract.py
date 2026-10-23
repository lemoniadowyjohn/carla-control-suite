"""Georeference parse contract: fail closed instead of silently defaulting.

Provenance of the defect (verified in the CARLA 0.9.16 tree)
----------------------------------------------------------
``LibCarla/source/carla/opendrive/parser/GeoReferenceParser.cpp`` splits the
``<geoReference>`` string on spaces, accepts **only** ``+lat_0`` and ``+lon_0``,
and if either remains NaN it logs a warning and substitutes::

    result.latitude  = 42.0;
    result.longitude = 2.0;

Ingolstadt's map of record contains exactly ``+proj=tmerc`` -- no ``+lat_0``,
no ``+lon_0`` -- because the generator default in
``Build/osm2odr-source/src/OSM2ODR.h`` is the bare string::

    std::string proj_string = "+proj=tmerc";

The complete form the generator *can* build lives in
``src/utils/geom/GeoConvHelper.cpp`` (e.g. ``+proj=tmerc +lat_0=... +lon_0=...``)
and every stock CARLA town map carries it. Ingolstadt is the only map in the
tree missing it.

Impact: the fallback places the map at lat 42.0 / lon 2.0 while Ingolstadt is at
lat ~48.766 / lon ~11.425 -- roughly 752 km of latitude error. Every runtime
``get_location()``/GNSS/perception geolocation would be silently wrong.

This module is the executable reference for the required policy:

    valid, complete  -> parse and continue
    invalid/incomplete -> raise GeoreferenceError, never substitute defaults

It mirrors the C++ token grammar exactly so the contract can be unit tested on
this host without building CARLA. ``GeoReferenceParser.cpp`` must be changed to
match; this file is the specification of that change, not a substitute for it.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "GeoreferenceError",
    "ParsedGeoreference",
    "REQUIRED_KEYS",
    "parse_georeference_strict",
    "parse_georeference_legacy",
]

# The two keys CARLA actually consumes. A georeference without both cannot
# produce a map origin, so both are mandatory.
REQUIRED_KEYS = ("+lat_0", "+lon_0")

# The values CARLA 0.9.16 silently substitutes. Named here so they can be
# asserted against and grepped for; they must never be produced by the strict
# parser.
LEGACY_FALLBACK_LAT = 42.0
LEGACY_FALLBACK_LON = 2.0


class GeoreferenceError(ValueError):
    """Raised when a georeference is absent, incomplete or malformed.

    Fail closed. The caller must abort; substituting a default is not permitted.
    """


@dataclass(frozen=True)
class ParsedGeoreference:
    latitude: float
    longitude: float
    tokens: dict

    def as_carla_string(self) -> str:
        return " ".join("%s=%s" % (k, v) for k, v in sorted(self.tokens.items()))


def _split_tokens(text: str) -> dict:
    """Reproduce GeoReferenceParser.cpp's grammar exactly.

    It splits the whole string on spaces, then each element on '=', and ignores
    any element that does not yield exactly two parts. So '+proj=tmerc' is
    skipped (no '='), and a bare '+k' would also be skipped.
    """
    tokens: dict[str, str] = {}
    for element in text.split(" "):
        parts = element.split("=")
        if len(parts) != 2:
            continue
        tokens[parts[0]] = parts[1]
    return tokens


def _as_float(key: str, value: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise GeoreferenceError(
            "georeference parameter %s=%r is not a number" % (key, value)) from exc
    if out != out or out in (float("inf"), float("-inf")):
        raise GeoreferenceError(
            "georeference parameter %s=%r is not finite" % (key, value))
    return out


def parse_georeference_strict(geo_reference_string: str | None) -> ParsedGeoreference:
    """Parse a georeference or raise. Never returns a default.

    Validates:
      * the string is present and non-empty;
      * both ``+lat_0`` and ``+lon_0`` are present;
      * every present numeric parameter parses as a finite float;
      * both required values are inside valid geographic ranges.
    """
    if geo_reference_string is None:
        raise GeoreferenceError("georeference is absent")
    text = geo_reference_string.strip()
    if not text:
        raise GeoreferenceError("georeference is empty")

    tokens = _split_tokens(text)
    missing = [k for k in REQUIRED_KEYS if k not in tokens]
    if missing:
        raise GeoreferenceError(
            "georeference %r is incomplete: missing %s. CARLA needs both to place "
            "the map origin; refusing to substitute a default."
            % (text, ", ".join(missing)))

    numeric: dict[str, float] = {}
    for key, value in tokens.items():
        if key in ("+proj", "+datum", "+ellps", "+units", "+no_defs"):
            continue
        numeric[key] = _as_float(key, value)

    lat = numeric["+lat_0"]
    lon = numeric["+lon_0"]
    if not -90.0 <= lat <= 90.0:
        raise GeoreferenceError("+lat_0=%r is outside [-90, 90]" % lat)
    if not -180.0 <= lon <= 180.0:
        raise GeoreferenceError("+lon_0=%r is outside [-180, 180]" % lon)

    return ParsedGeoreference(latitude=lat, longitude=lon, tokens=tokens)


def parse_georeference_legacy(geo_reference_string: str | None) -> ParsedGeoreference:
    """The current CARLA 0.9.16 behaviour, reproduced for regression comparison.

    Kept so the removal of the silent default can be asserted: this function
    must no longer be called by any production path. It exists only to
    demonstrate the exact defect being fixed.
    """
    tokens = _split_tokens((geo_reference_string or "").strip())
    lat = lon = None
    if "+lat_0" in tokens:
        lat = _as_float("+lat_0", tokens["+lat_0"])
    if "+lon_0" in tokens:
        lon = _as_float("+lon_0", tokens["+lon_0"])
    if lat is None or lon is None:
        return ParsedGeoreference(
            latitude=LEGACY_FALLBACK_LAT, longitude=LEGACY_FALLBACK_LON,
            tokens=dict(tokens, _fallback="true"))
    return ParsedGeoreference(latitude=lat, longitude=lon, tokens=tokens)