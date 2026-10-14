#!/usr/bin/env python3
"""Create COOK_LOG.txt and final summary."""
import json
from pathlib import Path

cook_dir = Path("reports/production_readiness/20260924T100614Z_FULL_GRID_TILE_FBX_COOK")
with (cook_dir / "COOK_RESULTS.json").open() as f:
    cook = json.load(f)

log_lines = []
log_lines.append("CARLA Large-Map Full-Grid FBX Cook Log")
log_lines.append("========================================")
log_lines.append(f"Run ID: {cook['run_id']}")
log_lines.append(f"Map: {cook['map_name']}")
log_lines.append(f"Tile size: {cook['tile_size_m']}m")
log_lines.append(f"Buildings: {cook['buildings_loaded']} total, {cook['buildings_placed']} placed, {cook['buildings_unplaceable']} unplaceable")
log_lines.append(f"Occupied cells: {cook['occupied_cells']}")
log_lines.append(f"Tiles attempted: {cook['tiles_attempted']}")
log_lines.append(f"Tiles OK: {cook['tiles_ok']}")
log_lines.append(f"Tiles failed: {cook['tiles_failed']}")
log_lines.append(f"Roundtrip pass: {cook['roundtrip_pass']}")
log_lines.append(f"Roundtrip fail: {cook['roundtrip_fail']}")
log_lines.append(f"Wall clock: {cook['wall_elapsed_sec']}s")
log_lines.append(f"Anomalies: {len(cook['anomalies'])}")
log_lines.append("")
log_lines.append("Per-Tile Results:")
log_lines.append("-" * 80)
for r in cook["results"]:
    ti = r["tile_index"]
    log_lines.append(f"  Tile ({ti[0]},{ti[1]}): {r['building_count']} buildings, {r['objects_total']} objects, {r['vertices_total']} vertices, {r['faces_total']} faces, {r['fbx_bytes']/1024:.1f} KB, roundtrip={r['roundtrip_verdict']}, status={r['status']}")
log_lines.append("")
log_lines.append("Source Provenance:")
log_lines.append(f"  Buildings source: {cook['source_provenance']['buildings_source']}")
log_lines.append(f"  Buildings SHA256: {cook['source_provenance']['buildings_source_sha256']}")
log_lines.append(f"  Map of record: {cook['source_provenance']['map_of_record']}")
log_lines.append(f"  Map SHA256: {cook['source_provenance']['map_of_record_sha256']}")
log_lines.append(f"  Header offset XY: {cook['source_provenance']['header_offset_xy']}")
log_lines.append("")
log_lines.append("Bug fixes applied:")
log_lines.append("  - Duplicate type key in multipolygon XML tags (write_tile_osm_xml)")
log_lines.append("")
log_lines.append("Claim boundary: Offline FBX generation only. No UE4/UE5 Editor invoked.")

cook_log_path = Path("Import/Ingolstadt/COOK_LOG.txt")
cook_log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
print(f"Wrote {cook_log_path}")

print("\n=== FINAL PACKAGE CONTENTS ===")
for f in sorted(Path("Import/Ingolstadt").iterdir()):
    print(f"  {f.name}")

print("\n=== ALL EVIDENCE FILES ===")
evidence = ["AUTO_COOK_RECEIPT.json", "IMPORT_MANIFEST.json", "PACKAGE_SHA256.json", "COOK_LOG.txt"]
for e in evidence:
    p = Path("Import/Ingolstadt") / e
    if p.exists():
        print(f"  {e}: EXISTS ({p.stat().st_size} bytes)")
    else:
        print(f"  {e}: MISSING")

print("\n=== PHASES C-F: PENDING UE4.26/CARLA 0.9.16 ===")
print("  UE_CONTENT_AUDIT.json: requires make import")
print("  RUNTIME_LOAD_RECEIPT.json: requires CARLA runtime")
print("  SEMANTIC_SMOKE.json: requires CARLA runtime")
print("  SEAM_TRAVERSAL.json: requires CARLA runtime")
print("  COOK_LOG.txt: CREATED (offline log)")
print("  PACKAGE_SHA256.json: CREATED")
