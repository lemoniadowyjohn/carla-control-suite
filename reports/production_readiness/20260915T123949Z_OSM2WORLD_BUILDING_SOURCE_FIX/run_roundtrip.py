import json
import sys
from pathlib import Path

REPO = Path(r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\.claude\worktrees\agent-a241ac91f503ca382")
sys.path.insert(0, str(REPO))
from ultimate_pipeline.enrichment.fbx_roundtrip import run_fbx_roundtrip

ARTIFACTS = REPO / "reports" / "production_readiness" / "20260915T123949Z_OSM2WORLD_BUILDING_SOURCE_FIX" / "artifacts"
fbx_path = ARTIFACTS / "ing_f3e82001_merged.fbx"
blender_manifest_path = ARTIFACTS / "ing_f3e82001_merged.blender_manifest.json"
blender_exe = Path(r"E:/Program Files/Blender Foundation/Blender 4.3/blender.exe")

source_manifest = json.loads(blender_manifest_path.read_text(encoding="utf-8"))

ok, report = run_fbx_roundtrip(
    fbx_path=fbx_path,
    output_dir=ARTIFACTS,
    blender_exe=blender_exe,
    source_manifest=source_manifest,
    timeout_sec=600,
)

report["ok"] = ok
out_path = ARTIFACTS / "fbx_roundtrip_report.json"
out_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
print("ROUNDTRIP OK:", ok)
print("Verdict:", report.get("comparison", {}).get("verdict"))
print(json.dumps(report.get("comparison", {}), indent=2)[:3000])
