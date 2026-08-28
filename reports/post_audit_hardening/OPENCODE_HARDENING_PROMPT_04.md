# OPENCODE HARDENING PROMPT 04 — Enriched map-of-record regen (SUMO/F1/frame blockers)

**Status: EXECUTED 2026-08-19.** Fixes the canonical regen blockers and produces the
first buildings+signals-enriched, SUMO-repaired, acceptance-passing map of record.

## Verdict
`ENRICHED_MAP_OF_RECORD_PRODUCED valid_for_experiments=True candidate_sha256=69b1f52016ebdc3e643616f86161d85789624c94d48e5caf56c53004d534de6e`
supersedes `83418373…` (buildings=1/signals=0 caveats). | DONE | needs human pin review + commit.

## Root causes fixed (code)
1. **`scripts/regen_map_of_record.py::_sumo_status`** — SUMO 1.24.0 is installed at
   `C:\Sumo\sumo-win64extra-1.24.0\sumo-1.24.0` but not on PATH and `SUMO_HOME` unset. The
   guard only accepted `SUMO_HOME`/PATH and wrongly blocked regen, contradicting the
   pipeline's own `Settings.SUMO_NETCONVERT` autodetect (`settings.py:1904`, walks `C:\Sumo`).
   → Guard now accepts `Settings.SUMO_NETCONVERT` when it resolves to an existing file.
2. **`UP_OSM_FILE` never wired** — the F1 DEM CRS contract (`elevation_importer.py:1372`)
   reads `UP_OSM_FILE` to establish the geographic frame against the pinned OSM. The
   canonical entrypoint verified the manifest but never passed it → `resolve_sampling_crs`
   returned `UNRESOLVED/osm_source_unavailable` and stage 05 failed closed.
   → `_run_pipeline` now sets `UP_OSM_FILE` from the manifest's `roads_osm` path.
3. **Lane-successor autofix off by default** — SUMO repair (netconvert) drops lane-level
   successors; stage 08 enforces the CARLA invariant and crashed with 10,565 broken lanes
   (C0 evidence `LANE_SUCCESSOR_AUTOFIX_DISABLED_BY_DEFAULT`: 10565/10565 repaired,
   0 downgraded when enabled).
   → `_run_pipeline` now sets `UP_AUTOFIX_LANE_SUCCESSORS=1`, `UP_STRICT_LANE_SUCCESSORS=0`.
4. **Global frame kept through finalization** — `--offset.disable-normalization` preserves
   tmerc(0,0) global coords (~832k/5458k), which breaks CARLA float32 precision and fails
   `origin_sanity` (centroid 5.5M m). The C0 path only got a local frame because it ran
   with the manual map / THESIS_STRICT CRS comparability.
   → New `_rebase_to_local` post-finalization step: translation-invariant shift of planView
   geometry to bbox-min origin, original frame recorded in header `<offset>`; acceptance is
   measured on the re-based file; frame recorded in `rebase_report.json` + provenance.

## Tests added
- `tests/unit/test_regen_map_of_record_sumo_guard.py` (7 tests): settings/SUMO_HOME/PATH
  acceptance, no-SUMO raise, env wiring (`UP_OSM_FILE`, `UP_AUTOFIX_LANE_SUCCESSORS`,
  `UP_STRICT_LANE_SUCCESSORS`, `UP_DISABLE_CARLA`), `_rebase_to_local` global→local + no-op.

## Execution evidence
- Regen run: `campaigns/ingolstadt_cooked_perception_v1/regen/20260819T142310Z/`
- Provenance: `regen_provenance.json` (osm sha `b9e07465…`, seed sha `c32d136a…`)
- Frame: `rebase_report.json` (dx=832671.676, dy=5458671.104)
- Candidate: `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260819_160350.xodr`
- Pin evidence: `C1_PIN_20260817/C1_PIN_MAP_OF_RECORD_20260819.json`
- Acceptance: valid=True; hard_fail=[]; soft=33 isolated lane components; metrics: roads=32297,
  signals=21171, buildings=5686, objects=51797, lane_successor_missing=0, length_invariant=0,
  dem_coverage=1.0, seams=0.

## Held / operator (unchanged)
- Human pin review + commit of this batch.
- Live CARLA drivability smoke on the new candidate (restart server).
- UE4.26 cook + fair capture; manual Grid0821/0828 for C2/B3/B4.
- Note: `settings_snapshot()` reports RELEASE_PROFILE=DEVELOPMENT because it builds a fresh
  `Settings()` without the env override — reporting-only nit, pipeline ran PERCEPTION_RELEASE.