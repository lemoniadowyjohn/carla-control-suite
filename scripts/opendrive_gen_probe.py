import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()
CARLA_SERVER = r"E:\CARLA\CARLA_0.9.16\CarlaUE4.exe"
RPC_PORT = 2000
STREAM_PORT = 2001
MINI_XODR = """<?xml version="1.0" encoding="utf-8"?>
<OpenDRIVE>
<header revMajor="1" revMinor="4" name="mini_probe" version="1.00" date="2026-08-11T00:00:00" north="100" south="0" east="100" west="0" vendor="probe">
<geoReference>+proj=utm +zone=32 +ellps=WGS84 +datum=WGS84 +units=m +no_defs</geoReference>
</header>
<road id="0" length="100.0" junction="-1">
<link><successor elementType="road" elementId="1" contactPoint="start"/></link>
<planView><geometry s="0.0" x="0.0" y="0.0" hdg="0.0" length="100.0"><line/></geometry></planView>
<lateralProfile><centerLane><left/> <right/></centerLane></lateralProfile>
<lanes><laneSection s="0.0">
<left><lane id="1" type="driving" level="false"><link/><width sOffset="0.0" a="3.5" b="0.0" c="0.0" d="0.0"/><roadMark sOffset="0.0" type="solid" weight="standard" color="white" width="0.2" laneChange="both"/></lane></left>
<center><lane id="0" type="none"><link/><roadMark sOffset="0.0" type="solid" weight="standard" color="white" width="0.2" laneChange="none"/></lane></center>
<right><lane id="-1" type="driving" level="false"><link/><width sOffset="0.0" a="3.5" b="0.0" c="0.0" d="0.0"/><roadMark sOffset="0.0" type="solid" weight="standard" color="white" width="0.2" laneChange="both"/></lane></right>
</laneSection></lanes>
</road>
<road id="1" length="100.0" junction="-1">
<link><predecessor elementType="road" elementId="0" contactPoint="start"/></link>
<planView><geometry s="0.0" x="100.0" y="0.0" hdg="0.0" length="100.0"><line/></geometry></planView>
<lateralProfile><centerLane><left/> <right/></centerLane></lateralProfile>
<lanes><laneSection s="0.0">
<left><lane id="1" type="driving" level="false"><link/><width sOffset="0.0" a="3.5" b="0.0" c="0.0" d="0.0"/><roadMark sOffset="0.0" type="solid" weight="standard" color="white" width="0.2" laneChange="both"/></lane></left>
<center><lane id="0" type="none"><link/><roadMark sOffset="0.0" type="solid" weight="standard" color="white" width="0.2" laneChange="none"/></lane></center>
<right><lane id="-1" type="driving" level="false"><link/><width sOffset="0.0" a="3.5" b="0.0" c="0.0" d="0.0"/><roadMark sOffset="0.0" type="solid" weight="standard" color="white" width="0.2" laneChange="both"/></lane></right>
</laneSection></lanes>
</road>
<signal id="0" s="50.0" t="-1.75" dynamic="no" name="probe_signal" type="206" subtype="1" value="10" unit="km/h" orientation="-" zOffset="2.0" country="Germany">
<validity fromLane="-1" toLane="-1"/>
</signal>
</OpenDRIVE>
"""


def wait_socket(port: int, timeout_s: float = 180.0) -> bool:
    import socket
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2.0):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def main() -> int:
    run_dir = REPO_ROOT / "reports" / "post_audit_hardening" / "OPENDDRIVE_GEN_PROBE"
    run_dir.mkdir(parents=True, exist_ok=True)
    evidence = {
        "phase": "P1-diag",
        "verdict": "FAIL",
        "stages": {},
        "error": None,
    }
    server = None
    try:
        t0 = time.time()
        server = subprocess.Popen(
            [
                CARLA_SERVER,
                f"-carla-rpc-port={RPC_PORT}",
                f"-carla-streaming-port={STREAM_PORT}",
                "-quality-level=Low",
                "-nosound",
                "-windowed",
                "-ResX=1280",
                "-ResY=720",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        evidence["stages"]["launch"] = round(time.time() - t0, 3)
        ok = wait_socket(RPC_PORT, timeout_s=180.0)
        evidence["stages"]["rpc_port_ready"] = round(time.time() - t0, 3)
        if not ok:
            raise RuntimeError("RPC port 2000 never opened")
        if not wait_socket(STREAM_PORT, timeout_s=120.0):
            raise RuntimeError("streaming port 2001 never opened")

        sys.path.insert(0, ".")
        import carla  # noqa: E402  (venv client lib)

        client = carla.Client("127.0.0.1", RPC_PORT)
        client.set_timeout(10.0)
        # wait for world list + a real world
        t1 = time.time()
        while time.time() - t1 < 60.0:
            try:
                world = client.get_world()
                world.get_map()
                break
            except Exception:
                time.sleep(1.0)
        evidence["stages"]["world_ready"] = round(time.time() - t1, 3)

        params = carla.OpendriveGenerationParameters()
        params.map_layers = carla.MapLayer.NONE
        params.wall_height = 0.0
        params.additional_width = 0.0
        params.vertex_distance = 1.0
        params.smooth_junctions = True

        evidence["stages"]["start_generate"] = round(time.time(), 3)
        gen_t0 = time.time()
        client.set_timeout(300.0)
        gworld = client.generate_opendrive_world(MINI_XODR, params)
        evidence["stages"]["generate_done"] = round(time.time() - gen_t0, 3)
        gout = gworld.get_map()
        evidence["stages"]["post_generate_map"] = str(getattr(gout, "name", ""))
        evidence["verdict"] = "PASS"
        evidence["map_name"] = str(getattr(gout, "name", ""))
        evidence["note"] = "MINI_XODR procedural generation succeeded"
    except Exception as e:
        evidence["error"] = f"{type(e).__name__}: {e}"
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10.0)
            except Exception:
                pass
        evidence_file = run_dir / "OPENDDRIVE_GEN_PROBE.json"
        evidence_file.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(json.dumps(evidence, indent=2))
        print(f"evidence: {evidence_file}")
        return 0 if evidence["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())