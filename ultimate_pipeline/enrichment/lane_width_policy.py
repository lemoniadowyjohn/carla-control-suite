from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional


DEFAULT_DRIVING_WIDTH_M = 3.5
MIN_DRIVING_WIDTH_M = 2.75
MAX_DRIVING_WIDTH_M = 3.75
SIX_METER_PLACEHOLDER_M = 6.0

HIGHWAY_DEFAULT_WIDTH_M: Dict[str, float] = {
    "motorway": 3.75,
    "motorway_link": 3.75,
    "trunk": 3.75,
    "trunk_link": 3.5,
    "primary": 3.5,
    "primary_link": 3.5,
    "secondary": 3.5,
    "secondary_link": 3.25,
    "tertiary": 3.25,
    "tertiary_link": 3.25,
    "unclassified": 3.0,
    "residential": 3.25,
    "living_street": 3.0,
    "service": 3.0,
    "track": 3.0,
}

_FLOAT_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


@dataclass(frozen=True)
class LaneWidthDecision:
    width_m: float
    source: str
    highway: Optional[str] = None
    lane_count: Optional[int] = None
    explicit_width_m: Optional[float] = None


def _clean_key(key: str | None) -> str:
    return (key or "").strip().lower()


def _clean_value(value: Any) -> str:
    return str(value).strip()


def _is_finite_positive(value: float) -> bool:
    return math.isfinite(value) and value > 0.0


def _clamp_driving_width(value: float) -> float:
    return max(MIN_DRIVING_WIDTH_M, min(MAX_DRIVING_WIDTH_M, float(value)))


def parse_width_m(raw: Any) -> Optional[float]:
    """Parse common OSM width strings such as '7.2', '7.2 m' or '7,2 m'."""
    if raw is None:
        return None
    match = _FLOAT_RE.search(str(raw))
    if not match:
        return None
    try:
        value = float(match.group(0).replace(",", "."))
    except Exception:
        return None
    return value if _is_finite_positive(value) else None


def parse_lane_count(raw: Any) -> Optional[int]:
    if raw is None:
        return None
    match = re.search(r"\d+", str(raw))
    if not match:
        return None
    try:
        value = int(match.group(0))
    except Exception:
        return None
    return value if value > 0 else None


def _metadata_from_vectors(parent: ET.Element) -> Dict[str, str]:
    meta: Dict[str, str] = {}
    for user_data in parent.findall(".//userData"):
        for vector in list(user_data.findall("vector")) + list(user_data.findall("vectorObject")):
            key = _clean_key(vector.get("key"))
            value = _clean_value(vector.get("value"))
            if not key or not value:
                continue
            if key.startswith("osm:tag:"):
                meta.setdefault(key.removeprefix("osm:tag:"), value)
            elif key.startswith("osm:"):
                meta.setdefault(key.removeprefix("osm:"), value)
            else:
                meta.setdefault(key, value)
    return meta


def _metadata_from_attrs(road: ET.Element) -> Dict[str, str]:
    meta: Dict[str, str] = {}
    for key in (
        "highway",
        "osm:highway",
        "lanes",
        "osm:lanes",
        "lanes:forward",
        "lanes:backward",
        "width",
        "osm:width",
    ):
        value = road.get(key)
        if value:
            clean = _clean_key(key).removeprefix("osm:")
            meta.setdefault(clean, _clean_value(value))
    return meta


def road_lane_width_metadata(
    road: ET.Element,
    osm_meta: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Dict[str, str]:
    """Collect width-relevant OSM metadata from direct map input and XODR provenance.

    osm_meta (from build_osm_meta_index) is keyed by street NAME, not XODR road id --
    OSM way ids and Osm2Odr/netconvert-assigned XODR road ids are disjoint numbering
    schemes (verified 2026-08-26; see osm_meta_index.py's module docstring).
    """
    meta: Dict[str, str] = {}
    road_name = (road.get("name") or "").strip()
    if osm_meta and road_name and road_name in osm_meta:
        for key, value in osm_meta[road_name].items():
            if value is not None:
                meta[_clean_key(str(key))] = _clean_value(value)
    meta.update(_metadata_from_attrs(road))
    meta.update(_metadata_from_vectors(road))
    return meta


def _lane_count_from_meta(meta: Mapping[str, str]) -> Optional[int]:
    lanes = parse_lane_count(meta.get("lanes"))
    if lanes is not None:
        return lanes
    forward = parse_lane_count(meta.get("lanes:forward"))
    backward = parse_lane_count(meta.get("lanes:backward"))
    if forward is not None or backward is not None:
        return int(forward or 0) + int(backward or 0) or None
    return None


def target_driving_width_m(
    road: ET.Element,
    *,
    osm_meta: Optional[Mapping[str, Mapping[str, Any]]] = None,
    fallback_width_m: float = DEFAULT_DRIVING_WIDTH_M,
) -> LaneWidthDecision:
    meta = road_lane_width_metadata(road, osm_meta)
    highway = _clean_key(meta.get("highway"))
    lane_count = _lane_count_from_meta(meta)
    explicit_width = parse_width_m(meta.get("width") or meta.get("est_width"))

    if explicit_width is not None:
        if lane_count and lane_count > 0:
            per_lane = explicit_width / float(lane_count)
            if 2.4 <= per_lane <= 4.5:
                return LaneWidthDecision(
                    width_m=round(_clamp_driving_width(per_lane), 3),
                    source="osm_width_per_lane",
                    highway=highway or None,
                    lane_count=lane_count,
                    explicit_width_m=explicit_width,
                )
        if 2.4 <= explicit_width <= 4.5:
            return LaneWidthDecision(
                width_m=round(_clamp_driving_width(explicit_width), 3),
                source="osm_width",
                highway=highway or None,
                lane_count=lane_count,
                explicit_width_m=explicit_width,
            )

    if highway in HIGHWAY_DEFAULT_WIDTH_M:
        return LaneWidthDecision(
            width_m=round(_clamp_driving_width(HIGHWAY_DEFAULT_WIDTH_M[highway]), 3),
            source="osm_highway",
            highway=highway,
            lane_count=lane_count,
            explicit_width_m=explicit_width,
        )

    return LaneWidthDecision(
        width_m=round(_clamp_driving_width(float(fallback_width_m)), 3),
        source="fallback",
        highway=highway or None,
        lane_count=lane_count,
        explicit_width_m=explicit_width,
    )


def _first_width(lane: ET.Element) -> Optional[ET.Element]:
    return lane.find("width")


def _safe_float(raw: Any, default: float = 0.0) -> float:
    try:
        value = float(str(raw).strip())
    except Exception:
        return default
    return value if math.isfinite(value) else default


def _ensure_width(lane: ET.Element) -> ET.Element:
    width = _first_width(lane)
    if width is not None:
        return width
    return ET.SubElement(
        lane,
        "width",
        sOffset="0.0",
        a=f"{DEFAULT_DRIVING_WIDTH_M:.3f}",
        b="0.0",
        c="0.0",
        d="0.0",
    )


def apply_lane_width_policy(
    root: ET.Element,
    *,
    osm_meta: Optional[Mapping[str, Mapping[str, Any]]] = None,
    fallback_width_m: float = DEFAULT_DRIVING_WIDTH_M,
    max_examples: int = 25,
) -> Dict[str, Any]:
    """Replace placeholder driving-lane widths with OSM-derived or documented fallback widths."""
    source_counts: Dict[str, int] = {}
    examples: list[Dict[str, Any]] = []
    roads_checked = 0
    lanes_checked = 0
    updated = 0
    missing_added = 0
    six_meter_found = 0

    for road in root.findall("road"):
        roads_checked += 1
        decision = target_driving_width_m(
            road,
            osm_meta=osm_meta,
            fallback_width_m=fallback_width_m,
        )
        source_counts[decision.source] = source_counts.get(decision.source, 0) + 1

        for lane in road.findall(".//lane"):
            if (lane.get("type") or "").strip().lower() != "driving":
                continue
            lanes_checked += 1
            width = _first_width(lane)
            if width is None:
                width = _ensure_width(lane)
                missing_added += 1
            old = _safe_float(width.get("a"), fallback_width_m)
            if abs(old - SIX_METER_PLACEHOLDER_M) <= 1e-6:
                six_meter_found += 1
            if abs(old - decision.width_m) <= 1e-6:
                continue

            width.set("a", f"{decision.width_m:.3f}")
            width.set("b", "0.0")
            width.set("c", "0.0")
            width.set("d", "0.0")
            width.set("sOffset", width.get("sOffset") or "0.0")
            updated += 1

            if len(examples) < max_examples:
                examples.append(
                    {
                        "road_id": road.get("id", ""),
                        "lane_id": lane.get("id", ""),
                        "old_width_m": round(old, 3),
                        "new_width_m": decision.width_m,
                        "source": decision.source,
                        "highway": decision.highway,
                        "lane_count": decision.lane_count,
                        "explicit_width_m": decision.explicit_width_m,
                    }
                )

    return {
        "ok": True,
        "policy": {
            "min_driving_width_m": MIN_DRIVING_WIDTH_M,
            "max_driving_width_m": MAX_DRIVING_WIDTH_M,
            "fallback_width_m": float(fallback_width_m),
            "six_meter_placeholder_m": SIX_METER_PLACEHOLDER_M,
        },
        "totals": {
            "roads_checked": roads_checked,
            "driving_lanes_checked": lanes_checked,
            "driving_widths_updated": updated,
            "missing_widths_added": missing_added,
            "six_meter_placeholders_found": six_meter_found,
            "source_counts": source_counts,
        },
        "examples": examples,
    }


__all__ = [
    "DEFAULT_DRIVING_WIDTH_M",
    "HIGHWAY_DEFAULT_WIDTH_M",
    "LaneWidthDecision",
    "apply_lane_width_policy",
    "parse_lane_count",
    "parse_width_m",
    "road_lane_width_metadata",
    "target_driving_width_m",
]
