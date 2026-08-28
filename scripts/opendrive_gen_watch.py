import json
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

REPO_ROOT = Path(__file__).parent.parent.resolve()
CARLA_SERVER = r"E:\CARLA\CARLA_0.9.16\CarlaUE4.exe"
CARLA_ROOT = Path(r"E:\CARLA\CARLA_0.9.16")
GOVERNED_XODR = Path(os.environ.get("GEN_WATCH_XODR", str(REPO_ROOT / "campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_final.xodr")))
GOVERNED_SHA = "248ffbbe6a1aa2a9cbd4330a69ad1c1680d39698e2d186dd45f5a2eb91c5db6c"
OD_VERTEX_DISTANCE = 3.0
RPC_PORT = 2000
STREAM_PORT = 2001
WINDOW_S = int(os.environ.get("GEN_WATCH_WINDOW_S", "7200"))

LOG_DIR = REPO_ROOT / "reports" / "post_audit_hardening" / "_gen_watch_log"
LOG_DIR.mkdir(parents=True, exist_ok=True)
PROGRESS = LOG_DIR / "progress.log"
SAMPLES = LOG_DIR / "samples.jsonl"


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


def vram_mb() -> int:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        return int(out.splitlines()[0].strip())
    except Exception:
        return -1


class Sampler:
    def __init__(self, proc) -> None:
        self.proc = proc
        self.stop_flag = threading.Event()
        self.pcpu = None

    def find_server(self) -> None:
        """CarlaUE4.exe is a launcher; the real server is CarlaUE4-Win64-Shipping."""
        deadline = time.monotonic() + 120.0
        while self.pcpu is None and time.monotonic() < deadline:
            try:
                parent = psutil.Process(self.proc.pid)
                children = [c for c in parent.children(recursive=True)]
                for c in children:
                    if c.name() == "CarlaUE4-Win64-Shipping.exe":
                        self.pcpu = c
                        break
            except Exception:
                pass
            time.sleep(1.0)
        if self.pcpu is None:
            for p in psutil.process_iter(["pid", "name"]):
                if p.info["name"] == "CarlaUE4-Win64-Shipping.exe":
                    self.pcpu = p
                    break

    def run(self) -> None:
        self.find_server()
        if self.pcpu is None:
            log("sampler: could not locate CarlaUE4-Win64-Shipping; sampling disabled")
            return
        log(f"sampler: watching PID {self.pcpu.pid}")
        t0 = time.monotonic()
        while not self.stop_flag.is_set():
            ts = time.monotonic() - t0
            try:
                cpu = self.pcpu.cpu_percent(interval=1.0)
                mem_mb = self.pcpu.memory_info().rss / 1e6
            except Exception:
                cpu, mem_mb = -1.0, -1.0
            rec = {"t_s": round(ts, 1), "cpu_pct": round(cpu, 1), "rss_mb": round(mem_mb, 1), "vram_mb": vram_mb()}
            with SAMPLES.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            time.sleep(9.0)


def main() -> int:
    import carla

    server = subprocess.Popen(
        [CARLA_SERVER,
         f"-carla-rpc-port={RPC_PORT}",
         f"-carla-streaming-port={STREAM_PORT}",
         "-quality-level=Low", "-nosound", "-windowed", "-ResX=1280", "-ResY=720",
         "-log", f"-abslog={LOG_DIR / 'carla_ue.log'}"],
        stdout=(LOG_DIR / "server_stdout.txt").open("wb"),
        stderr=(LOG_DIR / "server_stderr.txt").open("wb"),
    )
    evidence = {"verdict": "FAIL", "window_s": WINDOW_S, "stages": {}}
    try:
        if not wait_socket(RPC_PORT, 180):
            raise RuntimeError("RPC port never opened")
        if not wait_socket(STREAM_PORT, 120):
            raise RuntimeError("streaming port never opened")

        sampler = Sampler(server)
        threading.Thread(target=sampler.run, daemon=True).start()

        sys.path.insert(0, ".")
        client = carla.Client("127.0.0.1", RPC_PORT)
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

        os.environ["UP_OD_VERTEX_DISTANCE"] = str(OD_VERTEX_DISTANCE)
        xodr_text = GOVERNED_XODR.read_text(encoding="utf-8", errors="ignore")
        params = carla.OpendriveGenerationParameters()
        params.map_layers = carla.MapLayer.NONE
        params.wall_height = 0.0
        params.additional_width = 0.0
        params.vertex_distance = OD_VERTEX_DISTANCE
        params.smooth_junctions = True

        log(f"generation start (vertex_distance={OD_VERTEX_DISTANCE}, window={WINDOW_S}s)")
        client.set_timeout(WINDOW_S)
        t_gen = time.monotonic()
        gworld = client.generate_opendrive_world(xodr_text, params)
        elapsed = time.monotonic() - t_gen
        gmap = gworld.get_map()
        evidence["verdict"] = "PASS"
        evidence["generation_s"] = round(elapsed, 1)
        evidence["map_name"] = str(getattr(gmap, "name", ""))
        log(f"GENERATION COMPLETE in {elapsed:.1f}s, map={getattr(gmap, 'name', '?')}")
    except Exception as e:
        evidence["error"] = f"{type(e).__name__}: {e}"
        log(f"FAILED: {e}")
    finally:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(server.pid), "/T", "/F"],
                capture_output=True, timeout=15,
            )
        except Exception:
            pass
        out = REPO_ROOT / "reports" / "post_audit_hardening" / "OPENDDRIVE_GEN_WATCH.json"
        out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        log(f"evidence -> {out}")
        return 0 if evidence["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())