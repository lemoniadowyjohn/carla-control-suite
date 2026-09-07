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



def _road_samples(road: ET.Element, spacing: float = 1.0) -> list[tuple[float, float]]:
    """Deterministically sample the supported reference-line primitives."""
    samples: list[tuple[float, float]] = []
    for geometry in sorted(road.findall("./planView/geometry"), key=lambda g: float(g.get("s", 0))):
        x0, y0 = float(geometry.get("x", 0)), float(geometry.get("y", 0))
        hdg, length = float(geometry.get("hdg", 0)), float(geometry.get("length", 0))
        primitive = next(iter(geometry), None)
        kind = "line" if primitive is None else primitive.tag.rsplit("}", 1)[-1]
        count = max(1, int(math.ceil(length / spacing)))
        for i in range(count + 1):
            s = length * i / count
            if kind == "arc":
                curvature = float(primitive.get("curvature", 0))
                if abs(curvature) < 1e-12:
                    lx, ly = s, 0.0
                else:
                    lx, ly = math.sin(curvature * s) / curvature, (1 - math.cos(curvature * s)) / curvature
            else:
                lx, ly = s, 0.0
            point = (x0 + math.cos(hdg) * lx - math.sin(hdg) * ly, y0 + math.sin(hdg) * lx + math.cos(hdg) * ly)
            if not samples or _distance(samples[-1], point) > 1e-9:
                samples.append(point)
    return samples


def _nearest_distance(points: Sequence[tuple[float, float]], query: tuple[float, float]) -> float:
    return min((_distance(point, query) for point in points), default=math.inf)


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
            distances = [_nearest_distance(_road_samples(road), (x, y)) for x, y in points]
        except (TypeError, ValueError, IndexError):
            continue
        mean_distance = sum(distances) / len(distances)
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
    return [match_osm_way_to_xodr(way, roads, **kwargs) for way in sorted(osm_ways, key=lambda w: str(w.get("id", w.get("way_id", ""))))]
