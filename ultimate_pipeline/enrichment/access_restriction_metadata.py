"""Attach provenance-only OSM access metadata to spatially matched XODR roads.

This module intentionally does not change lane generation, lane counts, road
links, or routing.  It records a governed association for downstream consumers
that may later enforce an approved routing policy.

The association contract is the one used by the 2026-09-08 access audit:
native Osm2Odr transverse-Mercator coordinates, inverse header-offset handling,
exact road-name agreement, direction-independent geometry distance, a mean
distance of at most 2 m, and at least 90% XODR-sample coverage within 2 m.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.coordinate_control import (
    project_wgs84_to_xodr_native,
)
from ultimate_pipeline.enrichment.osm_xodr_correspondence import RoadSampleIndex


ACCESS_TAG_KEYS = ("access", "motor_vehicle", "vehicle", "psv", "bicycle")
MATCH_SAMPLE_SPACING_M = 3.0
MATCH_MAX_MEAN_DISTANCE_M = 2.0
MATCH_MIN_COVERAGE = 0.90
USERDATA_KEY = "osm_access_restriction_v1"
MATCH_METHOD = "exact_name_and_projected_geometry_direction_independent"


@dataclass(frozen=True)
class AccessWay:
    osm_way_id: str
    name: str
    highway: str
    geometry: tuple[tuple[float, float], ...]
    tags: Mapping[str, str]


@dataclass(frozen=True)
class AccessMatch:
    osm_way_id: str
    xodr_road_id: str
    tags: Mapping[str, str]
    confidence: float
    match_class: str
    mean_distance_m: float
    coverage_within_2m: float

    def to_userdata_value(self) -> str:
        return json.dumps(
            {
                "confidence": round(self.confidence, 6),
                "coverage_within_2m": round(self.coverage_within_2m, 6),
                "match_class": self.match_class,
                "match_method": MATCH_METHOD,
                "mean_distance_m": round(self.mean_distance_m, 6),
                "osm_way_id": self.osm_way_id,
                "tags": dict(sorted(self.tags.items())),
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )


def _number(value: str | None) -> float:
    try:
        parsed = float(value or "0")
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) else 0.0


def _header_offset(root: ET.Element) -> tuple[float, float, float]:
    offset = root.find("header/offset")
    if offset is None:
        return 0.0, 0.0, 0.0
    return _number(offset.get("x")), _number(offset.get("y")), _number(offset.get("hdg"))


def _native_to_planview(
    x_native: float, y_native: float, offset: tuple[float, float, float]
) -> tuple[float, float]:
    """Inverse the OpenDRIVE header offset for planView matching."""
    offset_x, offset_y, offset_hdg = offset
    dx, dy = x_native - offset_x, y_native - offset_y
    return (
        dx * math.cos(offset_hdg) + dy * math.sin(offset_hdg),
        -dx * math.sin(offset_hdg) + dy * math.cos(offset_hdg),
    )


def extract_access_ways(osm_path: str | Path, root: ET.Element) -> list[AccessWay]:
    """Extract and project OSM ways with access-related tags deterministically."""
    source = Path(osm_path)
    if not source.is_file():
        return []
    try:
        osm_root = ET.parse(source).getroot()
    except ET.ParseError:
        return []

    nodes: dict[str, tuple[float, float]] = {}
    for node in osm_root.findall("node"):
        node_id = node.get("id")
        if not node_id:
            continue
        try:
            nodes[node_id] = (float(node.get("lon", "")), float(node.get("lat", "")))
        except (TypeError, ValueError):
            continue

    offset = _header_offset(root)
    ways: list[AccessWay] = []
    for way in osm_root.findall("way"):
        raw_tags = {tag.get("k", ""): tag.get("v", "") for tag in way.findall("tag")}
        tags = {key: raw_tags[key] for key in ACCESS_TAG_KEYS if raw_tags.get(key)}
        name = raw_tags.get("name", "").strip()
        if not tags or not name:
            continue
        lonlat = [nodes[ref.get("ref", "")] for ref in way.findall("nd") if ref.get("ref", "") in nodes]
        if len(lonlat) < 2:
            continue
        native = project_wgs84_to_xodr_native(lonlat)
        if len(native) != len(lonlat):
            continue
        geometry = tuple(_native_to_planview(x, y, offset) for x, y in native)
        ways.append(
            AccessWay(
                osm_way_id=str(way.get("id", "")),
                name=name,
                highway=raw_tags.get("highway", ""),
                geometry=geometry,
                tags=tags,
            )
        )
    return sorted(ways, key=lambda way: way.osm_way_id)


def _point_to_segment_distance(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-18:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    projection = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq
    projection = min(1.0, max(0.0, projection))
    return math.hypot(point[0] - (start[0] + projection * dx), point[1] - (start[1] + projection * dy))


def _point_to_polyline_distance(point: tuple[float, float], polyline: Sequence[tuple[float, float]]) -> float:
    if len(polyline) < 2:
        return math.inf
    return min(
        _point_to_segment_distance(point, start, end)
        for start, end in zip(polyline, polyline[1:])
    )


def match_access_ways(
    root: ET.Element,
    ways: Iterable[AccessWay],
    *,
    spacing_m: float = MATCH_SAMPLE_SPACING_M,
    max_mean_distance_m: float = MATCH_MAX_MEAN_DISTANCE_M,
    min_coverage: float = MATCH_MIN_COVERAGE,
) -> tuple[list[AccessMatch], dict[str, int]]:
    """Match every eligible OSM way to every XODR segment meeting the audit contract."""
    index = RoadSampleIndex(root.findall("road"), cell_size_m=25.0, spacing_m=spacing_m)
    matches: list[AccessMatch] = []
    outcomes: Counter[str] = Counter()

    for way in sorted(ways, key=lambda item: item.osm_way_id):
        candidates = index.candidates_near(way.geometry, max_mean_distance_m)
        accepted = 0
        for road in candidates:
            road_id = str(road.get("id", ""))
            if not road_id or road.get("name", "").strip() != way.name:
                continue
            samples = index.samples.get(road_id, ())
            distances = [_point_to_polyline_distance(sample, way.geometry) for sample in samples]
            if not distances:
                continue
            mean_distance = sum(distances) / len(distances)
            coverage = sum(distance <= max_mean_distance_m for distance in distances) / len(distances)
            if mean_distance > max_mean_distance_m or coverage < min_coverage:
                outcomes["name_match_geometry_rejected"] += 1
                continue
            match_class = "EXACT" if mean_distance <= 0.25 and coverage == 1.0 else "HIGH"
            confidence = min(1.0, 0.5 * coverage + 0.5 * max(0.0, 1.0 - mean_distance / max_mean_distance_m))
            matches.append(
                AccessMatch(
                    osm_way_id=way.osm_way_id,
                    xodr_road_id=road_id,
                    tags=way.tags,
                    confidence=confidence,
                    match_class=match_class,
                    mean_distance_m=mean_distance,
                    coverage_within_2m=coverage,
                )
            )
            accepted += 1
        outcomes["matched_way" if accepted else "unmatched_way"] += 1

    matches.sort(key=lambda item: (item.xodr_road_id, item.osm_way_id, tuple(sorted(item.tags.items()))))
    return matches, dict(sorted(outcomes.items()))


def attach_access_metadata(root: ET.Element, matches: Iterable[AccessMatch]) -> dict[str, Any]:
    """Write only versioned access-provenance vectors; never alter lane behavior."""
    by_road: dict[str, list[AccessMatch]] = {}
    for match in matches:
        by_road.setdefault(match.xodr_road_id, []).append(match)
    road_map = {str(road.get("id", "")): road for road in root.findall("road")}
    attached_roads = 0
    tag_counts: Counter[str] = Counter()
    written_records = 0
    for road_id in sorted(by_road):
        road = road_map.get(road_id)
        if road is None:
            continue
        user_data = road.find("userData")
        if user_data is None:
            user_data = ET.SubElement(road, "userData")
        for vector in list(user_data.findall("vector")):
            if vector.get("key") == USERDATA_KEY:
                user_data.remove(vector)
        for match in sorted(by_road[road_id], key=lambda item: (item.osm_way_id, tuple(sorted(item.tags.items())))):
            ET.SubElement(user_data, "vector", key=USERDATA_KEY, value=match.to_userdata_value())
            written_records += 1
            for key in match.tags:
                tag_counts[key] += 1
        attached_roads += 1
    return {
        "schema_version": 1,
        "metadata_key": USERDATA_KEY,
        "match_method": MATCH_METHOD,
        "roads_with_access_metadata": attached_roads,
        "metadata_records_written": written_records,
        "tag_type_counts": dict(sorted(tag_counts.items())),
        "routing_or_lane_behavior_changed": False,
    }


def apply_access_metadata_from_osm(root: ET.Element, osm_path: str | Path) -> dict[str, Any]:
    """Extract, match, and attach metadata, returning evidence for the pipeline/report."""
    ways = extract_access_ways(osm_path, root)
    matches, outcomes = match_access_ways(root, ways)
    report = attach_access_metadata(root, matches)
    report.update(
        {
            "osm_access_ways_considered": len(ways),
            "accepted_matches": len(matches),
            "matching_outcomes": outcomes,
            "thresholds": {
                "sample_spacing_m": MATCH_SAMPLE_SPACING_M,
                "max_mean_distance_m": MATCH_MAX_MEAN_DISTANCE_M,
                "minimum_coverage_within_2m": MATCH_MIN_COVERAGE,
            },
        }
    )
    return report
