#!/usr/bin/env python3
"""C20 Tier 1 — CARLA RPC-hang config workarounds.

Launches CarlaUE4.exe with a chosen flag variant, then polls
client.get_server_version() (NOT just the TCP port -- that's the exact gap
in ultimate_pipeline.core.carla_utils.restart_carla, which only waits for
the port to open) up to a long timeout. Reports elapsed time, GPU state at
launch/settle, and writes a JSON evidence file.

Usage:
    python scripts/c20_tier1_probe.py <variant> [--timeout 600]

Variants:
    patient   -RenderOffScreen -quality-level=Low -nosound          (attempt 1)
    minimal   + -ResX=64 -ResY=64 -windowed                          (attempt 2)
    nullrhi   -nullrhi (diagnostic: no rendering at all)             (attempt 3)
    vulkan    -vulkan                                                (attempt 4)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
import carla  # noqa: E402

CARLA_EXE = r"E:\CARLA\CARLA_0.9.16\CarlaUE4.exe"
RPC_PORT = 2000
OUT_DIR = Path("reports/post_audit_hardening/C20_TIER1_PROBE_20260821")

VARIANTS = {
    "patient": ["-RenderOffScreen", "-quality-level=Low", "-nosound"],
    "minimal": ["-RenderOffScreen", "-quality-level=Low", "-nosound", "-ResX=64", "-ResY=64", "-windowed"],
    "nullrhi": ["-nullrhi", "-nosound"],
    "vulkan": ["-RenderOffScreen", "-quality-level=Low", "-nosound", "-vulkan"],
}


def _gpu_snapshot() -> dict:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,temperature.gpu,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout.strip()
        parts = [p.strip() for p in out.split(",")]
        return {
            "vram_used_mib": int(parts[0]), "vram_total_mib": int(parts[1]),
            "temp_c": int(parts[2]), "util_pct": int(parts[3]),
        }
    except Exception as exc:
        return {"error": str(exc)}


def _kill_carla() -> None:
    # PowerShell Stop-Process, NOT taskkill from this shell (documented C20
    # gotcha: `taskkill /F` from Git Bash mangles `/F` -> `F:/` and silently
    # fails, leaving stale VRAM-holding instances).
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Stop-Process -Name CarlaUE4-Win64-Shipping,CarlaUE4 -Force -ErrorAction SilentlyContinue"],
        capture_output=True, timeout=30, check=False,
    )
    time.sleep(2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("variant", choices=sorted(VARIANTS))
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--poll-interval", type=float, default=5.0)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log_path = OUT_DIR / f"{args.variant}_server.log"
    result_path = OUT_DIR / f"{args.variant}_result.json"

    print(f"[c20-tier1:{args.variant}] killing any stale CARLA + confirming VRAM clean...")
    _kill_carla()
    gpu_before = _gpu_snapshot()
    print(f"[c20-tier1:{args.variant}] GPU before launch: {gpu_before}")
    if gpu_before.get("vram_used_mib", 0) > 500:
        print(f"[c20-tier1:{args.variant}] WARNING: VRAM not clean after kill ({gpu_before}); proceeding anyway.")

    extra_args = VARIANTS[args.variant]
    cmd = [CARLA_EXE, f"-carla-rpc-port={RPC_PORT}", "-log", *extra_args]
    print(f"[c20-tier1:{args.variant}] launching: {' '.join(cmd)}")
    print(f"[c20-tier1:{args.variant}] server log -> {log_path}")

    t_launch = time.time()
    with open(log_path, "w", encoding="utf-8", errors="replace") as logf:
        proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT)

    client = carla.Client("127.0.0.1", RPC_PORT)
    client.set_timeout(2.0)

    server_version = None
    ready_elapsed = None
    samples = []
    t0 = time.time()
    while time.time() - t0 < args.timeout:
        elapsed = time.time() - t0
        gpu = _gpu_snapshot()
        samples.append({"elapsed_s": round(elapsed, 1), **gpu})
        try:
            server_version = client.get_server_version()
            ready_elapsed = elapsed
            print(f"[c20-tier1:{args.variant}] READY at {elapsed:.1f}s -- server_version={server_version}")
            break
        except Exception:
            pass
        if int(elapsed) % 30 < args.poll_interval:
            print(f"[c20-tier1:{args.variant}] still waiting at {elapsed:.1f}s -- GPU: {gpu}")
        time.sleep(args.poll_interval)

    world_loaded = False
    map_name = None
    if server_version is not None:
        try:
            client.set_timeout(20.0)
            world = client.get_world()
            map_name = world.get_map().name
            world_loaded = True
            print(f"[c20-tier1:{args.variant}] get_world() OK, map={map_name}")
        except Exception as exc:
            print(f"[c20-tier1:{args.variant}] get_world() FAILED after RPC came up: {exc}")

    gpu_final = _gpu_snapshot()
    total_elapsed = time.time() - t0

    print(f"[c20-tier1:{args.variant}] killing CARLA to reset VRAM for the next attempt...")
    proc.terminate()
    _kill_carla()
    gpu_after_kill = _gpu_snapshot()

    result = {
        "variant": args.variant,
        "cmd": cmd,
        "timeout_s": args.timeout,
        "gpu_before_launch": gpu_before,
        "server_ready": server_version is not None,
        "server_version": server_version,
        "ready_elapsed_s": ready_elapsed,
        "total_wait_elapsed_s": round(total_elapsed, 1),
        "world_loaded": world_loaded,
        "map_name": map_name,
        "gpu_final": gpu_final,
        "gpu_after_kill": gpu_after_kill,
        "gpu_samples": samples,
        "server_log": str(log_path),
    }
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"[c20-tier1:{args.variant}] result -> {result_path}")
    print(f"[c20-tier1:{args.variant}] VERDICT: {'PASS' if server_version else 'TIMEOUT'}")
    return 0 if server_version else 1


if __name__ == "__main__":
    raise SystemExit(main())
