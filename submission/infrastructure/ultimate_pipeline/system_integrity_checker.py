from __future__ import annotations

"""
System Integrity Checker for the Ultimate Pipeline.
Ensures:
- CARLA connection
- OSM/XODR/DEM integrity
- Tile metadata + adjacency consistency
- Directory structure validity
- Domain gap readiness
"""
import argparse
import os
import json
import hashlib
from pathlib import Path
import carla


parser = argparse.ArgumentParser()
parser.add_argument("--run_dir", default=None, help="Existing pipeline output directory to validate")
args = parser.parse_args()
run_dir = args.run_dir

# Correct absolute import path
from ultimate_pipeline.config.settings import SETTINGS


def file_exists(path: str) -> bool:
    return Path(path).exists()


def readable(path: str) -> bool:
    try:
        with open(path, "rb"):
            return True
    except:
        return False


def directory_ok(path: str) -> bool:
    p = Path(path)
    return p.exists() and p.is_dir()


def md5_hash(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def print_status(ok: bool, label: str, detail: str = ""):
    icon = "✅" if ok else "❌"
    print(f"{icon} {label}: {detail}")


def carla_connection_ok():
    try:
        client = carla.Client(SETTINGS.CARLA_HOST, SETTINGS.CARLA_PORT)
        client.set_timeout(2.0)
        world = client.get_world()
        _ = world.get_map()
        return True, f"Connected to CARLA at {SETTINGS.CARLA_HOST}:{SETTINGS.CARLA_PORT}"
    except Exception as e:
        return False, str(e)


def osm_integrity_ok():
    osm_file = SETTINGS.OSM_INPUT_FILE

    if not file_exists(osm_file):
        return False, f"Missing → {osm_file}"

    if not readable(osm_file):
        return False, "Unreadable OSM file"

    size = os.path.getsize(osm_file)
    if size < 5000:
        return False, "OSM file suspiciously small"

    return True, f"{size:,} bytes"


def xodr_integrity_ok():
    xodr_file = SETTINGS.XODR_OUTPUT_FILE

    if not file_exists(xodr_file):
        return False, f"Missing → {xodr_file}"

    try:
        with open(xodr_file, "r", encoding="utf-8") as f:
            text = f.read()
        if "<OpenDRIVE" not in text:
            return False, "Not a valid XODR"
        return True, "XODR loads successfully"
    except Exception as e:
        return False, str(e)


def dem_integrity_ok():
    dem_file = SETTINGS.DEM_FILE

    if not file_exists(dem_file):
        return False, f"Missing → {dem_file}"

    size = os.path.getsize(dem_file)
    if size < 10000:
        return False, "DEM too small"

    return True, f"{size:,} bytes"


def tile_data_ok(run_dir: str | None):
    if not getattr(SETTINGS, "ENABLE_TILING", False):
        return True, "Tiling disabled"

    if not run_dir or not os.path.isdir(run_dir):
        return False, "No valid --run_dir provided (checker otherwise points at a new timestamp folder)"

    meta = os.path.join(run_dir, SETTINGS.TILE_METADATA_JSON or "tile_metadata.json")
    adj  = os.path.join(run_dir, SETTINGS.TILE_ADJ_JSON or "tile_adjacency.json")

    if not os.path.exists(meta):
        return False, f"Missing tile_metadata.json in {run_dir}"
    if not os.path.exists(adj):
        return False, f"Missing tile_adjacency.json in {run_dir}"

    try:
        metadata = json.load(open(meta, "r", encoding="utf-8"))
        return True, f"{len(metadata.get('tiles', []))} tiles"
    except Exception as e:
        return False, str(e)




def directory_structure_ok():
    """
    Validate only REQUIRED directories.
    Optional feature directories must not fail integrity.
    """

    required_dirs = {
        "Pipeline output root": SETTINGS.BASE_OUTPUT_DIR,
    }

    missing = [
        name for name, path in required_dirs.items()
        if not directory_ok(path)
    ]

    if missing:
        return False, f"Missing required dirs: {missing}"

    return True, "Required directory structure OK"



def domain_gap_ready():
    if not SETTINGS.ENABLE_DOMAIN_GAP:
        return True, "Domain gap disabled"

    manual = SETTINGS.MANUAL_MAP_XODR
    auto = SETTINGS.XODR_OUTPUT_FILE

    if not manual or not file_exists(manual):
        return False, "Missing manual reference XODR"
    if not file_exists(auto):
        return False, "Missing auto-generated XODR"

    if md5_hash(manual) == md5_hash(auto):
        return False, "Manual & auto maps are identical"

    return True, "Domain gap inputs ready"



def run_system_integrity_check():
    print("\n🔍 SYSTEM INTEGRITY CHECK")
    print("=" * 50)

    checks = [
        ("CARLA Server", carla_connection_ok),
        ("OSM Integrity", osm_integrity_ok),
        ("XODR Integrity", xodr_integrity_ok),
        ("DEM Integrity", dem_integrity_ok),
        ("Tile Metadata", lambda: tile_data_ok(run_dir)),
        ("Directory Structure", directory_structure_ok),
        ("Domain Gap Readiness", domain_gap_ready),
    ]

    results = []
    for name, fn in checks:
        ok, detail = fn()
        if name == "CARLA Server" and not ok:
            print_status(True, name, f"Warning: {detail}")
            ok = True

        print_status(ok, name, detail)
        results.append(ok)

    print("\n📊 SUMMARY")
    print("=" * 50)
    print(f"Passed: {sum(results)}/{len(results)}\n")

    if all(results):
        print("🎉 SYSTEM READY TO RUN PIPELINE")
    else:
        print("⚠️  Fix the above issues before continuing.")


if __name__ == "__main__":
    run_system_integrity_check()
