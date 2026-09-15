import json
import sys
from pathlib import Path

REPO = Path(r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\.claude\worktrees\agent-a241ac91f503ca382")
sys.path.insert(0, str(REPO))

from ultimate_pipeline.enrichment.blender_runner import BlenderRunner

RUN_DIR = REPO / "reports" / "production_readiness" / "20260915T123949Z_OSM2WORLD_BUILDING_SOURCE_FIX"
ARTIFACTS = RUN_DIR / "artifacts"
obj_path = ARTIFACTS / "osm2world" / "ingolstadt_cooked_perception_v1_merged_full_pin.obj"

blender_exe = Path(r"E:/Program Files/Blender Foundation/Blender 4.3/blender.exe")
print("blender exists:", blender_exe.exists())

runner = BlenderRunner(
    obj_path=str(obj_path),
    output_dir=str(ARTIFACTS),
    blender_exe=str(blender_exe),
    timeout_sec=600,
    name_prefix="ing_f3e82001_merged",
)
result = runner.run()
print("status:", result.status)
print("reason:", result.reason)
print("duration_sec:", result.duration_sec)
print("output_fbx:", result.output_fbx)
print("manifest summary:", json.dumps(result.manifest, indent=2)[:2000] if result.manifest else None)
(ARTIFACTS / "blender_run_result.json").write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
