"""Write an advisory OSM turn-lane agreement report for one OpenDRIVE map."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from ultimate_pipeline.lanes.turn_restriction_audit import (
    audit_lane_link_turn_classification,
)


def run(
    xodr_path: str | Path,
    *,
    correspondence_path: str | Path | None = None,
) -> dict[str, Any]:
    """Audit an XODR map without mutating it.

    The optional JSON correspondence payload is either a direct road-id map or
    an object with a by_xodr_road_id member. Associations without both a
    high-confidence match class and an explicit OSM-to-XODR orientation are
    rejected by the underlying audit.
    """

    root = ET.parse(xodr_path).getroot()
    correspondence: dict[str, Any] = {}
    if correspondence_path is not None:
        with Path(correspondence_path).open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            candidate = payload.get("by_xodr_road_id", payload)
            if isinstance(candidate, dict):
                correspondence = candidate
    return audit_lane_link_turn_classification(root, correspondence)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit OSM turn-lane agreement for existing junction lane links."
    )
    parser.add_argument("xodr", type=Path, help="OpenDRIVE map to inspect")
    parser.add_argument(
        "--correspondence",
        type=Path,
        help="Optional road-resolved OSM correspondence JSON",
    )
    parser.add_argument("--out", required=True, type=Path, help="Report JSON path")
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Return non-zero unless every inspected lane link has usable direct OSM data.",
    )
    args = parser.parse_args(argv)
    report = run(args.xodr, correspondence_path=args.correspondence)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return 0 if not args.require_complete or report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
