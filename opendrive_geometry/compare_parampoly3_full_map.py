"""Read-only full-map comparison against frozen pre-migration production."""
from __future__ import annotations

import hashlib
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from opendrive_geometry.errors import ParamPoly3Error
from opendrive_geometry.primitives import (
    evaluate_param_poly3,
    param_poly3_curvature_at,
)
from opendrive_geometry.parampoly3_legacy_baseline import (
    BASELINE_COMMIT,
    BASELINE_CURVATURE_SOURCE,
    BASELINE_POSE_SOURCE,
    legacy_curvatures,
    legacy_pose,
)

COEFFICIENT_NAMES = ("aU", "bU", "cU", "dU", "aV", "bV", "cV", "dV")
STATION_FRACTIONS = (0.0, 0.25, 0.5, 0.75, 1.0)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = fraction * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _angle_difference(left: float, right: float) -> float:
    return abs((left - right + math.pi) % (2.0 * math.pi) - math.pi)


def _parse_record(
    road: ET.Element,
    geometry: ET.Element,
    geometry_index: int,
    param_poly3: ET.Element,
) -> tuple[dict | None, str | None]:
    try:
        p_range = param_poly3.get("pRange")
        if p_range is None or p_range == "":
            return None, "missing_pRange"
        if p_range not in {"normalized", "arcLength"}:
            return None, "unsupported_pRange"
        record = {
            "road_id": road.get("id", ""),
            "geometry_index": geometry_index,
            "x0": float(geometry.attrib["x"]),
            "y0": float(geometry.attrib["y"]),
            "hdg0": float(geometry.attrib["hdg"]),
            "length": float(geometry.attrib["length"]),
            "pRange": p_range,
        }
        if not math.isfinite(record["length"]) or record["length"] <= 0.0:
            return None, "invalid_length"
        for name in COEFFICIENT_NAMES:
            value = float(param_poly3.attrib[name])
            if not math.isfinite(value):
                return None, "nonfinite_coefficient"
            record[name] = value
        return record, None
    except (KeyError, TypeError, ValueError):
        return None, "malformed_numeric_record"


def compare(paths: list[Path]) -> dict:
    position_differences: list[float] = []
    heading_differences: list[float] = []
    curvature_differences: list[float] = []
    malformed_by_reason: dict[str, int] = {}
    source_reports = []
    totals = {
        "records_discovered": 0,
        "normalized_records": 0,
        "arcLength_records": 0,
        "malformed_records": 0,
        "nonfinite_outputs": 0,
        "degenerate_records": 0,
    }

    for path in paths:
        source_counts = {"records_discovered": 0, "normalized": 0, "arcLength": 0}
        root = ET.parse(path).getroot()
        for road in root.findall(".//road"):
            plan = road.find("planView")
            if plan is None:
                continue
            for geometry_index, geometry in enumerate(plan.findall("geometry")):
                param_poly3 = geometry.find("paramPoly3")
                if param_poly3 is None:
                    continue
                totals["records_discovered"] += 1
                source_counts["records_discovered"] += 1
                record, malformed_reason = _parse_record(
                    road, geometry, geometry_index, param_poly3
                )
                if malformed_reason is not None:
                    totals["malformed_records"] += 1
                    malformed_by_reason[malformed_reason] = (
                        malformed_by_reason.get(malformed_reason, 0) + 1
                    )
                    continue
                assert record is not None
                totals[f"{record['pRange']}_records"] += 1
                source_counts[record["pRange"]] += 1
                production_curvatures = legacy_curvatures(
                    record, n_samples=len(STATION_FRACTIONS)
                )
                if len(production_curvatures) != len(STATION_FRACTIONS):
                    totals["degenerate_records"] += 1
                    continue
                record_degenerate = False
                for index, fraction in enumerate(STATION_FRACTIONS):
                    s = record["length"] * fraction
                    try:
                        production_pose = legacy_pose(record, s)
                        canonical_pose = evaluate_param_poly3(
                            record["x0"], record["y0"], record["hdg0"], record["length"],
                            *(record[name] for name in COEFFICIENT_NAMES),
                            record["pRange"], s,
                        )
                        canonical_curvature = param_poly3_curvature_at(
                            *(record[name] for name in COEFFICIENT_NAMES),
                            record["pRange"], record["length"], s,
                        )
                    except ParamPoly3Error:
                        record_degenerate = True
                        continue
                    outputs = (
                        canonical_pose.x,
                        canonical_pose.y,
                        canonical_pose.hdg,
                        canonical_curvature,
                        production_pose.x,
                        production_pose.y,
                        production_pose.hdg,
                        production_curvatures[index],
                    )
                    if not all(math.isfinite(value) for value in outputs):
                        totals["nonfinite_outputs"] += 1
                        continue
                    position_differences.append(
                        math.hypot(
                            canonical_pose.x - production_pose.x,
                            canonical_pose.y - production_pose.y,
                        )
                    )
                    heading_differences.append(
                        _angle_difference(canonical_pose.hdg, production_pose.hdg)
                    )
                    curvature_differences.append(
                        abs(abs(canonical_curvature) - production_curvatures[index])
                    )
                if record_degenerate:
                    totals["degenerate_records"] += 1
        source_reports.append(
            {"file": path.name, "sha256": _sha256(path), **source_counts}
        )

    return {
        "schema_version": 4,
        "production_baseline": {
            "commit": BASELINE_COMMIT,
            "pose_source": BASELINE_POSE_SOURCE,
            "curvature_source": BASELINE_CURVATURE_SOURCE,
            "adapter": "opendrive_geometry/parampoly3_legacy_baseline.py",
        },
        "comparison": {
            "position_heading": (
                "canonical vs frozen pre-migration continuity pose implementation"
            ),
            "curvature": (
                "abs(canonical signed curvature) vs "
                "frozen pre-migration curvature sampler"
            ),
        },
        "stations_per_record": list(STATION_FRACTIONS),
        "sources": source_reports,
        **totals,
        "malformed_by_reason": malformed_by_reason,
        "position_difference": {
            "max": max(position_differences, default=0.0),
            "p95": _percentile(position_differences, 0.95),
        },
        "heading_difference": {
            "max": max(heading_differences, default=0.0),
            "p95": _percentile(heading_differences, 0.95),
        },
        "curvature_difference": {
            "max": max(curvature_differences, default=0.0),
            "p95": _percentile(curvature_differences, 0.95),
        },
        "evaluations_compared": len(position_differences),
    }


def main() -> int:
    repository = Path(__file__).resolve().parent.parent
    paths = [repository / "auto_master.xodr", repository / "manual_grid0828.xodr"]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing comparison source(s): {missing}")
    report = compare(paths)
    output = repository / "reports" / "parampoly3_comparison.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
