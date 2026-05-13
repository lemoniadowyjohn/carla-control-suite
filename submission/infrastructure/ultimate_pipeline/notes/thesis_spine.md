# Thesis spine (working notes)

## Research question
How large is the domain gap between automatically generated OSM→CARLA maps (same Ingolstadt bbox) and a manually modeled CARLA Ingolstadt map, and how does that gap affect perception generalization?

## Fixed Ingolstadt bbox (OSM cut)
- Lat-Min: 48.74935649548228
- Lon-Min: 11.422268084715878
- Lat-Max: 48.77444431571603
- Lon-Max: 11.47882091528412

## Main claims (to be supported by artifacts)
1) Automatically generated maps differ structurally from the manual map (roads/lanes/junctions/curvature/intersections).
2) Repeating OSM→XODR conversion may (or may not) produce different outputs (“natural domain randomization”).
3) Map differences explain part of the perception generalization gap when training on generated maps and testing on the manual map.
4) Elevation + roundabout geometry are key contributors to map quality issues / CARLA import failures.

## Evidence checklist (what files must exist)
- Generated maps dataset:
  - artifacts/datasets/maps_ingolstadt_bbox_*/run_0001/map.xodr
  - artifacts/datasets/maps_ingolstadt_bbox_*/run_0001/signature.json
  - artifacts/datasets/maps_ingolstadt_bbox_*/run_0001/run_manifest.json
- Determinism:
  - artifacts/experiments/determinism_osm2xodr/hashes.csv
  - artifacts/experiments/determinism_osm2xodr/report.json
- Structural domain gap:
  - artifacts/experiments/domain_gap_structural/structural_metrics.csv
  - artifacts/experiments/domain_gap_structural/plots/
- Elevation + roundabouts:
  - artifacts/experiments/elevation_gap/elevation_metrics.csv
  - artifacts/experiments/roundabout_gap/roundabout_metrics.csv
- CARLA Visual QA:
  - artifacts/experiments/carla_visual_qa/manual/screenshots/
  - artifacts/experiments/carla_visual_qa/generated_run_000X/screenshots/

## Figures/Tables I plan to include (placeholder names)
- Table: determinism hashes (hashes.csv)
- Table: structural metrics (structural_metrics.csv)
- Figure: lane count / curvature distributions (plots/)
- Figure: elevation slope distributions (elevation plots)
- Figure: CARLA screenshots (manual + generated maps)

## Limitations (draft bullets)
- CARLA import can fail for some generated maps (roundabouts/elevation/geometry artifacts).
- DEM resolution and smoothing may distort elevation compared to real terrain.
- N generated maps may be limited by runtime and stability.
- Real-world evaluation may be unlabeled; use confidence/entropy proxies.

## Panic recovery plan (if time runs out)
- Keep dataset + determinism + structural gap analysis as the core thesis.
- Treat CARLA visual QA as proof-of-existence for a small subset of maps.
- Keep ML evaluation minimal (one segmentation comparison) or omit if it blocks finishing.
