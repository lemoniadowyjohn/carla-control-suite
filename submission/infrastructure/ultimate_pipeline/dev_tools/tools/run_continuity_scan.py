#!/usr/bin/env python3
import os, sys, subprocess

if len(sys.argv) < 2:
    print("Usage: python tools/run_continuity_scan.py <pipeline_output_dir>")
    sys.exit()

out_dir = sys.argv[1]
debug_json = os.path.join(out_dir, "continuity_debug.json")

if not os.path.exists(debug_json):
    raise FileNotFoundError(debug_json)

cmd = [
    sys.executable,
    "-m",
    "ultimate_pipeline.diagnostics.continuity_summary",
    out_dir
]

subprocess.run(cmd)
