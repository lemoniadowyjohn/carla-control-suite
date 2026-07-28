# Active Execution Path — Gemini 3.1 Pro Audit

## Summary Diagram

```
run()
 └─ _run_internal()
     ├── [Preamble: archive, bootstrap, DB, settings, determinism, OSM, DEM, CARLA]
     ├── STAGE  0: sanitize          → _step1_sanitize()            [FILE MISSING from tracking]
     ├── STAGE  1: topology          → _step2_topology_semantics()  [FILE MISSING from tracking]
     ├── STAGE  2: topology_repair   → _step3_topology_repair()     [FILE MISSING from tracking]
     ├── STAGE  3: enrichment        → _step4_enrichment()          [stage_04_enrichment ✓ tracked]
     ├── STAGE  4: geometry          → _step5_geometry_elevation_continuity()
     │                                ├── _step6_planview_continuity() [stage_06_links ✓]
     │                                │    └── 4 _stage_gate calls (06_continuity/*)
     │                                ├── Freeze geometry + hash
     │                                └── _step5_dem_and_geometry() [stage_05_geometry ✓]
     │                                     └── 5 _stage_gate calls (05_elevation/*)
     ├── STAGE  5: lanes             → _step7_lanes_sidewalks()     [FILE MISSING from tracking]
     │                                └── 2 _stage_gate calls (07_lanes/*)
     ├── STAGE  6: final_integrity   → _step8_markings_and_integrity() [stage_08_integrity ✓]
     │                                ├── 2 _stage_gate calls (08_final/*)
     │                                ├── 08G drivable_surface gate
     │                                └── 08H full_map_metrics gate
     ├── STAGE  7: tiling            → _step9_tiling()              [FILE MISSING from tracking]
     │                                └── 2 _stage_gate calls (09_tiling/*)
     ├── STAGE  8: tile_qa           → _step10_tile_qa()            [FILE MISSING from tracking]
     ├── STAGE  9: perception        → _step10c_road_perception_screenshots()
     ├── STAGE 10: simulation        → _step11_simulation()         [FILE MISSING from tracking]
     ├── STAGE 11: domain_gap        → _step12_domain_gap()         [FILE MISSING from tracking]
     ├── STAGE 12: quality_gates     → _run_quality_gates_wrapper() [inline]
     ├── STAGE 13: cumulative_gates  → _finalize_gates()            [inline — NEW]
     └── STAGE 14: final_summary     → _final_summary_and_llm()     [inline]
```

## Critical Finding: Stage Files Missing from Git Tracking

| Stage | Delegation file | Tracked? | Status |
|---|---|---|---|
| 0 sanitize | `pipeline_stages/stage_01_sanitize.py` | **NO** | Missing from git |
| 1 topology_semantics | `pipeline_stages/stage_02_topology_semantics.py` | **NO** | Missing from git |
| 2 topology_repair | `pipeline_stages/stage_03_topology_repair.py` | **NO** | Missing from git |
| 3 enrichment | `pipeline_stages/stage_04_enrichment.py` | ✓ | Tracked |
| 4 geometry | `pipeline_stages/stage_05_geometry.py` | ✓ | Tracked |
| 5 planview/links | `pipeline_stages/stage_06_links.py` | ✓ | Tracked |
| 6 lanes | `pipeline_stages/stage_07_lanes.py` | **NO** | Missing from git |
| 7 markings/integrity | `pipeline_stages/stage_08_integrity.py` | ✓ | Tracked |
| 7b final integrity | `pipeline_stages/stage_08_final_integrity.py` | ✓ | Tracked |
| 8 tiling | `pipeline_stages/stage_09_tiling.py` | **NO** | Missing from git |
| 9 tile_qa | `pipeline_stages/stage_10_tile_qa.py` | **NO** | Missing from git |
| 10 simulation | `pipeline_stages/stage_11_simulation.py` | **NO** | Missing from git |
| 11 domain_gap | `pipeline_stages/stage_12_domain_gap.py` | **NO** | Missing from git |

**Impact:** The pipeline WILL fail at runtime when it reaches the first missing stage file. Only stages 3–7 can execute successfully from tracked code.

## Gate Call Inventory (19 total)

| # | Stage Label | Gate Name | Source | Always? |
|---|---|---|---|---|
| 1 | `06_continuity` | `geometric_continuity` | stage_06_links.py:92 | ✓ |
| 2 | `06_continuity` | `road_quarantine` | stage_06_links.py:164 | toggle |
| 3 | `06_continuity_quarantine` | `geometric_continuity` | stage_06_links.py:169 | toggle |
| 4 | `06_continuity` | `planview_internal_seams` | stage_06_links.py:257 | toggle |
| 5 | `05_elevation` | `dem_full_coverage` | stage_05_geometry.py:457 | ✓ |
| 6 | `05_elevation` | `dem_coverage` | stage_05_geometry.py:757 | ✓ |
| 7 | `05_elevation` | `elevation_variance` | stage_05_geometry.py:783 | ✓ |
| 8 | `05_elevation` | `elevation_stddev` | stage_05_geometry.py:841 | ✓ |
| 9 | `05_elevation` | `elevation_continuity` | stage_05_geometry.py:941 | ✓ |
| 10 | `07_lanes` | `lane_width_continuity` | main_pipeline.py:1988 | toggle |
| 11 | `07_lanes` | `lane_geometry_continuity` | main_pipeline.py:1997 | toggle |
| 12 | `08_final` | `origin_sanity` | main_pipeline.py:2008 | ✓ |
| 13 | `08_final` | `elevation_seams` | main_pipeline.py:2021 | ✓ |
| 14 | `08_final_autofix` | `elevation_seams` | main_pipeline.py:2066 | toggle |
| 15 | `08_carla_prune` | `geometric_continuity` | stage_08_integrity.py:898 | toggle |
| 16 | `08G` | `drivable_surface` | main_pipeline.py:2158 | toggle |
| 17 | `08H` | `full_map_metrics` | main_pipeline.py:2174 | ✓ |
| 18 | `09_tiling` | `geometric_continuity` | main_pipeline.py:2210 | toggle |
| 19 | `09_tiling` | `elevation_continuity` | main_pipeline.py:2215 | toggle |

## Default Toggle States (Safe Defaults)

| Toggle | Default | Effect |
|---|---|---|
| `UP_ENABLE_LANE_WIDTH_CONTINUITY` | `1` | ON |
| `UP_ENABLE_LANE_GEOMETRY_CONTINUITY` | `1` | ON |
| `UP_ENABLE_GEOMETRIC_CONTINUITY` | `1` | ON |
| `UP_ENABLE_PLANVIEW_SEAM_GATE` | not set (see env) | OFF |
| `UP_ENABLE_ROAD_QUARANTINE` | not set | OFF |
| `UP_AUTOFIX_POSTPRUNE_ELEVATION` | not set | OFF |
| `ENABLE_DRIVABLE_SURFACE_HOLE_SCAN` | `True` (code default) | ON |
| `ENABLE_ROUNDABOUT_RECONSTRUCTION` | `False` (hardened) | OFF |
| `ENABLE_TRAFFIC_LIGHTS` | `False` (hardened) | OFF |
| `UP_AUTOFIX_LANE_SUCCESSORS` | `"0"` (hardened) | OFF |
| `UP_AUTOFIX_MISSING_LANE_SUCCESSORS` | `"0"` (hardened) | OFF |
| `UP_ENABLE_UNSAFE_PLANVIEW_MUTATIONS` | not set | OFF |
| `ENABLE_LANELINK_REGEN` | `False` | OFF |
