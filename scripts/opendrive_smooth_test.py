import json
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()
CARLA_SERVER = r"E:\CARLA\CARLA_0.9.16\CarlaUE4.exe"
GOVERNED_XODR = Path(os.environ.get("SMOOTH_TEST_XODR", str(REPO_ROOT / "campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_final.xodr")))
VERTEX = float(os.environ.get("OD_VERTEX_DISTANCE", "3.0"))
SMOOTH = os.environ.get("OD_SMOOTH_JUNCTIONS", "0") == "1"
WINDOW_S = int(os.environ.get("WINDOW_S", "3600"))

LOG_DIR = REPO_ROOT / "reports" / "post_audit_hardening" / "_gen_watch_log"
LOG_DIR.mkdir(parents=True, exist_ok=True)
PROGRESS = LOG_DIR / "smooth_test_progress.log"


def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with PROGRESS.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def wait_socket(port: int, timeout_s: float = 180.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2.0):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def main() -> int:
    server = subprocess.Popen(
        [CARLA_SERVER,
         "-carla-rpc-port=2000", "-carla-streaming-port=2001",
         "-quality-level=Low", "-nosound", "-windowed", "-ResX=1280", "-ResY=720"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    evidence = {"verdict": "FAIL", "vertex_distance": VERTEX, "smooth_junctions": SMOOTH, "stages": {}}
    try:
        if not wait_socket(2000, 180):
            raise RuntimeError("RPC port never opened")
        if not wait_socket(2001, 120):
            raise RuntimeError("streaming port never opened")
        sys.path.insert(0, ".")
        import carla

        client = carla.Client("127.0.0.1", 2000)
        client.set_timeout(30.0)
        t1 = time.time()
        while time.time() - t1 < 60:
            try:
                world = client.get_world()
                world.get_map()
                break
            except Exception:
                time.sleep(1.0)
        evidence["stages"]["server_ready_s"] = round(time.time() - t1, 1)

        xodr_text = GOVERNED_XODR.read_text(encoding="utf-8", errors="ignore")
        params = carla.OpendriveGenerationParameters()
        params.map_layers = carla.MapLayer.NONE
        params.wall_height = 0.0
        params.additional_width = 0.0
        params.vertex_distance = VERTEX
        params.smooth_junctions = SMOOTH

        log(f"generation start (vertex={VERTEX}, smooth={SMOOTH}, window={WINDOW_S}s)")
        client.set_timeout(WINDOW_S)
        t_gen = time.monotonic()
        gworld = client.generate_opendrive_world(xodr_text, params)
        elapsed = time.monotonic() - t_gen
        gmap = gworld.get_map()
        evidence["verdict"] = "PASS"
        evidence["generation_s"] = round(elapsed, 1)
        evidence["map_name"] = str(getattr(gmap, "name", ""))
        log(f"GENERATION COMPLETE in {elapsed:.1f}s map={evidence['map_name']}")
    except Exception as e:
        evidence["error"] = f"{type(e).__name__}: {e}"
        log(f"FAILED: {e}")
    finally:
        try:
            subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"], capture_output=True, timeout=15)
        except Exception:
            pass
        out = REPO_ROOT / "reports" / "post_audit_hardening" / "OPENDDRIVE_SMOOTH_TEST.json"
        out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        log(f"evidence -> {out}")
        return 0 if evidence["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())