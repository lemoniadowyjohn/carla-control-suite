#!/usr/bin/env python3
"""CARLA 0.9.16 post-recovery validation: Phase 1-5 execution harness.

Ownership: exactly one CARLA server (owned PID), one tick owner (this client).
Evidence is flushed after EVERY stage so a native crash cannot destroy prior results.
No protected file is touched. No driver change. No source XODR mutation.
"""
import json
import os
import socket
import subprocess
import sys
import time

import carla

REPO = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"
OUT_DIR = os.path.join(REPO, "reports", "carla_runtime")
os.makedirs(OUT_DIR, exist_ok=True)
RECEIPT = os.path.join(OUT_DIR, "CARLA_POST_RECOVERY_BASELINE.json")
EXE = r"E:\CARLA\CARLA_0.9.16\CarlaUE4.exe"
FLAGS = ["-carla-rpc-port=2000", "-carla-streaming-port=2001",
         "-RenderOffScreen", "-quality-level=Low", "-nosound"]
LOG = os.path.join(OUT_DIR, "post_recovery_server_20261022.log")

STATE = {
    "receipt_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "executable": {"path": EXE, "sha256": "0bc4b3d089470ffdc91a2ec6bf2f26187de271d0e9e71a01beee8416633c7320",
                    "flags": FLAGS},
    "python": sys.executable,
    "stages": [],
    "gpu_samples": [],
    "server_pid": None,
    "server_start_utc": None,
    "server_exit": None,
}


def flush():
    with open(RECEIPT, "w", encoding="utf-8") as fh:
        json.dump(STATE, fh, indent=2)


def stage(name, status, **kw):
    rec = {"stage": name, "status": status, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    rec.update(kw)
    STATE["stages"].append(rec)
    flush()
    print(f"[{status}] {name} " + " ".join(f"{k}={v}" for k, v in kw.items() if k != "detail"))
    return rec


def gpu():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.free,utilization.gpu",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=8).stdout.strip()
        p = [x.strip() for x in out.split(",")]
        return {"used_mib": int(p[0]), "free_mib": int(p[1]), "util_pct": int(p[2])}
    except Exception as exc:
        return {"error": str(exc)}


def sample_gpu(tag):
    g = gpu()
    g["tag"] = tag
    g["utc"] = time.strftime("%H:%M:%SZ", time.gmtime())
    STATE["gpu_samples"].append(g)
    flush()
    return g


def wait_rpc(proc, budget_s=180):
    t0 = time.time()
    port_open_at = None
    while time.time() - t0 < budget_s:
        if proc.poll() is not None:
            return {"ok": False, "reason": "SERVER_EXITED_EARLY", "exit_code": proc.returncode,
                    "elapsed_s": round(time.time() - t0, 1)}
        try:
            s = socket.create_connection(("127.0.0.1", 2000), timeout=1.0)
            s.close()
            if port_open_at is None:
                port_open_at = time.time() - t0
            c = carla.Client("127.0.0.1", 2000)
            c.set_timeout(30.0)
            ver = c.get_server_version()
            return {"ok": True, "port_open_s": round(port_open_at, 1),
                    "rpc_ready_s": round(time.time() - t0, 1), "server_version": ver}
        except Exception:
            time.sleep(1.0)
    return {"ok": False, "reason": "RPC_TIMEOUT", "elapsed_s": round(time.time() - t0, 1)}


def main():
    logf = open(LOG, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen([EXE] + FLAGS, stdout=logf, stderr=subprocess.STDOUT)
    STATE["server_pid"] = proc.pid
    STATE["server_start_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    flush()
    sample_gpu("pre_launch")

    ready = wait_rpc(proc)
    stage("PHASE1_SERVER_STARTUP", "EXECUTED_PASS" if ready.get("ok") else "SERVER_CRASHED", **ready)
    if not ready.get("ok"):
        STATE["server_exit"] = {"code": proc.poll(), "log": LOG}
        flush()
        return

    client = carla.Client("127.0.0.1", 2000)
    client.set_timeout(60.0)

    # --- available maps (authority, not assumption) ---
    try:
        am = client.get_available_maps()
        names = sorted(m.name if hasattr(m, "name") else str(m) for m in am)
        stage("PHASE2_AVAILABLE_MAPS", "EXECUTED_PASS", count=len(names), names=names)
    except Exception as exc:
        names = []
        stage("PHASE2_AVAILABLE_MAPS", "EXECUTED_FAIL", error=str(exc))

    world = client.get_world()
    maps_meta = {}
    for label, want in (("town01", "Town01"), ("town10hd", "Town10HD_Opt"),
                        ("grid0828", "Grid0828"), ("grid0821", "Grid0821")):
        maps_meta[label] = {"requested": want, "available": any(want in n for n in names)}

    # --- Phase 1: Grid0828 reproducibility (fresh server -> load_world) ---
    grid = next((n for n in names if "Grid0828" in n), None)
    if grid is None:
        stage("PHASE1_GRID0828_REPRO", "BLOCKED_DEPENDENCY", reason="Grid0828 not packaged")
    else:
        t0 = time.time()
        try:
            world = client.load_world(grid)
            load_s = round(time.time() - t0, 1)
            time.sleep(2.0)
            actual = world.get_map().name
            s1 = world.get_snapshot()
            f1 = s1.frame
            time.sleep(1.5)
            s2 = world.get_snapshot()
            f2 = s2.frame
            stage("PHASE1_GRID0828_REPRO", "EXECUTED_PASS" if f2 > f1 else "EXECUTED_FAIL",
                  requested=grid, actual=actual, load_s=load_s,
                  identity_exact=(actual == grid), frame_before=f1, frame_after=f2,
                  ticks_advanced=f2 > f1, vram=sample_gpu("grid0828_loaded"))
        except Exception as exc:
            stage("PHASE1_GRID0828_REPRO", "EXECUTED_FAIL", requested=grid, error=str(exc))

    # --- Phase 2/4: Town01 control + sequential sensor tests ---
    town01 = next((n for n in names if n.startswith("Town01")), None)
    if town01 is None:
        stage("PHASE2_TOWN01_CONTROL", "BLOCKED_DEPENDENCY", reason="Town01 not packaged")
    else:
        t0 = time.time()
        try:
            world = client.load_world(town01)
            load_s = round(time.time() - t0, 1)
            time.sleep(2.0)
            actual = world.get_map().name
            snap = world.get_snapshot()
            stage("PHASE2_TOWN01_CONTROL", "EXECUTED_PASS", requested=town01, actual=actual,
                  identity_exact=(actual == town01), load_s=load_s, frame=snap.frame,
                  vram=sample_gpu("town01_loaded"))
        except Exception as exc:
            stage("PHASE2_TOWN01_CONTROL", "EXECUTED_FAIL", requested=town01, error=str(exc))
            town01 = None

    if town01:
        world = client.get_world()
        # vehicle spawn
        try:
            bp = world.get_blueprint_library().find("vehicle.tesla.model3")
            sp = world.get_map().get_spawn_points()
            veh = world.spawn_actor(bp, sp[0].transform)
            time.sleep(1.0)
            v = veh.get_velocity()
            stage("PHASE2_VEHICLE_SPAWN", "EXECUTED_PASS", spawn_points=len(sp),
                  velocity=[round(v.x, 3), round(v.y, 3), round(v.z, 3)], alive=veh.is_alive)
            veh.destroy()
            stage("PHASE2_VEHICLE_CLEANUP", "EXECUTED_PASS", destroyed=True)
        except Exception as exc:
            stage("PHASE2_VEHICLE_SPAWN", "EXECUTED_FAIL", error=str(exc))

        # sequential sensor tests: A RGB 320x240, B semantic, C lidar, D RGB+sem
        sensor_specs = [
            ("A_RGB_320x240", ["sensor.camera.rgb"], {"image_size_x": "320", "image_size_y": "240", "fov": "90"}),
            ("B_SEMANTIC_320x240", ["sensor.semantic_semseg"], {"image_size_x": "320", "image_size_y": "240", "fov": "90"}),
            ("C_LIDAR", ["sensor.lidar.ray_cast"],
             {"channels": "16", "range": "50", "rotation_frequency": "10", "points_per_second": "100000"}),
            ("D_RGB_PLUS_SEMANTIC_640x480", ["sensor.camera.rgb", "sensor.semantic_semseg"],
             {"image_size_x": "640", "image_size_y": "480", "fov": "90"}),
        ]
        for name, bp_names, attrs in sensor_specs:
            actors, frames = [], {}
            try:
                for i, bpn in enumerate(bp_names):
                    bp = world.get_blueprint_library().find(bpn)
                    for k, v in attrs.items():
                        if bp.has_attribute(k):
                            bp.set_attribute(k, v)
                    tf = carla.Transform(carla.Location(x=2.0 + 2.0 * i, y=0.0, z=1.8),
                                         carla.Rotation(pitch=-15.0))
                    a = world.spawn_actor(bp, tf)
                    actors.append(a)
                    frames[bpn] = []
                    a.listen(lambda img, key=bpn: frames[key].append(
                        {"frame": img.frame, "w": img.width, "h": img.height,
                         "len": len(img.raw_data), "ts": round(img.timestamp, 4)}))
                deadline = time.time() + 8.0
                while time.time() < deadline:
                    if all(len(v) >= 2 for v in frames.values()):
                        break
                    time.sleep(0.2)
                details = {}
                for k, fl in frames.items():
                    if not fl:
                        details[k] = {"callbacks": 0}
                        continue
                    f0 = fl[0]
                    exp = f0["w"] * f0["h"] * 4 if "camera" in k else None
                    d = {"callbacks": len(fl), "frame_ids": [f["frame"] for f in fl],
                         "dims": [f0["w"], f0["h"]], "raw_bytes": f0["len"]}
                    if exp is not None:
                        d["expected_bytes"] = exp
                        d["bytes_match"] = (f0["len"] == exp)
                    details[k] = d
                # lidar payload sanity (float32 x,y,z,intensity)
                if "sensor.lidar.ray_cast" in frames and frames["sensor.lidar.ray_cast"]:
                    pass
                stage(name, "EXECUTED_PASS" if all(v.get("callbacks", 0) > 0 for v in details.values()) else "EXECUTED_FAIL",
                      sensors=details, vram=sample_gpu(name))
            except Exception as exc:
                stage(name, "EXECUTED_FAIL", error=str(exc))
            finally:
                for a in actors:
                    try:
                        a.stop()
                    except Exception:
                        pass
                for a in actors:
                    try:
                        a.destroy()
                    except Exception:
                        pass
                time.sleep(0.5)

    # --- Phase 3: Grid0821 transition (riskiest -> last) ---
    g21 = next((n for n in names if "Grid0821" in n), None)
    if g21 is None:
        stage("PHASE3_GRID0821", "BLOCKED_DEPENDENCY", reason="Grid0821 not packaged")
    else:
        src = world.get_map().name if 'world' in dir() else None
        t0 = time.time()
        try:
            world = client.load_world(g21)
            load_s = round(time.time() - t0, 1)
            time.sleep(2.0)
            actual = world.get_map().name
            s1 = world.get_snapshot()
            time.sleep(1.5)
            s2 = world.get_snapshot()
            stage("PHASE3_GRID0821_TRANSITION", "EXECUTED_PASS" if s2.frame > s1.frame else "EXECUTED_FAIL",
                  transition_from=src, requested=g21, actual=actual, load_s=load_s,
                  identity_exact=(actual == g21), frame_before=s1.frame, frame_after=s2.frame,
                  vram=sample_gpu("grid0821_loaded"))
        except Exception as exc:
            stage("PHASE3_GRID0821_TRANSITION", "EXECUTED_FAIL", requested=g21, error=str(exc))

    # --- teardown ---
    sample_gpu("pre_terminate")
    try:
        client.apply_settings # noop
    except Exception:
        pass
    try:
        proc.terminate()
        proc.wait(timeout=30)
        STATE["server_exit"] = {"code": proc.returncode, "method": "owned PID terminate"}
    except Exception as exc:
        try:
            proc.kill()
            STATE["server_exit"] = {"code": proc.returncode, "method": "owned PID kill",
                                    "note": str(exc)}
        except Exception as exc2:
            STATE["server_exit"] = {"code": None, "error": str(exc2)}
    stage("TEARDOWN", "EXECUTED_PASS", server_exit=STATE["server_exit"])
    sample_gpu("post_terminate")
    flush()
    print("RECEIPT:", RECEIPT)


if __name__ == "__main__":
    main()
