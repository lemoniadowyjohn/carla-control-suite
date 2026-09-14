"""Emit a read-only OSM/XODR road-boundary topology cross-check report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ultimate_pipeline.quality.osm_road_link_topology import run_osm_road_link_topology_audit


def run(xodr_path: str | Path, osm_path: str | Path) -> dict[str, Any]:
    return run_osm_road_link_topology_audit(xodr_path, osm_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only HIGH/EXACT OSM-to-XODR road-link topology cross-check."
    )
    parser.add_argument("--xodr", required=True, type=Path, help="Input OpenDRIVE map")
    parser.add_argument("--osm", required=True, type=Path, help="Pinned OSM source")
    parser.add_argument("--out", required=True, type=Path, help="Report JSON output")
    args = parser.parse_args(argv)
    report = run(args.xodr, args.osm)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    # This is advisory; discrepancies are reported in JSON and intentionally
    # do not make the inspection command unsuitable for evidence collection.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
