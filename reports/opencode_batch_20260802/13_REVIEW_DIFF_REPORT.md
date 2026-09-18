# P13 REVIEW-DIFF-001 — Diff and Preservation Review

Date: 2026-08-02
Scope: full diff from audited commit `dac6930a7de1698c4b2a1fe4cfb6deb7f2679fe2`
to HEAD `841f861e` (Phase A + P02–P12).

## Diff summary
- 59 files changed, 16 680 insertions, **0 deletions**
- All changes are additions (new modules/tests/reports) or modifications of
  intended targets only:
  - `opendrive_geometry/primitives.py`, `opendrive_geometry/__init__.py` (P05)
  - `submission/infrastructure/ultimate_pipeline/DEPRECATION_POLICY.md` (P03)
  - `ultimate_pipeline/pipeline_stages/stage_09_tiling.py` (P09 release gate)

## Preservation checks
- **No tracked file deleted** in the entire diff.
- **Authoritative artifacts untouched**: re-hashed on disk —
  - OSM: `b9e074656f…` (matches recorded)
  - pinned XODR: `ff2a05e7b0…` (matches recorded)
  - both are untracked and absent from the diff
- **Pre-existing dirty files never touched by our commits**: the three
  modified tracked files (`submission/.../stage_08_final_integrity.py`,
  `submission/.../stage_08_integrity.py`, `ultimate_pipeline/run_full_domain_gap.py`)
  appear in `git diff dac6930a HEAD --name-only` **zero times**; their working-tree
  modifications predate this batch and are preserved as-is.
- **Restored modules match their claimed origins** (LF-normalized byte equality):
  - `ultimate_pipeline/artifacts/map_event_record.py` = `fabcc277`
  - `ultimate_pipeline/perception/calibration.py` = `ab9edb2a`
  - `ultimate_pipeline/roadrunner/installation.py` = `8329d50c`
  - `ultimate_pipeline/diagnostics/audit_xodr_visual_geometry.py` = `f631b11f`

## Verdict
**PASS** — no unintended deletions, no authoritative artifact drift,
no collateral changes.
