#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import math
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence

from tools.verify_candidate_digest import sha256_file

MARGIN_M = 1e-3
TOL_M = 1e-9

REPAIR_SOURCE = {
    "lineage": [
        "reports/post_audit_hardening/20260811T000000Z_C3_PROTOCOL",
        "reports/post_audit_hardening/20260813T000000Z_C3_REGOVERN",
    ],
    "governed_runtime_rule": "ultimate_pipeline/core/carla_opendrive_loader.py::repair_road_lengths",
    "rule": "if max(planView.geometry.s + geometry.length) > road.length, set road.length = repr(geom_end + 1e-3)",
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _parse_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _iter_roads(root: ET.Element) -> Iterable[ET.Element]:
    return root.findall("road")


def _iter_roads_indexed(root: ET.Element) -> Iterable[tuple[int, ET.Element]]:
    return enumerate(root.findall("road"))


def _road_key(index: int, road: ET.Element) -> str:
    return f"{index}:{road.get('id') or ''}"


def _max_geometry_end(road: ET.Element) -> Optional[float]:
    geoms = road.findall("planView/geometry")
    if not geoms:
        return None
    return max(_safe_float(g.get("s")) + _safe_float(g.get("length")) for g in geoms)


def length_invariant_summary(root: ET.Element, *, tol: float = TOL_M) -> Dict[str, Any]:
    violations = []
    roads_checked = 0
    max_excess_m = 0.0
    for index, road in _iter_roads_indexed(root):
        declared = _parse_float(road.get("length"))
        if declared is None:
            continue
        roads_checked += 1
        geom_end = _max_geometry_end(road)
        if geom_end is None:
            continue
        excess = geom_end - declared
        if excess > tol:
            max_excess_m = max(max_excess_m, excess)
            violations.append(
                {
                    "road_key": _road_key(index, road),
                    "road_index": index,
                    "road_id": str(road.get("id") or ""),
                    "declared_length_m": declared,
                    "max_geometry_end_m": geom_end,
                    "excess_m": excess,
                }
            )
    return {
        "violations": len(violations),
        "roads_checked": roads_checked,
        "max_excess_m": max_excess_m,
        "examples": violations[:20],
        "violation_details": violations,
    }


def structural_counts(root: ET.Element) -> Dict[str, int]:
    elevation_segments = root.findall(".//elevationProfile/elevation")
    nonzero_elevation = 0
    for segment in elevation_segments:
        coeffs = [_safe_float(segment.get(k)) for k in ("a", "b", "c", "d")]
        if any(abs(v) > 1e-12 for v in coeffs):
            nonzero_elevation += 1
    crosswalk_objects = 0
    for obj in root.findall(".//object"):
        obj_type = str(obj.get("type") or "").strip().lower()
        obj_subtype = str(obj.get("subtype") or "").strip().lower()
        if obj_type in {"crosswalk", "crosswalk zone", "crosswalkzone"} or obj_subtype in {
            "crosswalk",
            "zebra",
        }:
            crosswalk_objects += 1
    return {
        "roads": len(root.findall("road")),
        "junctions": len(root.findall("junction")),
        "signals": len(root.findall(".//signal")),
        "signal_references": len(root.findall(".//signalReference")),
        "objects": len(root.findall(".//object")),
        "crosswalk_objects": crosswalk_objects,
        "elevation_segments": len(elevation_segments),
        "nonzero_elevation_segments": nonzero_elevation,
        "roads_with_elevation_profile": len(
            [road for road in _iter_roads(root) if road.find("elevationProfile/elevation") is not None]
        ),
    }


def _road_length_attrs(root: ET.Element) -> Dict[str, str]:
    return {
        _road_key(index, road): str(road.get("length") or "")
        for index, road in _iter_roads_indexed(root)
    }


def apply_c3_violation_length_repair(
    root: ET.Element,
    *,
    margin_m: float = MARGIN_M,
    tol: float = TOL_M,
) -> Dict[str, Any]:
    changes = []
    for index, road in _iter_roads_indexed(root):
        geom_end = _max_geometry_end(road)
        if geom_end is None:
            continue
        declared = _parse_float(road.get("length"))
        if declared is None:
            continue
        excess = geom_end - declared
        if excess <= tol:
            continue

        before = str(road.get("length") or "")
        target = geom_end + float(margin_m)
        after = repr(target)
        road.set("length", after)
        changes.append(
            {
                "road_key": _road_key(index, road),
                "road_index": index,
                "road_id": str(road.get("id") or ""),
                "length_before": before,
                "length_after": after,
                "declared_before_m": declared,
                "max_geometry_end_m": geom_end,
                "excess_before_m": excess,
                "delta_m": target - declared,
            }
        )
    return {
        "mode": "c3_violation_only_full_precision_length_repair",
        "margin_m": float(margin_m),
        "tol_m": float(tol),
        "source": REPAIR_SOURCE,
        "roads_length_adjusted": len(changes),
        "examples": changes[:20],
        "changes": changes,
    }


def _object_identity(obj: ET.Element) -> tuple[str, str, str, str, str, str]:
    return (
        str(obj.get("id") or ""),
        str(obj.get("type") or ""),
        str(obj.get("subtype") or ""),
        str(obj.get("name") or ""),
        str(obj.get("s") or ""),
        str(obj.get("t") or ""),
    )


def merge_road_objects(
    target_root: ET.Element,
    source_root: ET.Element,
    *,
    tol: float = MARGIN_M,
) -> Dict[str, Any]:
    target_roads = {str(road.get("id") or ""): road for road in _iter_roads(target_root)}
    existing = set()
    for road in _iter_roads(target_root):
        rid = str(road.get("id") or "")
        for obj in road.findall("./objects/object"):
            existing.add((rid, _object_identity(obj)))

    source_objects = 0
    merged = 0
    skipped_duplicate = 0
    created_containers = 0
    touched_road_ids = set()
    examples = []
    infeasible = []

    for source_road in _iter_roads(source_root):
        road_id = str(source_road.get("id") or "")
        objects = source_road.findall("./objects/object")
        if not objects:
            continue
        target_road = target_roads.get(road_id)
        for obj in objects:
            source_objects += 1
            identity = _object_identity(obj)
            if target_road is None:
                infeasible.append(
                    {
                        "road_id": road_id,
                        "object_id": str(obj.get("id") or ""),
                        "reason": "target_road_missing",
                    }
                )
                continue

            target_length = _parse_float(target_road.get("length"))
            object_s = _parse_float(obj.get("s"))
            if target_length is not None and object_s is not None:
                if object_s < -tol or object_s - target_length > tol:
                    infeasible.append(
                        {
                            "road_id": road_id,
                            "object_id": str(obj.get("id") or ""),
                            "object_s_m": object_s,
                            "target_road_length_m": target_length,
                            "reason": "object_s_outside_target_road_length",
                        }
                    )
                    continue

            if (road_id, identity) in existing:
                skipped_duplicate += 1
                continue

            target_objects = target_road.find("objects")
            if target_objects is None:
                target_objects = ET.SubElement(target_road, "objects")
                created_containers += 1
            target_objects.append(copy.deepcopy(obj))
            existing.add((road_id, identity))
            merged += 1
            touched_road_ids.add(road_id)
            if len(examples) < 20:
                examples.append(
                    {
                        "road_id": road_id,
                        "object_id": str(obj.get("id") or ""),
                        "type": str(obj.get("type") or ""),
                        "subtype": str(obj.get("subtype") or ""),
                        "s": str(obj.get("s") or ""),
                    }
                )

    return {
        "requested": True,
        "object_s_tolerance_m": float(tol),
        "source_objects": source_objects,
        "merged": merged,
        "skipped_duplicate": skipped_duplicate,
        "created_object_containers": created_containers,
        "touched_road_count": len(touched_road_ids),
        "touched_road_ids": sorted(touched_road_ids),
        "examples": examples,
        "infeasible": infeasible,
        "feasible": not infeasible,
    }


def _diagnose_xodr(path: Path) -> Dict[str, Any]:
    root = ET.parse(path).getroot()
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "counts": structural_counts(root),
        "g19": length_invariant_summary(root),
    }


def _offline_validation(path: Path, root: ET.Element) -> Dict[str, Any]:
    validation: Dict[str, Any] = {"xml_parse": "ok"}
    try:
        from ultimate_pipeline.quality.check_xodr_schema import (
            check_xml_uniqueness,
            validate_xodr_schema,
        )

        uniqueness_issues = check_xml_uniqueness(root)
        schema_ok, schema_error = validate_xodr_schema(str(path), None)
        validation["check_xodr_schema"] = {
            "schema_ok": bool(schema_ok),
            "schema_error": schema_error,
            "uniqueness_issue_count": len(uniqueness_issues),
            "uniqueness_examples": uniqueness_issues[:20],
        }
    except Exception as exc:  # pragma: no cover - diagnostic only
        validation["check_xodr_schema"] = {"error": str(exc)}

    try:
        from ultimate_pipeline.quality.check_carla_import_s import CarlaImportSChecker

        issues = CarlaImportSChecker.validate(root)
        validation["check_carla_import_s"] = {
            "issue_count": len(issues),
            "examples": issues[:20],
        }
    except Exception as exc:  # pragma: no cover - diagnostic only
        validation["check_carla_import_s"] = {"error": str(exc)}

    try:
        from ultimate_pipeline.quality.xodr_strict_validator import StrictXodrValidator

        validator = StrictXodrValidator()
        issues = validator.validate_root(root)
        strict_report = validator._report(issues)
        validation["xodr_strict_validator"] = {
            "ok": bool(strict_report.get("ok", False)),
            "issue_count": int(strict_report.get("n_issues", 0)),
            "error_count": int(strict_report.get("n_errors", 0)),
            "warning_count": int(strict_report.get("n_warnings", 0)),
            "examples": strict_report.get("issues", [])[:20],
        }
    except Exception as exc:  # pragma: no cover - diagnostic only
        validation["xodr_strict_validator"] = {"error": str(exc)}

    return validation


def _summarize_preflight_report(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if path is None:
        return None
    if not path.is_file():
        return {
            "path": str(path.resolve()),
            "available": False,
            "reason": "missing",
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    errors = data.get("errors", [])
    classes = Counter((str(e.get("module", "")), str(e.get("code", ""))) for e in errors)
    return {
        "path": str(path.resolve()),
        "available": True,
        "summary": data.get("summary", {}),
        "error_classes": [
            {"module": module, "code": code, "count": count}
            for (module, code), count in sorted(classes.items())
        ],
        "error_examples": errors[:20],
        "warning_count": len(data.get("warnings", [])),
    }


def _load_optional_json(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if path is None:
        return None
    if not path.is_file():
        return {"path": str(path.resolve()), "available": False, "reason": "missing"}
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data.setdefault("path", str(path.resolve()))
        data.setdefault("available", True)
        return data
    return {"path": str(path.resolve()), "available": True, "value": data}


def _evaluate_acceptance(
    *,
    before_counts: Dict[str, int],
    after_counts: Dict[str, int],
    before_g19: Dict[str, Any],
    after_g19: Dict[str, Any],
    repair: Dict[str, Any],
    length_change_audit: Dict[str, Any],
    object_merge: Optional[Dict[str, Any]],
    validation: Dict[str, Any],
    expected_roads: Optional[int],
    expected_junctions: Optional[int],
    min_signals: Optional[int],
    min_nonzero_elevation: Optional[int],
) -> Dict[str, Any]:
    checks = {
        "g19_violations_removed": after_g19["violations"] == 0,
        "all_preexisting_violations_repaired": repair["roads_length_adjusted"] == before_g19["violations"],
        "only_preexisting_violating_road_lengths_changed": not length_change_audit["unexpected_length_changes"],
        "roads_preserved": after_counts["roads"] == before_counts["roads"],
        "junctions_preserved": after_counts["junctions"] == before_counts["junctions"],
        "signals_preserved": after_counts["signals"] >= before_counts["signals"],
        "signal_references_preserved": after_counts["signal_references"] == before_counts["signal_references"],
        "elevation_segments_preserved": after_counts["elevation_segments"] == before_counts["elevation_segments"],
        "nonzero_elevation_preserved": after_counts["nonzero_elevation_segments"] == before_counts["nonzero_elevation_segments"],
        "roads_with_elevation_profile_preserved": after_counts["roads_with_elevation_profile"]
        == before_counts["roads_with_elevation_profile"],
        "xml_parse_ok": validation.get("xml_parse") == "ok",
    }
    schema = validation.get("check_xodr_schema", {})
    if "schema_ok" in schema:
        checks["schema_ok_or_skipped"] = bool(schema.get("schema_ok"))
        checks["xml_uniqueness_clean"] = int(schema.get("uniqueness_issue_count", 0)) == 0
    carla_s = validation.get("check_carla_import_s", {})
    if "issue_count" in carla_s:
        checks["carla_import_s_clean"] = int(carla_s.get("issue_count", 0)) == 0

    if object_merge is not None:
        checks["object_merge_feasible"] = bool(object_merge.get("feasible"))
        checks["all_source_objects_carried"] = (
            int(object_merge.get("merged", 0)) + int(object_merge.get("skipped_duplicate", 0))
            == int(object_merge.get("source_objects", 0))
        )

    if expected_roads is not None:
        checks["expected_road_count"] = after_counts["roads"] == int(expected_roads)
    if expected_junctions is not None:
        checks["expected_junction_count"] = after_counts["junctions"] == int(expected_junctions)
    if min_signals is not None:
        checks["min_signal_count"] = after_counts["signals"] >= int(min_signals)
    if min_nonzero_elevation is not None:
        checks["min_nonzero_elevation_segments"] = (
            after_counts["nonzero_elevation_segments"] >= int(min_nonzero_elevation)
        )

    return {
        "checks": checks,
        "pass": all(checks.values()),
    }


def _length_change_audit(
    before_root: ET.Element,
    after_root: ET.Element,
    before_g19: Dict[str, Any],
) -> Dict[str, Any]:
    before_lengths = _road_length_attrs(before_root)
    after_lengths = _road_length_attrs(after_root)
    violating_keys = {v["road_key"] for v in before_g19["violation_details"]}
    changed = []
    for key, before in before_lengths.items():
        after = after_lengths.get(key)
        if after is None:
            continue
        if before != after:
            changed.append(
                {
                    "road_key": key,
                    "length_before": before,
                    "length_after": after,
                    "was_preexisting_violation": key in violating_keys,
                }
            )
    unexpected = [entry for entry in changed if not entry["was_preexisting_violation"]]
    missing_after = sorted(set(before_lengths) - set(after_lengths))
    new_after = sorted(set(after_lengths) - set(before_lengths))
    return {
        "changed_length_attrs": len(changed),
        "expected_preexisting_violating_roads": len(violating_keys),
        "unexpected_length_changes": unexpected,
        "missing_after_road_keys": missing_after,
        "new_after_road_keys": new_after,
        "examples": changed[:20],
    }


def write_markdown_report(path: Path, report: Dict[str, Any]) -> None:
    parents = report["parents"]
    before = report["before"]
    after = report["after"]
    safe = report.get("crash_safe_reference")
    object_merge = report.get("object_merge")
    acceptance = report["acceptance"]

    lines = [
        "# E1 Elevation Merge",
        "",
        f"Verdict: `{report['verdict']}`",
        "",
        "## Candidate",
        "",
        f"- Output: `{report['output_xodr']}`",
        f"- Output sha256: `{report['output_sha256']}`",
        f"- Elevated parent: `{parents['elevated_parent']['path']}`",
        f"- Elevated parent sha256: `{parents['elevated_parent']['sha256']}`",
    ]
    if safe:
        lines.extend(
            [
                f"- Crash-safe reference: `{safe['path']}`",
                f"- Crash-safe reference sha256: `{safe['sha256']}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Repair Source",
            "",
            f"- Lineage: `{', '.join(REPAIR_SOURCE['lineage'])}`",
            f"- Runtime rule reused: `{REPAIR_SOURCE['governed_runtime_rule']}`",
            f"- Rule: `{REPAIR_SOURCE['rule']}`",
            "",
            "## Counts",
            "",
            "| Metric | Elevated parent | Output | Delta |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for key in [
        "roads",
        "junctions",
        "signals",
        "signal_references",
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
            "## G19 Length Invariant",
            "",
            "| Candidate | Violations | Roads checked | Max excess m |",
            "| --- | ---: | ---: | ---: |",
            f"| Elevated parent | {before['g19']['violations']} | {before['g19']['roads_checked']} | {before['g19']['max_excess_m']:.12g} |",
        ]
    )
    if safe:
        lines.append(
            f"| Crash-safe reference | {safe['g19']['violations']} | {safe['g19']['roads_checked']} | {safe['g19']['max_excess_m']:.12g} |"
        )
    lines.append(
        f"| Output | {after['g19']['violations']} | {after['g19']['roads_checked']} | {after['g19']['max_excess_m']:.12g} |"
    )

    lines.extend(
        [
            "",
            "## Touch Scope",
            "",
            f"- Road length attributes changed: `{report['length_change_audit']['changed_length_attrs']}`",
            f"- Preexisting violating road keys: `{report['length_change_audit']['expected_preexisting_violating_roads']}`",
            f"- Unexpected non-violating length changes: `{len(report['length_change_audit']['unexpected_length_changes'])}`",
            "- Full violating road IDs and overflow values are in `E1_ELEVATION_MERGE.json` under `before.g19.violation_details`.",
        ]
    )
    if object_merge is not None:
        lines.extend(
            [
                "",
                "## Object Carry",
                "",
                f"- Source road objects: `{object_merge['source_objects']}`",
                f"- Objects merged: `{object_merge['merged']}`",
                f"- Duplicate objects skipped: `{object_merge['skipped_duplicate']}`",
                f"- Feasible: `{object_merge['feasible']}`",
            ]
        )

    preflight = report.get("preflight_xodr_loadability")
    baseline = report.get("inherited_loadability_baseline")
    if preflight is not None or baseline is not None:
        lines.extend(
            [
                "",
                "## Loadability Preflight",
                "",
            ]
        )
        if preflight is not None:
            summary = preflight.get("summary", {})
            lines.extend(
                [
                    f"- `preflight_xodr_loadability` status: `{summary.get('status', 'n/a')}`",
                    f"- Preflight errors: `{summary.get('error_count', 'n/a')}`",
                    f"- Preflight warnings: `{summary.get('warning_count', preflight.get('warning_count', 'n/a'))}`",
                ]
            )
            for entry in preflight.get("error_classes", []):
                lines.append(
                    f"- Error class `{entry['module']}:{entry['code']}`: `{entry['count']}`"
                )
        if baseline is not None:
            lines.extend(
                [
                    f"- Phase H loadability verdict: `{baseline.get('verdict', 'n/a')}`",
                    f"- Phase H candidate errors: `{baseline.get('candidate_error_count', 'n/a')}`",
                    f"- G0 baseline errors: `{baseline.get('g0_baseline_error_count', 'n/a')}`",
                    f"- New/exceeded error classes: `{baseline.get('new_or_exceeded_error_classes', 'n/a')}`",
                ]
            )

    lines.extend(
        [
            "",
            "## Offline Validation",
            "",
            f"- XML parse: `{report['validation'].get('xml_parse')}`",
            f"- `check_xodr_schema` uniqueness issues: `{report['validation'].get('check_xodr_schema', {}).get('uniqueness_issue_count', 'n/a')}`",
            f"- `check_carla_import_s` issues: `{report['validation'].get('check_carla_import_s', {}).get('issue_count', 'n/a')}`",
            f"- `xodr_strict_validator` errors: `{report['validation'].get('xodr_strict_validator', {}).get('error_count', 'n/a')}`",
            "",
            "## Acceptance Checks",
            "",
        ]
    )
    for key, value in sorted(acceptance["checks"].items()):
        lines.append(f"- `{key}`: `{value}`")

    lines.extend(
        [
            "",
            "## Scope",
            "",
            "- This is candidate production evidence only.",
            "- No certifier or gate logic was changed.",
            "- No CARLA/live certification run was performed.",
            "- ESCALATE_TO_CLAUDE before this candidate is used for certification.",
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
    crash_safe_reference_xodr: Optional[Path] = None,
    merge_objects_from_xodr: Optional[Path] = None,
    preflight_report: Optional[Path] = None,
    loadability_baseline_summary: Optional[Path] = None,
    margin_m: float = MARGIN_M,
    tol: float = TOL_M,
    object_tol_m: float = MARGIN_M,
    expected_roads: Optional[int] = None,
    expected_junctions: Optional[int] = None,
    min_signals: Optional[int] = None,
    min_nonzero_elevation: Optional[int] = None,
) -> Dict[str, Any]:
    input_xodr = input_xodr.resolve()
    output_xodr = output_xodr.resolve()
    report_json = report_json.resolve()
    if report_md is not None:
        report_md = report_md.resolve()
    if crash_safe_reference_xodr is not None:
        crash_safe_reference_xodr = crash_safe_reference_xodr.resolve()
    if merge_objects_from_xodr is not None:
        merge_objects_from_xodr = merge_objects_from_xodr.resolve()
    if preflight_report is not None:
        preflight_report = preflight_report.resolve()
    if loadability_baseline_summary is not None:
        loadability_baseline_summary = loadability_baseline_summary.resolve()

    before_tree = ET.parse(input_xodr)
    before_root = before_tree.getroot()
    before_counts = structural_counts(before_root)
    before_g19 = length_invariant_summary(before_root, tol=tol)

    tree = ET.parse(input_xodr)
    root = tree.getroot()
    repair = apply_c3_violation_length_repair(root, margin_m=margin_m, tol=tol)

    object_merge = None
    if merge_objects_from_xodr is not None:
        source_root = ET.parse(merge_objects_from_xodr).getroot()
        object_merge = merge_road_objects(root, source_root, tol=object_tol_m)

    output_xodr.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_xodr, encoding="utf-8", xml_declaration=True)

    after_root = ET.parse(output_xodr).getroot()
    after_counts = structural_counts(after_root)
    after_g19 = length_invariant_summary(after_root, tol=tol)
    validation = _offline_validation(output_xodr, after_root)
    length_audit = _length_change_audit(before_root, after_root, before_g19)

    safe_reference = None
    if crash_safe_reference_xodr is not None:
        safe_reference = _diagnose_xodr(crash_safe_reference_xodr)

    acceptance = _evaluate_acceptance(
        before_counts=before_counts,
        after_counts=after_counts,
        before_g19=before_g19,
        after_g19=after_g19,
        repair=repair,
        length_change_audit=length_audit,
        object_merge=object_merge,
        validation=validation,
        expected_roads=expected_roads,
        expected_junctions=expected_junctions,
        min_signals=min_signals,
        min_nonzero_elevation=min_nonzero_elevation,
    )

    report = {
        "schema": "E1_ELEVATION_MERGE/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_xodr": str(output_xodr),
        "output_sha256": sha256_file(output_xodr),
        "parents": {
            "elevated_parent": {
                "path": str(input_xodr),
                "sha256": sha256_file(input_xodr),
            }
        },
        "crash_safe_reference": safe_reference,
        "object_source": (
            {
                "path": str(merge_objects_from_xodr),
                "sha256": sha256_file(merge_objects_from_xodr),
            }
            if merge_objects_from_xodr is not None
            else None
        ),
        "repair_source": REPAIR_SOURCE,
        "repair": repair,
        "object_merge": object_merge,
        "before": {"counts": before_counts, "g19": before_g19},
        "after": {"counts": after_counts, "g19": after_g19},
        "length_change_audit": length_audit,
        "validation": validation,
        "preflight_xodr_loadability": _summarize_preflight_report(preflight_report),
        "inherited_loadability_baseline": _load_optional_json(loadability_baseline_summary),
        "acceptance": acceptance,
        "verdict": (
            "ELEVATED_SAFE_CANDIDATE_PRODUCED"
            if acceptance["pass"]
            else "ELEVATED_SAFE_CANDIDATE_REVIEW_REQUIRED"
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
        description="Apply the C3 violating-road-only length repair to an elevated XODR copy."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--report-md", type=Path)
    parser.add_argument("--crash-safe-reference", type=Path)
    parser.add_argument("--merge-objects-from", type=Path)
    parser.add_argument("--preflight-report", type=Path)
    parser.add_argument("--loadability-baseline-summary", type=Path)
    parser.add_argument("--margin-m", type=float, default=MARGIN_M)
    parser.add_argument("--tol-m", type=float, default=TOL_M)
    parser.add_argument("--object-tol-m", type=float, default=MARGIN_M)
    parser.add_argument("--expected-roads", type=int)
    parser.add_argument("--expected-junctions", type=int)
    parser.add_argument("--min-signals", type=int)
    parser.add_argument("--min-nonzero-elevation", type=int)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    report = repair_file(
        input_xodr=args.input,
        output_xodr=args.output,
        report_json=args.report,
        report_md=args.report_md,
        crash_safe_reference_xodr=args.crash_safe_reference,
        merge_objects_from_xodr=args.merge_objects_from,
        preflight_report=args.preflight_report,
        loadability_baseline_summary=args.loadability_baseline_summary,
        margin_m=args.margin_m,
        tol=args.tol_m,
        object_tol_m=args.object_tol_m,
        expected_roads=args.expected_roads,
        expected_junctions=args.expected_junctions,
        min_signals=args.min_signals,
        min_nonzero_elevation=args.min_nonzero_elevation,
    )
    print(f"verdict: {report['verdict']}")
    print(f"output_sha256: {report['output_sha256']}")
    print(f"violations_before: {report['before']['g19']['violations']}")
    print(f"violations_after: {report['after']['g19']['violations']}")
    print(f"roads_length_adjusted: {report['repair']['roads_length_adjusted']}")
    if report.get("object_merge") is not None:
        print(f"objects_merged: {report['object_merge']['merged']}")
    print(f"report: {args.report}")
    return 0 if report["verdict"] == "ELEVATED_SAFE_CANDIDATE_PRODUCED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
