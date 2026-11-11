#!/usr/bin/env python3
"""Town01 semantic + LiDAR test — VRAM-guided 320x240."""
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

EXE = r"E:\CARLA\CARLA_0.9.16\CarlaUE4.exe"
FLAGS = ["-carla-rpc-port=2000", "-carla-streaming-port=2001",
         "-RenderOffScreen", "-quality-level=Low", "-nosound"]
LOG = os.path.join(OUT_DIR, f"town01_sensors_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.log")

EVIDENCE = {
    "task_id": "TOWN01_SENSORS_MAIN_AGENT",
    "source_sha": "69c818be",
    "start_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "executable": {"path": EXE, "flags": FLAGS},
    "server": {"pid": None, "started": False, "rpc_ready": False},
    "map": {"requested": "Town01", "identity": None, "ticks_advanced": False},
    "sensors": {
        "semantic": {"tested": False, "callbacks": 0, "frame_ids": [], "shape": None},
        "lidar": {"tested": False, "callbacks": 0, "frame_ids": [], "point_counts": []}
    },
    "vram_samples": [],
    "exit": {"code": None, "method": None},
    "verdict": None
}


def gpu_sample(tag):
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.free,utilization.gpu",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=8).stdout.strip()
        p = [int(x.strip()) for x in out.split(",")]
        return {"tag": tag, "utc": time.strftime("%H:%M:%SZ", time.gmtime()),
                "used_mib": p[0], "free_mib": p[1], "util_pct": p[2]}
    except Exception as exc:
        return {"tag": tag, "error": str(exc)}


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


def flush():
    with open(os.path.join(OUT_DIR, "TOWN01_SENSORS_EVIDENCE.json"), "w", encoding="utf-8") as fh:
        json.dump(EVIDENCE, fh, indent=2)


def main():
    logf = open(LOG, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen([EXE] + FLAGS, stdout=logf, stderr=subprocess.STDOUT)
    EVIDENCE["server"]["pid"] = proc.pid
    EVIDENCE["server"]["started"] = True
    flush()
    EVIDENCE["vram_samples"].append(gpu_sample("pre_launch"))

    ready = wait_rpc(proc)
    EVIDENCE["server"]["rpc_ready"] = ready.get("ok", False)
    flush()
    if not ready.get("ok"):
        EVIDENCE["verdict"] = "BLOCKED"
        proc.terminate()
        proc.wait(timeout=30)
        EVIDENCE["exit"] = {"code": proc.returncode, "method": "owned PID terminate"}
        flush()
        return

    client = carla.Client("127.0.0.1", 2000)
    client.set_timeout(60.0)

    # Load Town01
    t0 = time.time()
    try:
        world = client.load_world("Town01")
        EVIDENCE["map"]["load_s"] = round(time.time() - t0, 1)
        time.sleep(2.0)
        EVIDENCE["map"]["identity"] = world.get_map().name
        s1 = world.get_snapshot()
        EVIDENCE["map"]["tick_before"] = s1.frame if s1 else None
        time.sleep(1.0)
        s2 = world.get_snapshot()
        EVIDENCE["map"]["tick_after"] = s2.frame if s2 else None
        EVIDENCE["map"]["ticks_advanced"] = (s2.frame > s1.frame) if (s1 and s2) else False
    except Exception as exc:
        EVIDENCE["verdict"] = "FAIL"
        EVIDENCE["blockers"].append(f"load_world Town01 failed: {exc}")
        flush()
        proc.terminate()
        proc.wait(timeout=30)
        EVIDENCE["exit"] = {"code": proc.returncode, "method": "owned PID terminate"}
        flush()
        return

    EVIDENCE["vram_samples"].append(gpu_sample("post_load"))

    if not EVIDENCE["map"]["ticks_advanced"]:
        EVIDENCE["verdict"] = "FAIL"
        flush()
        proc.terminate()
        proc.wait(timeout=30)
        EVIDENCE["exit"] = {"code": proc.returncode, "method": "owned PID terminate"}
        flush()
        return

    # Semantic 320x240
    sem_frames = []
    try:
        bp = world.get_blueprint_library().find("sensor.semantic_semseg")
        bp.set_attribute("image_size_x", "320")
        bp.set_attribute("image_size_y", "240")
        bp.set_attribute("fov", "90")
        sem = world.spawn_actor(bp, carla.Transform(carla.Location(x=2, y=0, z=1.8), carla.Rotation(pitch=-15)))
        def cb_sem(img):
            sem_frames.append({"frame": img.frame, "w": img.width, "h": img.height, "len": len(img.raw_data)})
        sem.listen(cb_sem)
        deadline = time.time() + 15.0
        while time.time() < deadline and len(sem_frames) < 2:
            time.sleep(0.2)
        sem.stop()
        sem.destroy()
        EVIDENCE["sensors"]["semantic"]["tested"] = True
        EVIDENCE["sensors"]["semantic"]["callbacks"] = len(sem_frames)
        EVIDENCE["sensors"]["semantic"]["frame_ids"] = [f["frame"] for f in sem_frames]
        if sem_frames:
            f0 = sem_frames[0]
            EVIDENCE["sensors"]["semantic"]["shape"] = [f0["w"], f0["h"]]
            EVIDENCE["sensors"]["semantic"]["raw_bytes"] = f0["len"]
    except Exception as exc:
        EVIDENCE["sensors"]["semantic"]["error"] = str(exc)

    # LiDAR 16ch
    lidar_frames = []
    try:
        bp = world.get_blueprint_library().find("sensor.lidar.ray_cast")
        bp.set_attribute("channels", "16")
        bp.set_attribute("range", "50")
        bp.set_attribute("rotation_frequency", "10")
        bp.set_attribute("points_per_second", "100000")
        lidar = world.spawn_actor(bp, carla.Transform(carla.Location(x=0, y=0, z=2.5)))
        def cb_lidar(pc):
            lidar_frames.append({"frame": pc.frame, "len": len(pc.raw_data)})
        lidar.listen(cb_lidar)
        deadline = time.time() + 15.0
        while time.time() < deadline and len(lidar_frames) < 2:
            time.sleep(0.2)
        lidar.stop()
        lidar.destroy()
        EVIDENCE["sensors"]["lidar"]["tested"] = True
        EVIDENCE["sensors"]["lidar"]["callbacks"] = len(lidar_frames)
        EVIDENCE["sensors"]["lidar"]["frame_ids"] = [f["frame"] for f in lidar_frames]
        if lidar_frames:
            f0 = lidar_frames[0]
            # 4 bytes per float (x,y,z,intensity) = 16 bytes per point
            EVIDENCE["sensors"]["lidar"]["point_counts"] = [f["len"] // 16 for f in lidar_frames]
    except Exception as exc:
        EVIDENCE["sensors"]["lidar"]["error"] = str(exc)

    EVIDENCE["vram_samples"].append(gpu_sample("post_sensors"))

    # Clean teardown
    try:
        proc.terminate()
        proc.wait(timeout=30)
        EVIDENCE["exit"] = {"code": proc.returncode, "method": "owned PID terminate"}
    except Exception:
        try:
            proc.kill()
            EVIDENCE["exit"] = {"code": proc.returncode, "method": "owned PID kill"}
        except Exception as exc:
            EVIDENCE["exit"] = {"code": None, "error": str(exc)}

    EVIDENCE["vram_samples"].append(gpu_sample("post_terminate"))
    EVIDENCE["end_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Verdict
    sem_ok = EVIDENCE["sensors"]["semantic"]["callbacks"] >= 2
    lidar_ok = EVIDENCE["sensors"]["lidar"]["callbacks"] >= 2
    if sem_ok and lidar_ok:
        EVIDENCE["verdict"] = "PASS"
    elif sem_ok or lidar_ok:
        EVIDENCE["verdict"] = "PARTIAL"
    else:
        EVIDENCE["verdict"] = "FAIL"

    flush()
    print("VERDICT:", EVIDENCE["verdict"])
    print("Evidence:", os.path.join(OUT_DIR, "TOWN01_SENSORS_EVIDENCE.json"))


if __name__ == "__main__":
    main()