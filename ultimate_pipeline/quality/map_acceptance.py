#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Map acceptance summary for gating perception runs.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from ultimate_pipeline.utils.file_hashing import safe_sha256_file


def _run_id_from_out_dir(out_dir: Optional[str]) -> Optional[str]:
    if not out_dir:
        return None
    base = os.path.basename(os.path.normpath(out_dir))
    return base or None


def _artifact_path_from_report(report: Dict[str, Any]) -> Optional[str]:
    for key in ("artifact_path", "report_path", "path", "output"):
        value = report.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _reason_from_report(report: Dict[str, Any]) -> str:
    for key in ("reason", "error", "message"):
        value = report.get(key)
        if isinstance(value, str) and value:
            return value
    decision = report.get("decision")
    if isinstance(decision, dict):
        value = decision.get("reason")
        if isinstance(value, str) and value:
            return value
    if "issues" in report:
        return f"issues={len(report.get('issues') or [])}"
    if "failures" in report:
        return f"failures={len(report.get('failures') or [])}"
    if "still_broken_count" in report:
        return f"still_broken_count={report.get('still_broken_count')}"
    if "broken_count" in report:
        return f"broken_count={report.get('broken_count')}"
    return "gate_failed"


def _determine_report_ok(report: Dict[str, Any]) -> Optional[bool]:
    if "ok" in report:
        return bool(report.get("ok"))
    decision = report.get("decision")
    if isinstance(decision, dict) and "pass" in decision:
        return bool(decision.get("pass"))
    return None


def _determine_lane_ok(report: Dict[str, Any]) -> Optional[bool]:
    if "ok" in report:
        return bool(report.get("ok"))
    if "still_broken_count" in report:
        return int(report.get("still_broken_count") or 0) == 0
    if "broken_count" in report:
        return int(report.get("broken_count") or 0) == 0
    if "num_issues" in report:
        return int(report.get("num_issues") or 0) == 0
    if "failures" in report:
        return len(report.get("failures") or []) == 0
    return None


def _lane_missing_count(report: Dict[str, Any]) -> Optional[int]:
    if "still_broken_count" in report:
        return int(report.get("still_broken_count") or 0)
    if "broken_count" in report:
        return int(report.get("broken_count") or 0)
    if "num_issues" in report:
        return int(report.get("num_issues") or 0)
    if "failures" in report:
        return len(report.get("failures") or [])
    return None


def _write_acceptance(out_dir: Optional[str], run_id: Optional[str], payload: Dict[str, Any]) -> Optional[str]:
    if not out_dir or not run_id:
        return None
    try:
        art_dir = os.path.join(out_dir, "artifacts", run_id)
        os.makedirs(art_dir, exist_ok=True)
        path = os.path.join(art_dir, "map_acceptance.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True, ensure_ascii=True)
        return path
    except Exception:
        return None


def build_map_acceptance(
    reports: Dict[str, Any],
    *,
    run_id: str | None = None,
    final_xodr_path: str | None = None,
    out_dir: str | None = None,
) -> Dict[str, Any]:
    hard_fail_reasons: List[Dict[str, str]] = []
    soft_warnings: List[Dict[str, str]] = []
    metrics: Dict[str, Any] = {}
    linked_artifacts: Dict[str, str] = {}

    if not run_id:
        run_id = _run_id_from_out_dir(out_dir)

    final_xodr_sha256 = None
    if final_xodr_path and os.path.exists(final_xodr_path):
        final_xodr_sha256 = safe_sha256_file(final_xodr_path)

    seam = reports.get("elevation_seams")
    if isinstance(seam, dict):
        metrics["seam_stats"] = seam.get("seam_stats")
        metrics["elevation_stats"] = seam.get("elevation_stats")
        art = _artifact_path_from_report(seam)
        if art:
            linked_artifacts["elevation_seams"] = art
        if seam.get("ok") is False:
            hard_fail_reasons.append({"gate": "elevation_seams", "reason": _reason_from_report(seam)})

    dem = reports.get("dem_coverage")
    if isinstance(dem, dict):
        metrics["dem_coverage_ratio"] = dem.get("valid_ratio")
        art = _artifact_path_from_report(dem)
        if art:
            linked_artifacts["dem_coverage"] = art
        if dem.get("ok") is False:
            hard_fail_reasons.append({"gate": "dem_coverage", "reason": _reason_from_report(dem)})

    geom = reports.get("geometric_continuity")
    if isinstance(geom, dict):
        geom_ok = _determine_report_ok(geom)
        metrics["geometric_continuity_ok"] = geom_ok
        art = _artifact_path_from_report(geom)
        if art:
            linked_artifacts["geometric_continuity"] = art
        if geom_ok is False:
            hard_fail_reasons.append({"gate": "geometric_continuity", "reason": _reason_from_report(geom)})

    lane_section = reports.get("lane_section_successors")
    if isinstance(lane_section, dict):
        lane_ok = _determine_lane_ok(lane_section)
        metrics["lane_ok"] = lane_ok
        missing = _lane_missing_count(lane_section)
        if missing is not None:
            metrics["lane_successor_missing_count"] = missing
        art = _artifact_path_from_report(lane_section)
        if art:
            linked_artifacts["lane_section_successors"] = art
        if lane_ok is False:
            hard_fail_reasons.append({"gate": "lane_section_successors", "reason": _reason_from_report(lane_section)})

    lane_conn = reports.get("lane_connectivity")
    if isinstance(lane_conn, dict):
        lane_ok = _determine_lane_ok(lane_conn)
        metrics["lane_ok"] = lane_ok if metrics.get("lane_ok") is None else metrics.get("lane_ok")
        missing = _lane_missing_count(lane_conn)
        if missing is not None and "lane_successor_missing_count" not in metrics:
            metrics["lane_successor_missing_count"] = missing
        art = _artifact_path_from_report(lane_conn)
        if art:
            linked_artifacts["lane_connectivity"] = art
        if lane_ok is False:
            hard_fail_reasons.append({"gate": "lane_connectivity", "reason": _reason_from_report(lane_conn)})

    origin = reports.get("origin_sanity")
    if isinstance(origin, dict):
        dist = origin.get("centroid_distance_m")
        metrics["origin_centroid_distance_m"] = dist
        art = _artifact_path_from_report(origin)
        if art:
            linked_artifacts["origin_sanity"] = art
        if origin.get("ok") is False:
            if isinstance(dist, (int, float)) and dist > 500_000.0:
                hard_fail_reasons.append({"gate": "origin_sanity", "reason": _reason_from_report(origin)})
            else:
                soft_warnings.append({"gate": "origin_sanity", "reason": _reason_from_report(origin)})

    valid_for_experiments = len(hard_fail_reasons) == 0
    payload = {
        "run_id": run_id,
        "final_xodr_path": final_xodr_path,
        "final_xodr_sha256": final_xodr_sha256,
        "valid_for_experiments": valid_for_experiments,
        "hard_fail_reasons": hard_fail_reasons,
        "soft_warnings": soft_warnings,
        "metrics": metrics,
        "linked_artifacts": linked_artifacts,
    }
    payload["valid"] = valid_for_experiments
    payload["failed_gates"] = [item["gate"] for item in hard_fail_reasons]

    artifact_path = _write_acceptance(out_dir, run_id, payload)
    if artifact_path:
        payload["acceptance_artifact"] = artifact_path

    return payload
