# Whole-pipeline critical audit — 2026-08-16 (read-only, while Codex runs C6/C7)

Evidence base: code + the completed C0 run's own QA reports (`…/C0_CLEAN_REGEN/qa_stage_reports/`) + the final candidate `08_final…linkpatched.xodr`. Severity-ranked; **NEW** = not already covered by C6 (continuity checker) or C7 (enrichment).

## SEV-1 — CRITICAL (thesis showstoppers)

### P1. Perception dataset is unreadable by its own trainer  **[NEW]**
- Capture (`perception/dataset_generator.py:200-201,412-413`, `perception/perception_runner_local_aug.py:282-283,427-435`) writes `dataset/images/<cam>/` + `dataset/labels/<cam>/`, and for semantic it calls `seg_img.convert(carla.ColorConverter.CityScapesPalette)` **before** save → the raw class-id (R channel = 0..28) is **overwritten with RGB palette colors**.
- Trainer/eval (`perception/min_train_segmentation.py:44-45`, `eval_sim_labeled.py:43-44`, `class_weights.py:77`) read `dataset/rgb/<cam>/` + `dataset/semseg_raw/<cam>/` expecting **raw uint8 class ids** (R = class).
- Net: (a) **directory-name mismatch** (`images|labels` vs `rgb|semseg_raw`) → trainer finds nothing; (b) even if matched, **palette conversion destroys the labels**; (c) detection mode writes `_empty_yolo_label()` → **empty boxes**. Only `experiments/thesis/run_vision_domain_gap.py`/`record_route_fixed.py` reference the correct layout — capture paths are inconsistent.
- **Impact:** the entire perception train/eval (the thesis core) runs on empty/garbage labels. **Fix before any perception run.**

## SEV-2 — HIGH (already prompted; confirmed broader impact)

### P2. Geometric-continuity checker over-counts (C6) — also fails 407/531 tiles  **[confirmed]**
- `check_geometric_continuity` ignores `link_kind`+`contactPoint` → 26701 false "discontinuities" (true corrected ≈ 8231, residual = 3.5 m junction lane-offset). Confirmed the **post-tiling 407/531 "failed tiles"** are the SAME bug (e.g. `tile_0_19`: predecessor 66333→45419, dxy=1447 m, dhdg=2.52). C6 clears the map gate AND tiling gate. Prompt: `C6_geometric_continuity_checker_correctness.md`.

### P3. Enrichment: 1 building, signals as props (C7)  **[confirmed]**
- buildings.geojson download failed + roads-only OSM → **1 building**; 21171 traffic lights are `<object>` props, not functional `<signal>`. Prompt: `C7_enrichment_completeness.md`.

## SEV-3 — MEDIUM (real, narrower)

### P4. Measurement-bug EPIDEMIC — gates don't measure what they claim  **[NEW, systemic]**
Multiple gates are unreliable, so green/red can't be trusted:
- `check_geometric_continuity` (P2) + `check_elevation_continuity` (977 "z-seams" on the same predecessor/junction links — likely same contactPoint blind spot).
- `08H full_map_metrics.elevation_continuity` = `{max_gradient:0.0, variance:0.0, num_segments:0}` → **measures nothing** (broken sub-metric).
- The C0 gate I wrote mis-tolerances G19 (reported 0 vs certifier 798) and false-negatived G-ELEV (`summarize_elevation` returns null on real 32297-record elevation). `diagnostics.elevation_summary.summarize_elevation` itself is buggy.
- "signals" counted as `<signal>` (=0) while content lives in `<object>` (P3).
- **Fix pattern:** every acceptance gate needs a positive + negative-control test; audit checkers for link-direction/contactPoint and element-type assumptions.

### P5. Elevation z-seams at junction boundaries  **[NEW]**
- `elevation_continuity: ok=false, 977 issues`, dz up to ~0.93 m at road links (mostly junction connectors). Real (roads meet at slightly different z) but small; partly overlaps the lane-offset artifact. Vehicles bump at ~2% of junctions. Note: elevation itself is sound (stddev 5.15 m, 70% of records sloped, DEM coverage 1.0).

### P6. Disconnected components + degenerate lane  **[NEW]**
- `graph_components: 10` — main = 35828, plus 9 islands (19,6,6, six ×1) → ~35 roads unreachable.
- `lane_width_continuity.min_width = 0.01 m` — a 1 cm lane (degenerate); `lane_geometry_continuity` 1 issue. Minor but should be quarantined/repaired.

## SEV-4 — LOW / hygiene

### P7. Fail-open on missing inputs  **[NEW]**
- buildings.geojson download failure → run continued with 1 building (should fail-closed for a map-of-record). Continuity gate non-strict (`fail_closed_active:false`) → pipeline proceeded on 27k "issues". Correct posture: fix checkers (P4) THEN make the gate strict.

### P8. Provenance: inputs not all pinned  **[NEW]**
- DEM (`cities/ingolstadt/dem/dem_ing.tif`) and the building source are not digest-pinned like the road OSM. For a reproducible thesis map, every input (roads OSM, DEM, buildings) must be pinned. The "suspicious elevation" diagnostic also over-fires (flagged all 32297) — noise.

## What is actually SOLID (balanced view)
- Drivable surface: **0** holes/seams/drops/dead-connections; connector_endpoint_errors: **0**.
- Real DEM elevation (stddev 5.15 m; 22759/32297 sloped; full DEM coverage).
- Lane successors repaired 10565→0 (inferred, none downgraded); 57399 lanelinks; 86013 roadMarks; 19390 sidewalks; 24940 lamp posts.
- Deterministic (seed=42); Osm2Odr seed clean.

## Recommended next Codex prompts
1. **C8 — Perception dataset correctness** (P1): unify capture→`rgb/`+`semseg_raw/`, save **raw class-id** semantic (no palette; palette only as a separate viz), real detection labels, round-trip test (capture→train reads it). SEV-1.
2. **C9 — Gate/checker correctness sweep** (P4): contactPoint/link-direction audit of all `check_*continuity` + fix `summarize_elevation` + `08H` elevation sub-metric + add positive/negative controls. (C6 is the first instance.)
3. Fold P5–P8 into C6/C7 tails or a hygiene pass.
