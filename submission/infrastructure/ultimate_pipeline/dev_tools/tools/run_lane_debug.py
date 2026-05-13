#!/usr/bin/env python3
import os, sys
from ultimate_pipeline.analysis.lane_debugger import LaneDebugger

if len(sys.argv) < 2:
    print("Usage: python tools/run_lane_debug.py <xodr_file>")
    sys.exit()

LaneDebugger.full_scan(sys.argv[1])
