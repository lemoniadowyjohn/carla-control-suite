#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from tools.verify_candidate_digest import sha256_file
from ultimate_pipeline.tools.crash_safe_length_repair import (
    length_invariant_summary,
    structural_counts,
)

TOL = 1e-6


def _parse_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _same_float(left: Any, right: Any, *, tol: float = TOL) -> bool:
    lval = _parse_float(left)
    rval = _parse_float(right)
    if lval is None or rval is None:
        return False
    return abs(lval - rval) <= tol


def _geometry_identity_matches(target: ET.Element, reference: ET.Element, *, tol: float = TOL) -> bool:
    return all(_same_float(target.get(attr), reference.get(attr), tol=tol) for attr in ("s", "x", "y", "hdg"))


def nonpositive_geometry_details(root: ET.Element) -> list[Dict[str, Any]]:
    details = []
    for road_index, road in enumerate(root.findall("road")):
        for geom_index, geom in enumerate(road.findall("./planView/geometry")):
            glen = _parse_float(geom.get("length"))
            if glen is None or glen <= 0.0:
                details.append(
                    {
                        "road_index": road_index,
                        "road_id": str(road.get("id") or ""),
                        "junction": str(road.get("junction") or ""),
                        "road_length": str(road.get("length") or ""),
                        "geometry_index": geom_index,
                        "geometry_length": str(geom.get("length") or ""),
                        "geometry": dict(geom.attrib),
                    }
                )
    return details


def apply_reference_zero_length_connector_repair(
    target_root: ET.Element,
    reference_root: ET.Element,
    *,
    tol: float = TOL,
) -> Dict[str, Any]:
    reference_roads = {str(road.get("id") or ""): road for road in reference_root.findall("road")}
    changes = []
    skipped = []

    for road in target_root.findall("road"):
        road_id = str(road.get("id") or "")
        ref_road = reference_roads.get(road_id)
        target_geoms = road.findall("./planView/geometry")
        ref_geoms = ref_road.findall("./planView/geometry") if ref_road is not None else []

        for geom_index, geom in enumerate(target_geoms):
            target_length = _parse_float(geom.get("length"))
            if target_length is not None and target_length > 0.0:
                continue

            if ref_road is None:
                skipped.append(
                    {
                        "road_id": road_id,
                        "geometry_index": geom_index,
                        "reason": "reference_road_missing",
                    }
                )
                continue
            if geom_index >= len(ref_geoms):
                skipped.append(
                    {
                        "road_id": road_id,
                        "geometry_index": geom_index,
                        "reason": "reference_geometry_missing",
                    }
                )
                continue

            ref_geom = ref_geoms[geom_index]
            ref_length = _parse_float(ref_geom.get("length"))
            if ref_length is None or ref_length <= 0.0:
                skipped.append(
                    {
                        "road_id": road_id,
                        "geometry_index": geom_index,
                        "reason": "reference_geometry_length_not_positive",
                        "reference_length": str(ref_geom.get("length") or ""),
                    }
                )
                continue
            if not _same_float(road.get("length"), ref_road.get("length"), tol=tol):
                skipped.append(
                    {
                        "road_id": road_id,
                        "geometry_index": geom_index,
                        "reason": "road_length_mismatch_against_reference",
                        "target_road_length": str(road.get("length") or ""),
                        "reference_road_length": str(ref_road.get("length") or ""),
                    }
                )
                continue
            if not _geometry_identity_matches(geom, ref_geom, tol=tol):
                skipped.append(
                    {
                        "road_id": road_id,
                        "geometry_index": geom_index,
                        "reason": "geometry_identity_mismatch_against_reference",
                        "target_geometry": dict(geom.attrib),
                        "reference_geometry": dict(ref_geom.attrib),
                    }
                )
                continue

            before = str(geom.get("length") or "")
            after = str(ref_geom.get("length") or "")
            geom.set("length", after)
            changes.append(
                {
                    "road_id": road_id,
                    "junction": str(road.get("junction") or ""),
                    "geometry_index": geom_index,
                    "length_before": before,
                    "length_after": after,
                    "source": "reference_same_road_same_geometry_index",
                }
            )

    return {
        "mode": "reference_derived_zero_length_connector_repair",
        "tol": float(tol),
        "geometry_lengths_changed": len(changes),
        "changes": changes,
        "skipped": skipped,
        "examples": changes[:20],
    }


def _summarize_preflight_report(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if path is None:
        return None
    if not path.is_file():
        return {"path": str(path.resolve()), "available": False, "reason": "missing"}
    data = json.loads(path.read_text(encoding="utf-8"))
    errors = data.get("errors", [])
    warnings = data.get("warnings", [])
    error_classes = Counter((str(e.get("module", "")), str(e.get("code", ""))) for e in errors)
    warning_classes = Counter((str(w.get("module", "")), str(w.get("code", ""))) for w in warnings)
    return {
        "path": str(path.resolve()),
        "available": True,
        "summary": data.get("summary", {}),
        "error_classes": [
            {"module": module, "code": code, "count": count}
            for (module, code), count in sorted(error_classes.items())
        ],
        "warning_classes": [
            {"module": module, "code": code, "count": count}
            for (module, code), count in sorted(warning_classes.items())
        ],
        "error_examples": errors[:20],
        "warning_examples": warnings[:20],
    }


def _acceptance(
    *,
    before_counts: Dict[str, int],
    after_counts: Dict[str, int],
    before_nonpositive: list[Dict[str, Any]],
    after_nonpositive: list[Dict[str, Any]],
    before_g19: Dict[str, Any],
    after_g19: Dict[str, Any],
    repair: Dict[str, Any],
    preflight: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    checks = {
        "all_nonpositive_geometries_repaired": len(after_nonpositive) == 0,
        "all_preexisting_nonpositive_geometries_touched": repair["geometry_lengths_changed"]
        == len(before_nonpositive),
        "no_reference_repair_skips": len(repair["skipped"]) == 0,
        "g19_clean_before": before_g19["violations"] == 0,
        "g19_clean_after": after_g19["violations"] == 0,
        "roads_preserved": after_counts["roads"] == before_counts["roads"],
        "junctions_preserved": after_counts["junctions"] == before_counts["junctions"],
        "signals_preserved": after_counts["signals"] == before_counts["signals"],
        "objects_preserved": after_counts["objects"] == before_counts["objects"],
        "crosswalk_objects_preserved": after_counts["crosswalk_objects"] == before_counts["crosswalk_objects"],
        "elevation_segments_preserved": after_counts["elevation_segments"] == before_counts["elevation_segments"],
        "nonzero_elevation_preserved": after_counts["nonzero_elevation_segments"]
        == before_counts["nonzero_elevation_segments"],
        "roads_with_elevation_profile_preserved": after_counts["roads_with_elevation_profile"]
        == before_counts["roads_with_elevation_profile"],
    }
    if preflight is not None and preflight.get("available"):
        summary = preflight.get("summary", {})
        checks["preflight_error_count_zero"] = int(summary.get("error_count", -1)) == 0
    return {"checks": checks, "pass": all(checks.values())}


def write_markdown_report(path: Path, report: Dict[str, Any]) -> None:
    before = report["before"]
    after = report["after"]
    preflight = report.get("preflight_xodr_loadability")
    lines = [
        "# E1B Loadability Connector Repair",
        "",
        f"Verdict: `{report['verdict']}`",
        "",
        "## Candidate",
        "",
        f"- Input: `{report['input_xodr']}`",
        f"- Input sha256: `{report['input_sha256']}`",
        f"- Reference: `{report['reference_xodr']}`",
        f"- Reference sha256: `{report['reference_sha256']}`",
        f"- Output: `{report['output_xodr']}`",
        f"- Output sha256: `{report['output_sha256']}`",
        "",
        "## Repair",
        "",
        "- Rule: for a target zero-length connector geometry, copy the positive geometry length from the same road id and geometry index in the flat crash-safe reference, only when road length and geometry s/x/y/hdg match.",
        f"- Geometry lengths changed: `{report['repair']['geometry_lengths_changed']}`",
        f"- Repair skips: `{len(report['repair']['skipped'])}`",
        "",
        "## Counts",
        "",
        "| Metric | Before | After | Delta |",
        "| --- | ---: | ---: | ---: |",
    ]
    for key in [
        "roads",
        "junctions",
        "signals",
        "objects",
        "crosswalk_objects",
        "elevation_segments",
        "nonzero_elevation_segments",
        "roads_with_elevation_profile",
    ]:
        before_value = before["counts"][key]
        after_value = after["counts"][key]
        lines.append(f"| {key} | {before_value} | {after_value} | {after_value - before_value} |")

    lines.extend(
        [
            "",
            "## Diagnostics",
            "",
            f"- Nonpositive geometries: `{len(before['nonpositive_geometry_details'])} -> {len(after['nonpositive_geometry_details'])}`",
            f"- G19 violations: `{before['g19']['violations']} -> {after['g19']['violations']}`",
        ]
    )
    if preflight is not None:
        summary = preflight.get("summary", {})
        lines.extend(
            [
                "",
                "## Loadability Preflight",
                "",
                f"- Status: `{summary.get('status', 'n/a')}`",
                f"- Errors: `{summary.get('error_count', 'n/a')}`",
                f"- Warnings: `{summary.get('warning_count', 'n/a')}`",
            ]
        )
        for entry in preflight.get("warning_classes", []):
            lines.append(
                f"- Warning class `{entry['module']}:{entry['code']}`: `{entry['count']}`"
            )

    lines.extend(["", "## Acceptance Checks", ""])
    for key, value in sorted(report["acceptance"]["checks"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Scope",
            "",
            "- Candidate production only.",
            "- No certifier or gate logic changed.",
            "- No CARLA/live run performed.",
            "- ESCALATE_TO_CLAUDE before certification use.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def repair_file(
    *,
    input_xodr: Path,
    reference_xodr: Path,
    output_xodr: Path,
    report_json: Path,
    report_md: Optional[Path] = None,
    preflight_report: Optional[Path] = None,
    tol: float = TOL,
) -> Dict[str, Any]:
    input_xodr = input_xodr.resolve()
    reference_xodr = reference_xodr.resolve()
    output_xodr = output_xodr.resolve()
    report_json = report_json.resolve()
    report_md = report_md.resolve() if report_md is not None else None
    preflight_report = preflight_report.resolve() if preflight_report is not None else None

    before_root = ET.parse(input_xodr).getroot()
    before_counts = structural_counts(before_root)
    before_nonpositive = nonpositive_geometry_details(before_root)
    before_g19 = length_invariant_summary(before_root)

    tree = ET.parse(input_xodr)
    target_root = tree.getroot()
    reference_root = ET.parse(reference_xodr).getroot()
    repair = apply_reference_zero_length_connector_repair(target_root, reference_root, tol=tol)

    output_xodr.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_xodr, encoding="utf-8", xml_declaration=True)

    after_root = ET.parse(output_xodr).getroot()
    after_counts = structural_counts(after_root)
    after_nonpositive = nonpositive_geometry_details(after_root)
    after_g19 = length_invariant_summary(after_root)
    preflight = _summarize_preflight_report(preflight_report)
    acceptance = _acceptance(
        before_counts=before_counts,
        after_counts=after_counts,
        before_nonpositive=before_nonpositive,
        after_nonpositive=after_nonpositive,
        before_g19=before_g19,
        after_g19=after_g19,
        repair=repair,
        preflight=preflight,
    )

    report = {
        "schema": "E1B_LOADABILITY_CONNECTOR_REPAIR/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_xodr": str(input_xodr),
        "input_sha256": sha256_file(input_xodr),
        "reference_xodr": str(reference_xodr),
        "reference_sha256": sha256_file(reference_xodr),
        "output_xodr": str(output_xodr),
        "output_sha256": sha256_file(output_xodr),
        "repair": repair,
        "before": {
            "counts": before_counts,
            "nonpositive_geometry_details": before_nonpositive,
            "g19": before_g19,
        },
        "after": {
            "counts": after_counts,
            "nonpositive_geometry_details": after_nonpositive,
            "g19": after_g19,
        },
        "preflight_xodr_loadability": preflight,
        "acceptance": acceptance,
        "verdict": (
            "E1B_LOADABILITY_CONNECTOR_REPAIR_PASS"
            if acceptance["pass"]
            else "E1B_LOADABILITY_CONNECTOR_REPAIR_REVIEW_REQUIRED"
        ),
    }
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    if report_md is not None:
        write_markdown_report(report_md, report)
    return report


def _parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Repair zero-length connector geometries by copying lengths from a crash-safe reference XODR."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--report-md", type=Path)
    parser.add_argument("--preflight-report", type=Path)
    parser.add_argument("--tol", type=float, default=TOL)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    report = repair_file(
        input_xodr=args.input,
        reference_xodr=args.reference,
        output_xodr=args.output,
        report_json=args.report,
        report_md=args.report_md,
        preflight_report=args.preflight_report,
        tol=args.tol,
    )
    print(f"verdict: {report['verdict']}")
    print(f"output_sha256: {report['output_sha256']}")
    print(
        "nonpositive_geometries: {} -> {}".format(
            len(report["before"]["nonpositive_geometry_details"]),
            len(report["after"]["nonpositive_geometry_details"]),
        )
    )
    print(
        "g19_violations: {} -> {}".format(
            report["before"]["g19"]["violations"],
            report["after"]["g19"]["violations"],
        )
    )
    print(f"geometry_lengths_changed: {report['repair']['geometry_lengths_changed']}")
    return 0 if report["verdict"] == "E1B_LOADABILITY_CONNECTOR_REPAIR_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
