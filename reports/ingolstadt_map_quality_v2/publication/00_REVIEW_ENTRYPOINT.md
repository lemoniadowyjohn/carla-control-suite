# Ingolstadt Map Quality v2 — Publication Review Entrypoint

## Repository Information

| Field | Value |
|-------|-------|
| Repository | `lemoniadowyjohn/carla-control-suite` |
| Branch | `improvement/ingolstadt-map-quality-v2-202608` |
| Base commit (baseline) | `877e9aef41f733a3ecf980a4559ec6bd359037bf` |
| Final commit | `bfde949445be808f2c6c791e5754f85f38d462f8` |
| Tag | `offline-domain-gap-v2-certified` |
| Base branch (PR) | `integration/governed-map-quality-20260729` |

## Campaign Objective

Verify coordinate-frame corrections for the Ingolstadt map candidate and evaluate connectivity repair. Coordinate correction is verified. Connectivity repair V1 is rejected.

## Verified Accomplishments

- **WP0**: Baseline metrics reconciled; metric lock references and threshold lock references published.
- **WP1A**: Coordinate inventory complete; coordinate-frame discrepancy diagnosed (tmerc origin offset).
- **WP1B/1C**: Actual reprojection verified; round-trip and inverse consistency passed (max error 0.0 m, 100 samples).
- **WP2A**: Connectivity diagnostics published (dangling references, reciprocity analysis, junction-reference analysis).
- **WP2C**: Independent verification completed; verdict = `CONNECTIVITY_REPAIR_REJECTED`.

## Failed / Rejected Work

- **WP2B V1 connectivity repair**: Rejected.
  - 6,132 of 7,144 successor repairs independently rejected (distance > 15 m or heading diff > 15°).
  - 0 of 4,596 predecessor repairs accepted (algorithm defect).
  - 10,098 directionally wrong reciprocals introduced.
  - 656 missing junction references remain.
  - Zero predecessor repairs accepted.

## Accepted Artifacts

| Artifact | SHA-256 | Location |
|----------|---------|----------|
| `candidate_actual_reprojection.xodr` | `3d55a86e...` | `work_package_01_coordinate_truth/candidates/` |
| `candidate_connectivity_repaired.xodr` | `c3dc29d3...` | `work_package_02_connectivity/` |
| `BASELINE_CANDIDATE.json` | (see hash registry) | `baseline_record/` |
| WP1 candidate XODRs (3 variants) | (see hash registry) | `work_package_01_coordinate_truth/candidates/` |

## Rejected Artifacts

| Artifact | SHA-256 | Location |
|----------|---------|----------|
| `candidate_connectivity_repaired.xodr` (V1) | `c3dc29d3...` | `work_package_02_connectivity/rejected_attempt_v1/` |

The rejected candidate is **not** committed as an XODR binary in the repository. It is referenced by hash in `rejected_attempt_v1/HASH_REGISTRY.json` and `rejected_attempt_v1/promotion_block.json` (or `PROMOTION_BLOCKED.json`). The rejected candidate must not be used as input to later stages.

## Current Blockers

- **WP3 elevation**: Not started — blocked pending corrected connectivity repair V2.
- **WP4 grounded semantics**: Not started.
- **WP5 tile extent reconciliation**: Not started.
- **P04 regression rerun**: Not started.
- **P05 domain-gap rerun**: Not started.
- **Unreal/CARLA runtime validation**: Not started.

## Directory Map

```
reports/ingolstadt_map_quality_v2/
  CAMPAIGN_POINTER.json              # Campaign authority & work package list
  BASELINE_CANDIDATE.json            # Baseline candidate metadata
  BASELINE_FIELD_DEFINITIONS.json    # Field definitions for baseline
  BASELINE_VALIDATION.md             # Baseline validation report
  METRIC_LOCK_REFERENCE.json         # Locked metric definitions
  THRESHOLD_LOCK_REFERENCE.json      # Locked thresholds
  EXTERNAL_ARTIFACT_MANIFEST.json    # External artifact hash-bound manifest
  MASTER_PROMPT.md                   # Campaign master prompt
  coordinate_inventory.json          # WP1 coordinate inventory (legacy copy)
  connectivity_diagnostics.json      # WP2A diagnostics (legacy copy)
  baseline_record/
    BASELINE_CANDIDATE.json          # Baseline candidate record
  work_package_01_coordinate_truth/    # WP1 evidence
    coordinate_inventory.json
    PHASE_1A_DIAGNOSIS.md
    candidates/
      candidate_actual_reprojection.xodr        # VERIFIED
      candidate_alignment_transform_only.xodr
      candidate_correct_georeference.xodr
      candidate_metadata_only.xodr
      coordinate_tests.json
  work_package_02_connectivity/        # WP2A/WP2B/WP2C evidence
    candidate_connectivity_repaired.xodr         # Verdict candidate (LFS)
    compute_semantic_hash.py
    repaired_validation.py
    repair_report.json
    validation_report.json
    wp2c_verify.py
    connectivity_diagnostics.json
    verification/        # WP2C independent verification package
      00_WP2C_EXECUTIVE_STATUS.md
      01_METRIC_DEFINITIONS.json
      02_BASELINE_RECOMPUTATION.json
      03_REPAIR_VALIDATION.csv
      04_REJECTED_REPAIRS.csv
      05_PREDECESSOR_FAILURE_CLASSIFICATION.csv
      06_RECIPROCITY_MATRIX_RESULTS.json
      07_JUNCTION_CONNECTION_REPORT.json
      08_LANELINK_REPORT.json
      09_COMPONENT_ANALYSIS.csv
      10_ROUTE_FIXTURE_RESULTS.json
      11_CONTENT_PRESERVATION.json
      12_MUTATION_DIFF.jsonl
      13_HASH_REGISTRY.json
      14_REMAINING_DEFECTS.csv
      15_WP2C_VERDICT.md
      COMMAND_TRANSCRIPT.txt
      EVIDENCE_MANIFEST.json
    rejected_attempt_v1/   # REJECTED V1 attempt (not promoted)
      candidate_connectivity_repaired.xodr  # NOT committed (hash-referenced)
      connectivity_diagnostics.json
      REJECTION_RECORD.json
      REPAIR_SUMMARY.md
      REPAIR_CONFIGURATION.json
      HASH_REGISTRY.json
      repair_report.json
      repaired_validation.py
      promotion_block.json     # Explicit promotion block marker
      PROMOTION_BLOCKED.json
      verification/
        (WP2C verification package for V1)
  publication/
    00_REVIEW_ENTRYPOINT.md
    01_PUBLICATION_INVENTORY.csv
    02_CHANGED_FILE_INDEX.csv
    03_ARTIFACT_HASH_REGISTRY.json
    04_REPRODUCTION_COMMANDS.md
    05_REVIEW_LIMITATIONS.md
    06_GITHUB_PUBLICATION_REPORT.md
    07_GITHUB_PUBLICATION_REPORT.json
```

## Recommended Review Order

1. `publication/00_REVIEW_ENTRYPOINT.md` (this file)
2. Campaign authority: `CAMPAIGN_POINTER.json`, `BASELINE_CANDIDATE.json`, `METRIC_LOCK_REFERENCE.json`, `THRESHOLD_LOCK_REFERENCE.json`
3. WP1 coordinate evidence: `work_package_01_coordinate_truth/PHASE_1A_DIAGNOSIS.md`, `coordinate_tests.json`
4. WP2A diagnostics: `work_package_02_connectivity/connectivity_diagnostics.json`
5. Rejected WP2B attempt: `work_package_02_connectivity/rejected_attempt_v1/REJECTION_RECORD.json`, `REPAIR_SUMMARY.md`, `promotion_block.json`
6. WP2C verification: `work_package_02_connectivity/verification/00_WP2C_EXECUTIVE_STATUS.md`, `15_WP2C_VERDICT.md`
7. Publication summaries: `02_CHANGED_FILE_INDEX.csv`, `03_ARTIFACT_HASH_REGISTRY.json`, `04_REPRODUCTION_COMMANDS.md`, `05_REVIEW_LIMITATIONS.md`

## Commands to Reproduce Checks

```powershell
# Verify coordinate reprojection round-trip
cd <repo-root>
git checkout 877e9aef -- .
git checkout improvement/ingolstadt-map-quality-v2-202608

# Run WP1 coordinate tests (if test file exists)
python -m pytest tests/ -k coordinate -v

# Verify XODR hashes
python -c "import hashlib; print(hashlib.sha256(open('reports/ingolstadt_map_quality_v2/work_package_01_coordinate_truth/candidates/candidate_actual_reprojection.xodr','rb').read()).hexdigest())"

# Verify rejected candidate hash matches registry
python -c "import hashlib; print(hashlib.sha256(open('carla_improvement/ingolstadt-map-quality-v2-202608/work_package_02_connectivity/rejected_attempt_v1/candidate_connectivity_repaired.xodr','rb').read()).hexdigest())"

# Verify Git LFS tracking
git lfs ls-files
git check-attr filter -- reports/ingolstadt_map_quality_v2/work_package_02_connectivity/candidate_connectivity_repaired.xodr
```

## Explicit Statements

- Coordinate correction is verified.
- Connectivity repair V1 is rejected.
- WP3 elevation, WP4 semantics, WP5 tiles, and locked P04/P05 have not started and remain blocked.
- The rejected candidate must not be used as the input to later stages.
