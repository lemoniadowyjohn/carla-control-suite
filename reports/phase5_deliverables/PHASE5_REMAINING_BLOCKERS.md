# PHASE 5 REMAINING BLOCKERS

## Status: OFFLINE IMPLEMENTATION COMPLETE — RUNTIME/RESOURCE BLOCKED

## Verified Fixes (COMMITTED)

| Fix | File | Line | Status |
|-----|------|------|--------|
| Stage-02 crash guard | `ultimate_pipeline/visualization/map_plotter.py` | 121-133 | ✅ 7/7 tests pass |
| `self.verbose` AttributeError | `ultimate_pipeline/perception/dataset_generator.py` | 197 | ✅ Added to `__init__` |
| `apply(img, seed)` no-op | `ultimate_pipeline/augmentation/realism_augmentor.py` | 291 | ✅ Delegates to `apply_random` |
| RQ3 protocol freeze | `configs/rq3_protocol_freeze_v1.json` | 1 | ✅ 25 decisions frozen |

## Remaining Blockers

### 1. STORAGE ADMISSION GATE (EXTERNAL — CRITICAL)
- **Requirement**: ≥20 GiB free on one drive
- **Current**: C: 6.13, E: 4.16, F: 2.22, G: 5.10, H: 15.70 GiB
- **Action**: Add ≥20 GiB to E: or G: (or gate revision authorization)

### 2. INDEPENDENT REVIEW-A (PENDING)
- Requires complete candidate and all static gates PASS
- Cannot self-certify

### 3. FULL PIPELINE REGENERATION (BLOCKED)
- Requires storage gate and stage-02 fix completion
- Produces `08_final_*.xodr` with embedded geoReference and sign objects

### 4. REGULATORY-SIGN FIXTURE MEASUREMENTS (PENDING)
- Requires controlled OSM/XODR fixtures
- Verify actual emission count from 529 OSM traffic_sign tags

### 5. RQ1 FIVE-RUN DETERMINISM EVIDENCE (BLOCKED)
- Requires fresh isolated runs with current source
- Current source is stale

### 6. STAGE-02 TOPOLOGY CRASH (PENDING)
- Root cause not fully resolved
- Requires degenerate-geometry guard and negative-control test

## Classification Summary

| Classification | Count |
|---------------|-------|
| OFFLINE_READY / COMPLETED | 4 |
| DATA_BLOCKED | 4 |
| RESOURCE_BLOCKED | 1 |
| PENDING | 2 |