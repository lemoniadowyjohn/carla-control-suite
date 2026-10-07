# RQ1 Determinism Trial Status — 2026-10-07

## Executive Summary

**No completed trial runs.** One trial (run 01) was started but did not complete within the 2-hour timeout. The pipeline successfully executed stages 1-6 but was interrupted at stage 7 (lanes) after ~3 hours of wall time.

## Run 01 Details

| Field | Value |
|-------|-------|
| Run index | 1 |
| Mode | B (full downstream pipeline) |
| Start time | 2026-10-07T19:48:38Z |
| Last update | 2026-10-07T23:28:23Z |
| Duration at timeout | ~3 hours 40 minutes |
| Status at timeout | `running` / stage `lanes` |
| Receipt generated | **No** |
| Matrix updated | **No** |

## Pipeline Progress at Timeout

| Stage | Status | Duration | Notes |
|-------|--------|----------|-------|
| 1. Sanitize | ✅ Complete | ~2 min | XODR sanitization + SUMO validation |
| 2. SUMO | ✅ Complete | ~10 min | Net conversion |
| 3. Topology repair | ✅ Complete | ~22 min | Junction/connector repair |
| 4. Elevation (DEM) | ✅ Complete | ~55 min | **Major bottleneck** — PROJ/GDAL warnings, slow projection |
| 5. Planview merge | ✅ Complete | ~6 min | |
| 6. Continuity | ✅ Complete | ~55 min | Geometric continuity + geometric freeze |
| 7. Lanes | 🔴 Interrupted | ~8 min | Was running when timeout killed process |
| 8. Tiling | ⏸️ Not reached | — | |
| 9. Post-generation QA | ⏸️ Not reached | — | |
| Map acceptance | ⏸️ Not reached | — | No receipt generated |

## Technical Blockers

### 1. PROJ/GDAL Version Mismatch (Critical for DEM stage)
```
proj.db contains DATABASE.LAYOUT.VERSION.MINOR = 4 whereas a number >= 6 is expected.
It comes from another PROJ installation.
```
This causes repeated GDAL/PROJ warnings and likely contributes to the DEM stage taking ~55 minutes.

**Remediation**: `pip install --force-reinstall --no-cache-dir pyproj` in the venv, or align GDAL's PROJ data with pyproj's bundled one.

### 2. Trial Timeout Too Short
- Configured timeout: 2 hours (7200 seconds)
- Actual time to complete stages 1-7: ~3 hours 40 minutes
- Full pipeline (stages 1-9 + map acceptance) likely takes 4-5 hours

### 3. Mode A (OSM→XODR only) Not Implemented
`rq1_trial_run.py` Mode A is a stub — it falls through to full pipeline. A true Mode A (OSM→Osm2Odr only) would complete in ~15-20 minutes.

## Current Matrix State

```json
{
  "schema": "rq1_full_determinism_matrix/v1",
  "status": "INCOMPLETE",
  "verdict": "INCOMPLETE",
  "run_count": 0,
  "reason": "five isolated run receipts required, got 0"
}
```

## Input Provenance (Verified)

| Input | SHA256 | Status |
|-------|--------|--------|
| OSM (ingolstadt_authoritative.osm) | `b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f` | ✅ Exists, pinned |
| DEM (dem_ing.tif) | `3cfa665dde3782a015502beaf457854db2f639d01008a386c925d171e41f4ff8` | ✅ Exists |
| Sensor calib | `054a2d8b706ab8f6e5f7ef63c2e630a7bb7c3d0f3839afa943d2d10476679ce0` | ✅ Exists |
| XODR (map-of-record) | `370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8` | ✅ Verified |

## Recommendations

1. **Fix PROJ/GDAL environment** — Reinstall pyproj with clean proj.db to eliminate DEM bottleneck.
2. **Increase trial timeout** to at least 6 hours (21600 seconds) for Mode B full pipeline.
3. **Implement true Mode A** (OSM→Osm2Odr only) for fast byte-determinism check.
4. **Run 5 trials sequentially** with proper isolation — each needs independent output directory.
5. **Only then** build matrix with `rq1_five_run_matrix.py`.

## Honest Assessment

**RQ1 determinism is UNVERIFIED.** No trial run has completed. The current state is `INCOMPLETE (0/5)` with a known environmental blocker (PROJ/GDAL) that must be fixed before any trial can complete in reasonable time.

No determinism conclusion can be drawn from zero completed runs.