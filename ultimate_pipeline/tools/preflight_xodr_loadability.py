#!/usr/bin/env python3
"""
Lightweight preflight for OpenDRIVE loadability.

Parses an XODR file, runs the strict validator (covers laneSection s / center lane checks),
the CARLA compatibility gate, and the laneSection successor scan so dangling successors
are reported before engaging CARLA. Report includes all errors/warnings with counts.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import xml.etree.ElementTree as ET

try:
    from ultimate_pipeline.quality.check_carla_opendrive_compat import StrictCarlaOpendriveGate
except ImportError:  # pragma: no cover - best effort when module absent
    StrictCarlaOpendriveGate = None  # type: ignore[assignment]
try:
    from ultimate_pipeline.quality.check_lane_section_successors import repair_and_assert_lane_section_successors
except ImportError:  # pragma: no cover
    repair_and_assert_lane_section_successors = None  # type: ignore[assignment]
try:
    from ultimate_pipeline.quality.xodr_strict_validator import StrictXodrValidator
except ImportError:  # pragma: no cover
    StrictXodrValidator = None  # type: ignore[assignment]


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Preflight OpenDRIVE loadability with existing validators.")
    ap.add_argument("--xodr", type=Path, required=True, help="Input OpenDRIVE (*.xodr)")
    ap.add_argument("--out", type=Path, required=True, help="Output directory for preflight_report.json")
    return ap.parse_args()


def _parse_xodr(path: Path) -> tuple[Optional[ET.Element], Optional[str]]:
    try:
        tree = ET.parse(path)
        return tree.getroot(), None
    except Exception as exc:  # pragma: no cover - parse errors are reported
        return None, str(exc)


def _run_strict_validator(root: ET.Element) -> Dict[str, Any]:
    if StrictXodrValidator is None:
        return {"available": False, "note": "StrictXodrValidator module missing."}
    try:
        validator = StrictXodrValidator()
        issues = validator.validate_root(root)
        return {"available": True, "report": validator._report(issues)}
    except Exception as exc:
        return {"available": True, "error": str(exc)}


def _run_carla_gate(root: ET.Element) -> Dict[str, Any]:
    if StrictCarlaOpendriveGate is None:
        return {"available": False, "note": "StrictCarlaOpendriveGate module missing."}
    try:
        issues = StrictCarlaOpendriveGate.validate(root)
        stats = {"errors": sum(1 for i in issues if i.get("severity") == "error"),
                 "warnings": sum(1 for i in issues if i.get("severity") == "warn")}
        return {"available": True, "issues": issues, "stats": stats}
    except Exception as exc:
        return {"available": True, "error": str(exc)}


def _run_successor_scan(xodr_path: Path) -> Dict[str, Any]:
    if repair_and_assert_lane_section_successors is None:
        return {"available": False, "note": "Lane section successor scan module missing."}
    try:
        report = repair_and_assert_lane_section_successors(str(xodr_path), strict=False)
        return {"available": True, "report": report}
    except Exception as exc:
        return {"available": True, "error": str(exc)}


def _attach_issues(module: str, issues: Iterable[Dict[str, Any]], errors: List[Dict[str, Any]], warnings: List[Dict[str, Any]]) -> None:
    for issue in issues:
        entry = {"module": module, **issue}
        severity = issue.get("severity", "error")
        if severity == "error":
            errors.append(entry)
        else:
            warnings.append(entry)


def _summarize_successor_failures(report: Dict[str, Any], errors: List[Dict[str, Any]]) -> None:
    failures = report.get("failures", [])
    for failure in failures:
        entry = {
            "module": "lane_section_successor_scan",
            "severity": "error",
            "code": failure.get("reason", "dangling_successor"),
            "message": "Lane successor repair reported an unresolved connection.",
            "context": failure,
        }
        errors.append(entry)


def run_preflight(xodr_path: Path, out_dir: Path) -> Dict[str, Any]:
    """
    Programmatic entrypoint for preflight validation.
    Returns the full preflight report dict.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "preflight_report.json"

    root, parse_error = _parse_xodr(xodr_path)

    strict_result = _run_strict_validator(root) if root is not None else {"available": bool(StrictXodrValidator), "note": "Skipped because XML failed to parse."}
    carla_result = _run_carla_gate(root) if root is not None else {"available": bool(StrictCarlaOpendriveGate), "note": "Skipped because XML failed to parse."}
    successor_result = _run_successor_scan(xodr_path) if root is not None else {"available": bool(repair_and_assert_lane_section_successors), "note": "Skipped because XML failed to parse."}

    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    if parse_error:
        errors.append(
            {
                "module": "xml_parse",
                "severity": "error",
                "code": "parse_error",
                "message": parse_error,
                "context": {"path": str(xodr_path)},
            }
        )

    if strict_result.get("report"):
        _attach_issues("strict_validator", strict_result["report"].get("issues", []), errors, warnings)
    elif strict_result.get("error"):
        errors.append(
            {
                "module": "strict_validator",
                "severity": "error",
                "code": "validator_exception",
                "message": strict_result["error"],
            }
        )
    elif not strict_result.get("available", False):
        warnings.append(
            {
                "module": "strict_validator",
                "severity": "warn",
                "code": "validator_unavailable",
                "message": strict_result.get("note", "Strict validator unavailable."),
            }
        )

    if carla_result.get("issues"):
        _attach_issues("carla_compat_gate", carla_result["issues"], errors, warnings)
    elif carla_result.get("error"):
        errors.append(
            {
                "module": "carla_compat_gate",
                "severity": "error",
                "code": "gate_exception",
                "message": carla_result["error"],
            }
        )
    elif not carla_result.get("available", False):
        warnings.append(
            {
                "module": "carla_compat_gate",
                "severity": "warn",
                "code": "gate_unavailable",
                "message": carla_result.get("note", "CARLA compatibility gate unavailable."),
            }
        )

    if successor_result.get("report"):
        _summarize_successor_failures(successor_result["report"], errors)
    elif successor_result.get("error"):
        errors.append(
            {
                "module": "lane_section_successor_scan",
                "severity": "error",
                "code": "successor_exception",
                "message": successor_result["error"],
            }
        )
    elif not successor_result.get("available", False):
        warnings.append(
            {
                "module": "lane_section_successor_scan",
                "severity": "warn",
                "code": "successor_unavailable",
                "message": successor_result.get("note", "Lane successor scan unavailable."),
            }
        )

    summary = {
        "error_count": len(errors),
        "warning_count": len(warnings),
        "status": "ok" if not errors else "fail",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    preflight_report = {
        "xodr_path": str(xodr_path),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "parse_error": parse_error,
        "modules": {
            "strict_validator": strict_result,
            "carla_compat_gate": carla_result,
            "lane_section_successor_scan": successor_result,
        },
        "errors": errors,
        "warnings": warnings,
        "summary": summary,
    }

    with report_path.open("w", encoding="utf-8") as fh:
        json.dump(preflight_report, fh, indent=2, sort_keys=True)

    print(f"[preflight_xodr_loadability] Report saved to {report_path} (status={summary['status']})")

    return preflight_report


def main() -> int:
    args = _parse_args()
    preflight_report = run_preflight(args.xodr, args.out)
    return 0 if preflight_report["summary"]["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
