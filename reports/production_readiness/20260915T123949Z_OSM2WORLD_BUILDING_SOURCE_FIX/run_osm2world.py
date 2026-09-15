import json
import sys
from pathlib import Path

REPO = Path(r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\.claude\worktrees\agent-a241ac91f503ca382")
sys.path.insert(0, str(REPO))

from ultimate_pipeline.enrichment.osm2world_runner import OSM2WorldRunner

RUN_DIR = REPO / "reports" / "production_readiness" / "20260915T123949Z_OSM2WORLD_BUILDING_SOURCE_FIX"
ARTIFACTS = RUN_DIR / "artifacts"
merged_osm = ARTIFACTS / "merged_roads_and_buildings.osm"

osm2world_home = REPO.parents[3] / "carla_governed" / "OSM2World-latest-bin"
# REPO is the worktree; carla_governed lives in the real repo root, not the worktree.
osm2world_home = Path(r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\carla_governed\OSM2World-latest-bin")
print("osm2world_home exists:", osm2world_home.is_dir())

import os
os.environ["OSM2WORLD_OUTPUTS"] = "obj,png,glb"

runner = OSM2WorldRunner(
    osm_path=str(merged_osm),
    output_dir=str(ARTIFACTS / "osm2world"),
    osm2world_home=str(osm2world_home),
    timeout_sec=1800,
    name_prefix="ingolstadt_cooked_perception_v1_merged_full_pin",
)
result = runner.run()
print("status:", result.status)
print("reason:", result.reason)
print("duration_sec:", result.duration_sec)
print("outputs:", result.outputs)
print("exit_codes:", result.exit_codes)
(ARTIFACTS / "osm2world_run_result.json").write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
