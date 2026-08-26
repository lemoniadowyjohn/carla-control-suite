#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
find_broken_roads.py

Standalone dev CLI: scan an OpenDRIVE (.xodr) file for road-to-road link
discontinuities (gap in x/y or a heading jump greater than tolerance).

This intentionally does NOT reimplement continuity checking. It wires
directly into `ultimate_pipeline.quality.check_geometric_continuity`, the
C6-corrected, actively-maintained checker that is also used by Stage 6's
`gate_geometric_continuity` quality gate. `ultimate_pipeline.geometry.
mesh_continuity_repairer.MeshContinuityRepairer` predates that fix and has
its own (older) `scan_roads()` used internally by the repair pipeline; this
CLI deliberately does not use it, to avoid two diverging notions of "broken".

Usage:
    python -m ultimate_pipeline.dev_tools.tools.find_broken_roads map.xodr
    python -m ultimate_pipeline.dev_tools.tools.find_broken_roads map.xodr --json
    python -m ultimate_pipeline.dev_tools.tools.find_broken_roads map.xodr --eps-xy 0.1 --eps-hdg 0.02
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Sequence

from ultimate_pipeline.quality.check_geometric_continuity import (
    check_geometric_continuity,
)


def find_broken_roads(
    xodr_path: str,
    eps_xy: float = 0.05,
    eps_hdg: float = 0.01,
) -> Dict[str, Any]:
    """
    Thin wrapper around check_geometric_continuity for CLI/programmatic use.

    Returns the same report dict documented on check_geometric_continuity:
    {"ok": bool, "num_issues": int, "issues": [...], ...}
    """
    return check_geometric_continuity(xodr_path, eps_xy=eps_xy, eps_hdg=eps_hdg)


def _format_issue(issue: Dict[str, Any]) -> str:
    return (
        f"  - Broken road link: road {issue.get('from_road')} "
        f"-> road {issue.get('to_road')} ({issue.get('link_kind')}): "
        f"dxy={issue.get('dxy', 0.0):.3f} m, dhdg={issue.get('dhdg', 0.0):.4f} rad"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="find_broken_roads",
        description="Scan an OpenDRIVE file for road-to-road link discontinuities.",
    )
    parser.add_argument("xodr", help="Path to the .xodr file to scan.")
    parser.add_argument(
        "--eps-xy", type=float, default=0.05, help="Max allowed endpoint gap in meters (default: 0.05)."
    )
    parser.add_argument(
        "--eps-hdg", type=float, default=0.01, help="Max allowed heading jump in radians (default: 0.01)."
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit the full report as JSON instead of a human-readable summary."
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    report = find_broken_roads(args.xodr, eps_xy=args.eps_xy, eps_hdg=args.eps_hdg)

    if args.json:
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") else 1

    issues: List[Dict[str, Any]] = report.get("issues", [])
    if not issues:
        print(f"No broken road links found ({report.get('num_links_checked', 0)} links checked).")
        return 0

    print(f"Found {len(issues)} broken road link(s):")
    for issue in issues:
        print(_format_issue(issue))
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
