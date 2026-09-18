#!/usr/bin/env python3
"""hpc_preflight.py

HPC-friendly preflight checks:
- Can we import CARLA PythonAPI?
- Can we connect to the server?
- Is the canonical OpenDRIVE loader importable?

Exit code:
- 0: OK
- 1: CARLA import/connect failed
- 2: Connected, but canonical loader not importable (fallback still possible)
"""

from __future__ import annotations

import argparse
import sys

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--timeout", type=float, default=10.0)
    args = ap.parse_args()

    try:
        import carla
    except Exception as e:
        print(f"❌ CARLA PythonAPI import failed: {e}")
        return 1

    try:
        client = carla.Client(args.host, args.port)
        client.set_timeout(args.timeout)
        world = client.get_world()
        print("✅ Connected to CARLA")
        print(f"   Map: {world.get_map().name}")
    except Exception as e:
        print(f"❌ CARLA connection failed: {e}")
        return 1

    # Canonical loader availability
    try:
        from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world  # noqa: F401
        print("✅ Canonical loader importable: ultimate_pipeline.core.carla_opendrive_loader.load_opendrive_world")
        return 0
    except Exception as e:
        print("⚠️  Canonical loader NOT importable (you can still fall back to client.generate_opendrive_world)")
        print(f"   Reason: {e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
