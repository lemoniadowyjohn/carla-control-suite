#!/usr/bin/env python3
"""Offline final-XODR verification for CARLA lane-width readiness.

This command performs static XML checks only. It does not connect to CARLA.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ultimate_pipeline.quality.lane_width_invariants import (
    enforce_lane_width_invariants_on_root,
)
from ultimate_pipeline.quality.xodr_validation_policy import (
    CARLA_0_9_16_COMPAT,
)
from ultimate_pipeline.quality.xodr_validation_result import (
    ValidationResult,
    merge_results,
)


_LANE_TYPES_REQUIRING_WIDTH = (
    "driving",
    "shoulder",
    "sidewalk",
    "border",
    "parking",
    "biking",
    "restricted",
    "none",
)

_EXPLICIT_TARGET_TYPES = {"restricted", "none"}


def _lane_requires_width(lane: ET.Element) -> bool:
    lane_id = lane.get("id")
    if lane_id is None:
        return False
    try:
        if int(lane_id) == 0:
            return False
    except Exception:
        pass
    lane_type = (lane.get("type") or "").strip()
    return (not lane_type) or lane_type in _LANE_TYPES_REQUIRING_WIDTH


def _scan_lane_width_warnings(root: ET.Element, max_examples: int = 25) -> Dict[str, Any]:
    examples: List[Dict[str, str]] = []
    restricted_or_none_road_ids = set()
    count = 0
    for road in root.findall("./road"):
        road_id = str(road.get("id", ""))
        for lane_section in road.findall("./lanes/laneSection"):
            section_s = str(lane_section.get("s", "0"))
            for lane in lane_section.findall(".//lane"):
                if not _lane_requires_width(lane):
                    continue
                if lane.find("./width") is not None:
                    continue
                count += 1
                lane_type = str(lane.get("type", ""))
                if lane_type in _EXPLICIT_TARGET_TYPES:
                    restricted_or_none_road_ids.add(road_id)
                if len(examples) < max_examples:
                    examples.append(
                        {
                            "road_id": road_id,
                            "lane_section_s": section_s,
                            "lane_id": str(lane.get("id", "")),
                            "lane_type": lane_type,
                        }
                    )
    return {
        "missing_width_lane_count": count,
        "restricted_or_none_missing_width_road_ids": sorted(
            restricted_or_none_road_ids,
            key=lambda value: (len(value), value),
        ),
        "examples": examples,
    }


def _count_junctions_and_connectors(root: ET.Element) -> Tuple[int, int]:
    junctions = root.findall("./junction")
    connecting_roads = {
        str(conn.get("connectingRoad") or "").strip()
        for junction in junctions
        for conn in junction.findall("./connection")
        if str(conn.get("connectingRoad") or "").strip()
    }
    if connecting_roads:
        return len(junctions), len(connecting_roads)

    connector_roads = [
        road
        for road in root.findall("./road")
        if str(road.get("junction") or "-1").strip() not in ("", "-1")
    ]
    return len(junctions), len(connector_roads)


def _default_report_path(xodr_path: Path) -> Path:
    return xodr_path.with_name("verify_final_xodr_report.json")


def verify_final_xodr(
    xodr_path: Path, report_path: Path | None = None
) -> Dict[str, Any]:
    xodr_path = Path(xodr_path)
    if report_path is None:
        report_path = _default_report_path(xodr_path)
    else:
        report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    parse_error = None
    root = None
    try:
        root = ET.parse(xodr_path).getroot()
    except Exception as exc:
        parse_error = str(exc)

    if root is None:
        road_count = 0
        lane_width = {
            "missing_width_lane_count": 0,
            "restricted_or_none_missing_width_road_ids": [],
            "examples": [],
        }
        invariant_report = None
        junction_count = 0
        connector_count = 0
    else:
        road_count = len(root.findall("./road"))
        lane_width = _scan_lane_width_warnings(root)
        junction_count, connector_count = _count_junctions_and_connectors(root)

        # Dry-run the production invariant on a copy so verification never mutates the file.
        invariant_report = enforce_lane_width_invariants_on_root(copy.deepcopy(root))

    missing_width_count = int(lane_width.get("missing_width_lane_count", 0))
    ok = bool(parse_error is None and missing_width_count == 0)

    report = {
        "schema": "verify_final_xodr_v1",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "xodr_path": str(xodr_path),
        "ok": ok,
        "parse_error": parse_error,
        "road_count": road_count,
        "junction_count": junction_count,
        "connector_count": connector_count,
        "lane_width_missing": missing_width_count,
        "lane_width_warnings": lane_width,
        "dry_run_invariant_report": invariant_report,
    }
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=True, sort_keys=True),
        encoding="utf-8",
    )
    report["report_path"] = str(report_path)
    return report


def validate_final_xodr_static(
    xodr_path: str | Path,
    *,
    profile: str = CARLA_0_9_16_COMPAT,
    xsd_path: str | Path | None = None,
) -> Dict[str, Any]:
    """One recommended offline entrypoint for final-XODR validation (§18).

    Orchestrates (no repairs): XML structure → numeric/structural validity
    → primitive contract → road geometry sequence → lane structure → width
    validity → basic road/junction references → optional XSD → CARLA static
    compatibility. Returns the shared §17 envelope.

    Static validation can only ever prove VERIFIED_OFFLINE_STATIC (§19): it
    cannot prove CARLA_LOAD_VERIFIED without the runtime, and the envelope
    says so explicitly.
    """
    import hashlib

    from ultimate_pipeline.quality.check_carla_opendrive_compat import (
        StrictCarlaOpendriveGate,
    )
    from ultimate_pipeline.quality.check_xodr_schema import (
        validate_xodr_schema_structured,
    )
    from ultimate_pipeline.quality.check_xml_integrity import (
        XMLIntegrityChecker,
    )
    from ultimate_pipeline.quality.xodr_strict_validator import (
        StrictXodrValidator,
    )

    xodr_path = Path(xodr_path)
    try:
        digest = hashlib.sha256(xodr_path.read_bytes()).hexdigest()
    except Exception:
        digest = None

    sub_results: List[ValidationResult] = []

    xml_res = ValidationResult(validator="XML_BASIC_INTEGRITY",
                               input_xodr_sha256=digest)
    # XML_BASIC_INTEGRITY is advisory except for structural blockers: a
    # missing bounds attribute must not fail an otherwise valid map, while
    # an unparseable file must.
    _XML_ERROR_TYPES = {"missing_file", "parse_error", "root_tag_mismatch",
                        "no_roads"}
    try:
        xml_issues = XMLIntegrityChecker.validate(str(xodr_path))
        for issue in xml_issues:
            payload = {"code": issue.get("type", "xml_issue"),
                       "message": f"basic XML integrity: {issue}"}
            if issue.get("type") in _XML_ERROR_TYPES:
                xml_res.errors.append(payload)
            else:
                xml_res.warnings.append(payload)
        xml_res.statistics["n_issues"] = len(xml_issues)
        if not xml_res.errors:
            xml_res.status = "PASS"
    except Exception as exc:
        xml_res.status = "INCOMPLETE"
        xml_res.fail("xml_check_crashed", f"XML check crashed: {exc}")
    sub_results.append(xml_res.finalize())

    struct_res = ValidationResult(validator="XODR_STRUCTURAL",
                                  input_xodr_sha256=digest)
    try:
        report = StrictXodrValidator(profile=profile).validate_path(xodr_path)
        for issue in report.get("issues", []):
            payload = {"code": issue.get("code"), "message": issue.get("message"),
                       "context": issue.get("context", {})}
            if issue.get("severity") == "error":
                struct_res.errors.append(payload)
            else:
                struct_res.warnings.append(payload)
        struct_res.statistics["n_errors"] = report.get("n_errors", 0)
        struct_res.statistics["n_warnings"] = report.get("n_warnings", 0)
        if not struct_res.errors:
            struct_res.status = "PASS"
    except Exception as exc:
        struct_res.status = "INCOMPLETE"
        struct_res.fail("structural_check_crashed", f"structural check crashed: {exc}")
    sub_results.append(struct_res.finalize())

    compat_res = ValidationResult(validator="CARLA_STATIC_COMPAT",
                                  input_xodr_sha256=digest)
    try:
        import xml.etree.ElementTree as _ET

        root = _ET.parse(str(xodr_path)).getroot()
        compat_issues = StrictCarlaOpendriveGate.validate(root)
        for issue in compat_issues:
            payload = {"code": issue.get("code"), "message": issue.get("message"),
                       "context": issue.get("context", {})}
            if issue.get("severity") == "error":
                compat_res.errors.append(payload)
            else:
                compat_res.warnings.append(payload)
        if not compat_res.errors:
            compat_res.status = "PASS"
    except Exception as exc:
        compat_res.status = "INCOMPLETE"
        compat_res.fail("compat_check_crashed", f"compat check crashed: {exc}")
    sub_results.append(compat_res.finalize())

    xsd_res = ValidationResult(validator="XSD_SCHEMA",
                               input_xodr_sha256=digest)
    try:
        xsd_evidence = validate_xodr_schema_structured(
            str(xodr_path), str(xsd_path) if xsd_path else None
        )
        xsd_res.statistics["xsd"] = {
            k: xsd_evidence.get(k)
            for k in ("xsd_path", "xsd_sha256", "lxml_version")
        }
        envelope_status = xsd_evidence.get("envelope_status", "INCOMPLETE")
        if envelope_status == "FAIL":
            xsd_res.errors.extend(xsd_evidence.get("errors", []))
            xsd_res.status = "FAIL"
        else:
            # NOT_RUN / INCOMPLETE: visible but non-blocking per the facade
            # overall rule (overall PASS still shows XSD_SCHEMA: NOT_RUN).
            for entry in xsd_evidence.get("errors", []):
                xsd_res.warnings.append(dict(entry))
            xsd_res.status = envelope_status
    except Exception as exc:
        xsd_res.status = "INCOMPLETE"
        xsd_res.fail("xsd_check_crashed", f"XSD check crashed: {exc}")
    sub_results.append(xsd_res.finalize())

    merged = merge_results("FINAL_XODR_STATIC", sub_results,
                           input_xodr_sha256=digest)
    # Facade overall rule (documented in 05_STATIC_VALIDATION_CONTRACT.json):
    # FAIL if any executed check failed; INCOMPLETE if any check could not
    # run; a NOT_RUN sub-result (e.g. unconfigured XSD) is recorded
    # explicitly per-validator but does not fail the envelope -- overall
    # PASS therefore means "all executed checks passed", never "XSD passed".
    envelope = merged.to_dict()
    sub_status = {k: v.get("status") for k, v in
                  envelope.get("statistics", {}).items()
                  if isinstance(v, dict)}
    if (envelope["status"] == "NOT_RUN"
            and not any(s == "FAIL" for s in sub_status.values())
            and not any(s == "INCOMPLETE" for s in sub_status.values())):
        envelope["status"] = "PASS"
    envelope["attestation"] = (
        "VERIFIED_OFFLINE_STATIC" if envelope["status"] == "PASS"
        else "NOT_VERIFIED_OFFLINE_STATIC"
    )
    envelope["claim_boundary"] = (
        "Static validation only. This envelope can never certify "
        "CARLA_LOAD_VERIFIED -- that requires the CARLA runtime (§19)."
    )
    envelope["profile"] = profile
    return envelope


def _parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Offline final-XODR static lane-width verification."
    )
    parser.add_argument("--xodr", type=Path, required=True, help="Final XODR path")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="JSON report path (default: verify_final_xodr_report.json next to XODR)",
    )
    parser.add_argument(
        "--static-envelope",
        type=Path,
        default=None,
        help="Also run the §18 static-validation facade "
             "(validate_final_xodr_static) and write its envelope JSON here.",
    )
    parser.add_argument("--xsd", type=Path, default=None,
                        help="Optional XSD for the static envelope.")
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    report = verify_final_xodr(args.xodr, args.out)
    status = "PASS" if report["ok"] else "FAIL"
    lane_width = report["lane_width_warnings"]
    road_ids = lane_width.get("restricted_or_none_missing_width_road_ids", [])

    print(
        "[verify_final_xodr] "
        f"roads={report['road_count']} "
        f"junctions={report['junction_count']} "
        f"connectors={report['connector_count']}"
    )
    print(f"[verify_final_xodr] lane_width_missing={report['lane_width_missing']}")
    if road_ids:
        print(
            "[verify_final_xodr] restricted_or_none_missing_width_road_ids="
            + ",".join(str(road_id) for road_id in road_ids)
        )
    print(f"[verify_final_xodr] report={report['report_path']}")
    print(f"[verify_final_xodr] {status}")
    if args.static_envelope is not None:
        envelope = validate_final_xodr_static(args.xodr, xsd_path=args.xsd)
        args.static_envelope.parent.mkdir(parents=True, exist_ok=True)
        args.static_envelope.write_text(
            json.dumps(envelope, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"[verify_final_xodr] static envelope "
              f"{envelope['status']} ({envelope['attestation']}) "
              f"-> {args.static_envelope}")
        if envelope["status"] != "PASS":
            return 2
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
