# P11 REVIEW-STATIC-001 — Static Regression Sweep

Date: 2026-08-02
Scope: root package `ultimate_pipeline/`, root `opendrive_geometry/`, root-level
entrypoints, after commits P05–P10 (HEAD `715441c4`).

## Checks

### 1. Bytecode compilation
- `python -m compileall -q ultimate_pipeline opendrive_geometry` → exit 0
- Root `*.py` entrypoints (`main_pipeline.py`, `cli.py`, `entrypoints.py`, + 1)
  → `py_compile` all OK

### 2. Import sweep (18 modules)
`ultimate_pipeline.main_pipeline`, `.cli`, `.entrypoints`, `.config.settings`,
`.pipeline_stages.stage_04_enrichment`, `.pipeline_stages.stage_09_tiling`,
`.tiling.tile_extractor`, `.tiling.tile_metadata`, `.quality.check_elevation_seams`,
`.enrichment.osm2world_runner`, `.enrichment.blender_runner`, `.audit`,
`.topology.topology_validation`, `.signals.signal_enrichment`,
`.tiling.tile_equivalence`, `.elevation.elevation_seam_fixer`,
`.dem.dem_provenance`, `opendrive_geometry.freeze`
→ 18/18 imported OK (pre-existing path warnings from `settings.py` only)

### 3. Test suites
- `pytest ultimate_pipeline/tests/unit tests/opendrive_geometry`
  → **2528 passed, 78 skipped, 0 failed** (64 s)
- `test_sys001_import_smoke` → 11 passed

### 4. Working-tree hygiene
- No unintended modifications: only the 3 known pre-existing modified tracked
  files (`stage_08_final_integrity.py`, `stage_08_integrity.py` under
  `submission/`, `run_full_domain_gap.py`) and pre-existing untracked artifacts
  (`audit_output/`, `audit_output.zip`, `.githooks/`, `carla_governed/`, etc.)

## Verdict
**PASS** — no static regressions introduced by P05–P10.
