# DSV12 — Manifest Completion: Converter Profile, CARLA/Osm2Odr Version, CRS Contract Hash

**Model:** DeepSeek V4 Light · **Mode:** BOUNDED WRITE (campaigns/ingolstadt_cooked_perception_v1/manifest.json + candidate/manifest.json ONLY + reports) · **Task ID:** DSV12-MANIFEST
**Branch:** `integration/governed-map-quality-20260729` · **Base SHA:** `953ae945deb9064b35ff145b53f97dff969673d9`
**Writer lock:** `DSV12-MANIFEST` (acquired via canonical `WriterLock.acquire`; released after push)
**Verdict:** `MANIFEST_COMPLETED`

## 1. Fields bound (identical in both manifests)

| Field | Bound value | Evidence source |
|---|---|---|
| `converter_profile` | `osm_to_xodr_wrapper.py (ultimate_pipeline/osm) sha256 2678373C3AC9AB688D6B7CDFB30D326345605FF9162CC3901F1A51323DFE4973 — donor worktree codex-full-pipeline-rerun-20260427 (DSV02 matrix: codex-full-pipeline-rerun variant); Osm2Odr invoked via CARLA PythonAPI (carla.Osm2Odr + Osm2OdrSettings)` | `candidate/osm_to_xodr_conversion_status.json` donor_root = `carla_main_governed\work\codex-full-pipeline-rerun-20260427`; on-disk SHA256 of that worktree's `ultimate_pipeline/osm/osm_to_xodr_wrapper.py` = `2678373C3AC9…` (matches DSV02_xodr_donor_matrix entry for codex-full-pipeline-rerun); wrapper L151-180 calls `carla.Osm2Odr.convert` with `Osm2OdrSettings` |
| `carla_osm2odr_version` | `UNKNOWN_UNSOURCED (Osm2Odr via CARLA PythonAPI carla.Osm2Odr; no CARLA/Osm2Odr version string found in donor code or logs)` | Grep of donor worktree: no explicit CARLA/Osm2Odr version (only `get_server_version` call sites, `SETTINGS_SCHEMA_VERSION`); `carla_client.log` diagnostics contain no version string. Bound as unsourced rather than invented (coordinator rule) |
| `crs_contract_hash` | `8886CE90FD2F7D4F61B319FBCB162B0FD536211AFA31EEF2FD4F32921084D000` | SHA256 of `reports/visual_structural_reconciliation/C44V01_coordinate_contract.json` (14,823 bytes), recomputed and confirmed |

## 2. Verification

- Both manifests re-validated as JSON; only the 3 new fields added — no other field modified.
- Root manifest: 3-line addition before `protected_paths_not_modified`. Candidate manifest: 3 fields + trailing-brace normalization.
- OSM2World/Blender versions remain N/A-by-policy (CARLA_GENERATED_ROAD); random seeds were already flagged in DSV10 — out of DSV12 scope.

## 3. Notes

- `converter_profile` names the wrapper variant sha, not a release version — the only provenance-verifiable identifier (wrapper file is untracked in the governed repo).
- `carla_osm2odr_version` is bound-but-unsourced; follow-up: capture `carla.__version__`/`get_server_version()` at next runtime to source it.
