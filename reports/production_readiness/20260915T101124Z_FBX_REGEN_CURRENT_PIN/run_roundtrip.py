import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from ultimate_pipeline.enrichment.fbx_roundtrip import run_fbx_roundtrip

report_dir = Path(__file__).resolve().parent
artifacts = report_dir / "artifacts"
fbx_path = artifacts / "ingolstadt_cooked_perception_v1_b9e07465_full_pin.fbx"
blender_manifest_path = artifacts / "ingolstadt_cooked_perception_v1_b9e07465_full_pin.blender_manifest.json"
blender_exe = Path(r"E:/Program Files/Blender Foundation/Blender 4.3/blender.exe")

source_manifest = json.loads(blender_manifest_path.read_text(encoding="utf-8"))

ok, report = run_fbx_roundtrip(
    fbx_path=fbx_path,
    output_dir=artifacts,
    blender_exe=blender_exe,
    source_manifest=source_manifest,
    timeout_sec=600,
)

report["ok"] = ok
out_path = artifacts / "fbx_roundtrip_report.json"
out_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
print("ROUNDTRIP OK:", ok)
print("Verdict:", report.get("comparison", {}).get("verdict"))
print(json.dumps(report.get("comparison", {}), indent=2))
