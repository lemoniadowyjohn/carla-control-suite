#!/usr/bin/env python3
import sys
from ultimate_pipeline.visualization.map_diff import MapDiff

if len(sys.argv) < 3:
    print("Usage: python tools/compare_two_xodr.py <map1.xodr> <map2.xodr>")
    sys.exit()

MapDiff.compare(sys.argv[1], sys.argv[2], out_prefix="mapdiff")
