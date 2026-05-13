#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Helper to record perception data for an automatically generated XODR.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from ultimate_pipeline.tools import xodr_carla_hardener
from ultimate_pipeline.tools import carla_probe


from ultimate_pipeline.carla_tools.reload_ready_for_sensors import _reload_ready_for_sensors
def _md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_args():
    ap = argparse.ArgumentParser(description="Record auto-generated XODR via record_route.")
    ap.add_argument("--xodr-in", required=True, help="Auto-generated XODR path")
    ap.add_argument("--calib", required=True, help="Calibration JSON")
    ap.add_argument("--out-dir", required=True, help="Recording output root")
    ap.add_argument("--spawn-index", type=int, default=0)
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--duration", type=int, default=5)
    ap.add_argument("--repair-parampoly3-to-line", action="store_true", help="Repair paramPoly3 during hardening")
    ap.add_argument("--host", default="127.0.0.1", help="CARLA host")
    ap.add_argument("--port", type=int, default=2000, help="CARLA port")
    return ap.parse_args()


def ensure_carla_ready(host: str = "127.0.0.1", port: int = 2000) -> None:
    res = subprocess.run(
        [sys.executable, "-m", "ultimate_pipeline.tools.carla_probe", "--host", host, "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
    )
    if res.returncode != 0:
        raise RuntimeError(f"CARLA readiness probe failed:\n{res.stdout}\n{res.stderr}")


def load_open_drive_map(host: str = "127.0.0.1", port: int = 2000):
    import carla  # lazy import

    client = carla.Client(host, port)
    client.set_timeout(10.0)
    _reload_ready_for_sensors(client, map_name="OpenDriveMap", tm_port=8000)
    world = client.get_world()
    world.get_map()
    return client


def main():
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    hardened = Path(out_dir) / "auto_hardened.xodr"
    report = Path(out_dir) / "xodr_hardener_report.json"

    ensure_carla_ready(args.host, args.port)
    client = load_open_drive_map(args.host, args.port)
    version = None
    for attempt in range(2):
        try:
            version = client.get_server_version()
            break
        except Exception as exc:
            if attempt == 0:
                time.sleep(0.5)
                client = load_open_drive_map(args.host, args.port)
                continue
            raise RuntimeError("CARLA RPC not responsive after forcing OpenDriveMap") from exc

    used_xodr = Path(args.xodr_in)
    if args.repair_parampoly3_to_line:
        xodr_carla_hardener.harden_xodr(
            Path(args.xodr_in),
            hardened,
            repair_parampoly3_to_line=True,
            report_path=report,
            clamp_s_endpoints=True,
            parampoly3_sanity=True,
        )
        used_xodr = hardened

    cmd = [
        sys.executable,
        "-m",
        "ultimate_pipeline.perception.record_route",
        "--xodr",
        str(used_xodr),
        "--calib",
        args.calib,
        "--out-dir",
        str(out_dir),
        "--spawn-index",
        str(args.spawn_index),
        "--fps",
        str(args.fps),
        "--duration",
        str(args.duration),
        "--rpc-timeout",
        "3",
        "--startup-timeout",
        "30",
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    subprocess.run(cmd, check=True)

    meta = {
        "input_xodr": str(Path(args.xodr_in).resolve()),
        "used_xodr": str(used_xodr.resolve()),
        "input_md5": _md5(Path(args.xodr_in)),
        "used_md5": _md5(used_xodr),
        "spawn_index": args.spawn_index,
        "fps": args.fps,
        "duration": args.duration,
        "repair_parampoly3_to_line": bool(args.repair_parampoly3_to_line),
        "strict_mode": os.environ.get("UP_THESIS_STRICT", "0"),
        "host": args.host,
        "port": args.port,
        "open_drive_map_forced": True,
        "carla_version": version,
    }
    with open(out_dir / "auto_record_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, sort_keys=True, ensure_ascii=True)


if __name__ == "__main__":
    main()
