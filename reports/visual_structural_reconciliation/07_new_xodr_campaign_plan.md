# 07 — New XODR Campaign Plan (`ingolstadt_cooked_perception_v1`)

**Status:** architecture/order = DECIDED (from prompt §11.4); **source selection = PENDING** (needs DSV02 + Claude §11.3).

## Safe campaign order (authoritative — supersedes the old order where elevation preceded PlanView mutation)
```
valid OSM
 → deterministic OSM→XODR conversion (≥2 identical runs, compare semantic hashes)
 → topology authority
 → final horizontal geometry / connectors
 → HORIZONTAL FREEZE (horizontal_freeze.json)
 → elevation against frozen geometry (known CRS+datum; block on unknown/missing DEM)
 → lanes and LaneLinks
 → signals and regulatory semantics
 → immutable structural validation
 → visual generation FROM SAME SOURCE IDENTITY
 → coordinate alignment (C44V01 gate)
 → minimal Unreal fixture
 → full cook
 → CARLA drivability
 → perception
```

## Preservation invariants (never overwrite/rename/delete)
`thesis_results/structural_gap_v1/run_11/` · `artifacts/final_runs/scenario_b_audit/contract_run/` ·
`08_final_structural_gap.xodr` · `submission/results/structural_gap_run11/`.

## Lineage
New artifacts ONLY under `campaigns/ingolstadt_cooked_perception_v1/`. Manifest binds Git SHA · OSM SHA · OSM bounds · converter profile · CARLA/Osm2Odr version · CRS-contract hash · DEM hash · OSM2World version · Blender version · visual config · seeds.

## Visible-road authority (choose exactly one before Unreal import — rule 4.6)
- **(A)** XODR-derived road mesh + OSM2World environment only, **or**
- **(B)** OSM2World road mesh + proven exact XODR alignment.
Do NOT import two overlapping road surfaces. Decision deferred to Claude §11 after C44V01 (couples to AG07 B3 `CARLA_GENERATED_ROAD` option).

## PENDING inputs (fill after discovery)
Authoritative OSM (sha/bounds/validity), OSM→XODR donor, structural-validation donor, visual donor(s), CRS contract, FBX decision, DEM availability. These are produced by DSV01/DSV02/C44V01 — not decided in this file.
