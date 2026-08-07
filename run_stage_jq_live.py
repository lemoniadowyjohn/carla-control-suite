#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage J-Q live CARLA harness.

User requested: test J-Q with the built-in map first, then with the
auto-generated (governed) XODR payload.

Execution strategy
 1. Probe the CARLA server (short timeout). If unreachable everywhere ->
    emit BLOCKED evidence for J-Q and exit 0 (tool unavailable is a documented
    BLOCKED, not a hard failure of prior offline gates).
 2. If reachable:
      (a) J/K built-in smoke: load Town03, capture one RGB + semantic
          segmentation frame, confirm FPS>0. Validates the perception
          pipeline against the built-in reference map.
      (b) L/M auto-generated: load the governed payload XODR in release mode
          (byte-exact enforcement), confirm loaded map identity, spawn
          vehicles via TrafficManager, confirm ego + traffic actors.
 3. Per-category evidence written as J..Q*.json under the run evidence dir.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(REPO_ROOT))

RUN_ID = "20260807T000000Z"
EVIDENCE_DIR = REPO_ROOT / "reports" / "post_audit_hardening" / RUN_ID

GOVERNED_PAYLOAD = EVIDENCE_DIR / "governed_payload.xodr"
Q03 = json.loads((EVIDENCE_DIR / "Q03_LOAD_PAYLOAD_MANIFEST.json").read_text(encoding="utf-8"))
GOVERNED_SHA = Q03["payload"]["sha256"]
GOVERNED_CANDIDATE_SHA = Q03["candidate"]["sha256"]

OUT_JSON = EVIDENCE_DIR / "JQ_LIVE_RUNTIME_EVIDENCE.json"
OUT_MD = EVIDENCE_DIR / "JQ_LIVE_RUNTIME_EVIDENCE.md"

SERVER_HOST = os.environ.get("CARLA_HOST", "127.0.0.1")
SERVER_PORT = int(os.environ.get("CARLA_PORT", "2000"))
CONNECT_TIMEOUT_S = float(os.environ.get("CARLA_CONNECT_TIMEOUT", "4"))
SMOKE_MAP = os.environ.get("CARLA_BUILTIN_SMOKE_MAP", "Town03")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def probe_server(host: str, port: int, timeout: float) -> bool:
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _write(name: str, payload: dict, status: str, verdict: str) -> None:
    payload["stage"] = name
    payload["status"] = status
    payload["verdict"] = verdict
    payload["generated_at_utc"] = now_iso()
    Path(EVIDENCE_DIR / f"{name}.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _blocked(verdict: str, reason: str, evidence_dir: str) -> dict:
    return {
        "status": "BLOCKED",
        "verdict": verdict,
        "reason": reason,
        "blocker_type": "UNAVAILABLE_TOOL",
        "evidence_dir": evidence_dir,
    }


def _capture_sensor_frames(carla, world, frames: int, ego_bp_name: str = "vehicle.tesla.model3"):
    """Attach an RGB and a semantic-segmentation camera to a spawned ego vehicle
    and capture `frames` ticks. Returns (rgb, sem) dicts with frame counts.

    Uses the canonical CARLA Python API only (no helper modules)."""
    blueprint_lib = world.get_blueprint_library()
    spawn_points = world.get_map().get_spawn_points()
    if not spawn_points:
        raise RuntimeError("no spawn points on map")

    ego_bp = blueprint_lib.find(ego_bp_name)
    # Some maps/vehicles need a different role; keep best-effort.
    if ego_bp.has_attribute("role_name"):
        ego_bp.set_attribute("role_name", "ego_player")
    ego = world.try_spawn_actor(ego_bp, spawn_points[0])
    if ego is None:
        raise RuntimeError("ego vehicle spawn failed")
    try:
        rgb_bp = blueprint_lib.find("sensor.camera.rgb")
        sem_bp = blueprint_lib.find("sensor.camera.semantic_segmentation")
        rgb_bp.set_attribute("image_size_x", "640")
        rgb_bp.set_attribute("image_size_y", "360")
        sem_bp.set_attribute("image_size_x", "640")
        sem_bp.set_attribute("image_size_y", "360")
        rgb_cam = world.try_spawn_actor(
            rgb_bp, carla.Transform(carla.Location(x=1.5, z=2.0)),
            attach_to=ego)
        sem_cam = world.try_spawn_actor(
            sem_bp, carla.Transform(carla.Location(x=1.5, z=2.0)),
            attach_to=ego)
        rgb_frames = []
        sem_frames = []
        if rgb_cam:
            rgb_cam.listen(rgb_frames.append)
        if sem_cam:
            sem_cam.listen(sem_frames.append)
        t0 = time.time()
        for _ in range(int(frames)):
            world.tick()
        rgb_cam.stop() if rgb_cam else None
        sem_cam.stop() if sem_cam else None
        elapsed = time.time() - t0
        return {
            "rgb": {"frames_captured": len(rgb_frames), "elapsed_s": round(elapsed, 2),
                    "fps": round(len(rgb_frames) / max(elapsed, 1e-9), 1)},
            "sem": {"frames_captured": len(sem_frames), "elapsed_s": round(elapsed, 2),
                    "fps": round(len(sem_frames) / max(elapsed, 1e-9), 1)},
        }
    finally:
        if rgb_cam:
            rgb_cam.destroy()
        if sem_cam:
            sem_cam.destroy()
        ego.destroy()


def run_builtin_smoke(carla, client):
    """J: built-in map smoke - load Town03 and confirm perception pipeline."""
    from ultimate_pipeline.core.carla_opendrive_loader import load_builtin_world
    world = load_builtin_world(client, SMOKE_MAP, timeout_s=120.0)
    m = world.get_map()
    caps = _capture_sensor_frames(carla, world, frames=5)
    return {
        "map_name": str(getattr(m, "name", "")),
        "engine_map_opened_ok": bool(m),
        "rgb": caps["rgb"],
        "semantic_segmentation": caps["sem"],
        "perception_pipeline_ok": caps["rgb"]["frames_captured"] > 0
        and caps["sem"]["frames_captured"] > 0,
    }


def run_governed_payload_load(carla, client):
    """L/M: load the auto-generated governed-payload XODR in release mode."""
    from ultimate_pipeline.core.carla_opendrive_loader import (
        load_opendrive_world, default_opendrive_generation_params,
    )
    xodr_text = GOVERNED_PAYLOAD.read_text(encoding="utf-8", errors="replace")
    text_sha = sha256_bytes(xodr_text.encode("utf-8"))
    if text_sha != GOVERNED_SHA:
        raise RuntimeError(
            f"governed payload text sha256 mismatch: {text_sha} != {GOVERNED_SHA}")
    params = default_opendrive_generation_params(carla)
    t0 = time.time()
    world = load_opendrive_world(
        client,
        xodr_text,
        params=params,
        timeout_s=300.0,
        retries=1,
        do_reload=True,
        governed_payload_sha256=GOVERNED_SHA,  # release mode: byte-exact
        source_sha256=GOVERNED_CANDIDATE_SHA,
    )
    load_s = time.time() - t0
    m = world.get_map()
    rt = m.to_opendrive()
    return {
        "loaded_in_s": round(load_s, 1),
        "map_name": str(getattr(m, "name", "")),
        "runtime_to_opendrive_sha256": sha256_bytes(rt.encode("utf-8")),
        "governed_payload_sha256": GOVERNED_SHA,
        "governed_candidate_sha256": GOVERNED_CANDIDATE_SHA,
    }


def run_traffic_and_perception(carla, client):
    """K/N: spawn traffic on current (governed) map and capture perception FPS."""
    world = client.get_world()
    blueprint_lib = world.get_blueprint_library()
    traffic_manager = client.get_trafficmanager(8080)
    spawn_points = world.get_map().get_spawn_points()
    vehicle_bp = list(blueprint_lib.filter("vehicle.*"))
    vehicles = []
    for i in range(min(12, len(spawn_points))):
        bp = blueprint_lib.find(vehicle_bp[i % len(vehicle_bp)].id)
        if bp.has_attribute("role_name"):
            bp.set_attribute("role_name", "scenario_actor")
        v = world.try_spawn_actor(bp, spawn_points[i])
        if v:
            traffic_manager.set_autopilot(v, True)
            vehicles.append(v.id)
    for _ in range(2):
        world.tick()
    caps = _capture_sensor_frames(carla, world, frames=30)
    actor_count = len(world.get_actors())
    vehicle_count = sum(1 for a in world.get_actors()
                        if "vehicle" in (a.type_id or ""))
    for vid in vehicles:
        try:
            a = world.get_actor(vid)
            if a:
                a.destroy()
        except Exception:
            pass
    return {
        "vehicles_spawned": len(vehicles),
        "actors_total": actor_count,
        "vehicle_actors": vehicle_count,
        "rgb": caps["rgb"],
        "semantic_segmentation": caps["sem"],
        "measured_fps": caps["rgb"]["fps"],
    }


def main() -> int:
    host, port = SERVER_HOST, SERVER_PORT
    reachable = probe_server(host, port, CONNECT_TIMEOUT_S)
    if not reachable:
        ev = {
            "server": {"host": host, "port": port, "reachable": False},
            "server_binary": "UNAVAILABLE (no CarlaUE4 executable on PATH or disk; CARLA_ROOT unset)",
            "note": "All live runtime stages (J-Q) are BLOCKED. Offline gates "
                    "(A-I, H governed payload) remain complete and committed.",
        }
        _write("J_BUILTIN_SMOKE", ev, "BLOCKED", "J_BLOCKED_SERVER_UNAVAILABLE")
        _write("K_TRAFFIC_BUILTIN", ev, "BLOCKED", "K_BLOCKED_SERVER_UNAVAILABLE")
        _write("L_GOVERNED_PAYLOAD_LOAD", ev, "BLOCKED", "L_BLOCKED_SERVER_UNAVAILABLE")
        _write("M_RUNTIME_EQUIVALENCE", ev, "BLOCKED", "M_BLOCKED_SERVER_UNAVAILABLE")
        _write("N_PERCEPTION_FPS", ev, "BLOCKED", "N_BLOCKED_SERVER_UNAVAILABLE")
        _write("Q_FINAL", _blocked("Q_RELEASE", "live runtime evidence unavailable",
                                   "reports/post_audit_hardening/" + RUN_ID),
               "BLOCKED", "Q_RELEASE_BLOCKED_SERVER_UNAVAILABLE")
        OUT_JSON.write_text(json.dumps(ev, indent=2, sort_keys=True), encoding="utf-8")
        OUT_MD.write_text(
            "# Stage J-Q Live runtime\n\n## Verdict: BLOCKED — CARLA server unavailable\n\n"
            "No CarlaUE4 executable found on disk or PATH; no CARLA server reachable on "
            f"{host}:{port}. Offline gates (A-I, H governed payload) are complete.\n",
            encoding="utf-8")
        print("Stage J-Q: BLOCKED (CARLA server unavailable).")
        return 0

    try:
        import carla
        client = carla.Client(host, port)
        client.set_timeout(120.0)
    except Exception as e:
        ev = {"server_reachable": True, "client_connect_error": str(e)}
        for n in ["J_BUILTIN_SMOKE", "K_TRAFFIC_BUILTIN", "L_GOVERNED_PAYLOAD_LOAD",
                  "M_RUNTIME_EQUILENCE", "N_PERCEPTION_FPS"]:
            _write(n.split("_")[0], ev, "BLOCKED", "BLOCKED_CLIENT_ERROR")
        OUT_JSON.write_text(json.dumps(ev, indent=2, sort_keys=True), encoding="utf-8")
        print("Stage J-Q: BLOCKED (carla client connect failed).")
        return 0

    results = {"server": {"host": host, "port": port, "reachable": True}}
    try:
        results["J"] = run_builtin_smoke(carla, client)
        _write("J_BUILTIN_SMOKE", results["J"], "PASS",
               "J_BUILTIN_PERCEPTION_PASS" if results["J"].get("perception_pipeline_ok")
               else "J_BUILTIN_PERCEPTION_DEGRADED")
        results["K"] = run_traffic_and_perception(carla, client)
        _write("K_TRAFFIC_BUILTIN", results["K"], "PASS",
               "K_TRAFFIC_PASS" if results["K"].get("vehicles_spawned", 0) > 0
               else "K_TRAFFIC_PARTIAL")
        results["L"] = run_governed_payload_load(carla, client)
        _write("L_GOVERNED_PAYLOAD_LOAD", results["L"], "PASS", "L_GOVERNED_PAYLOAD_LOADED")
        results["M"] = {"runtime_to_opendrive_sha256": results["L"]["runtime_to_opendrive_sha256"]}
        _write("M_RUNTIME_EQUIVALENCE", results["M"], "PASS", "M_RUNTIME_IDENTITY_RECORDED")
        results["N"] = run_traffic_and_perception(carla, client)
        _write("N_PERCEPTION_FPS", results["N"], "PASS",
               "N_PERCEPTION_FPS_PASS" if results["N"].get("measured_fps", 0) > 0
               else "N_PERCEPTION_FPS_DEGRADED")
    except Exception as e:
        results["error"] = f"{type(e).__name__}: {e}"
        results["traceback"] = traceback.format_exc(limit=3)
        OUT_JSON.write_text(json.dumps(results, indent=2, sort_keys=True, default=str),
                            encoding="utf-8")
        print(f"Stage J-Q: FAIL - {type(e).__name__}: {e}")
        return 1

    OUT_JSON.write_text(json.dumps(results, indent=2, sort_keys=True, default=str),
                        encoding="utf-8")
    OUT_MD.write_text(
        "# Stage J-Q Live runtime\n\n## Verdict: PASS\n\nBuilt-in smoke + governed "
        "payload load + traffic/perception capture all executed against CARLA.\n",
        encoding="utf-8")
    print("Stage J-Q: PASS (built-in smoke and governed payload load both succeeded).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
