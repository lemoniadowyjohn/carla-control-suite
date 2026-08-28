#!/usr/bin/env python3
"""
Phase 1 Minimal Smoke Test: Map-identity guard + procedural Ingolstadt liveness.

- Launches/connects to CARLA server on E:\CARLA\CARLA_0.9.16\CarlaUE4.exe
- load_opendrive_world(governed XODR 248ffbbe)
- assert map.name == OpenDriveMap (not Town10/*_Opt)
- get_crosswalks() == 66, get_all_landmarks() == 3467
- Spawn ego + sensor rig (RGB + LiDAR via DominikSensorSetup)
- Capture >=1 non-empty frame per sensor
- Emit PROC_SMOKE.json with hard verdict
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path(os.environ.get("PROC_SMOKE_LOG_DIR", str(Path(__file__).parent.parent / "reports" / "post_audit_hardening" / "_proc_smoke_log")))
LOG_DIR.mkdir(parents=True, exist_ok=True)
PROGRESS_LOG = LOG_DIR / "progress.log"

def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with PROGRESS_LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

# Add repo root to path
REPO_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))

from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world_from_file, CarlaOpendrivePreflightError
from ultimate_pipeline.sensors.dominik_sensor_setup import DominikSensorSetup, compute_lidar_attributes
from ultimate_pipeline.sensors.recorder import RecorderConfig, SensorRecorder

GOVERNED_XODR = Path(os.environ.get(
    "PROC_SMOKE_XODR",
    str(REPO_ROOT / "campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_final.xodr"),
))
# When validating a repaired (non-frozen) XODR, set PROC_SMOKE_PATCHED=1. The loader's
# release-mode mismatch check is disabled, and evidence records both the original
# governed sha (`original_governed_xodr_sha256`) and the patched file's sha
# (`patched_xodr_sha256`). Used to v-validate the road-length repair before re-governing.
SMOKE_PATCHED = os.environ.get("PROC_SMOKE_PATCHED", "0") == "1"
CALIB_JSON = REPO_ROOT / "submission/infrastructure/ultimate_pipeline/sensors/calib_data.json"
CARLA_EXE = Path(r"E:\CARLA\CARLA_0.9.16\CarlaUE4.exe")
CARLA_ROOT = Path(r"E:\CARLA\CARLA_0.9.16")

EXPECTED = {
    "map_name": "OpenDriveMap",
    "crosswalk_count": 66,
    "landmark_count": 3467,
    "governed_xodr_sha256": "248ffbbe6a1aa2a9cbd4330a69ad1c1680d39698e2d186dd45f5a2eb91c5db6c",
}

# Sensor rig config (match C3 frozen protocol where feasible)
LOW_MEM = True  # 4 GB VRAM -> low_mem=True
RESOLUTION_OVERRIDE = (960, 540)  # half-res for VRAM
# OpenDRIVE generation params (recorded in evidence): coarser vertex_distance
# for procedural-feasibility on this host (Quadro P3200 4GB, i7-8850H).
# The governed payload (XODR topology: crosswalks/landmarks) is unaffected.
OD_VERTEX_DISTANCE = float(os.environ.get("PROC_SMOKE_OD_VERTEX_DISTANCE", "3.0"))
os.environ["UP_OD_VERTEX_DISTANCE"] = str(OD_VERTEX_DISTANCE)
os.environ.setdefault("UP_OD_SMOOTH_JUNCTIONS", os.environ.get("PROC_SMOKE_OD_SMOOTH", "1"))


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _tcp_port_open(host: str, port: int, timeout_s: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except Exception:
        return False


def _wait_port(host: str, port: int, deadline_s: float = 60.0, probe_s: float = 0.5) -> bool:
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        if _tcp_port_open(host, port, probe_s):
            return True
        time.sleep(0.5)
    return False


def launch_carla_server() -> subprocess.Popen:
    """Launch CARLA server from E:\CARLA\CARLA_0.9.16\CarlaUE4.exe"""
    if not CARLA_EXE.exists():
        raise RuntimeError(f"CarlaUE4.exe not found at {CARLA_EXE}")

    env = os.environ.copy()
    env["CARLA_ROOT"] = str(CARLA_ROOT)

    cmd = [
        str(CARLA_EXE),
        "-carla-rpc-port=2000",
        "-carla-streaming-port=2001",
        "-quality-level=Low",
        "-nosound",
        "-windowed",
        "-ResX=1280",
        "-ResY=720",
    ]
    log(f"[PROC_SMOKE] Launching: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, env=env, cwd=str(CARLA_ROOT),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    # Start a thread to read stderr
    def read_stderr():
        for line in proc.stderr:
            log(f"[CARLA_SERVER_STDERR] {line.decode('utf-8', errors='replace').rstrip()}")
    def read_stdout():
        for line in proc.stdout:
            log(f"[CARLA_SERVER_STDOUT] {line.decode('utf-8', errors='replace').rstrip()}")
    
    threading.Thread(target=read_stderr, daemon=True).start()
    threading.Thread(target=read_stdout, daemon=True).start()
    
    return proc


def wait_server_ready(host: str = "127.0.0.1", rpc_port: int = 2000, streaming_port: int = 2001, timeout_s: float = 180.0) -> bool:
    log(f"[PROC_SMOKE] Waiting for RPC port {rpc_port}...")
    if not _wait_port(host, rpc_port, deadline_s=timeout_s):
        return False
    log(f"[PROC_SMOKE] RPC port ready. Waiting for streaming port {streaming_port}...")
    if not _wait_port(host, streaming_port, deadline_s=60.0):
        return False
    log("[PROC_SMOKE] Server ports ready. Waiting additional 10s for server to fully initialize...")
    time.sleep(10)
    return True


def run_smoke() -> dict:
    result = {
        "schema": "PROC_SMOKE/v1",
        "run_id": f"20260811T{datetime.now(timezone.utc).strftime('%H%M%S')}Z_PROC_SMOKE",
        "branch": "fix/post-audit-phase-e-junctions-roundabouts-20260803",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "verdict": "FAIL",
        "checks": {},
    }

    server_proc = None
    client = None
    world = None
    actors = {}

    try:
        # 0) Launch server
        log("[PROC_SMOKE] Step 0: Launch CARLA server...")
        server_proc = launch_carla_server()
        if not wait_server_ready():
            result["checks"]["server_launch"] = {"ok": False, "error": "Server ports did not become ready"}
            return result
        result["checks"]["server_launch"] = {"ok": True}

        # 1) Connect client and wait for server readiness
        import carla
        client = carla.Client("127.0.0.1", 2000)
        client.set_timeout(60.0)
        log("[PROC_SMOKE] Step 1: Waiting for server readiness...")
        # Use the loader's wait_for_carla_ready to ensure server responds
        from ultimate_pipeline.core.carla_opendrive_loader import wait_for_carla_ready
        world = wait_for_carla_ready(
            client,
            timeout_s=120.0,
            probe_timeout_s=5.0,  # longer probe timeout
            ready_ticks=3,
            tick_timeout_s=5.0,
            restore_timeout_s=60.0,
        )
        log(f"[PROC_SMOKE] Server ready. Current map: {world.get_map().name}")

        # 2) Load the OpenDRIVE payload. Two modes:
        #  - Governed   : release-mode sha check enforced (governed_payload_sha256 set).
        #  - Patched    : validating a repaired XODR (PROC_SMOKE_PATCHED=1). The file's
        #                   sha is recorded; release-mode check is OFF because the bytes
        #                   are a repair of the original governed artifact.
        log(f"[PROC_SMOKE] Step 2: Load XODR {GOVERNED_XODR} (patched={SMOKE_PATCHED}) ...")
        t_load0 = time.monotonic()
        file_sha = _sha256_of_file(GOVERNED_XODR)
        result["checks"]["xodr_source"] = {
            "path": str(GOVERNED_XODR),
            "file_sha256": file_sha,
            "original_governed_xodr_sha256": EXPECTED["governed_xodr_sha256"],
            "patched": SMOKE_PATCHED,
        }
        try:
            if SMOKE_PATCHED:
                world = load_opendrive_world_from_file(
                    client,
                    GOVERNED_XODR,
                    timeout_s=5400.0,
                    retries=0,
                    do_reload=False,
                    ready_timeout_s=240.0,
                    source_sha256=file_sha,
                )
                result["checks"]["xodr_source"]["patched_xodr_sha256"] = file_sha
            else:
                world = load_opendrive_world_from_file(
                    client,
                    GOVERNED_XODR,
                    timeout_s=5400.0,
                    retries=0,
                    do_reload=False,
                    ready_timeout_s=240.0,
                    source_sha256=EXPECTED["governed_xodr_sha256"],
                    governed_payload_sha256=EXPECTED["governed_xodr_sha256"],
                )
        except CarlaOpendrivePreflightError as e:
            result["checks"]["xodr_preflight"] = {"ok": False, "error": str(e)}
            return result
        except Exception as e:
            result["checks"]["xodr_load"] = {
                "ok": False,
                "error": str(e),
                "generation_elapsed_s": round(time.monotonic() - t_load0, 3),
                "od_vertex_distance": OD_VERTEX_DISTANCE,
                "od_smooth_junctions": os.environ.get("UP_OD_SMOOTH_JUNCTIONS"),
            }
            return result

        result["checks"]["xodr_load"] = {
            "ok": True,
            "generation_elapsed_s": round(time.monotonic() - t_load0, 3),
            "od_vertex_distance": OD_VERTEX_DISTANCE,
            "od_smooth_junctions": os.environ.get("UP_OD_SMOOTH_JUNCTIONS"),
        }

        # 3) Map identity guard
        map_obj = world.get_map()
        map_name = str(getattr(map_obj, "name", "") or "")
        log(f"[PROC_SMOKE] Map name: {map_name}")

        if map_name != EXPECTED["map_name"]:
            result["checks"]["map_identity"] = {
                "ok": False,
                "error": f"Expected map '{EXPECTED['map_name']}', got '{map_name}'",
                "actual_map_name": map_name,
            }
            return result
        result["checks"]["map_identity"] = {"ok": True, "map_name": map_name}

        # 4) Crosswalks + landmarks
        crosswalks = map_obj.get_crosswalks()
        landmarks = map_obj.get_all_landmarks()
        crosswalk_count = len(crosswalks)
        landmark_count = len(landmarks)
        log(f"[PROC_SMOKE] Crosswalks: {crosswalk_count}, Landmarks: {landmark_count}")

        if crosswalk_count != EXPECTED["crosswalk_count"]:
            result["checks"]["crosswalks"] = {
                "ok": False,
                "error": f"Expected {EXPECTED['crosswalk_count']} crosswalks, got {crosswalk_count}",
                "actual": crosswalk_count,
            }
            return result
        if landmark_count != EXPECTED["landmark_count"]:
            result["checks"]["landmarks"] = {
                "ok": False,
                "error": f"Expected {EXPECTED['landmark_count']} landmarks, got {landmark_count}",
                "actual": landmark_count,
            }
            return result

        result["checks"]["crosswalks"] = {"ok": True, "count": crosswalk_count}
        result["checks"]["landmarks"] = {"ok": True, "count": landmark_count}

        # 5) Spawn ego vehicle
        bp_lib = world.get_blueprint_library()
        vehicle_bp = bp_lib.filter("vehicle.*")[0]
        spawn_points = map_obj.get_spawn_points()
        if not spawn_points:
            result["checks"]["ego_spawn"] = {"ok": False, "error": "No spawn points"}
            return result
        vehicle = world.try_spawn_actor(vehicle_bp, spawn_points[0])
        if not vehicle:
            result["checks"]["ego_spawn"] = {"ok": False, "error": "Failed to spawn vehicle"}
            return result
        actors["ego"] = vehicle
        result["checks"]["ego_spawn"] = {"ok": True}

        # 6) Sensor rig (DominikSensorSetup)
        log("[PROC_SMOKE] Step 6: Spawn sensor rig...")
        rig = DominikSensorSetup(
            str(CALIB_JSON),
            flip_vehicle_y=True,
            opencv_camera_axes=True,
            lidar_axes_mode="auto",
            resolution_override=RESOLUTION_OVERRIDE if LOW_MEM else None,
        )
        sensor_actors = rig.spawn_on_vehicle(
            world,
            vehicle,
            include_segmentation=True,
            low_mem=LOW_MEM,
            strict=True,
            min_sensors=6,  # 5 cameras + 1 lidar
        )
        actors.update(sensor_actors)
        log(f"[PROC_SMOKE] Spawned sensors: {list(sensor_actors.keys())}")
        result["checks"]["sensor_spawn"] = {"ok": True, "sensors": list(sensor_actors.keys())}

        # 7) SensorRecorder - capture at least 1 frame per sensor
        log("[PROC_SMOKE] Step 7: Capture frames...")
        out_dir = REPO_ROOT / "reports" / "post_audit_hardening" / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_PROC_SMOKE"
        out_dir.mkdir(parents=True, exist_ok=True)

        recorder_config = RecorderConfig(
            fps=20,
            synchronous=True,
            fixed_delta_seconds=0.05,
            sensor_timeout_s=2.0,
        )
        recorder = SensorRecorder(
            world=world,
            ego_vehicle=vehicle,
            sensors=sensor_actors,
            out_dir=str(out_dir),
            cfg=recorder_config,
        )

        # Tick a few times to capture frames
        for i in range(10):
            world.tick(2.0)
            time.sleep(0.1)

        recorder.stop()
        recorder.close()

        # Verify each sensor got >=1 frame
        diag = recorder.get_diagnostics()
        frame_counts = diag.get("per_sensor_frame_counts", {})
        log(f"[PROC_SMOKE] Frame counts: {frame_counts}")

        all_nonempty = all(c > 0 for c in frame_counts.values())
        if not all_nonempty:
            result["checks"]["sensor_frames"] = {
                "ok": False,
                "error": "Some sensors delivered 0 frames",
                "frame_counts": frame_counts,
            }
            return result

        result["checks"]["sensor_frames"] = {"ok": True, "frame_counts": frame_counts}

        # All checks passed
        result["verdict"] = "PASS"
        log("[PROC_SMOKE] ALL CHECKS PASSED")

    except Exception as e:
        result["checks"]["exception"] = {"ok": False, "error": str(e)}
        log(f"[PROC_SMOKE] EXCEPTION: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # Cleanup
        for actor in list(actors.values()):
            try:
                if actor is not None and hasattr(actor, "is_alive") and actor.is_alive:
                    actor.destroy()
            except Exception:
                pass
        if server_proc:
            log("[PROC_SMOKE] Terminating server (process tree)...")
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(server_proc.pid), "/T", "/F"],
                    capture_output=True, timeout=15,
                )
            except Exception:
                pass

    return result


if __name__ == "__main__":
    result = run_smoke()
    out_dir = REPO_ROOT / "reports" / "post_audit_hardening" / result["run_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "PROC_SMOKE.json"
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    log(f"[PROC_SMOKE] Evidence written to {out_path}")
    log(f"[PROC_SMOKE] VERDICT: {result['verdict']}")
    sys.exit(0 if result["verdict"] == "PASS" else 1)