#!/usr/bin/env python3
# Quick debug pipeline runner

import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

MAIN = os.path.join(ROOT, "ultimate_pipeline", "main_pipeline.py")

if not os.path.exists(MAIN):
    print("❌ Could not find main_pipeline.py at:", MAIN)
    sys.exit(1)

print("🧪 Running DEBUG QUICK PIPELINE…")

env = os.environ.copy()
env["PYTHONPATH"] = ROOT

cmd = [
    sys.executable,
    MAIN,
    "--debug"
]

print("➡ Executing:", " ".join(cmd))
subprocess.run(cmd, env=env)
