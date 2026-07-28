# Stage Mutation Matrix

## Pipeline: `ultimate_pipeline/main_pipeline.py`

| Stage | Operation | Reads | Mutates (XODR) | Toggle | Default (Hardened) |
|---|---|---|---|---|---|
| **0** Preflight | CARLA connect, determinism, DEM check, OSM download | INPUT_XODR path, DEM_TIF, OSM_FILE | None (no XODR touched) | N/A | N/A |
| **1** Sanitize | XODRSanitizer sanitization + optional SUMO repair | INPUT_XODR | New `<OpenDRIVE>`: header/road/junction cleaned | `ENABLE_SUMO_REPAIR` | True |
| **2** Topology | geoReference provenance, junction ref repair, topology lint, SUMO repair, structure scan | sanitized (stage 1) | Always: `<header><geoReference>` patched; `<link><predecessor\|successor>` with dead junction refs removed. Optional: `ENABLE_AGGRESSIVE_STRUCTURE_PRUNE` deletes entire `<road>` elements; `ENABLE_SUMO_REPAIR` rewrite via SUMO | `ENABLE_AGGRESSIVE_STRUCTURE_PRUNE` | **False** |
| **3** Topology Repair | `TopologyRepair.run()` | working_topology (stage 2) | `<road>` successor/predecessor chains fixed, dead ends corrected, `<junction>` links sanitized | N/A (always) | Always ON |
| **4** Enrichment | Roundabouts, traffic lights, buildings, realism, OSM meta | topo_fixed (stage 3) | `ENABLE_ROUNDABOUT_RECONSTRUCTION`: `<road>` geometry reconstructed as roundabouts. Always: roundabout tagging. `ENABLE_TRAFFIC_LIGHTS`: `<signal>` inserted. `ENABLE_BUILDINGS`: `<object type="building">`. `ENABLE_REALISM`: `<object>` realism objects. Always: speed limits, turn lanes, signs from OSM | `ENABLE_ROUNDABOUT_RECONSTRUCTION` | **False** |
| | | | | `ENABLE_TRAFFIC_LIGHTS` | **False** |
| | | | | `ENABLE_BUILDINGS` | True |
| | | | | `ENABLE_REALISM` | True |
| **5+6** Geometry | Step 6 first: PlanView, then Step 5: DEM elevation on frozen XY | topo_fixed (stage 4) | **Unsafe (gated):** `PlanViewSmoother.smooth_heading_jumps`, `merge_small_geometries`, `merge_short_segments`, `recompute_geometry_starts`. **Always:** curvature clamp, recompute s-values, `MeshContinuityRepairer`, junction connector rebuild, planView seam auto-repair. Sets `<header geometryFrozen="true">`. **DEM:** `<elevationProfile><elevation>` written for every road | `ENABLE_UNSAFE_PLANVIEW_MUTATIONS` + profile permits experimental_unsafe | **False** |
| **7** Lanes | Lane generation, LaneSection fix, lane repair, offsets, sidewalks | geo_final (stage 5+6) | Always: `<laneSection><lane>` driving lanes via `LaneGenerator.ensure_lanes`; `<lane>` width/offset standardized; `<laneOffset>` smoothed; `<lane>` cross-sections enforced. `ENABLE_SIDEWALKS`: `<lane type="sidewalk">`. Lane width invariants enforced | `ENABLE_LANE_GNN_REFINER` | **False** |
| | | | | `ENABLE_SIDEWALKS` | True |
| **8** LaneLinks + Markings | LaneLink regen, markings, laneSection successor repair, collision mesh, junction link patch | lanes_out (stage 7) | Always: remove driving lane id=0; add missing `<link>` nodes; `MarkingBuilder.add_basic_markings`; `repair_and_assert_lane_section_successors`. `ENABLE_LANELINK_REGEN`: `<lane><link>` regenerated (needs experimental_unsafe). `USE_SHAPELY`: collision mesh | `ENABLE_LANELINK_REGEN` + profile | **False** |
| **9** Tiling | Map tiling, S-invariant fix, road link repair | final_out (stage 8) | `ENABLE_TILING`: creates `tile_*.xodr` files. `ENABLE_LANESECTION_FIX`: fixes negative s-values in tiles (default ON). `UP_ENABLE_ROAD_LINK_TARGET_REPAIR`: corrects road link targets in tiles | `ENABLE_TILING` | True |
| **10** Tile QA | Subprocess tile validation (CARLA load, spawn QA, seams) | tiles_dir, graph_path, final_out | None (read-only; subprocess CARLA workers) | `ENABLE_SIMULATION_GATE` | **False** |
| **10C/D/E** Perception | Road defect scan, local perception, screenshots | final_out | None (read-only; CARLA subprocesses capture data) | `ENABLE_ROAD_DEFECT_SCAN` | **False** |
| | | | | `ENABLE_LOCAL_PERCEPTION` | True |
| | | | | `ENABLE_SCREENSHOTS` | True |
| **11** Simulator | Interactive CARLA simulation | final_out, graph_path | None (read-only) | `ENABLE_SIMULATION_GATE` + `UP_INTERACTIVE=1` | **False** |
| **12** Domain Gap | Structural gap analysis (manual vs auto) | final_out, manual_xodr | None (read-only) | `ENABLE_DOMAIN_GAP` | True |
| **14** Finalization | Quality gates, determinism fingerprint, run summary, LLM | final_out | None (read-only; write summary artifacts only) | `ENABLE_QUALITY_GATES_WRAPPER` | True |

## Summary of Hardened Defaults (structural_release profile)

- **Unsafe planView mutations**: OFF (needs `ENABLE_UNSAFE_PLANVIEW_MUTATIONS=True` + `RELEASE_PROFILE=debug`)
- **LaneLink regeneration**: OFF (needs `ENABLE_LANELINK_REGEN=True` + `RELEASE_PROFILE=debug`)
- **Roundabout reconstruction**: OFF (needs `UP_ENABLE_ROUNDABOUT_RECONSTRUCTION=1`)
- **Traffic light insertion**: OFF (needs `UP_ENABLE_TRAFFIC_LIGHTS=1`)
- **Aggressive structure prune**: OFF (needs `UP_ENABLE_AGGRESSIVE_STRUCTURE_PRUNE=1`)
- **Lane GNN refiner**: OFF (needs `ENABLE_LANE_GNN_REFINER=True`)
- **Tile QA / Simulation**: OFF (needs `ENABLE_SIMULATION_GATE=True`)
- **Road defect scan**: OFF (needs `ENABLE_ROAD_DEFECT_SCAN=True`)

## Hardened Profile Matrix

| Profile | strict_quality_gates | experimental_unsafe |
|---|---|---|
| `structural_release` | True | **False** |
| `visual_build` | True | **False** |
| `scenario_augmentation` | False | **False** |
| `debug` | False | **True** |
