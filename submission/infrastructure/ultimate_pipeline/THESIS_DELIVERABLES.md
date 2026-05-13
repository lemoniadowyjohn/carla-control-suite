# Thesis deliverables (definition of done)

This document defines the thesis-critical outputs and where they must be written on disk.

## Fixed Ingolstadt bbox (OSM cut)
- Lat-Min: 48.74935649548228  
- Lon-Min: 11.422268084715878  
- Lat-Max: 48.77444431571603  
- Lon-Max: 11.47882091528412  

## Required artifact structure
All generated artifacts go under:

\\\
artifacts/
  datasets/
  experiments/
\\\

### Dataset: generated maps
Folder:
\\\
artifacts/datasets/maps_ingolstadt_bbox_<bboxhash>/
  run_0001/
    bbox.json
    input_osm.txt        # path or sha256/source info
    map.xodr
    hardening_report.json
    signature.json
    run_manifest.json
  run_0002/...
\\\

### Experiments
Determinism:
\\\
artifacts/experiments/determinism_osm2xodr/
  hashes.csv
  report.json
  diffs/ (optional)
\\\

Structural domain gap:
\\\
artifacts/experiments/domain_gap_structural/
  structural_metrics.csv
  plots/
\\\

Elevation gap:
\\\
artifacts/experiments/elevation_gap/
  elevation_metrics.csv
  plots/
\\\

Roundabout gap:
\\\
artifacts/experiments/roundabout_gap/
  roundabout_metrics.csv
  plots/
\\\

CARLA visual QA:
\\\
artifacts/experiments/carla_visual_qa/
  manual/
    manifest.json
    screenshots/*.png
  generated_run_0003/
    manifest.json
    screenshots/*.png
\\\

## Road quarantine + reproducibility artifacts
- roads_quarantined.json records quarantined road IDs, reasons, thresholds, and hashes
- map_content_fingerprint.json stores the final XODR hash (post-quarantine)
- determinism_fingerprint.json records git commit, python/OS info, env, and seeds
- pipeline_health_summary.json aggregates gate outcomes and quarantine counts
- settings_snapshot.json includes bbox, OSM source, smoothing params, quarantine thresholds, and CLI args

## Sensor rig rules (calib_data.json)
- Cameras: ignore \K\ and \D\; use \K_undistortion\ (pinhole intrinsics)
- Use \image_size\ width/height
- cTv is Vehicle?Camera transform (do not invert)
- LiDAR: vTl is LiDAR?Vehicle transform (MUST BE INVERTED for CARLA attachment)

## Stage 11: local perception + screenshots (optional)
- Implemented in the pipeline as STEP 10C/10D/10E inside `main_pipeline.py`
- Runs only if CARLA is reachable and settings enable it; failures are best-effort and do not abort batch runs
- Outputs: `road_defects.json`, `screenshots/screenshot_status.json`, optional local perception artifacts
- Smoke-load QA (best-effort):
  - `python -m ultimate_pipeline.tools.smoke_load_xodr --xodr <tile_or_map.xodr> --out <run_dir> --screenshot-timeout 8`
  - Add `--qa-sensors` to capture 1 frame per calibrated camera + 1 LiDAR snapshot

## Stage 12: interactive simulator (optional)
- Requires CARLA running and a user-present session; never runs by default
- Enable explicitly: set `ENABLE_SIMULATION_GATE=True` in settings and `UP_INTERACTIVE=1` in the environment
- Run: `python ultimate_pipeline/run_pipeline.py`

## Tile-based validation policy
- Smoke-load: prefer a canonical tile (`tile_0_0.xodr`) when using tiled outputs
- If a merged/full XODR is available, use that for smoke-load instead of a random tile
- Tile-based QA remains optional but is recommended for seam checks when using tiled maps


## Checklist (minimum)
- [x] N generated map runs saved with \map.xodr\, \signature.json\, \
un_manifest.json\
- [x] Determinism report: \hashes.csv\ + \
eport.json\
- [x] Structural gap: \structural_metrics.csv\ + plots
- [ ] Elevation + roundabout metrics + plots
- [ ] CARLA QA screenshots for manual + 2–3 generated maps
- [ ] One perception generalization result (mIoU on manual map; optional entropy on real unlabeled)

