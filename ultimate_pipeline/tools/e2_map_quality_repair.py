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
from ultimate_pipeline.quality.check_elevation_continuity import check_elevation_continuity
from ultimate_pipeline.quality.check_elevation_missing_and_cliffs import (
    check_elevation_missing_and_cliffs,
)
from ultimate_pipeline.quality.check_elevation_seams import check_elevation_seams
from ultimate_pipeline.quality.elevation_structure_invariants import (
    validate_elevation_profile_structure,
)
from ultimate_pipeline.tools.crash_safe_length_repair import (
    length_invariant_summary,
    structural_counts,
)

STRICT_ELEV_JUMP_M = 2.5
DEFAULT_MAX_DZ_PER_M = 0.25


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if math.isfinite(parsed) else float(default)


def _format_float(value: float) -> str:
    return f"{float(value):.6f}"


def strict_elevation_jump_details(
    root: ET.Element,
    *,
    threshold_m: float = STRICT_ELEV_JUMP_M,
) -> list[Dict[str, Any]]:
    details = []
    for road in root.findall("road"):
        road_id = str(road.get("id") or "")
        elems = sorted(
            road.findall("./elevationProfile/elevation"),
            key=lambda e: _safe_float(e.get("s")),
        )
        prev = None
        for idx, elem in enumerate(elems):
            a = _safe_float(elem.get("a"))
            s = _safe_float(elem.get("s"))
            if prev is not None:
                prev_s, prev_a = prev
                dz = a - prev_a
                if abs(dz) > threshold_m:
                    details.append(
                        {
                            "road_id": road_id,
                            "idx": idx,
                            "s": s,
                            "prev_s": prev_s,
                            "a": a,
                            "prev_a": prev_a,
                            "dz_m": dz,
                            "abs_dz_m": abs(dz),
                        }
                    )
            prev = (s, a)
    return details


def add_header_offset_if_missing(root: ET.Element) -> Dict[str, Any]:
    header = root.find("header")
    if header is None:
        return {"changed": False, "reason": "header_missing"}
    offset = header.find("offset")
    if offset is not None:
        missing = []
        for key, value in {"x": "0.0", "y": "0.0", "z": "0.0", "hdg": "0.0"}.items():
            if key not in offset.attrib:
                offset.set(key, value)
                missing.append(key)
        return {"changed": bool(missing), "reason": "completed_existing_offset", "attrs_added": missing}
    ET.SubElement(header, "offset", {"x": "0.0", "y": "0.0", "z": "0.0", "hdg": "0.0"})
    return {
        "changed": True,
        "reason": "added_zero_offset_without_moving_geometry",
        "attrs": {"x": "0.0", "y": "0.0", "z": "0.0", "hdg": "0.0"},
    }


def reconcile_short_connector_geometry_lengths(
    root: ET.Element,
    *,
    max_road_length_m: float = 0.100001,
    rel_threshold: float = 0.10,
) -> Dict[str, Any]:
    changes = []
    skipped = []
    for road in root.findall("road"):
        road_id = str(road.get("id") or "")
        road_length = _safe_float(road.get("length"))
        if road_length <= 0.0 or road_length > max_road_length_m:
            continue
        geoms = road.findall("./planView/geometry")
        if len(geoms) != 1:
            continue
        geom = geoms[0]
        geom_length = _safe_float(geom.get("length"))
        if geom_length <= 0.0:
            skipped.append(
                {
                    "road_id": road_id,
                    "reason": "geometry_length_nonpositive_not_e2_scope",
                    "geometry_length": str(geom.get("length") or ""),
                }
            )
            continue
        rel = abs(road_length - geom_length) / max(1e-6, road_length)
        if rel <= rel_threshold:
            continue
        before = str(geom.get("length") or "")
        after = str(road.get("length") or "")
        geom.set("length", after)
        changes.append(
            {
                "road_id": road_id,
                "junction": str(road.get("junction") or ""),
                "geometry_index": 0,
                "length_before": before,
                "length_after": after,
                "road_length": str(road.get("length") or ""),
                "relative_mismatch_before": rel,
            }
        )
    return {
        "mode": "short_single_geometry_connector_length_reconcile",
        "max_road_length_m": float(max_road_length_m),
        "rel_threshold": float(rel_threshold),
        "geometry_lengths_changed": len(changes),
        "changes": changes,
        "skipped": skipped,
    }


def smooth_elevation_jumps_endpoint_preserving(
    root: ET.Element,
    *,
    strict_jump_m: float = STRICT_ELEV_JUMP_M,
    max_dz_per_m: float = DEFAULT_MAX_DZ_PER_M,
) -> Dict[str, Any]:
    road_reports = []
    entries_a_changed = 0
    coeffs_rewritten = 0
    endpoint_locked_residuals = []

    for road in root.findall("road"):
        road_id = str(road.get("id") or "")
        elems = sorted(
            road.findall("./elevationProfile/elevation"),
            key=lambda e: _safe_float(e.get("s")),
        )
        if len(elems) < 3:
            continue

        s_vals = [_safe_float(e.get("s")) for e in elems]
        a_vals = [_safe_float(e.get("a")) for e in elems]
        before_jumps = [
            {
                "idx": idx,
                "s": s_vals[idx],
                "prev_s": s_vals[idx - 1],
                "a": a_vals[idx],
                "prev_a": a_vals[idx - 1],
                "abs_dz_m": abs(a_vals[idx] - a_vals[idx - 1]),
            }
            for idx in range(1, len(a_vals))
            if abs(a_vals[idx] - a_vals[idx - 1]) > strict_jump_m
        ]
        if not before_jumps:
            continue

        smoothed = list(a_vals)
        limits = [
            min(
                strict_jump_m - 1e-3,
                max(1e-6, float(max_dz_per_m) * max(1e-6, s_vals[idx] - s_vals[idx - 1])),
            )
            for idx in range(1, len(s_vals))
        ]

        # Keep first/last elevation anchors fixed to avoid injecting new road-link
        # endpoint discontinuities just to satisfy a local warning threshold.
        for _ in range(50):
            for idx in range(1, len(smoothed) - 1):
                lo = smoothed[idx - 1] - limits[idx - 1]
                hi = smoothed[idx - 1] + limits[idx - 1]
                if smoothed[idx] < lo:
                    smoothed[idx] = lo
                elif smoothed[idx] > hi:
                    smoothed[idx] = hi
            for idx in range(len(smoothed) - 2, 0, -1):
                lo = smoothed[idx + 1] - limits[idx]
                hi = smoothed[idx + 1] + limits[idx]
                if smoothed[idx] < lo:
                    smoothed[idx] = lo
                elif smoothed[idx] > hi:
                    smoothed[idx] = hi

        after_jumps = [
            {
                "idx": idx,
                "s": s_vals[idx],
                "prev_s": s_vals[idx - 1],
                "a": smoothed[idx],
                "prev_a": smoothed[idx - 1],
                "abs_dz_m": abs(smoothed[idx] - smoothed[idx - 1]),
                "reason": "endpoint_anchor_preserved" if idx in (1, len(smoothed) - 1) else "residual",
            }
            for idx in range(1, len(smoothed))
            if abs(smoothed[idx] - smoothed[idx - 1]) > strict_jump_m
        ]
        endpoint_locked_residuals.extend(
            {"road_id": road_id, **jump}
            for jump in after_jumps
        )

        changed_entries_this_road = 0
        for idx, elem in enumerate(elems):
            if abs(smoothed[idx] - a_vals[idx]) > 1e-9:
                elem.set("a", _format_float(smoothed[idx]))
                entries_a_changed += 1
                changed_entries_this_road += 1

            if idx + 1 < len(elems):
                ds = max(1e-6, s_vals[idx + 1] - s_vals[idx])
                b = (smoothed[idx + 1] - smoothed[idx]) / ds
            else:
                b = 0.0
            elem.set("b", _format_float(b))
            elem.set("c", "0.000000")
            elem.set("d", "0.000000")
            coeffs_rewritten += 1

        road_reports.append(
            {
                "road_id": road_id,
                "elevation_entries": len(elems),
                "a_entries_changed": changed_entries_this_road,
                "jumps_before": len(before_jumps),
                "jumps_after": len(after_jumps),
                "before_examples": before_jumps[:5],
                "after_residual_examples": after_jumps[:5],
            }
        )

    return {
        "mode": "endpoint_preserving_constrained_piecewise_linear_elevation_smoothing",
        "strict_jump_m": float(strict_jump_m),
        "max_dz_per_m": float(max_dz_per_m),
        "roads_smoothed": len(road_reports),
        "a_entries_changed": entries_a_changed,
        "elevation_coeff_entries_rewritten": coeffs_rewritten,
        "endpoint_locked_residual_count": len(endpoint_locked_residuals),
        "endpoint_locked_residuals": endpoint_locked_residuals,
        "road_examples": road_reports[:20],
    }


def _summarize_preflight(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if path is None:
        return None
    if not path.is_file():
        return {"path": str(path.resolve()), "available": False}
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


def _compact_elevation_qa(xodr_path: Path) -> Dict[str, Any]:
    root = ET.parse(xodr_path).getroot()
    seam = check_elevation_seams(str(xodr_path))
    continuity = check_elevation_continuity(str(xodr_path))
    missing_cliffs = check_elevation_missing_and_cliffs(str(xodr_path))
    structure = validate_elevation_profile_structure(root)
    strict_jumps = strict_elevation_jump_details(root)
    return {
        "strict_elev_jump_count": len(strict_jumps),
        "strict_elev_jump_examples": strict_jumps[:20],
        "seams": {
            "ok": seam.get("ok"),
            "seam_stats": seam.get("seam_stats"),
            "elevation_stats": seam.get("elevation_stats"),
            "top_offenders": seam.get("top_offenders", [])[:10],
        },
        "continuity": {
            "ok": continuity.get("ok"),
            "eps_z": continuity.get("eps_z"),
            "num_links_checked": continuity.get("num_links_checked"),
            "num_issues": continuity.get("num_issues"),
            "examples": continuity.get("issues", [])[:20],
        },
        "missing_and_cliffs": {
            "ok": missing_cliffs.get("ok"),
            "roads_zero_a": missing_cliffs.get("roads_zero_a"),
            "zero_ratio": missing_cliffs.get("zero_ratio"),
            "max_link_dz": missing_cliffs.get("max_link_dz"),
            "p99_link_dz": missing_cliffs.get("p99_link_dz"),
            "examples": missing_cliffs.get("examples", [])[:20],
        },
        "structure": {
            "ok": structure.get("ok"),
            "issue_count": structure.get("issue_count"),
            "fail_count": structure.get("fail_count"),
            "examples": structure.get("issues", [])[:20],
        },
    }


def _acceptance(
    *,
    before_counts: Dict[str, int],
    after_counts: Dict[str, int],
    before_g19: Dict[str, Any],
    after_g19: Dict[str, Any],
    before_qa: Dict[str, Any],
    after_qa: Dict[str, Any],
    preflight_after: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    checks = {
        "preflight_errors_zero": (
            preflight_after is not None
            and preflight_after.get("available")
            and int(preflight_after.get("summary", {}).get("error_count", -1)) == 0
        ),
        "strict_elev_jumps_materially_reduced": after_qa["strict_elev_jump_count"]
        <= max(5, int(0.01 * before_qa["strict_elev_jump_count"])),
        "elevation_seam_gate_ok": bool(after_qa["seams"].get("ok")),
        "elevation_missing_and_cliffs_ok": bool(after_qa["missing_and_cliffs"].get("ok")),
        "elevation_structure_ok": bool(after_qa["structure"].get("ok")),
        "g19_clean_before": before_g19["violations"] == 0,
        "g19_clean_after": after_g19["violations"] == 0,
        "roads_preserved": after_counts["roads"] == before_counts["roads"],
        "junctions_preserved": after_counts["junctions"] == before_counts["junctions"],
        "signals_preserved": after_counts["signals"] == before_counts["signals"],
        "objects_preserved": after_counts["objects"] == before_counts["objects"],
        "crosswalk_objects_preserved": after_counts["crosswalk_objects"] == before_counts["crosswalk_objects"],
        "nonzero_elevation_preserved": after_counts["nonzero_elevation_segments"]
        == before_counts["nonzero_elevation_segments"],
        "not_flat": after_counts["nonzero_elevation_segments"] >= 400000,
    }
    return {"checks": checks, "pass": all(checks.values())}


def write_markdown_report(path: Path, report: Dict[str, Any]) -> None:
    before = report["before"]
    after = report["after"]
    before_preflight = report.get("preflight_before")
    after_preflight = report.get("preflight_after")
    lines = [
        "# E2 Map Quality",
        "",
        f"Verdict: `{report['verdict']}`",
        "",
        "## Candidate",
        "",
        f"- Input: `{report['input_xodr']}`",
        f"- Input sha256: `{report['input_sha256']}`",
        f"- Output: `{report['output_xodr']}`",
        f"- Output sha256: `{report['output_sha256']}`",
        "",
        "## Repair Summary",
        "",
        f"- Header offset: `{report['repairs']['header_offset']['reason']}`",
        f"- Short connector geometry lengths changed: `{report['repairs']['road_length_reconcile']['geometry_lengths_changed']}`",
        f"- Elevation roads smoothed: `{report['repairs']['elevation_smoothing']['roads_smoothed']}`",
        f"- Elevation `a` entries changed: `{report['repairs']['elevation_smoothing']['a_entries_changed']}`",
        f"- Endpoint-locked residual strict jumps: `{report['repairs']['elevation_smoothing']['endpoint_locked_residual_count']}`",
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
        b = before["counts"][key]
        a = after["counts"][key]
        lines.append(f"| {key} | {b} | {a} | {a - b} |")

    lines.extend(
        [
            "",
            "## Diagnostics",
            "",
            f"- G19 violations: `{before['g19']['violations']} -> {after['g19']['violations']}`",
            f"- Strict `elev_jump`: `{before['elevation_qa']['strict_elev_jump_count']} -> {after['elevation_qa']['strict_elev_jump_count']}`",
            f"- Elevation seam gate: `{before['elevation_qa']['seams']['ok']} -> {after['elevation_qa']['seams']['ok']}`",
            f"- Elevation seam steps: `{before['elevation_qa']['seams']['seam_stats']['count']} -> {after['elevation_qa']['seams']['seam_stats']['count']}`",
            f"- Elevation continuity issues: `{before['elevation_qa']['continuity']['num_issues']} -> {after['elevation_qa']['continuity']['num_issues']}`",
            f"- Missing/cliffs gate: `{before['elevation_qa']['missing_and_cliffs']['ok']} -> {after['elevation_qa']['missing_and_cliffs']['ok']}`",
            f"- Elevation structure gate: `{before['elevation_qa']['structure']['ok']} -> {after['elevation_qa']['structure']['ok']}`",
        ]
    )
    if before_preflight is not None and after_preflight is not None:
        lines.extend(
            [
                "",
                "## Preflight",
                "",
                f"- Status: `{before_preflight['summary'].get('status')} -> {after_preflight['summary'].get('status')}`",
                f"- Errors: `{before_preflight['summary'].get('error_count')} -> {after_preflight['summary'].get('error_count')}`",
                f"- Warnings: `{before_preflight['summary'].get('warning_count')} -> {after_preflight['summary'].get('warning_count')}`",
            ]
        )
        for entry in after_preflight.get("warning_classes", []):
            lines.append(f"- After warning class `{entry['module']}:{entry['code']}`: `{entry['count']}`")

    lines.extend(["", "## Acceptance Checks", ""])
    for key, value in sorted(report["acceptance"]["checks"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Scope",
            "",
            "- Candidate production only.",
            "- No certifier/gate logic changed.",
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
    output_xodr: Path,
    report_json: Path,
    report_md: Optional[Path] = None,
    preflight_before: Optional[Path] = None,
    preflight_after: Optional[Path] = None,
    max_dz_per_m: float = DEFAULT_MAX_DZ_PER_M,
) -> Dict[str, Any]:
    input_xodr = input_xodr.resolve()
    output_xodr = output_xodr.resolve()
    report_json = report_json.resolve()
    report_md = report_md.resolve() if report_md is not None else None
    preflight_before = preflight_before.resolve() if preflight_before is not None else None
    preflight_after = preflight_after.resolve() if preflight_after is not None else None

    before_root = ET.parse(input_xodr).getroot()
    before_counts = structural_counts(before_root)
    before_g19 = length_invariant_summary(before_root)
    before_qa = _compact_elevation_qa(input_xodr)

    tree = ET.parse(input_xodr)
    root = tree.getroot()
    header_report = add_header_offset_if_missing(root)
    length_report = reconcile_short_connector_geometry_lengths(root)
    smoothing_report = smooth_elevation_jumps_endpoint_preserving(
        root,
        max_dz_per_m=max_dz_per_m,
    )

    output_xodr.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_xodr, encoding="utf-8", xml_declaration=True)

    after_root = ET.parse(output_xodr).getroot()
    after_counts = structural_counts(after_root)
    after_g19 = length_invariant_summary(after_root)
    after_qa = _compact_elevation_qa(output_xodr)
    preflight_before_summary = _summarize_preflight(preflight_before)
    preflight_after_summary = _summarize_preflight(preflight_after)
    acceptance = _acceptance(
        before_counts=before_counts,
        after_counts=after_counts,
        before_g19=before_g19,
        after_g19=after_g19,
        before_qa=before_qa,
        after_qa=after_qa,
        preflight_after=preflight_after_summary,
    )

    report = {
        "schema": "E2_MAP_QUALITY/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_xodr": str(input_xodr),
        "input_sha256": sha256_file(input_xodr),
        "output_xodr": str(output_xodr),
        "output_sha256": sha256_file(output_xodr),
        "repairs": {
            "header_offset": header_report,
            "road_length_reconcile": length_report,
            "elevation_smoothing": smoothing_report,
        },
        "before": {
            "counts": before_counts,
            "g19": before_g19,
            "elevation_qa": before_qa,
        },
        "after": {
            "counts": after_counts,
            "g19": after_g19,
            "elevation_qa": after_qa,
        },
        "preflight_before": preflight_before_summary,
        "preflight_after": preflight_after_summary,
        "acceptance": acceptance,
        "verdict": (
            "DRIVABLE_CANDIDATE_PRODUCED"
            if acceptance["pass"]
            else "DRIVABLE_CANDIDATE_REVIEW_REQUIRED"
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
    parser = argparse.ArgumentParser(description="E2 map-quality repair for the elevated loadable candidate.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--report-md", type=Path)
    parser.add_argument("--preflight-before", type=Path)
    parser.add_argument("--preflight-after", type=Path)
    parser.add_argument("--max-dz-per-m", type=float, default=DEFAULT_MAX_DZ_PER_M)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    report = repair_file(
        input_xodr=args.input,
        output_xodr=args.output,
        report_json=args.report,
        report_md=args.report_md,
        preflight_before=args.preflight_before,
        preflight_after=args.preflight_after,
        max_dz_per_m=args.max_dz_per_m,
    )
    print(f"verdict: {report['verdict']}")
    print(f"output_sha256: {report['output_sha256']}")
    print(
        "strict_elev_jump: {} -> {}".format(
            report["before"]["elevation_qa"]["strict_elev_jump_count"],
            report["after"]["elevation_qa"]["strict_elev_jump_count"],
        )
    )
    print(
        "preflight_after_errors: {}".format(
            None
            if report.get("preflight_after") is None
            else report["preflight_after"]["summary"].get("error_count")
        )
    )
    return 0 if report["verdict"] == "DRIVABLE_CANDIDATE_PRODUCED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
