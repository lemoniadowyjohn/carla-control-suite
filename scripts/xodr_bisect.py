import json
import os
import socket
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()
CARLA_SERVER = r"E:\CARLA\CARLA_0.9.16\CarlaUE4.exe"
GOVERNED = REPO_ROOT / "campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_final.xodr"
WORK = REPO_ROOT / "reports" / "post_audit_hardening" / "_bisect"
WORK.mkdir(parents=True, exist_ok=True)
FETCH_SUBSET = int(os.environ.get("FETCH_SUBSET", "0"))  # 0=all, else take first N roads
MAX_TIME_S = int(os.environ.get("BISECT_MAX_S", "600"))
CRASH_MARKER = "s <= road->GetLength()"
UE_CRASH_DIR = Path(r"C:\Users\admin\AppData\Local\CarlaUE4\Saved\Crashes")


def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with (WORK / "bisect.log").open("a", encoding="utf-8") as f:
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


def last_crash(n=3) -> list:
    if not UE_CRASH_DIR.exists():
        return []
    out = []
    for d in sorted(UE_CRASH_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)[:n]:
        for xml in d.glob("*.runtime-xml"):
            m = re_match(xml.read_text(encoding="utf-8", errors="ignore"))
            if m:
                out.append((d.stat().st_mtime, m))
            break
    return out


def re_match(txt: str) -> str | None:
    import re as _re
    m = _re.search(r"<ErrorMessage>(.*?)</ErrorMessage>", txt, _re.S)
    return m.group(1).strip() if m else None


def make_subset(full: Path, n_keep: int, out: Path, skip_prefix: int = 0) -> int:
    """Keep roads [skip_prefix, skip_prefix+n_keep) in document order; drop others."""
    tree = ET.parse(full)
    root = tree.getroot()
    roads = root.findall("road")
    kept_ids = set()
    keep = roads[skip_prefix:skip_prefix + n_keep]
    n = len(keep)
    for r in keep:
        kept_ids.add(r.get("id"))
    for r in roads:
        if r not in keep:
            root.remove(r)
    # drop junctions referencing removed roads
    if isinstance(root.tag, str) and n_keep > 0:
        for j in root.findall("junction"):
            conn_ids = [c.get("connectingRoad") for c in j.findall("connection")]
            linked = [c.get("linkedRoad") for c in j.findall("connection")]
            if any(cid in kept_ids and (not lk or lk in kept_ids) for cid, lk in zip(conn_ids, linked)):
                pass
            elif n_keep < len(roads):
                root.remove(j)
    ET.ElementTree(root).write(out, encoding="utf-8", xml_declaration=True)
    return n


def run_generation(xodr: Path, label: str) -> dict:
    server = subprocess.Popen(
        [CARLA_SERVER,
         "-carla-rpc-port=2000", "-carla-streaming-port=2001",
         "-quality-level=Low", "-nosound", "-windowed", "-ResX=1280", "-ResY=720"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    result = {"label": label, "verdict": "UNKNOWN"}
    try:
        if not wait_socket(2000, 180):
            result["verdict"] = "NO_RPC"
            return result
        if not wait_socket(2001, 120):
            result["verdict"] = "NO_STREAM"
            return result
        sys.path.insert(0, str(REPO_ROOT))
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
        xodr_text = xodr.read_text(encoding="utf-8", errors="ignore")
        params = carla.OpendriveGenerationParameters()
        params.map_layers = carla.MapLayer.NONE
        params.wall_height = 0.0
        params.additional_width = 0.0
        params.vertex_distance = 10.0  # coarse -> fast diagnostic
        params.smooth_junctions = False
        before = last_crash(1)
        t0 = time.monotonic()
        client.set_timeout(MAX_TIME_S)
        gworld = client.generate_opendrive_world(xodr_text, params)
        result["verdict"] = "PASS"
        result["took_s"] = round(time.monotonic() - t0, 1)
        result["map"] = str(getattr(gworld.get_map(), "name", ""))
        log(f"{label}: PASS in {result['took_s']}s ({xodr.name})")
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["took_s"] = round(time.monotonic() - t0, 1) if "t0" in locals() else None
        after = last_crash(1)
        crashed = bool(after) and (not before or after[0][0] > before[0][0]) and CRASH_MARKER in after[0][1]
        result["verdict"] = "HANG" if not crashed else "CRASH"
        result["crash_msg"] = after[0][1] if after else None
        log(f"{label}: {result['verdict']} after {result.get('took_s')}s err={e} ({xodr.name})")
    finally:
        try:
            subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"], capture_output=True, timeout=15)
        except Exception:
            pass
    return result


def main() -> int:
    delay = float(os.environ.get("BISECT_START_DELAY_S", "0"))
    if delay:
        log(f"waiting {delay}s for prior server shutdown")
        time.sleep(delay)
    subset = FETCH_SUBSET
    if subset > 0:
        out = WORK / f"keep_{subset}.xodr"
        n = make_subset(GOVERNED, subset, out)
        log(f"subset written: {out} roads={n} (from {GOVERNED.name})")
    else:
        out = GOVERNED
    res = run_generation(out, "full" if subset == 0 else f"keep_{subset}")
    with (WORK / f"result_{'full' if subset == 0 else 'keep_' + str(subset)}.json").open("w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    print(json.dumps(res, indent=2))
    return 0 if res["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())