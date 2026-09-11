#!/usr/bin/env python3
"""Compare global and local OpenDRIVE elevation seam repair strategies.

This is an offline evidence tool.  It never mutates its input: it copies the
input map into the requested output directory, then produces one candidate for
the F5 graph-relaxation solver and one for the stage-08 local seam repair.

The summaries use the same ``contactPoint`` semantics as the continuity
checker.  That distinction matters: older F5 evidence measured predecessor and
successor targets as fixed end/start points, irrespective of ``contactPoint``.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import shutil
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from ultimate_pipeline.enrichment.elevation_link_offset_solver import (
    _parse_links,
    _read_profile,
    _resolve_link_sides,
    _z_at,
    apply_link_offset_correction_root,
)
from ultimate_pipeline.quality.check_elevation_continuity import (
    check_elevation_continuity,
)
from ultimate_pipeline.quality.map_hygiene import repair_true_zseams


def sha256(path: Path) -> str:
    """Return the streaming SHA-256 hash for a possibly large artifact."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _digest_strings(values: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _xml_or_none(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    normalized = copy.deepcopy(element)
    for node in normalized.iter():
        if node.text is not None and not node.text.strip():
            node.text = None
        if node.tail is not None and not node.tail.strip():
            node.tail = None
    return ET.tostring(normalized, encoding="unicode")


def structure_snapshot(root: ET.Element) -> Dict[str, Any]:
    """Digest fields F5 promises not to alter.

    Elevation ``a`` is intentionally excluded.  ``s`` and b/c/d are included,
    so segment-count and slope-preservation claims remain independently
    checkable without retaining a second full XML tree in the report.
    """
    roads = root.findall("road")
    structural_rows: List[str] = []
    elevation_rows: List[str] = []
    for road in roads:
        road_id = str(road.get("id") or "")
        structural_rows.append(
            json.dumps(
                {
                    "id": road_id,
                    "length": road.get("length"),
                    "junction": road.get("junction"),
                    "link": _xml_or_none(road.find("link")),
                    "plan_view": _xml_or_none(road.find("planView")),
                    "lanes": _xml_or_none(road.find("lanes")),
                },
                sort_keys=True,
            )
        )
        profile = road.find("elevationProfile")
        elevations = [] if profile is None else profile.findall("elevation")
        elevation_rows.append(
            json.dumps(
                {
                    "id": road_id,
                    "segment_count": len(elevations),
                    "s_bcd": [
                        (e.get("s"), e.get("b"), e.get("c"), e.get("d"))
                        for e in elevations
                    ],
                },
                sort_keys=True,
            )
        )

    return {
        "road_count": len(roads),
        "road_link_planview_lane_sha256": _digest_strings(structural_rows),
        "elevation_segment_s_bcd_sha256": _digest_strings(elevation_rows),
        "junction_sha256": _digest_strings(
            _xml_or_none(junction) or ""
            for junction in root.findall("junction")
        ),
    }


def canonical_seam_metrics(root: ET.Element, threshold_m: float) -> Dict[str, Any]:
    """Measure all resolvable road-to-road seam deltas with contact points."""
    roads = {
        str(road.get("id")): road
        for road in root.findall("road")
        if road.get("id") is not None
    }
    profiles = {
        road_id: profile
        for road_id, road in roads.items()
        if (profile := _read_profile(road)) is not None
    }
    ordinary: List[float] = []
    junction: List[float] = []
    unresolved_links = 0
    missing_profiles = 0

    for road_id, road in roads.items():
        own_profile = profiles.get(road_id)
        if own_profile is None:
            continue
        own_is_junction = (road.get("junction") or "-1").strip() != "-1"
        for link_kind, target_id, contact_point in _parse_links(road):
            target_road = roads.get(target_id)
            target_profile = profiles.get(target_id)
            if target_profile is None:
                if target_road is None:
                    unresolved_links += 1
                else:
                    missing_profiles += 1
                continue
            own_side, target_side = _resolve_link_sides(link_kind, contact_point)
            delta = abs(_z_at(own_profile, own_side) - _z_at(target_profile, target_side))
            if not math.isfinite(delta):
                delta = float("inf")
            target_is_junction = (
                (target_road.get("junction") or "-1").strip() != "-1"
            )
            (junction if own_is_junction or target_is_junction else ordinary).append(delta)

    def summarize(values: List[float]) -> Dict[str, Any]:
        values = sorted(values)
        if not values:
            return {
                "count": 0,
                "max_m": 0.0,
                "mean_m": 0.0,
                "median_m": 0.0,
                "p95_m": 0.0,
                "over_threshold": 0,
            }
        percentile_index = int((len(values) - 1) * 0.95)
        return {
            "count": len(values),
            "max_m": max(values),
            "mean_m": sum(values) / len(values),
            "median_m": values[(len(values) - 1) // 2],
            "p95_m": values[percentile_index],
            "over_threshold": sum(
                1 for value in values if not math.isfinite(value) or value > threshold_m
            ),
        }

    all_values = ordinary + junction
    return {
        "threshold_m": threshold_m,
        "all_road_to_road": summarize(all_values),
        "ordinary_road_to_road": summarize(ordinary),
        "junction_connector": summarize(junction),
        "unresolved_links": unresolved_links,
        "missing_elevation_profiles": missing_profiles,
    }


def _write_tree(root: ET.Element, path: Path) -> None:
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def validate_f5_preservation(input_path: Path, f5_path: Path) -> Dict[str, Any]:
    """Validate F5's non-elevation invariants without rerunning either repair."""
    source_snapshot = structure_snapshot(ET.parse(input_path).getroot())
    candidate_snapshot = structure_snapshot(ET.parse(f5_path).getroot())
    checks = {
        "road_count_preserved": (
            source_snapshot["road_count"] == candidate_snapshot["road_count"]
        ),
        "road_link_planview_lane_structure_preserved": (
            source_snapshot["road_link_planview_lane_sha256"]
            == candidate_snapshot["road_link_planview_lane_sha256"]
        ),
        "junction_structure_preserved": (
            source_snapshot["junction_sha256"] == candidate_snapshot["junction_sha256"]
        ),
        "elevation_segment_counts_and_s_bcd_preserved": (
            source_snapshot["elevation_segment_s_bcd_sha256"]
            == candidate_snapshot["elevation_segment_s_bcd_sha256"]
        ),
    }
    return {
        "input": {"path": str(input_path), "sha256": sha256(input_path)},
        "candidate": {"path": str(f5_path), "sha256": sha256(f5_path)},
        "source_snapshot": source_snapshot,
        "candidate_snapshot": candidate_snapshot,
        "checks": checks,
        "checks_pass": all(checks.values()),
    }


def compare(input_path: Path, output_dir: Path) -> Dict[str, Any]:
    """Run both repair strategies from identical immutable source bytes."""
    output_dir.mkdir(parents=True, exist_ok=True)
    source_copy = output_dir / "source_copy.xodr"
    f5_path = output_dir / "f5_graph_relaxation.xodr"
    local_path = output_dir / "live_local_repair.xodr"
    shutil.copy2(input_path, source_copy)

    input_sha = sha256(input_path)
    copy_sha = sha256(source_copy)
    source_root = ET.parse(source_copy).getroot()
    source_snapshot = structure_snapshot(source_root)

    f5_tree = ET.parse(source_copy)
    f5_root = f5_tree.getroot()
    start = time.perf_counter()
    f5_solver = apply_link_offset_correction_root(f5_root)
    f5_seconds = time.perf_counter() - start
    _write_tree(f5_root, f5_path)
    f5_root_after = ET.parse(f5_path).getroot()

    start = time.perf_counter()
    local_result = repair_true_zseams(str(source_copy), str(local_path), eps_z=0.5)
    local_seconds = time.perf_counter() - start
    local_root_after = ET.parse(local_path).getroot()
    local_snapshot = structure_snapshot(local_root_after)

    f5_checks = {
        "input_copy_unchanged": sha256(source_copy) == copy_sha,
        "solver_ok": bool(f5_solver.get("ok")),
        **validate_f5_preservation(source_copy, f5_path)["checks"],
    }

    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input": {
            "path": str(input_path),
            "sha256_before": input_sha,
            "sha256_after": sha256(input_path),
            "bytes": input_path.stat().st_size,
            "copy_sha256": copy_sha,
            "copy_matches_input": input_sha == copy_sha,
        },
        "source": {
            "structure": source_snapshot,
            "metrics": {
                "0.5": canonical_seam_metrics(source_root, 0.5),
                "5.0": canonical_seam_metrics(source_root, 5.0),
            },
            "canonical_quality_checker": {
                "eps_0_5": check_elevation_continuity(str(source_copy), eps_z=0.5),
                "eps_5_0": check_elevation_continuity(str(source_copy), eps_z=5.0),
            },
        },
        "f5_graph_relaxation": {
            "output_path": str(f5_path),
            "sha256": sha256(f5_path),
            "bytes": f5_path.stat().st_size,
            "wall_clock_seconds": f5_seconds,
            "solver": f5_solver,
            "metrics": {
                "0.5": canonical_seam_metrics(f5_root_after, 0.5),
                "5.0": canonical_seam_metrics(f5_root_after, 5.0),
            },
            "canonical_quality_checker": {
                "eps_0_5": check_elevation_continuity(str(f5_path), eps_z=0.5),
                "eps_5_0": check_elevation_continuity(str(f5_path), eps_z=5.0),
            },
            "checks": f5_checks,
            "checks_pass": all(f5_checks.values()),
        },
        "live_local_repair": {
            "output_path": str(local_path),
            "sha256": sha256(local_path),
            "bytes": local_path.stat().st_size,
            "wall_clock_seconds": local_seconds,
            "result": local_result,
            "metrics": {
                "0.5": canonical_seam_metrics(local_root_after, 0.5),
                "5.0": canonical_seam_metrics(local_root_after, 5.0),
            },
            "canonical_quality_checker": {
                "eps_0_5": check_elevation_continuity(str(local_path), eps_z=0.5),
                "eps_5_0": check_elevation_continuity(str(local_path), eps_z=5.0),
            },
            "structure": local_snapshot,
            "input_copy_unchanged": sha256(source_copy) == copy_sha,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_xodr", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--validate-f5-candidate",
        type=Path,
        help="Validate an existing F5 candidate without rerunning repairs.",
    )
    args = parser.parse_args()

    input_path = args.input_xodr.resolve()
    output_dir = args.output_dir.resolve()
    if args.validate_f5_candidate is not None:
        report = validate_f5_preservation(
            input_path, args.validate_f5_candidate.resolve()
        )
        report_path = output_dir / "F5_PRESERVATION_VALIDATION.json"
        exit_code = 0 if report["checks_pass"] else 2
    else:
        report = compare(input_path, output_dir)
        report_path = output_dir / "F5_VS_LIVE_MEASUREMENT.json"
        exit_code = 0 if report["f5_graph_relaxation"]["checks_pass"] else 2
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"report_path": str(report_path), "checks_pass": exit_code == 0}, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
