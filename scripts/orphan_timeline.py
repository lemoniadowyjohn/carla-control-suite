"""Non-intrusive observation of PID 12312 across a real time window.

Deliberately does NOT attach a debugger, does not open the process with
DEBUG rights, and writes nothing into Content. The only goal is to decide
whether authoritative output is advancing, because CPU alone is not evidence of
progress (see batch section 4).

Samples: T0, +5, +10, +20, +30 minutes.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from orch_core import atomic_write_json, utc_now  # noqa: E402

REPO = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"
OUT = os.path.join(REPO, "reports")
CARLA = r"G:\CARLA\carla_source_probe"
CONTENT = os.path.join(CARLA, "Unreal", "CarlaUE4", "Content", "Ingolstadt")
MAPS = os.path.join(CONTENT, "Maps", "Ingolstadt")
MESH = os.path.join(CONTENT, "Static", "Terrain", "Ingolstadt")
SAVED = os.path.join(CARLA, "Unreal", "CarlaUE4", "Saved")
IMPORTSETTINGS = os.path.join(CARLA, "importsetting.json")

TARGET_PID = 12312
SCHEDULE_MIN = [0, 5, 10, 20, 30]


def sha256_file(path):
    if not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def proc_snapshot():
    import psutil
    try:
        p = psutil.Process(TARGET_PID)
    except psutil.NoSuchProcess:
        return {"alive": False}
    with p.oneshot():
        ct = p.cpu_times()
        io = p.io_counters()
        mi = p.memory_info()
        return {
            "alive": True,
            "cpu_user_s": round(ct.user, 2),
            "cpu_system_s": round(ct.system, 2),
            "cpu_total_s": round(ct.user + ct.system, 2),
            "working_set_bytes": mi.rss,
            "private_bytes": getattr(mi, "private", 0),
            "virtual_bytes": getattr(mi, "vms", 0),
            "handles": getattr(mi, "num_handles", None),
            "threads": p.num_threads(),
            "read_bytes": io.read_bytes,
            "write_bytes": io.write_bytes,
            "read_ops": io.read_count,
            "write_ops": io.write_count,
            "create_time": p.create_time(),
            "status": p.status(),
            "children": [c.pid for c in p.children(recursive=True)],
        }


def tree_census():
    """Content inventory plus AssetRegistry observation."""
    files = 0
    total = 0
    newest = (0.0, None)
    newest20 = []
    for root, _d, names in os.walk(CONTENT):
        for n in names:
            full = os.path.join(root, n)
            try:
                st = os.stat(full)
            except OSError:
                continue
            files += 1
            total += st.st_size
            newest20.append((st.st_mtime, os.path.relpath(full, CONTENT), st.st_size))
            if st.st_mtime > newest[0]:
                newest = (st.st_mtime, os.path.relpath(full, CONTENT))
    newest20.sort(reverse=True)

    umaps, tile_umaps = [], []
    for root, _d, names in os.walk(MAPS):
        for n in names:
            if n.endswith(".umap"):
                rel = os.path.relpath(os.path.join(root, n), MAPS).replace("\\", "/")
                umaps.append(rel)
                if "_Tile_" in n:
                    tile_umaps.append(rel)

    meshes = 0
    if os.path.isdir(MESH):
        meshes = sum(1 for n in os.listdir(MESH) if n.endswith(".uasset"))

    # AssetRegistry caches
    ar = []
    for root, _d, names in os.walk(os.path.join(SAVED, "Config")) if os.path.isdir(
            os.path.join(SAVED, "Config")) else []:
        for n in names:
            if "AssetRegistry" in n or "Metadata" in n:
                full = os.path.join(root, n)
                try:
                    st = os.stat(full)
                    ar.append({"path": os.path.relpath(full, SAVED),
                               "bytes": st.st_size, "mtime_epoch": st.st_mtime})
                except OSError:
                    pass

    return {
        "content_files": files,
        "content_bytes": total,
        "newest_path": newest[1],
        "newest_mtime_epoch": newest[0],
        "newest_assets": [{"path": p, "bytes": b,
                           "mtime_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                      time.gmtime(m))}
                          for m, p, b in newest20[:20]],
        "umaps": sorted(umaps),
        "umap_count": len(umaps),
        "tile_umaps": sorted(tile_umaps),
        "tile_umap_count": len(tile_umaps),
        "static_meshes": meshes,
        "asset_registry_files": ar,
    }


def log_state():
    candidates = []
    for root, _d, names in os.walk(os.path.join(SAVED, "Logs")):
        for n in names:
            p = os.path.join(root, n)
            try:
                candidates.append((os.path.getmtime(p), os.path.getsize(p), p))
            except OSError:
                pass
    supervision = os.path.join(CARLA, "Util", "BuildTools", "_import_supervision")
    if os.path.isdir(supervision):
        for n in os.listdir(supervision):
            p = os.path.join(supervision, n)
            try:
                candidates.append((os.path.getmtime(p), os.path.getsize(p), p))
            except OSError:
                pass
    if not candidates:
        return {"path": None, "size": None, "mtime_epoch": None}
    candidates.sort(reverse=True)
    m, s, p = candidates[0]
    return {"path": p, "size": s, "mtime_epoch": m,
            "mtime_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(m))}


def ddc_activity():
    """DDC recent-write observation, best effort and strictly read-only."""
    ddc = os.path.join(r"G:\UnrealEngine_4.26_CARLA\Engine\DerivedDataCache")
    if not os.path.isdir(ddc):
        return {"exists": False}
    newest = (0.0, None)
    count = 0
    for root, _d, names in os.walk(ddc):
        for n in names:
            try:
                mt = os.path.getmtime(os.path.join(root, n))
            except OSError:
                continue
            if mt > newest[0]:
                newest = (mt, n)
            if time.time() - mt < 3600:
                count += 1
    return {"exists": True, "newest_mtime_epoch": newest[0],
            "newest_file": newest[1], "files_written_last_hour": count}


def sample(label, index):
    s = {
        "label": label,
        "index": index,
        "utc": utc_now(),
        "epoch": time.time(),
        "process": proc_snapshot(),
        "content": tree_census(),
        "log": log_state(),
        "ddc": ddc_activity(),
        "import_settings": {
            "path": IMPORTSETTINGS,
            "sha256": sha256_file(IMPORTSETTINGS),
            "mtime_utc": (time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                       time.gmtime(os.path.getmtime(IMPORTSETTINGS)))
                          if os.path.isfile(IMPORTSETTINGS) else None),
        },
    }
    atomic_write_json(os.path.join(OUT, "ORPHAN_SAMPLE_%s.json" % label), s)
    return s


def main():
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    samples = []
    for i, minute in enumerate(SCHEDULE_MIN):
        target = t0 + minute * 60
        now = time.time()
        if target > now:
            time.sleep(target - now)
        s = sample("T%02d" % minute, i)
        samples.append(s)
        p = s["process"]
        print("T+%02dmin alive=%s cpu=%.0f ws=%dMB wr=%d files=%d tile_umaps=%d log=%s" % (
            minute, p.get("alive"), p.get("cpu_total_s") or 0,
            (p.get("working_set_bytes") or 0) // (1024 * 1024),
            p.get("write_bytes") or 0, s["content"]["content_files"],
            s["content"]["tile_umap_count"],
            s["log"].get("size")), flush=True)

    # ---- CSV timeline ----
    path = os.path.join(OUT, "ORPHAN_IMPORT_TIMELINE.csv")
    cols = ["label", "utc", "alive", "cpu_total_s", "cpu_delta_s", "read_bytes",
            "read_delta", "write_bytes", "write_delta", "handles", "threads",
            "working_set_mb", "private_mb", "log_size", "log_delta",
            "content_files", "content_files_delta", "content_bytes",
            "content_bytes_delta", "umap_count", "tile_umap_count",
            "ddc_files_last_hour", "import_settings_sha256"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        prev = None
        for s in samples:
            p = s["process"]
            c = s["content"]
            row = {
                "label": s["label"], "utc": s["utc"],
                "alive": p.get("alive"),
                "cpu_total_s": p.get("cpu_total_s"),
                "cpu_delta_s": (p.get("cpu_total_s") - prev["cpu_total_s"]
                                if prev and prev.get("alive") and p.get("alive") else None),
                "read_bytes": p.get("read_bytes"),
                "read_delta": (p.get("read_bytes") - prev["read_bytes"]
                               if prev and prev.get("alive") and p.get("alive") else None),
                "write_bytes": p.get("write_bytes"),
                "write_delta": (p.get("write_bytes") - prev["write_bytes"]
                                if prev and prev.get("alive") and p.get("alive") else None),
                "handles": p.get("handles"), "threads": p.get("threads"),
                "working_set_mb": (p.get("working_set_bytes") or 0) // (1024 * 1024),
                "private_mb": (p.get("private_bytes") or 0) // (1024 * 1024),
                "log_size": s["log"].get("size"),
                "log_delta": (s["log"].get("size") - prev["log_size"]
                              if prev and prev.get("size") is not None
                              and s["log"].get("size") is not None else None),
                "content_files": c["content_files"],
                "content_files_delta": (c["content_files"] - prev["content_files"]
                                        if prev else None),
                "content_bytes": c["content_bytes"],
                "content_bytes_delta": (c["content_bytes"] - prev["content_bytes"]
                                        if prev else None),
                "umap_count": c["umap_count"],
                "tile_umap_count": c["tile_umap_count"],
                "ddc_files_last_hour": s["ddc"].get("files_written_last_hour"),
                "import_settings_sha256": s["import_settings"]["sha256"],
            }
            w.writerow(row)
            prev = {"cpu_total_s": p.get("cpu_total_s") or 0,
                    "read_bytes": p.get("read_bytes") or 0,
                    "write_bytes": p.get("write_bytes") or 0,
                    "log_size": s["log"].get("size"),
                    "content_files": c["content_files"],
                    "content_bytes": c["content_bytes"]}

    atomic_write_json(os.path.join(OUT, "ORPHAN_TIMELINE_SAMPLES.json"),
                      {"schema": "ORPHAN_TIMELINE/v1", "schema_version": 1,
                       "schedule_minutes": SCHEDULE_MIN, "samples": samples})
    print("TIMELINE_WRITTEN", flush=True)


if __name__ == "__main__":
    main()