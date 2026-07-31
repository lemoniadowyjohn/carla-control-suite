# DSV02 — OSM→XODR Generator & Structural-Validation Donor Discovery

**Model:** DeepSeek V4 Light · **Mode:** READ-ONLY · **Parent:** `ingolstadt_cooked_perception_v1`
**Base SHA:** `7053bab56de4ba1680c4fb73bf85a5dc9b911694`

## Worktrees Scanned (12)
Same 12 worktrees as DSV01. Key donors: `carla_main_governed`, `carla_main_governed/work/codex-full-pipeline-rerun-20260427`, `carla_main_governed_worktrees/codex-jsnap-20260428`, `carla_rr_recovery`.

## Converter Implementations

### Primary: `osm_to_xodr_wrapper.py`
| Variant | SHA256 | Worktrees |
|---------|--------|-----------|
| carla_-main submission | `37DB812C3C86...` | carla_-main, carla_main_audit, carla_rr_recovery |
| carla_main_governed root | `436CB7945026...` | carla_main_governed (untracked) |
| codex-full-pipeline-rerun | `2678373C3AC9...` | work/codex-full-pipeline-rerun, submission_ready packs |

All variants use `carla.Osm2Odr.convert()` as primary method with external tool fallback.

### Direct: `osm_to_xodr.py`
- `D64C80A601A1...` in carla_-main (submission/)
- `472BEFD59B84...` in codex-full-pipeline-rerun + submission_ready

### CLI entry points
- `ultimate_pipeline/cli.py` — present in all worktrees
- `submission/infrastructure/ultimate_pipeline/cli.py` — present in carla_-main, carla_main_audit, carla_rr_recovery

### Junction Connector Snap (unique to codex-jsnap)
- `ultimate_pipeline/tools/junction_connector_snap.py` — `D668FA593BF2...`
- Produces `08_final_rerun3_BEST_jsnap.xodr` (19,149,977 B, 5,539 roads, 677 junctions)

## Key XODR Artifacts

| Artifact | SHA256 | Size | Roads | Junctions | Worktree | Status |
|----------|--------|------|-------|-----------|----------|--------|
| `auto_aligned_rigid.xodr` (run_11) | `C765C4DAF84E...` | 13,845,703 | 5,837 | 779 | carla_-main, audit, rr_recovery, submission_ready | untracked |
| `auto_aligned_rigid.xodr` (codex rerun) | `03AA18418318...` | 13,625,961 | — | — | codex-full-pipeline-rerun | untracked |
| `08_final_structural_gap.xodr` (contract_run) | `2C120DC7CA73...` | 16,031,746 | 5,712 | 680 | carla_main_governed | untracked |
| `08_final_structural_gap.xodr` (submission_ready) | `BEB329A53255...` | same | 5,837 | 779 | submission_ready packs | untracked |
| `08_final_rerun3_BEST_jsnap.xodr` | (not computed) | 19,149,977 | 5,539 | 677 | codex-jsnap | tracked (modified) |
| `_normalized_input.xodr` (scenario B) | (multiple) | ~14.3 MB | 5,780 | 748 | carla_main_governed + submission_ready | untracked |
| `auto_aligned.xodr` (run_04) | `898EBD639464...` | — | 5,712 | 680 | codex-full-pipeline-rerun | untracked |

## Protected Artifact Verification

| Artifact | Location | Exists | SHA256 |
|----------|----------|--------|--------|
| `thesis_results/structural_gap_v1/run_11/` | carla_main_governed | ✅ (4 files, no XODR) | — |
| `artifacts/final_runs/scenario_b_audit/contract_run/` | carla_main_governed | ✅ (4 XODR files) | `2C120DC7...` |
| `08_final_structural_gap.xodr` | carla_main_governed + submission_ready | ✅ (2 distinct variants) | See above |
| `submission/results/structural_gap_run11/auto_aligned_rigid.xodr` | carla_-main | ✅ | `C765C4DAF84E...` |

## geoReference Analysis

| Strategy | geoReference | Offset | Used By |
|----------|-------------|--------|---------|
| UTM zone 32N | `+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 +datum=WGS84 +units=m` | `x="677577.43" y="5401899.77"` | contract_run, jsnap, normalized_input |
| Negative offset UTM | Same as above | `x="-838640.80" y="-5464783.89"` | auto_aligned_rigid, submission_ready `08_final` |
| Localized CRS | `+proj=tmerc +lat_0=48.749... +lon_0=11.422... +k=1 +x_0=0 +y_0=0` | `x="-838640.80" y="-5464783.89"` | submission_ready `08_final_structural_gap.xodr` only |

## Run Manifests Found
- `carla_main_governed/thesis_results/structural_gap_v1/`: runs 11–18, test_crs_warn_v2
- `codex-full-pipeline-rerun/thesis_results/structural_gap_v1/`: runs 01–04
- `carla_main_governed/ultimate_pipeline_out/`: rerun2, rerun3, audit_run_000, audit_run_001
- `carla_main_governed/_tmp_verify_manual_828/`: manual baseline + env manifests

## Best-Donor Identification

| Subsystem | Donor Worktree | SHA | Evidence |
|-----------|---------------|-----|----------|
| OSM validation | carla_main_governed | deb261bf | osm_to_xodr_wrapper.py with input validation |
| OSM→XODR conversion | codex-full-pipeline-rerun | 6b250621 | Full pipeline rerun with 4 run manifests |
| Canonical geometry | carla_-main (this branch) | 7053bab5 | 0c1a4293 committed canonical geometry authority |
| Topology validation | carla_main_governed | deb261bf | Multiple run manifests with structural summaries |
| Lane validation | codex-full-pipeline-rerun | 6b250621 | Run_04 auto_aligned.xodr with lane analysis |
| Elevation validation | carla_main_governed | deb261bf | Elevation impartation with geoReference handling |
| Artifact transactions | carla_-main (this branch) | 7053bab5 | ultimate_pipeline/artifacts/ committed |
| Junction connector snap | codex-jsnap | 2b1a3d11 | Unique junction_connector_snap.py tool |
| CARLA standalone loading | NONE | NONE | No CARLA runtime infrastructure found in any worktree |

## Verdict

```
XODR_DONORS_MAPPED
```

Two distinct XODR lineages exist: (1) `auto_aligned_rigid.xodr` family (5,837 roads, negative offset) used in run_11/submission_ready, and (2) `08_final_structural_gap.xodr` family (5,712 roads, UTM offset) from contract_run. The codex-jsnap branch offers the most recent junction-repaired variant (5,539 roads). No single authoritative base XODR can be declared without architecture-gate resolution. CARLA standalone loading cannot be verified — no CARLA runtime infrastructure exists in any worktree.
