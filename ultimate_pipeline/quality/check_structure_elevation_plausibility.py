"""Read-only terrain plausibility checks for classified grade-separated roads.

An OSM ``bridge`` or ``tunnel`` tag identifies a structure, not its deck or
clearance height.  This module therefore validates the final XODR elevation
against a supplied terrain sampler without fabricating a replacement profile.
The report is deliberately fail-closed: missing classification, geometry,
elevation, or terrain evidence is ``INCOMPLETE``, never a pass.
"""
from __future__ import annotations

from collections import Counter
import math
from pathlib import Path
from typing import Any, Callable, Mapping
import xml.etree.ElementTree as ET

from ultimate_pipeline.geometry.opendrive_geometry_kernel import sample as sample_geometry


BRIDGE_LIKE_CLASSES = frozenset({"bridge", "elevated"})
TUNNEL_LIKE_CLASSES = frozenset({"tunnel"})
TERRAIN_AMBIGUOUS_CLASSES = frozenset({"underpass", "covered"})


def _finite(value: Any, default: float | None = None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _root(xodr_or_root: str | Path | ET.Element) -> ET.Element:
    if isinstance(xodr_or_root, ET.Element):
        return xodr_or_root
    return ET.parse(xodr_or_root).getroot()


def _terrain_value(sampler: Callable[[float, float], Any], x: float, y: float) -> float | None:
    try:
        sampled = sampler(x, y)
    except Exception:
        return None
    if isinstance(sampled, tuple):
        if len(sampled) < 2 or not bool(sampled[1]):
            return None
        sampled = sampled[0]
    return _finite(sampled)


def elevation_at_s(road: ET.Element, s: float) -> float | None:
    """Evaluate the active OpenDRIVE elevation polynomial at global road ``s``."""
    records: list[tuple[float, ET.Element]] = []
    for elevation in road.findall("./elevationProfile/elevation"):
        start = _finite(elevation.get("s"))
        if start is not None:
            records.append((start, elevation))
    if not records:
        return None
    records.sort(key=lambda item: item[0])
    active = next((item for item in reversed(records) if item[0] <= s + 1e-9), None)
    if active is None:
        return None
    start, elevation = active
    coefficients = [_finite(elevation.get(name)) for name in ("a", "b", "c", "d")]
    if any(value is None for value in coefficients):
        return None
    a, b, c, d = coefficients
    ds = s - start
    return a + b * ds + c * ds * ds + d * ds * ds * ds


def _interior_samples(road: ET.Element, spacing_m: float) -> list[tuple[float, float, float]]:
    samples: list[tuple[float, float, float]] = []
    for geometry in road.findall("./planView/geometry"):
        geometry_s = _finite(geometry.get("s"))
        if geometry_s is None:
            raise ValueError("geometry without a finite s")
        for pose_index, pose in enumerate(sample_geometry(geometry, spacing_m)):
            if samples and pose_index == 0:
                continue
            local_length = _finite(geometry.get("length"))
            if local_length is None:
                raise ValueError("geometry without a finite length")
            sample_count = max(1, math.ceil(local_length / spacing_m))
            samples.append((geometry_s + local_length * pose_index / sample_count, pose.x, pose.y))
    road_length = _finite(road.get("length"))
    if road_length is None or road_length <= 0:
        raise ValueError("road without a positive finite length")
    endpoint_margin = min(spacing_m * 0.5, road_length * 0.1)
    return [sample for sample in samples if endpoint_margin < sample[0] < road_length - endpoint_margin]


def check_structure_elevation_plausibility(
    xodr_or_root: str | Path | ET.Element,
    *,
    road_classes: Mapping[str, str] | None,
    terrain_sampler: Callable[[float, float], Any] | None,
    sample_spacing_m: float = 5.0,
    min_bridge_clearance_m: float = 0.5,
    min_tunnel_cover_m: float = 0.5,
    max_violation_ratio: float = 0.2,
    minimum_interior_samples: int = 2,
) -> dict[str, Any]:
    """Report whether classified bridges/tunnels remain plausible against terrain.

    Bridge-like roads require ``elevation - terrain >= min_bridge_clearance_m``
    for the allowed fraction of interior samples; tunnels require the inverse
    inequality.  ``underpass`` and ``covered`` deliberately remain reported as
    terrain-ambiguous because their OSM tags do not prove an above/below-ground
    road profile.
    """
    thresholds = {
        "sample_spacing_m": float(sample_spacing_m),
        "min_bridge_clearance_m": float(min_bridge_clearance_m),
        "min_tunnel_cover_m": float(min_tunnel_cover_m),
        "max_violation_ratio": float(max_violation_ratio),
        "minimum_interior_samples": int(minimum_interior_samples),
    }
    if (
        not math.isfinite(sample_spacing_m)
        or sample_spacing_m <= 0
        or min_bridge_clearance_m < 0
        or min_tunnel_cover_m < 0
        or not 0 <= max_violation_ratio <= 1
        or minimum_interior_samples < 1
    ):
        return {"status": "INCOMPLETE", "ok": False, "reason": "invalid_thresholds", "thresholds": thresholds}
    if not road_classes:
        return {"status": "INCOMPLETE", "ok": False, "reason": "structure_classification_unavailable", "thresholds": thresholds}
    if terrain_sampler is None:
        return {"status": "INCOMPLETE", "ok": False, "reason": "terrain_sampler_unavailable", "thresholds": thresholds}

    root = _root(xodr_or_root)
    roads = {str(road.get("id", "")): road for road in root.findall("road")}
    records: list[dict[str, Any]] = []
    skipped = Counter()
    for road_id, road_class in sorted(road_classes.items()):
        if road_class in TERRAIN_AMBIGUOUS_CLASSES:
            skipped[road_class] += 1
            continue
        if road_class not in BRIDGE_LIKE_CLASSES | TUNNEL_LIKE_CLASSES:
            continue
        road = roads.get(str(road_id))
        if road is None:
            records.append({"road_id": str(road_id), "class": road_class, "status": "INCOMPLETE", "reason": "road_missing"})
            continue
        try:
            samples = _interior_samples(road, sample_spacing_m)
        except (TypeError, ValueError, OverflowError) as exc:
            records.append({"road_id": str(road_id), "class": road_class, "status": "INCOMPLETE", "reason": f"geometry_sampling_failed:{exc}"})
            continue
        deltas: list[float] = []
        missing_elevation = 0
        missing_terrain = 0
        for s, x, y in samples:
            elevation = elevation_at_s(road, s)
            terrain = _terrain_value(terrain_sampler, x, y)
            if elevation is None:
                missing_elevation += 1
            elif terrain is None:
                missing_terrain += 1
            else:
                deltas.append(elevation - terrain)
        if len(deltas) < minimum_interior_samples:
            records.append({
                "road_id": str(road_id), "class": road_class, "status": "INCOMPLETE",
                "reason": "insufficient_evaluable_interior_samples", "sample_count": len(samples),
                "evaluable_sample_count": len(deltas), "missing_elevation_count": missing_elevation,
                "missing_terrain_count": missing_terrain,
            })
            continue
        if road_class in BRIDGE_LIKE_CLASSES:
            violations = [delta for delta in deltas if delta < min_bridge_clearance_m]
            expectation = "above_terrain"
        else:
            violations = [delta for delta in deltas if -delta < min_tunnel_cover_m]
            expectation = "below_terrain"
        violation_ratio = len(violations) / len(deltas)
        records.append({
            "road_id": str(road_id), "class": road_class,
            "status": "FAIL" if violation_ratio > max_violation_ratio else "PASS",
            "expectation": expectation, "sample_count": len(samples),
            "evaluable_sample_count": len(deltas), "missing_elevation_count": missing_elevation,
            "missing_terrain_count": missing_terrain, "min_delta_m": min(deltas),
            "max_delta_m": max(deltas), "mean_delta_m": sum(deltas) / len(deltas),
            "violation_count": len(violations), "violation_ratio": violation_ratio,
        })

    status_counts = Counter(record["status"] for record in records)
    if status_counts["INCOMPLETE"]:
        status, ok = "INCOMPLETE", False
    elif status_counts["FAIL"]:
        status, ok = "FAIL", False
    else:
        status, ok = "PASS", True
    return {
        "status": status,
        "ok": ok,
        "thresholds": thresholds,
        "checked_road_count": len(records),
        "status_counts": dict(sorted(status_counts.items())),
        "skipped_terrain_ambiguous_class_counts": dict(sorted(skipped.items())),
        "records": records,
    }
