"""Characterise, without mutating, structure-elevation plausibility evidence.

The probe reuses the classification, DEM sampler, and exact interior-sample
semantics of the production-quality gate. It distinguishes genuine map defects
from short-segment evidence limits before any remediation is proposed.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping
import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.elevation_importer import ElevationImporter
from ultimate_pipeline.enrichment.structure_classifier import classify_xodr_roads
from ultimate_pipeline.quality.check_structure_elevation_plausibility import (
    BRIDGE_LIKE_CLASSES,
    check_structure_elevation_plausibility,
    evaluate_road_elevation_samples,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _finite(value: Any) -> float | None:
    try:
        candidate = float(value)
    except (TypeError, ValueError):
        return None
    return candidate if math.isfinite(candidate) else None


def _shortfall(delta_m: float, road_class: str, thresholds: Mapping[str, Any]) -> float:
    if road_class in BRIDGE_LIKE_CLASSES:
        return float(thresholds["min_bridge_clearance_m"]) - delta_m
    return float(thresholds["min_tunnel_cover_m"]) + delta_m


def failure_characterization(
    record: Mapping[str, Any],
    observations: list[Mapping[str, Any]],
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    """Return explicit, reproducible failure-severity labels for one road."""
    deltas = [
        float(item["delta_m"])
        for item in observations
        if item.get("status") == "EVALUABLE" and item.get("delta_m") is not None
    ]
    road_class = str(record["class"])
    violation_shortfalls = [
        shortfall
        for shortfall in (_shortfall(delta, road_class, thresholds) for delta in deltas)
        if shortfall > 0
    ]
    maximum_shortfall = max(violation_shortfalls, default=0.0)
    min_delta = min(deltas) if deltas else None
    max_delta = max(deltas) if deltas else None
    near_miss = bool(violation_shortfalls) and maximum_shortfall <= 0.15
    terrain_crossing = bool(
        min_delta is not None and max_delta is not None and min_delta < 0 < max_delta
    )
    multi_meter_delta = any(abs(delta) >= 2.0 for delta in deltas)
    if near_miss:
        primary_bucket = "near_miss"
    elif terrain_crossing:
        primary_bucket = "mixed_sign"
    elif multi_meter_delta:
        primary_bucket = "multi_meter"
    else:
        primary_bucket = "material_other"
    return {
        "primary_bucket": primary_bucket,
        "maximum_violation_shortfall_m": maximum_shortfall,
        "near_miss_all_violations_within_0_15m": near_miss,
        "terrain_crossing": terrain_crossing,
        "multi_meter_absolute_delta": multi_meter_delta,
        "min_observed_delta_m": min_delta,
        "max_observed_delta_m": max_delta,
    }


def incomplete_characterization(
    record: Mapping[str, Any], minimum_interior_samples: int
) -> str:
    """Classify why the unchanged fail-closed gate had insufficient evidence."""
    sample_count = int(record.get("sample_count", 0))
    evaluable_count = int(record.get("evaluable_sample_count", 0))
    if sample_count < minimum_interior_samples:
        return "insufficient_interior_geometry_samples"
    if evaluable_count >= minimum_interior_samples:
        return "unexpected_complete_record"
    if int(record.get("missing_elevation_count", 0)) == sample_count:
        return "missing_elevation_profile"
    if int(record.get("missing_terrain_count", 0)) == sample_count:
        return "terrain_out_of_coverage_or_nodata"
    return "partial_evidence_unresolved"


def _road_shape(road: ET.Element | None) -> dict[str, Any]:
    if road is None:
        return {"road_missing": True}
    return {
        "road_length_m": _finite(road.get("length")),
        "planview": [
            {
                "s": _finite(geometry.get("s")),
                "length_m": _finite(geometry.get("length")),
                "primitive": next(iter(geometry), ET.Element("missing")).tag,
            }
            for geometry in road.findall("./planView/geometry")
        ],
        "elevation_profile": [
            {key: _finite(elevation.get(key)) for key in ("s", "a", "b", "c", "d")}
            for elevation in road.findall("./elevationProfile/elevation")
        ],
    }


def _structure_sources(classification: Mapping[str, Any], road_id: str) -> list[dict[str, Any]]:
    per_road = classification["per_road"].get(road_id, {})
    structures = {
        str(item["way_id"]): item
        for item in classification["structure_ways"]["structures"]
    }
    return [
        {
            "way_id": way_id,
            "class": structures[way_id]["class"],
            "layer": structures[way_id]["layer"],
            "tags": structures[way_id]["tags"],
        }
        for way_id in per_road.get("matched_structure_way_ids", [])
        if way_id in structures
    ]


def _distribution(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "p25": None, "median": None, "p75": None, "max": None}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "p25": ordered[math.floor((len(ordered) - 1) * 0.25)],
        "median": ordered[math.floor((len(ordered) - 1) * 0.50)],
        "p75": ordered[math.floor((len(ordered) - 1) * 0.75)],
        "max": ordered[-1],
    }


def probe_xodr(xodr_path: Path, *, osm_path: Path, dem_path: Path) -> dict[str, Any]:
    """Return a deterministic, read-only diagnosis of the current gate result."""
    xodr_path = xodr_path.resolve()
    osm_path = osm_path.resolve()
    dem_path = dem_path.resolve()
    before_sha256 = _sha256_file(xodr_path)
    root = ET.parse(xodr_path).getroot()
    roads = {str(road.get("id", "")): road for road in root.findall("road")}
    classification = classify_xodr_roads(str(xodr_path), osm_path=str(osm_path))
    sampler = ElevationImporter.make_raster_sampler(
        str(dem_path), xodr_path=str(xodr_path), osm_path=str(osm_path)
    )
    classes = {
        road_id: item["class"] for road_id, item in classification["per_road"].items()
    }
    gate = check_structure_elevation_plausibility(
        str(xodr_path), road_classes=classes, terrain_sampler=sampler
    )
    thresholds = gate["thresholds"]
    failures: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []
    for record in gate["records"]:
        road_id = str(record["road_id"])
        road = roads.get(road_id)
        observations = (
            evaluate_road_elevation_samples(
                road, sampler, sample_spacing_m=float(thresholds["sample_spacing_m"])
            )["observations"]
            if road is not None
            else []
        )
        common = {
            "road_id": road_id,
            "class": record["class"],
            "gate_record": dict(record),
            "road_shape": _road_shape(road),
            "classification": classification["per_road"].get(road_id, {}),
            "matched_osm_structures": _structure_sources(classification, road_id),
            "observations": observations,
        }
        if record["status"] == "FAIL":
            failures.append(
                {
                    **common,
                    "characterization": failure_characterization(
                        record, observations, thresholds
                    ),
                }
            )
        elif record["status"] == "INCOMPLETE":
            incomplete.append(
                {
                    **common,
                    "incomplete_cause": incomplete_characterization(
                        record, int(thresholds["minimum_interior_samples"])
                    ),
                }
            )
    failure_buckets = Counter(
        item["characterization"]["primary_bucket"] for item in failures
    )
    incomplete_causes = Counter(item["incomplete_cause"] for item in incomplete)
    failure_axes = {
        "terrain_crossing": sum(
            item["characterization"]["terrain_crossing"] for item in failures
        ),
        "multi_meter_absolute_delta": sum(
            item["characterization"]["multi_meter_absolute_delta"] for item in failures
        ),
        "maximum_shortfall_at_least_1m": sum(
            item["characterization"]["maximum_violation_shortfall_m"] >= 1.0
            for item in failures
        ),
        "bridge_or_elevated_entirely_at_or_below_terrain": sum(
            item["class"] in BRIDGE_LIKE_CLASSES
            and item["characterization"]["max_observed_delta_m"] is not None
            and item["characterization"]["max_observed_delta_m"] <= 0.0
            for item in failures
        ),
        "tunnel_entirely_at_or_above_terrain": sum(
            item["class"] == "tunnel"
            and item["characterization"]["min_observed_delta_m"] is not None
            and item["characterization"]["min_observed_delta_m"] >= 0.0
            for item in failures
        ),
    }
    incomplete_lengths = [
        float(item["road_shape"]["road_length_m"])
        for item in incomplete
        if item["road_shape"].get("road_length_m") is not None
    ]
    failure_by_class_and_bucket = Counter(
        f"{item['class']}|{item['characterization']['primary_bucket']}"
        for item in failures
    )
    after_sha256 = _sha256_file(xodr_path)
    return {
        "schema_version": 1,
        "tool": "ultimate_pipeline.tools.structure_elevation_remediation_probe",
        "input": {
            "xodr_path": str(xodr_path),
            "xodr_sha256": before_sha256,
            "osm_path": str(osm_path),
            "osm_sha256": _sha256_file(osm_path),
            "dem_path": str(dem_path),
            "dem_sha256": _sha256_file(dem_path),
        },
        "gate": gate,
        "characterization": {
            "failure_primary_bucket_counts": dict(sorted(failure_buckets.items())),
            "failure_class_and_primary_bucket_counts": dict(
                sorted(failure_by_class_and_bucket.items())
            ),
            "failure_axes_counts": failure_axes,
            "incomplete_cause_counts": dict(sorted(incomplete_causes.items())),
            "incomplete_sample_count_distribution": dict(
                sorted(
                    Counter(
                        int(item["gate_record"].get("sample_count", 0))
                        for item in incomplete
                    ).items()
                )
            ),
            "incomplete_road_length_m_distribution": _distribution(incomplete_lengths),
            "failures": failures,
            "incomplete": incomplete,
        },
        "source_xodr_unchanged": before_sha256 == after_sha256,
        "map_of_record_mutated": "NO",
        "live_carla": "NOT_RUN",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xodr", required=True, type=Path)
    parser.add_argument("--osm", required=True, type=Path)
    parser.add_argument("--dem", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = probe_xodr(args.xodr, osm_path=args.osm, dem_path=args.dem)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
