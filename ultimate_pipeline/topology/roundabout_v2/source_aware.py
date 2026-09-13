"""Fail-closed OSM spatial evidence for Roundabout Reconstruction V2.

The generic OSM/XODR correspondence engine deliberately returns one best road
per OSM way. That contract is unsuitable for a roundabout: one closed OSM way
commonly becomes several XODR roads and junctions. This module reuses its
projected coordinates, cached grid index, and nearest-sample evidence, then
aggregates only strong multi-road support into one V2 candidate.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import math
from pathlib import Path
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.osm_meta_index import (
    project_positioned_osm_metadata_ways,
)
from ultimate_pipeline.enrichment.osm_xodr_correspondence import (
    RoadSampleIndex,
    sample_distance_evidence,
)

from .core import Candidate


ROUNDABOUT_VALUES = frozenset({"roundabout", "circular"})
ROAD_SAMPLE_SPACING_M = 2.0
ROAD_INDEX_CELL_SIZE_M = 25.0
SEARCH_RADIUS_M = 10.0
ROAD_DISTANCE_THRESHOLD_M = 5.0
MAX_ROAD_MEAN_DISTANCE_M = 4.0
MIN_ROAD_COVERAGE = 0.70
SOURCE_DISTANCE_THRESHOLD_M = 8.0
MIN_SOURCE_COVERAGE = 0.75
MIN_SUPPORTED_ROADS = 2


def extract_osm_roundabout_ways(osm_path: str | Path) -> list[dict[str, Any]]:
    """Extract geometry-bearing explicit OSM roundabouts in stable ID order."""
    try:
        root = ET.parse(osm_path).getroot()
    except (FileNotFoundError, ET.ParseError, OSError):
        return []

    nodes: dict[str, tuple[float, float]] = {}
    for node in root.findall("node"):
        node_id = node.get("id")
        try:
            longitude = float(node.get("lon", ""))
            latitude = float(node.get("lat", ""))
        except (TypeError, ValueError):
            continue
        if node_id and math.isfinite(longitude) and math.isfinite(latitude):
            nodes[node_id] = (longitude, latitude)

    records: list[dict[str, Any]] = []
    for way in root.findall("way"):
        way_id = way.get("id")
        tags = {tag.get("k", ""): tag.get("v", "") for tag in way.findall("tag")}
        if not way_id or tags.get("junction") not in ROUNDABOUT_VALUES:
            continue
        geometry = [
            nodes[ref]
            for ref in (node.get("ref") for node in way.findall("nd"))
            if ref in nodes
        ]
        if len(geometry) < 2:
            continue
        records.append(
            {
                "id": str(way_id),
                "name": tags.get("name", ""),
                "highway": tags.get("highway", ""),
                "geometry": geometry,
                "metadata": {
                    key: value
                    for key, value in tags.items()
                    if key
                    in {
                        "junction",
                        "oneway",
                        "lanes",
                        "lanes:forward",
                        "lanes:backward",
                        "width",
                        "highway",
                    }
                },
            }
        )
    return sorted(records, key=lambda record: record["id"])


def _road_to_junction_ids(root: ET.Element) -> dict[str, tuple[str, ...]]:
    membership: dict[str, set[str]] = defaultdict(set)
    for road in root.findall("./road"):
        road_id = road.get("id")
        junction_id = road.get("junction")
        if road_id and junction_id and junction_id != "-1":
            membership[road_id].add(junction_id)
    for junction in root.findall("./junction"):
        junction_id = junction.get("id")
        if not junction_id:
            continue
        for connection in junction.findall("connection"):
            for road_id in (
                connection.get("incomingRoad"),
                connection.get("connectingRoad"),
            ):
                if road_id:
                    membership[road_id].add(junction_id)
    return {
        road_id: tuple(sorted(junction_ids, key=str))
        for road_id, junction_ids in membership.items()
    }


def _source_evidence(
    source_points: list[tuple[float, float]],
    road_ids: Iterable[str],
    index: RoadSampleIndex,
) -> dict[str, float]:
    points = [
        point
        for road_id in road_ids
        for point in index.samples.get(road_id, ())
    ]
    return sample_distance_evidence(
        source_points, points, threshold_m=SOURCE_DISTANCE_THRESHOLD_M
    )


def _confidence(source_evidence: Mapping[str, float], supported_roads: int) -> float:
    coverage = float(source_evidence["coverage_within_threshold"])
    mean_distance = float(source_evidence["mean_distance_m"])
    distance_score = max(0.0, 1.0 - mean_distance / SOURCE_DISTANCE_THRESHOLD_M)
    support_score = min(1.0, supported_roads / 3.0)
    return round(0.70 * coverage + 0.20 * distance_score + 0.10 * support_score, 6)


def detect_osm_spatial_candidates_from_projected_ways(
    root: ET.Element,
    projected_ways: Iterable[Mapping[str, Any]],
) -> tuple[list[Candidate], dict[str, Any]]:
    """Aggregate strong projected OSM roundabout evidence into V2 candidates."""
    roads = sorted(root.findall("./road"), key=lambda road: str(road.get("id", "")))
    index = RoadSampleIndex(
        roads,
        cell_size_m=ROAD_INDEX_CELL_SIZE_M,
        spacing_m=ROAD_SAMPLE_SPACING_M,
    )
    road_junctions = _road_to_junction_ids(root)
    candidates: list[Candidate] = []
    records: list[dict[str, Any]] = []

    for way in sorted(projected_ways, key=lambda item: str(item.get("id", ""))):
        way_id = str(way.get("id", ""))
        try:
            source_points = [
                (float(point[0]), float(point[1])) for point in way.get("geometry", ())
            ]
        except (TypeError, ValueError, IndexError):
            source_points = []
        if len(source_points) < 2:
            records.append(
                {
                    "osm_way_id": way_id,
                    "status": "EXCLUDED",
                    "reason": "missing_or_degenerate_projected_geometry",
                }
            )
            continue

        supported_road_ids: list[str] = []
        road_evidence: dict[str, dict[str, float]] = {}
        nearby = index.candidates_near(source_points, SEARCH_RADIUS_M)
        for road in nearby:
            road_id = str(road.get("id", ""))
            evidence = sample_distance_evidence(
                index.samples.get(road_id, ()),
                source_points,
                threshold_m=ROAD_DISTANCE_THRESHOLD_M,
            )
            if (
                evidence["coverage_within_threshold"] >= MIN_ROAD_COVERAGE
                and evidence["mean_distance_m"] <= MAX_ROAD_MEAN_DISTANCE_M
            ):
                supported_road_ids.append(road_id)
                road_evidence[road_id] = evidence
        supported_road_ids.sort()
        aggregate = _source_evidence(source_points, supported_road_ids, index)
        junction_ids = sorted(
            {
                junction_id
                for road_id in supported_road_ids
                for junction_id in road_junctions.get(road_id, ())
            },
            key=str,
        )

        reason: str | None = None
        if not supported_road_ids:
            reason = "no_spatial_road_support"
        elif len(supported_road_ids) < MIN_SUPPORTED_ROADS:
            reason = "insufficient_supported_roads"
        elif not junction_ids:
            reason = "supported_roads_not_in_junction"
        elif aggregate["coverage_within_threshold"] < MIN_SOURCE_COVERAGE:
            reason = "insufficient_source_coverage"

        record: dict[str, Any] = {
            "osm_way_id": way_id,
            "supported_road_ids": supported_road_ids,
            "junction_ids": junction_ids,
            "nearby_road_count": len(nearby),
            "aggregate_evidence": aggregate,
            "road_evidence": road_evidence,
        }
        if reason is not None:
            record.update({"status": "EXCLUDED", "reason": reason})
            records.append(record)
            continue

        candidate = Candidate(
            tuple(junction_ids),
            tuple(supported_road_ids),
            (way_id,),
            "OSM_SPATIAL",
            _confidence(aggregate, len(supported_road_ids)),
            "explicit OSM roundabout spatially supported by multi-road junction cluster",
        )
        candidates.append(candidate)
        record.update(
            {
                "status": "CANDIDATE",
                "detection_method": candidate.detection_method,
                "detection_confidence": candidate.detection_confidence,
                "reason": candidate.reason,
            }
        )
        records.append(record)

    records.sort(key=lambda record: str(record.get("osm_way_id", "")))
    excluded = Counter(
        record["reason"] for record in records if record["status"] == "EXCLUDED"
    )
    return candidates, {
        "source_way_count": len(records),
        "candidate_count": len(candidates),
        "excluded_count": len(records) - len(candidates),
        "excluded_reason_counts": dict(sorted(excluded.items())),
        "thresholds": {
            "road_sample_spacing_m": ROAD_SAMPLE_SPACING_M,
            "road_distance_threshold_m": ROAD_DISTANCE_THRESHOLD_M,
            "max_road_mean_distance_m": MAX_ROAD_MEAN_DISTANCE_M,
            "min_road_coverage": MIN_ROAD_COVERAGE,
            "source_distance_threshold_m": SOURCE_DISTANCE_THRESHOLD_M,
            "min_source_coverage": MIN_SOURCE_COVERAGE,
            "min_supported_roads": MIN_SUPPORTED_ROADS,
        },
        "records": records,
    }


def detect_osm_spatial_candidates(
    root: ET.Element,
    osm_path: str | Path,
) -> tuple[list[Candidate], dict[str, Any]]:
    """Extract, project, and match explicit OSM roundabouts against ``root``."""
    source_ways = extract_osm_roundabout_ways(osm_path)
    if not source_ways:
        return [], {
            "source_way_count": 0,
            "candidate_count": 0,
            "excluded_count": 0,
            "excluded_reason_counts": {"no_roundabout_source_geometry": 1},
            "records": [],
        }
    projected = project_positioned_osm_metadata_ways(source_ways, root)
    candidates, report = detect_osm_spatial_candidates_from_projected_ways(root, projected)
    report["source_way_count"] = len(source_ways)
    report["projected_way_count"] = len(projected)
    if len(projected) != len(source_ways):
        report["projection_excluded_count"] = len(source_ways) - len(projected)
    return candidates, report
