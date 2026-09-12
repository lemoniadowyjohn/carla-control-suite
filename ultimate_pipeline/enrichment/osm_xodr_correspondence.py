"""Deterministic spatial correspondence between OSM ways and XODR roads.

The matcher is deliberately independent of pipeline globals.  Callers provide
OSM way records with ``geometry`` (projected ``(x, y)`` pairs) and an XODR root.
Position-specific metadata must use ``EXACT`` or ``HIGH`` results; ambiguous
and unmatched results are explicit and never silently assigned.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence
import xml.etree.ElementTree as ET

from ultimate_pipeline.geometry.opendrive_geometry_kernel import sample as kernel_sample



def _road_samples(road: ET.Element, spacing: float = 1.0) -> list[tuple[float, float]]:
    """Sample every XODR primitive through the canonical geometry kernel."""
    samples: list[tuple[float, float]] = []
    for geometry in sorted(road.findall("./planView/geometry"), key=lambda g: float(g.get("s", 0))):
        try:
            poses = kernel_sample(geometry, spacing)
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        for pose in poses:
            point = (float(pose.x), float(pose.y))
            if not samples or _distance(samples[-1], point) > 1e-9:
                samples.append(point)
    return samples


def _nearest_distance(points: Sequence[tuple[float, float]], query: tuple[float, float]) -> float:
    return min((_distance(point, query) for point in points), default=math.inf)


def sample_distance_evidence(
    query_points: Sequence[tuple[float, float]],
    candidate_points: Sequence[tuple[float, float]],
    *,
    threshold_m: float,
) -> dict[str, float]:
    """Return deterministic nearest-sample evidence for one correspondence.

    Callers that need a stricter domain-specific acceptance contract can use
    the mean distance and within-threshold coverage without resampling the
    candidate road.  Empty inputs intentionally produce an infinite distance
    and zero coverage instead of being treated as a weak match.
    """
    if not query_points or not candidate_points:
        return {
            "mean_distance_m": math.inf,
            "max_distance_m": math.inf,
            "coverage_within_threshold": 0.0,
        }
    distances = [_nearest_distance(candidate_points, point) for point in query_points]
    return {
        "mean_distance_m": sum(distances) / len(distances),
        "max_distance_m": max(distances),
        "coverage_within_threshold": (
            sum(distance <= threshold_m for distance in distances) / len(distances)
        ),
    }


class RoadSampleIndex:
    """Deterministic grid index over cached XODR reference-line samples."""

    def __init__(self, roads: Iterable[ET.Element], *, cell_size_m: float = 25.0, spacing_m: float = 1.0):
        self.cell_size_m = float(cell_size_m)
        if not math.isfinite(self.cell_size_m) or self.cell_size_m <= 0:
            raise ValueError("cell_size_m must be positive and finite")
        self.samples: dict[str, list[tuple[float, float]]] = {}
        self.roads: dict[str, ET.Element] = {}
        self.cells: dict[tuple[int, int], set[str]] = {}
        for road in sorted(roads, key=lambda r: str(r.get("id", ""))):
            road_id = str(road.get("id", ""))
            if not road_id:
                continue
            points = _road_samples(road, spacing_m)
            self.roads[road_id] = road
            self.samples[road_id] = points
            for x, y in points:
                self.cells.setdefault(self._cell(x, y), set()).add(road_id)

    def _cell(self, x: float, y: float) -> tuple[int, int]:
        return math.floor(x / self.cell_size_m), math.floor(y / self.cell_size_m)

    def candidates_near(self, points: Sequence[tuple[float, float]], radius_m: float) -> list[ET.Element]:
        span = max(0, math.ceil(float(radius_m) / self.cell_size_m))
        ids: set[str] = set()
        for x, y in points:
            cx, cy = self._cell(x, y)
            for dx in range(-span, span + 1):
                for dy in range(-span, span + 1):
                    ids.update(self.cells.get((cx + dx, cy + dy), ()))
        return [self.roads[road_id] for road_id in sorted(ids)]


@dataclass(frozen=True)
class MatchResult:
    osm_way_id: str
    xodr_road_id: str | None
    confidence: float
    match_class: str
    evidence: Mapping[str, Any]
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "osm_way_id": self.osm_way_id,
            "xodr_road_id": self.xodr_road_id,
            "confidence": self.confidence,
            "class": self.match_class,
            "evidence": dict(self.evidence),
            **({"reason": self.reason} if self.reason else {}),
        }


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _heading(points: Sequence[tuple[float, float]]) -> float | None:
    if len(points) < 2:
        return None
    for a, b in zip(points, points[1:]):
        if _distance(a, b) > 1e-9:
            return math.atan2(b[1] - a[1], b[0] - a[0])
    return None


def _angle_error(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return abs((a - b + math.pi) % (2 * math.pi) - math.pi)


def _way_points(way: Mapping[str, Any]) -> list[tuple[float, float]]:
    return [(float(p[0]), float(p[1])) for p in way.get("geometry", ())]


def match_osm_way_to_xodr(
    osm_way: Mapping[str, Any],
    xodr_candidates: Iterable[ET.Element],
    *,
    max_distance_m: float = 5.0,
    ambiguity_margin_m: float = 0.25,
    sample_cache: Mapping[str, Sequence[tuple[float, float]]] | None = None,
) -> MatchResult:
    """Match one OSM way against candidate roads using spatial evidence."""
    way_id = str(osm_way.get("id", osm_way.get("way_id", "")))
    points = _way_points(osm_way)
    if len(points) < 2:
        return MatchResult(way_id, None, 0.0, "UNMATCHED", {}, "missing_or_degenerate_geometry")
    candidates = sorted(list(xodr_candidates), key=lambda r: str(r.get("id", "")))
    scored: list[tuple[float, float, ET.Element, dict[str, Any]]] = []
    source_heading = _heading(points)
    source_name = str(osm_way.get("name", "")).strip()
    source_class = str(osm_way.get("highway", "")).strip()
    for road in candidates:
        try:
            road_id = str(road.get("id", ""))
            road_points = sample_cache.get(road_id) if sample_cache is not None else _road_samples(road)
            distance_evidence = sample_distance_evidence(
                points, road_points or (), threshold_m=max_distance_m
            )
            mean_distance = distance_evidence["mean_distance_m"]
        except (TypeError, ValueError, IndexError):
            continue
        if mean_distance > max_distance_m:
            continue
        road_heading = None
        geom = road.find("./planView/geometry")
        if geom is not None:
            try:
                road_heading = float(geom.get("hdg", "nan"))
            except ValueError:
                pass
        name_match = bool(source_name) and source_name == str(road.get("name", "")).strip()
        class_match = bool(source_class) and source_class == str(road.get("type", "")).strip()
        heading_error = _angle_error(source_heading, road_heading)
        score = max(0.0, 1.0 - mean_distance / max_distance_m)
        score += 0.15 if name_match else 0.0
        score += 0.10 if class_match else 0.0
        score += 0.10 * max(0.0, 1.0 - (heading_error or math.pi) / math.pi)
        scored.append((score, mean_distance, road, {
            "mean_distance_m": mean_distance,
            "max_distance_m": distance_evidence["max_distance_m"],
            "coverage_within_threshold": distance_evidence["coverage_within_threshold"],
            "heading_error_deg": None if heading_error is None else math.degrees(heading_error),
            "name_match": name_match,
            "road_class_match": class_match,
        }))
    if not scored:
        return MatchResult(way_id, None, 0.0, "UNMATCHED", {}, "no_candidate_within_distance")
    scored.sort(key=lambda row: (-row[0], row[1], str(row[2].get("id", ""))))
    best = scored[0]
    if len(scored) > 1 and best[1] - scored[1][1] < ambiguity_margin_m and abs(best[0] - scored[1][0]) < 0.10:
        return MatchResult(way_id, None, 0.0, "AMBIGUOUS", best[3], "competing_spatial_candidates")
    confidence = min(1.0, best[0] / 1.35)
    match_class = "EXACT" if confidence >= 0.90 and best[3]["mean_distance_m"] <= 0.25 else "HIGH" if confidence >= 0.65 else "AMBIGUOUS"
    if match_class == "AMBIGUOUS":
        return MatchResult(way_id, None, confidence, match_class, best[3], "insufficient_confidence")
    return MatchResult(way_id, str(best[2].get("id")), confidence, match_class, best[3])


def build_correspondence(osm_ways: Iterable[Mapping[str, Any]], root: ET.Element, **kwargs: Any) -> list[MatchResult]:
    roads = sorted(root.findall("./road"), key=lambda r: str(r.get("id", "")))
    max_distance = float(kwargs.get("max_distance_m", 5.0))
    index = RoadSampleIndex(roads, cell_size_m=float(kwargs.pop("cell_size_m", 25.0)), spacing_m=float(kwargs.pop("sample_spacing_m", 1.0)))
    ways = sorted(osm_ways, key=lambda w: str(w.get("id", w.get("way_id", ""))))
    results: list[MatchResult] = []
    for way in ways:
        points = _way_points(way)
        candidates = index.candidates_near(points, max_distance) if points else []
        results.append(match_osm_way_to_xodr(way, candidates, sample_cache=index.samples, **kwargs))
    return results


def build_metadata_associations(
    osm_ways: Iterable[Mapping[str, Any]],
    root: ET.Element,
    **kwargs: Any,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Resolve HIGH/EXACT OSM-way matches into fail-closed road metadata.

    Multiple OSM ways may spatially match a generated XODR road.  Identical
    metadata is deterministicly coalesced; conflicting values are not selected
    by incidental iteration order and instead make the target road ineligible
    for position-sensitive enrichment.
    """
    ways = sorted(
        (dict(way) for way in osm_ways),
        key=lambda way: str(way.get("id", way.get("way_id", ""))),
    )
    ways_by_id = {
        str(way.get("id", way.get("way_id", ""))): way
        for way in ways
    }
    results = build_correspondence(ways, root, **kwargs)
    candidates: dict[str, list[tuple[MatchResult, Mapping[str, Any]]]] = {}
    class_counts = {"EXACT": 0, "HIGH": 0, "AMBIGUOUS": 0, "UNMATCHED": 0}
    for result in results:
        class_counts[result.match_class] = class_counts.get(result.match_class, 0) + 1
        if result.match_class not in {"EXACT", "HIGH"} or not result.xodr_road_id:
            continue
        way = ways_by_id.get(result.osm_way_id)
        if way is None:
            continue
        candidates.setdefault(result.xodr_road_id, []).append((result, way))

    associations: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    for road_id in sorted(candidates):
        matches = sorted(
            candidates[road_id],
            key=lambda row: (
                0 if row[0].match_class == "EXACT" else 1,
                -row[0].confidence,
                row[0].osm_way_id,
            ),
        )
        selected_result, selected_way = matches[0]
        selected_metadata = dict(selected_way.get("metadata", {}))
        conflicting_way_ids: list[str] = []
        for candidate_result, candidate_way in matches[1:]:
            candidate_metadata = dict(candidate_way.get("metadata", {}))
            shared_keys = set(selected_metadata).intersection(candidate_metadata)
            if any(
                selected_metadata[key] != candidate_metadata[key]
                for key in shared_keys
            ):
                conflicting_way_ids.append(candidate_result.osm_way_id)
        if conflicting_way_ids:
            conflicts.append(
                {
                    "xodr_road_id": road_id,
                    "selected_osm_way_id": selected_result.osm_way_id,
                    "conflicting_osm_way_ids": conflicting_way_ids,
                    "reason": "conflicting_high_confidence_osm_metadata",
                }
            )
            continue
        associations[road_id] = {
            "class": selected_result.match_class,
            "confidence": selected_result.confidence,
            "osm_way_id": selected_result.osm_way_id,
            "metadata": selected_metadata,
            "evidence": dict(selected_result.evidence),
        }

    report = {
        "source_way_count": len(ways),
        "match_class_counts": class_counts,
        "eligible_road_count": len(associations),
        "conflicting_road_count": len(conflicts),
        "conflicts": conflicts,
    }
    return associations, report
