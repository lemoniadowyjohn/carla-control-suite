#!/usr/bin/env python3
"""carla_server_launcher.py

Convenience CARLA server launcher for HPC / headless setups.

This does NOT replace a real cluster job script — it's a small helper to keep flags consistent.

Defaults:
- uses CARLA_ROOT env var to locate CarlaUE4.sh / CarlaUE4.exe
- --offscreen enables -RenderOffScreen
- --low-quality sets -quality-level=Low
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
from pathlib import Path

def find_carla_exe(carla_root: Path) -> Path:
    if platform.system().lower().startswith("win"):
        exe = carla_root / "CarlaUE4.exe"
    else:
        exe = carla_root / "CarlaUE4.sh"
    return exe

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--carla-root", default=os.environ.get("CARLA_ROOT", ""), help="Path to CARLA root (or set CARLA_ROOT env var)")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--offscreen", action="store_true", help="Add -RenderOffScreen")
    ap.add_argument("--low-quality", action="store_true", help="Add -quality-level=Low")
    ap.add_argument("--fps", type=int, default=20, help="Server FPS for fixed delta (passed as -fps=)")
    ap.add_argument("--extra", default="", help="Extra args string appended verbatim")
    args = ap.parse_args()

    if not args.carla_root:
        print("❌ Provide --carla-root or set CARLA_ROOT")
        return 1

    carla_root = Path(args.carla_root)
    exe = find_carla_exe(carla_root)
    if not exe.exists():
        print(f"❌ CARLA executable not found: {exe}")
        return 1

    cmd = [str(exe), f"-carla-port={args.port}", f"-fps={args.fps}"]
    if args.offscreen:
        cmd.append("-RenderOffScreen")
    if args.low_quality:
        cmd.append("-quality-level=Low")
    if args.extra.strip():
        cmd += args.extra.strip().split()

    print("🚀 Launching CARLA:")
    print("   " + " ".join(cmd))
    return subprocess.call(cmd)

if __name__ == "__main__":
    raise SystemExit(main())
