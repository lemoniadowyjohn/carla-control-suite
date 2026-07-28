#!/usr/bin/env python3
"""CLI tool for RoadRunner roundtrip validation.

Compares a parent (governed/candidate) XODR with a RoadRunner-exported
candidate XODR, computes semantic diffs, applies hard gates, and writes
a JSON report.

Usage:
    python -m tools.roadrunner.validate_roundtrip \\
        --parent parent.xodr \\
        --candidate candidate.xodr \\
        --output report.json

Exit codes:
    0  PASS (all required gates passed)
    1  FAIL (one or more required gates failed)
    2  BLOCKED (one or more required gates blocked)
    3  ERROR (unexpected error)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ultimate_pipeline.roadrunner.roundtrip import RoundtripReport, compare_roundtrip, write_report
from ultimate_pipeline.roadrunner.validation import RoundtripConfig


def _build_config(args: argparse.Namespace) -> RoundtripConfig:
    return RoundtripConfig(
        tangent_regression_threshold_deg=args.tangent_threshold,
        position_tolerance_m=args.position_tolerance,
        length_tolerance_m=args.length_tolerance,
        width_tolerance_m=args.width_tolerance,
        curvature_tolerance=args.curvature_tolerance,
        sample_interval_m=args.sample_interval,
        shapely_available=not args.no_shapely,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate RoadRunner roundtrip: compare parent XODR with exported candidate.",
    )
    parser.add_argument(
        "--parent",
        required=True,
        type=Path,
        help="Path to the parent (governed/candidate) XODR file.",
    )
    parser.add_argument(
        "--candidate",
        required=True,
        type=Path,
        help="Path to the RoadRunner-exported candidate XODR file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON report path. Defaults to stdout.",
    )
    parser.add_argument(
        "--report-id",
        type=str,
        default=None,
        help="Override report identifier.",
    )
    parser.add_argument(
        "--tangent-threshold",
        type=float,
        default=1.0,
        help="Tangent regression threshold in degrees (default: 1.0).",
    )
    parser.add_argument(
        "--position-tolerance",
        type=float,
        default=0.1,
        help="Position tolerance in metres (default: 0.1).",
    )
    parser.add_argument(
        "--length-tolerance",
        type=float,
        default=0.5,
        help="Total road length tolerance in metres (default: 0.5).",
    )
    parser.add_argument(
        "--width-tolerance",
        type=float,
        default=0.05,
        help="Lane width tolerance in metres (default: 0.05).",
    )
    parser.add_argument(
        "--curvature-tolerance",
        type=float,
        default=0.01,
        help="Curvature tolerance (default: 0.01).",
    )
    parser.add_argument(
        "--sample-interval",
        type=float,
        default=1.0,
        help="Centreline sampling interval in metres (default: 1.0).",
    )
    parser.add_argument(
        "--no-shapely",
        action="store_true",
        help="Force disable Shapely for polygon-specific checks (marks them BLOCKED).",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Output only a compact summary (fewer diffs).",
    )
    args = parser.parse_args(argv)

    config = _build_config(args)

    try:
        report = compare_roundtrip(
            parent_path=args.parent,
            candidate_path=args.candidate,
            config=config,
            report_id=args.report_id,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 3

    if args.output:
        written_path = write_report(report, args.output)
        print(f"Report written to {written_path}", file=sys.stderr)
    else:
        output = report.to_json()
        if args.summary:
            summary = report.to_summary_dict()
            summary["diffs"] = summary["diffs"][:50]
            summary["diff_count"] = report.diff_count
            output = json.dumps(summary, indent=2, sort_keys=True)
        print(output)

    status = report.overall_status.value
    if status == "PASS":
        print(f"PASS: roundtrip validation succeeded ({report.diff_count} diffs, {report.gate_count} gates)", file=sys.stderr)
        return 0
    elif status == "FAIL":
        print(
            f"FAIL: roundtrip validation failed ({report.failed_gate_count} gate(s) failed, {report.diff_count} diffs)",
            file=sys.stderr,
        )
        return 1
    elif status == "BLOCKED":
        print(
            f"BLOCKED: roundtrip validation blocked ({report.blocked_gate_count} gate(s) blocked)",
            file=sys.stderr,
        )
        return 2
    else:
        print(f"NOT_APPLICABLE: {status}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
