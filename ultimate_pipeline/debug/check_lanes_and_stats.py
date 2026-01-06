# ultimate_pipeline/debug/check_lanes_and_stats.py

from __future__ import annotations
import sys
import os
import json

from ultimate_pipeline.core.odr_io import load_xodr
from ultimate_pipeline.core.xodr_statistics import XODRStatistics


def main(xodr_path: str):
    if not os.path.isfile(xodr_path):
        raise FileNotFoundError(xodr_path)

    tree, root = load_xodr(xodr_path)
    roads = root.findall(".//road")
    lanes = root.findall(".//lane")
    lane_sections = root.findall(".//laneSection")

    print(f"XODR: {xodr_path}")
    print(f"  roads:         {len(roads)}")
    print(f"  laneSections:  {len(lane_sections)}")
    print(f"  lanes:         {len(lanes)}")

    stats = XODRStatistics.compute(xodr_path)
    print("\n[Lane stats from XODRStatistics]")
    print(json.dumps(stats.get("lanes", {}), indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m ultimate_pipeline.debug.check_lanes_and_stats path/to/file.xodr")
        sys.exit(1)
    main(sys.argv[1])
