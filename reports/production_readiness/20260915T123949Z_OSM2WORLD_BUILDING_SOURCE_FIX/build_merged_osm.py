import hashlib
import json
import sys
import time
from pathlib import Path

REPO = Path(r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\.claude\worktrees\agent-a241ac91f503ca382")
sys.path.insert(0, str(REPO))

from ultimate_pipeline.enrichment.overpass_to_osm_xml import (
    convert_overpass_json_to_osm_xml,
    merge_osm_xml_files,
)

RUN_DIR = REPO / "reports" / "production_readiness" / "20260915T123949Z_OSM2WORLD_BUILDING_SOURCE_FIX"
ARTIFACTS = RUN_DIR / "artifacts"
ARTIFACTS.mkdir(parents=True, exist_ok=True)

roads_path = REPO / "campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm"
buildings_path = REPO / "campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_buildings_overpass.json"

def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

print("roads sha256:", sha256(roads_path), roads_path.stat().st_size)
print("buildings sha256:", sha256(buildings_path), buildings_path.stat().st_size)

t0 = time.time()
buildings_osm = ARTIFACTS / "converted_buildings.osm"
convert_stats = convert_overpass_json_to_osm_xml(str(buildings_path), str(buildings_osm))
t1 = time.time()
print("convert_stats:", convert_stats, "elapsed_s:", round(t1 - t0, 2))

merged_osm = ARTIFACTS / "merged_roads_and_buildings.osm"
merge_stats = merge_osm_xml_files(str(roads_path), str(buildings_osm), str(merged_osm))
t2 = time.time()
print("merge_stats:", merge_stats, "elapsed_s:", round(t2 - t1, 2))

print("merged file size:", merged_osm.stat().st_size)
print("merged sha256:", sha256(merged_osm))

summary = {
    "roads_source": {"path": str(roads_path.relative_to(REPO)), "sha256": sha256(roads_path), "bytes": roads_path.stat().st_size},
    "buildings_source": {"path": str(buildings_path.relative_to(REPO)), "sha256": sha256(buildings_path), "bytes": buildings_path.stat().st_size},
    "convert_stats": convert_stats,
    "convert_elapsed_sec": round(t1 - t0, 3),
    "merge_stats": merge_stats,
    "merge_elapsed_sec": round(t2 - t1, 3),
    "converted_buildings_osm": {"path": str(buildings_osm.relative_to(REPO)), "sha256": sha256(buildings_osm), "bytes": buildings_osm.stat().st_size},
    "merged_osm": {"path": str(merged_osm.relative_to(REPO)), "sha256": sha256(merged_osm), "bytes": merged_osm.stat().st_size},
}
(ARTIFACTS / "merge_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print("wrote", ARTIFACTS / "merge_summary.json")
