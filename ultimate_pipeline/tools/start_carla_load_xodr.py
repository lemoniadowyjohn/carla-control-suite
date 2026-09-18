#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Start CARLA (if needed) and load an OpenDRIVE (.xodr) map.

Example:
python -m ultimate_pipeline.tools.start_carla_load_xodr --xodr "C:\\path\\to\\map.xodr"
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world_from_file
from ultimate_pipeline.core.carla_utils import autostart_carla_if_needed


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Start CARLA (if needed) and load a .xodr map."
    )
    ap.add_argument("--xodr", type=Path, required=True, help="Path to .xodr file.")
    ap.add_argument("--host", default="127.0.0.1", help="CARLA host.")
    ap.add_argument("--port", type=int, default=2000, help="CARLA RPC port.")
    ap.add_argument(
        "--timeout-s",
        type=float,
        default=180.0,
        help="Load timeout in seconds.",
    )
    ap.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Number of OpenDRIVE load retries.",
    )
    ap.add_argument(
        "--wait-s",
        type=float,
        default=5.0,
        help="Seconds to keep process alive after successful load.",
    )
    ap.add_argument(
        "--no-reload",
        action="store_true",
        help="Do not force world reload after generation.",
    )
    return ap.parse_args()


def main() -> int:
    args = _parse_args()
    xodr_path = Path(args.xodr).expanduser().resolve()
    if not xodr_path.is_file():
        raise FileNotFoundError(f"XODR file not found: {xodr_path}")

    print(f"[start_carla_load_xodr] xodr={xodr_path}")
    print(f"[start_carla_load_xodr] connecting host={args.host} port={int(args.port)}")
    client = autostart_carla_if_needed(
        host=str(args.host),
        port=int(args.port),
        timeout_s=max(5.0, float(args.timeout_s)),
    )
    print("[start_carla_load_xodr] CARLA ready.")

    world = load_opendrive_world_from_file(
        client,
        xodr_path,
        timeout_s=float(args.timeout_s),
        retries=max(1, int(args.retries)),
        do_reload=not bool(args.no_reload),
        fallback_enabled=False,
    )

    map_name = "UNKNOWN"
    try:
        map_name = str(world.get_map().name or "UNKNOWN")
    except Exception:
        map_name = "UNKNOWN"

    print(f"[start_carla_load_xodr] map loaded. carla_map_name={map_name}")
    if float(args.wait_s) > 0.0:
        print(f"[start_carla_load_xodr] waiting {float(args.wait_s):.1f}s before exit...")
        time.sleep(float(args.wait_s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
