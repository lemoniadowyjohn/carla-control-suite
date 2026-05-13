#!/usr/bin/env python3
"""Final-map readiness gate for generated OpenDRIVE artifacts.

This tool is intentionally CARLA-free. It consolidates the static XODR check,
junction connector rebuild report, optional CARLA visual smoke report, optional
perception status, and signal/object counts into one conservative readiness
verdict.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ultimate_pipeline.tools.carla_visual_smoke_gate import evaluate_visual_smoke_report
from ultimate_pipeline.tools.verify_final_xodr import verify_final_xodr
from ultimate_pipeline.utils.file_hashing import safe_sha256_file


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True)
    path.write_text(text + ("\n" if not text.endswith("\n") else ""), encoding="utf-8")


def _load_json(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if path is None or not Path(path).exists():
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except Exception:
        return int(default)


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("1", "true", "yes", "on", "y")


def _first_int(data: Dict[str, Any], names: Tuple[str, ...]) -> Optional[int]:
    for name in names:
        if name in data and data.get(name) is not None:
            return _safe_int(data.get(name))
    return None


def _default_connector_report(xodr_path: Path) -> Optional[Path]:
    candidates = [
        xodr_path.with_name(f"{xodr_path.stem}_rebuild_report.json"),
        xodr_path.parent / "junction_connector_rebuild_report.json",
        xodr_path.parent / "junction_connector_risk.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _default_visual_gate_report(xodr_path: Path) -> Optional[Path]:
    candidates = [
        xodr_path.parent / "carla_visual_smoke_gate.json",
        xodr_path.parent / "final_visual_smoke" / "carla_visual_smoke_gate.json",
        xodr_path.parent / "carla_visual_smoke" / "carla_visual_smoke_gate.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _signal_object_counts(xodr_path: Path) -> Dict[str, Any]:
    payload = {
        "signals_total": 0,
        "objects_total": 0,
        "traffic_light_objects": 0,
        "traffic_sign_objects": 0,
        "parse_error": "",
    }
    try:
        root = ET.parse(xodr_path).getroot()
    except Exception as exc:
        payload["parse_error"] = str(exc)
        return payload

    signals = root.findall(".//signal")
    objects = root.findall(".//object")
    payload["signals_total"] = len(signals)
    payload["objects_total"] = len(objects)
    for obj in objects:
        obj_type = str(obj.get("type") or obj.get("name") or "").strip().lower()
        if "traffic_light" in obj_type or "trafficlight" in obj_type:
            payload["traffic_light_objects"] += 1
        if "traffic_sign" in obj_type or obj_type in {"stop", "giveway", "give_way"}:
            payload["traffic_sign_objects"] += 1
    return payload


def evaluate_connector_report(
    report: Optional[Dict[str, Any]],
    *,
    xodr_path: Path,
    max_start_mismatch: int = 100,
    max_end_mismatch: int = 200,
) -> Dict[str, Any]:
    if not report:
        return {
            "ok": False,
            "status": "missing",
            "reason": "connector_report_missing",
            "start_mismatch_after": None,
            "end_mismatch_after": None,
        }

    start_before = _first_int(
        report,
        (
            "connector_start_mismatch_before",
            "start_gap_over_threshold_before",
            "start_mismatch_before",
        ),
    )
    start_after = _first_int(
        report,
        (
            "connector_start_mismatch_after",
            "start_gap_over_threshold_after",
            "start_mismatch_after",
        ),
    )
    end_before = _first_int(
        report,
        (
            "connector_end_mismatch_before",
            "end_gap_over_tolerance_before",
            "end_mismatch_before",
        ),
    )
    end_after = _first_int(
        report,
        (
            "connector_end_mismatch_after",
            "end_gap_over_tolerance_after",
            "end_mismatch_after",
        ),
    )
    lt1_before = _first_int(report, ("connectors_lt_1m_before", "lt_1m_before"))
    lt1_after = _first_int(report, ("connectors_lt_1m_after", "lt_1m_after"))

    issues: List[str] = []
    if start_after is None:
        issues.append("start_mismatch_after_missing")
    elif start_after >= int(max_start_mismatch):
        issues.append(f"start_mismatch_after_ge_{max_start_mismatch}")
    if end_after is None:
        issues.append("end_mismatch_after_missing")
    elif end_after >= int(max_end_mismatch):
        issues.append(f"end_mismatch_after_ge_{max_end_mismatch}")
    if lt1_before is not None and lt1_after is not None and lt1_after > lt1_before:
        issues.append("lt_1m_connectors_increased")
    if report.get("fix_effective") is False:
        issues.append("fix_effective_false")
    if start_before is not None and start_after is not None and start_after >= start_before:
        issues.append("start_mismatch_not_improved")

    sha_issue = ""
    output_sha = str(report.get("output_sha256") or "").strip().lower()
    if len(output_sha) == 64 and xodr_path.exists():
        actual_sha = safe_sha256_file(xodr_path).lower()
        if output_sha != actual_sha:
            sha_issue = "output_sha256_mismatch"
            issues.append(sha_issue)

    explicit_ok = report.get("ok")
    if explicit_ok is False and (start_after is None or end_after is None):
        # Risk reports may be stricter than this final threshold gate. Only let an
        # explicit false fail the gate when no threshold metrics are available.
        issues.append("connector_report_explicit_ok_false")

    return {
        "ok": not issues,
        "status": "pass" if not issues else "fail",
        "reason": ";".join(issues),
        "start_mismatch_before": start_before,
        "start_mismatch_after": start_after,
        "end_mismatch_before": end_before,
        "end_mismatch_after": end_after,
        "connectors_lt_1m_before": lt1_before,
        "connectors_lt_1m_after": lt1_after,
        "sha_issue": sha_issue,
        "connector_report_explicit_ok": explicit_ok,
    }


def evaluate_visual_gate_report(report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not report:
        return {
            "ok": False,
            "status": "missing",
            "reason": "carla_visual_smoke_gate_missing",
        }
    evaluation = evaluate_visual_smoke_report(report, require_files=False)
    return {
        "ok": bool(evaluation.get("ok", False)),
        "status": "pass" if bool(evaluation.get("ok", False)) else "fail",
        "reason": str(evaluation.get("reason") or ""),
        "CARLA_VISUAL_READY": "yes" if bool(evaluation.get("ok", False)) else "no",
        "PERCEPTION_EVIDENCE_ALLOWED": bool(evaluation.get("ok", False)),
        "required_views": evaluation.get("required_views", []),
        "missing_views": evaluation.get("missing_views", []),
        "failed_views": evaluation.get("failed_views", []),
    }


def evaluate_perception_status(
    report: Optional[Dict[str, Any]],
    *,
    visual_ok: bool,
    min_frames: int = 1,
) -> Dict[str, Any]:
    if not visual_ok:
        return {
            "ok": False,
            "status": "blocked",
            "reason": "blocked_until_carla_visual_smoke_gate_passes",
            "frames_recorded": 0,
        }
    if not report:
        return {
            "ok": False,
            "status": "missing",
            "reason": "perception_status_missing",
            "frames_recorded": 0,
        }

    frames = _safe_int(
        report.get("frames_recorded", report.get("rgb_frames", report.get("frames", 0)))
    )
    ok = _safe_bool(report.get("ok", report.get("success", False))) and frames >= int(min_frames)
    reason = ""
    if not _safe_bool(report.get("ok", report.get("success", False))):
        reason = str(report.get("failure_reason") or "perception_status_not_ok")
    elif frames < int(min_frames):
        reason = f"frames_recorded_lt_{int(min_frames)}"
    return {
        "ok": ok,
        "status": "pass" if ok else "fail",
        "reason": reason,
        "frames_recorded": frames,
    }


def build_final_map_readiness_report(
    *,
    xodr_path: Path,
    connector_report_path: Optional[Path] = None,
    visual_gate_report_path: Optional[Path] = None,
    perception_status_path: Optional[Path] = None,
    report_path: Optional[Path] = None,
    max_start_mismatch: int = 100,
    max_end_mismatch: int = 200,
    min_perception_frames: int = 1,
    require_visual: bool = True,
    require_perception: bool = False,
    require_signals: bool = False,
) -> Dict[str, Any]:
    xodr_path = Path(xodr_path)
    if connector_report_path is None:
        connector_report_path = _default_connector_report(xodr_path)
    if visual_gate_report_path is None:
        visual_gate_report_path = _default_visual_gate_report(xodr_path)
    if report_path is None:
        report_path = xodr_path.with_name("final_map_readiness_report.json")

    verify_report_path = report_path.with_name("verify_final_xodr_report.json")
    static_report = verify_final_xodr(xodr_path, verify_report_path)
    connector_report = _load_json(connector_report_path)
    visual_report = _load_json(visual_gate_report_path)
    perception_report = _load_json(perception_status_path)

    connector_gate = evaluate_connector_report(
        connector_report,
        xodr_path=xodr_path,
        max_start_mismatch=max_start_mismatch,
        max_end_mismatch=max_end_mismatch,
    )
    visual_gate = evaluate_visual_gate_report(visual_report)
    perception_gate = evaluate_perception_status(
        perception_report,
        visual_ok=bool(visual_gate.get("ok", False)),
        min_frames=int(min_perception_frames),
    )
    signal_counts = _signal_object_counts(xodr_path)
    signal_gate_ok = True
    signal_reason = ""
    if bool(require_signals):
        signal_gate_ok = bool(
            int(signal_counts.get("signals_total", 0)) > 0
            or int(signal_counts.get("traffic_light_objects", 0)) > 0
            or int(signal_counts.get("traffic_sign_objects", 0)) > 0
        )
        if not signal_gate_ok:
            signal_reason = "no_signal_or_traffic_object_records"

    offline_ok = bool(static_report.get("ok", False)) and bool(connector_gate.get("ok", False))
    visual_ok_for_overall = bool(visual_gate.get("ok", False)) if require_visual else True
    perception_ok_for_overall = (
        bool(perception_gate.get("ok", False)) if require_perception else True
    )
    ok = bool(offline_ok and visual_ok_for_overall and perception_ok_for_overall and signal_gate_ok)

    report = {
        "schema": "final_map_readiness_gate_v1",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "xodr_path": str(xodr_path),
        "xodr_sha256": safe_sha256_file(xodr_path) if xodr_path.exists() else "",
        "ok": ok,
        "XODR_PARSE_READY": "yes" if static_report.get("parse_error") is None else "no",
        "STRUCTURAL_ANALYSIS_READY": "yes" if offline_ok else "no",
        "CARLA_VISUAL_READY": "yes" if bool(visual_gate.get("ok", False)) else "no",
        "PERCEPTION_READY": "yes" if bool(perception_gate.get("ok", False)) else "no",
        "perception_evidence_gate": {
            "allowed": bool(visual_gate.get("ok", False)),
            "reason": "" if bool(visual_gate.get("ok", False)) else "blocked_until_carla_visual_smoke_gate_passes",
        },
        "static_xodr_report": static_report,
        "connector_report_path": str(connector_report_path or ""),
        "connector_gate": connector_gate,
        "visual_gate_report_path": str(visual_gate_report_path or ""),
        "visual_gate": visual_gate,
        "perception_status_path": str(perception_status_path or ""),
        "perception_gate": perception_gate,
        "signal_object_counts": signal_counts,
        "signal_gate": {
            "required": bool(require_signals),
            "ok": bool(signal_gate_ok),
            "reason": signal_reason,
        },
        "requirements": {
            "max_start_mismatch": int(max_start_mismatch),
            "max_end_mismatch": int(max_end_mismatch),
            "min_perception_frames": int(min_perception_frames),
            "require_visual": bool(require_visual),
            "require_perception": bool(require_perception),
            "require_signals": bool(require_signals),
        },
    }
    _write_json(report_path, report)
    report["report_path"] = str(report_path)
    return report


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Conservative final-map readiness gate for generated XODR artifacts."
    )
    parser.add_argument("--xodr", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None, help="Output readiness JSON path")
    parser.add_argument("--connector-report", type=Path, default=None)
    parser.add_argument("--visual-gate-report", type=Path, default=None)
    parser.add_argument("--perception-status", type=Path, default=None)
    parser.add_argument("--max-start-mismatch", type=int, default=100)
    parser.add_argument("--max-end-mismatch", type=int, default=200)
    parser.add_argument("--min-perception-frames", type=int, default=1)
    parser.add_argument(
        "--allow-missing-visual-gate",
        action="store_true",
        help="Do not fail the overall readiness verdict when the CARLA visual gate is missing.",
    )
    parser.add_argument(
        "--require-perception",
        action="store_true",
        help="Require perception_status.json to pass after visual QA.",
    )
    parser.add_argument(
        "--require-signals",
        action="store_true",
        help="Require at least one OpenDRIVE signal or traffic object record.",
    )
    return parser.parse_args(sys.argv[1:] if argv is None else argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    report = build_final_map_readiness_report(
        xodr_path=args.xodr,
        connector_report_path=args.connector_report,
        visual_gate_report_path=args.visual_gate_report,
        perception_status_path=args.perception_status,
        report_path=args.out,
        max_start_mismatch=args.max_start_mismatch,
        max_end_mismatch=args.max_end_mismatch,
        min_perception_frames=args.min_perception_frames,
        require_visual=not bool(args.allow_missing_visual_gate),
        require_perception=bool(args.require_perception),
        require_signals=bool(args.require_signals),
    )
    print(
        "[final_map_readiness_gate] "
        f"ok={report['ok']} "
        f"STRUCTURAL_ANALYSIS_READY={report['STRUCTURAL_ANALYSIS_READY']} "
        f"CARLA_VISUAL_READY={report['CARLA_VISUAL_READY']} "
        f"PERCEPTION_READY={report['PERCEPTION_READY']} "
        f"report={report['report_path']}"
    )
    return 0 if bool(report.get("ok", False)) else 2


if __name__ == "__main__":
    raise SystemExit(main())
