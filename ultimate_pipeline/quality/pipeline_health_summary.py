# ultimate_pipeline/quality/pipeline_health_summary.py
# -*- coding: utf-8 -*-

"""
Pipeline health summary generator.

Aggregates quality gate outputs and run metadata into a single JSON report.
Best-effort: missing or malformed files never crash the pipeline.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Tuple


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: str) -> Optional[Dict[str, Any]]:
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else None
    except Exception:
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _report_status(report: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(report, dict):
        return True, "unknown"
    if "ok" in report:
        ok = bool(report.get("ok"))
        return ok, "pass" if ok else "fail"
    status = str(report.get("status", "")).strip().lower()
    if status in {"fail", "failed", "error"}:
        return False, status
    if status in {"skip", "skipped", "skipped_by_env"}:
        return True, "skipped"
    if _safe_int(report.get("n_errors", 0)) > 0:
        return False, "fail"
    return True, "pass"


def _extract_issue_counts(report: Dict[str, Any]) -> Dict[str, int]:
    counts = {"issues": 0, "errors": 0, "warnings": 0}
    if not isinstance(report, dict):
        return counts

    num_issues = report.get("num_issues", report.get("n_issues"))
    failures = report.get("failures", report.get("n_errors", report.get("num_errors")))
    warnings = report.get("warnings", report.get("n_warnings"))

    if isinstance(num_issues, list):
        num_issues = len(num_issues)
    if isinstance(failures, list):
        failures = len(failures)
    if isinstance(warnings, list):
        warnings = len(warnings)

    if num_issues is None and isinstance(report.get("issues"), list):
        num_issues = len(report.get("issues"))

    counts["errors"] = _safe_int(failures, 0)
    counts["warnings"] = _safe_int(warnings, 0)

    if num_issues is None:
        num_issues = counts["errors"] + counts["warnings"]

    counts["issues"] = _safe_int(num_issues, 0)

    ok, _ = _report_status(report)
    if not ok and counts["errors"] == 0:
        counts["errors"] = 1
        if counts["issues"] == 0:
            counts["issues"] = 1

    return counts


def _collect_tolerances(report: Dict[str, Any]) -> Dict[str, Any]:
    tolerances: Dict[str, Any] = {}
    if not isinstance(report, dict):
        return tolerances

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                key_l = str(key).lower()
                if isinstance(value, (int, float)) and ("eps" in key_l or "tolerance" in key_l):
                    tolerances[str(key)] = value
                if key_l == "tolerances" and isinstance(value, dict):
                    for t_key, t_val in value.items():
                        if isinstance(t_val, (int, float)):
                            tolerances[str(t_key)] = t_val
                _walk(value)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(report)
    return tolerances


def _merge_gate_entry(
    gates: Dict[str, Dict[str, Any]],
    name: str,
    report: Dict[str, Any],
    source: str,
) -> None:
    ok, status = _report_status(report)
    counts = _extract_issue_counts(report)

    existing = gates.get(name)
    if not existing:
        gates[name] = {
            "ok": ok,
            "status": status,
            "issues": counts["issues"],
            "errors": counts["errors"],
            "warnings": counts["warnings"],
            "sources": [source],
        }
        return

    existing["ok"] = bool(existing.get("ok", True) and ok)
    if existing.get("status") == "pass" and status != "pass":
        existing["status"] = status
    existing["issues"] = max(_safe_int(existing.get("issues", 0)), counts["issues"])
    existing["errors"] = max(_safe_int(existing.get("errors", 0)), counts["errors"])
    existing["warnings"] = max(_safe_int(existing.get("warnings", 0)), counts["warnings"])
    sources = existing.get("sources", [])
    if source not in sources:
        sources.append(source)
    existing["sources"] = sources


def _parse_stage_gate(filename: str) -> Tuple[str, str]:
    stem = os.path.splitext(os.path.basename(filename))[0]
    if "__" in stem:
        stage, gate = stem.split("__", 1)
        return stage or "unknown", gate or stem
    return "unknown", stem


def _first_string_value(data: Dict[str, Any], keys: Iterable[str]) -> Optional[str]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_bbox(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(data, dict):
        return None
    for key in ("gps_bounds_wgs84", "gps_bounds", "bbox", "bounds"):
        value = data.get(key)
        if isinstance(value, dict):
            keys = {"lat_min", "lat_max", "lon_min", "lon_max"}
            if keys.issubset(value.keys()):
                return value
    return None


def build_pipeline_health_summary(
    out_dir: str,
    stage_reports_dir: str | None = None,
    expected_gates: Iterable[str] | None = None,
) -> Dict[str, Any]:
    """Aggregate gate evidence for one run.

    ``expected_gates`` is the registry-derived list of gates a complete run is
    contractually supposed to have produced evidence for (NEW-335).  When it is
    provided, an expected gate with *no* evidence is reported as missing/skipped
    and makes the summary fail: "the gate never ran" must never be silently
    equivalent to "the gate passed".  When it is ``None`` (legacy callers and
    the module's own CLI) behaviour is unchanged: only observed evidence is
    scored, and ``not_run_gates`` stays empty.
    """
    summary: Dict[str, Any] = {
        "generated_at_utc": _utc_now(),
        "out_dir": out_dir,
        "overall_ok": False,
        "status": "NOT_RUN",
        "evidence_complete": False,
        "expected_gates": [],
        "required_gates": [],
        "passed_gates": [],
        "not_run_gates": [],
        "missing_required_gates": [],
        "skipped_required_gates": [],
        "malformed_gates": [],
        "gates": {},
        "per_stage_failures": {},
        "malformed_gate_reports": [],
        "tolerances": {},
        "run_metadata": {
            "map_name": None,
            "bbox": None,
            "roads": None,
            "junctions": None,
        },
    }
    expected: list[str] = sorted({str(g).strip() for g in (expected_gates or []) if str(g).strip()})
    summary["expected_gates"] = list(expected)

    try:
        stage_dir = stage_reports_dir or os.path.join(out_dir, "qa_stage_reports")
        if os.path.isdir(stage_dir):
            for fname in os.listdir(stage_dir):
                if not fname.endswith(".json"):
                    continue
                path = os.path.join(stage_dir, fname)
                report = _load_json(path)
                if not report:
                    # The file was enumerated by listdir(), so it definitely
                    # exists -- this is unambiguously a malformed/unparseable
                    # report (e.g. a stage that crashed mid-write), not a
                    # gate that simply never applied to this run. Flag it
                    # explicitly so it can't be silently indistinguishable
                    # from "nothing to report here".
                    stage, gate = _parse_stage_gate(fname)
                    summary["malformed_gate_reports"].append(f"{stage}/{gate}")
                    continue
                stage, gate = _parse_stage_gate(fname)
                _merge_gate_entry(summary["gates"], gate, report, f"stage:{stage}")
                ok, _ = _report_status(report)
                if not ok:
                    summary["per_stage_failures"].setdefault(stage, []).append(gate)
                tolerances = _collect_tolerances(report)
                if tolerances:
                    summary["tolerances"].setdefault(gate, {}).update(tolerances)
    except Exception:
        pass

    try:
        artifact_files = [
            # main_pipeline writes this one at the release root (via
            # _run_geometric_continuity_gate); there is no geometric_continuity.json.
            "geometric_continuity_gate.json",
            "elevation_continuity.json",
            "post_tiling_integrity.json",
            "lane_width_continuity.json",
            "lane_geometry_continuity.json",
            "dem_coverage.json",
            "lane_link_check.json",
            "carla_compat_report.json",
            "strict_xodr_validation.json",
            "strict_xodr_report.json",
        ]
        for fname in artifact_files:
            path = os.path.join(out_dir, fname)
            report = _load_json(path)
            if not report:
                continue
            gate = os.path.splitext(fname)[0]
            _merge_gate_entry(summary["gates"], gate, report, "artifact")
            tolerances = _collect_tolerances(report)
            if tolerances:
                summary["tolerances"].setdefault(gate, {}).update(tolerances)
    except Exception:
        pass

    try:
        # No gate evidence at all (no qa_stage_reports/ dir, no optional
        # artifact files, and no malformed-but-present reports either) is a
        # DIFFERENT condition from "every gate ran and passed" -- it means
        # this summary was built against an incomplete/absent run, and must
        # never be reported as a clean overall_ok=True pass.
        evidence_complete = bool(summary["gates"]) or bool(summary["malformed_gate_reports"])
        summary["evidence_complete"] = evidence_complete
        summary["required_gates"] = sorted(summary["gates"].keys())
        summary["passed_gates"] = sorted(
            name for name, data in summary["gates"].items() if data.get("ok", True)
        )
        summary["malformed_gates"] = sorted(summary["malformed_gate_reports"])

        # NEW-335: diff what was EXPECTED against what was OBSERVED, so an
        # expected gate that never produced evidence is a reported failure
        # rather than an invisible absence.
        missing: list[str] = []
        skipped: list[str] = []
        not_run: list[str] = []
        for name in expected:
            observed = summary["gates"].get(name)
            if observed is None:
                missing.append(name)
                not_run.append(name)
                continue
            status = str(observed.get("status", "")).strip().lower()
            if observed.get("ok", True) and status in {"skip", "skipped", "skipped_by_env"}:
                skipped.append(name)
        summary["missing_required_gates"] = missing
        summary["skipped_required_gates"] = skipped
        # Without an expected list there is nothing to diff against; keep the
        # field explicit (rather than omitted) for schema stability.
        summary["not_run_gates"] = not_run if expected else []

        if not evidence_complete:
            summary["overall_ok"] = False
            summary["status"] = "NOT_RUN"
        else:
            overall_ok = not summary["malformed_gate_reports"]
            for gate_data in summary["gates"].values():
                if not gate_data.get("ok", True):
                    overall_ok = False
                    break
            if expected and (missing or skipped):
                # An expected gate that did not run (or reported a skip) makes
                # the run incomplete, not merely "not observed".
                overall_ok = False
            summary["overall_ok"] = overall_ok
            summary["status"] = "PASS" if overall_ok else "FAIL"
    except Exception:
        summary["overall_ok"] = False
        summary["status"] = "NOT_RUN"
        summary["evidence_complete"] = False

    try:
        map_stats = _load_json(os.path.join(out_dir, "map_statistics.json")) or {}
        roads = map_stats.get("roads", {}).get("count")
        junctions = map_stats.get("junctions", {}).get("count")
        if roads is not None:
            summary["run_metadata"]["roads"] = roads
        if junctions is not None:
            summary["run_metadata"]["junctions"] = junctions
    except Exception:
        pass

    try:
        run_manifest = _load_json(os.path.join(out_dir, "run_manifest.json")) or {}
        bbox = _extract_bbox(run_manifest)
        if bbox:
            summary["run_metadata"]["bbox"] = bbox
    except Exception:
        pass

    try:
        settings_snapshot = _load_json(os.path.join(out_dir, "settings_snapshot.json")) or {}
        map_name = _first_string_value(
            settings_snapshot,
            ("MAP_NAME", "CARLA_MAP", "CITY_NAME", "UP_CITY", "map_name", "city"),
        )
        if map_name:
            summary["run_metadata"]["map_name"] = map_name
    except Exception:
        pass

    try:
        logs_report = _load_json(os.path.join(out_dir, "logs", "validation_report_full.json")) or {}
        if not summary["run_metadata"]["map_name"]:
            map_name = _first_string_value(logs_report, ("map_name", "map", "town", "city"))
            if map_name:
                summary["run_metadata"]["map_name"] = map_name
        if summary["run_metadata"]["bbox"] is None:
            bbox = _extract_bbox(logs_report)
            if bbox:
                summary["run_metadata"]["bbox"] = bbox
    except Exception:
        pass

    try:
        dem_report = _load_json(os.path.join(out_dir, "dem_coverage.json")) or {}
        if "valid_ratio" in dem_report:
            summary["run_metadata"]["dem_coverage_ratio"] = dem_report.get("valid_ratio")
    except Exception:
        pass

    try:
        seam_report = _load_json(os.path.join(out_dir, "elevation_seam_report.json")) or {}
        seam_stats = seam_report.get("seam_stats") if isinstance(seam_report, dict) else None
        elev_stats = seam_report.get("elevation_stats") if isinstance(seam_report, dict) else None
        if isinstance(seam_stats, dict):
            summary["run_metadata"]["seam_stats"] = seam_stats
        if isinstance(elev_stats, dict):
            summary["run_metadata"]["elevation_z_min"] = elev_stats.get("z_min")
            summary["run_metadata"]["elevation_z_max"] = elev_stats.get("z_max")
            summary["run_metadata"]["elevation_z_range"] = elev_stats.get("z_range")
    except Exception:
        pass

    try:
        quarantine = _load_json(os.path.join(out_dir, "roads_quarantined.json"))
        if quarantine:
            summary["run_metadata"]["roads_quarantined"] = quarantine
    except Exception:
        pass

    return summary


def write_pipeline_health_summary(
    out_dir: str,
    stage_reports_dir: str | None = None,
    expected_gates: Iterable[str] | None = None,
) -> str:
    """Durably write ``pipeline_health_summary.json``.

    Fail-closed (NEW-335): this artifact is a HARD_GATE signal consumed by the
    final run verdict, so a write failure must abort the run rather than leave
    the signal silently absent.
    """
    summary = build_pipeline_health_summary(
        out_dir, stage_reports_dir=stage_reports_dir, expected_gates=expected_gates
    )
    output_path = os.path.join(out_dir, "pipeline_health_summary.json")
    os.makedirs(out_dir, exist_ok=True)
    text = json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=True)
    if not text.endswith("\n"):
        text += "\n"
    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    return output_path


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Build pipeline health summary")
    ap.add_argument("out_dir", help="Pipeline output directory")
    ap.add_argument("--stage-reports-dir", default=None, help="Optional stage reports directory")
    args = ap.parse_args()

    result = build_pipeline_health_summary(args.out_dir, stage_reports_dir=args.stage_reports_dir)
    print(json.dumps(result, indent=2, ensure_ascii=True))
