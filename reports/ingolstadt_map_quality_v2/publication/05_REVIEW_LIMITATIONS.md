# Review Limitations

This document records the limitations and scope boundaries of the Ingolstadt map quality v2 publication.

## 1. Scope of Publication

This publication covers evidence for **WP0–WP2C** only:

- **WP0**: Baseline validation and campaign authority (published)
- **WP1A**: Coordinate inventory and Phase 1A diagnosis (published)
- **WP1B**: Coordinate correction / actual reprojection (published, verified)
- **WP1C**: Independent coordinate verification (published — coordinate_tests.json)
- **WP2A**: Connectivity diagnostics (published)
- **WP2B**: Connectivity repair attempt — V1 **rejected**; V2 **not published** (see below)
- **WP2C**: Independent topology verification (published — rejection evidence)

## 2. WP2B V1 Rejection

The V1 connectivity repair candidate was rejected by WP2C independent verification. The candidate XODR binary is **not** committed to the repository as a promoted artifact. It is:

- Referenced by hash (`c3dc29d3...`) in `rejected_attempt_v1/HASH_REGISTRY.json`
- Explicitly marked `promotion_allowed: false` in `rejected_attempt_v1/promotion_block.json`
- Stored on disk in the external campaign workspace for independent inspection

The rejected candidate must **not** be used as input to WP3 or any later stage.

## 3. WP2B V2 Not Published

A V2 repair attempt exists in the external workspace (`work_package_02_connectivity/v2/`). This work is **not** published in this campaign. It represents future, unverified work and is explicitly excluded from this publication to avoid implying any verification or acceptance status.

## 4. WP3 Elevation — Not Started

- WP3 elevation correction has **not** been started.
- Elevation data is not present in the baseline OSM source.
- Any future WP3 work must use the `candidate_actual_reprojection.xodr` as input, **not** the rejected V1 candidate.

## 5. WP4 Grounded Semantics — Not Started

- WP4 semantic enrichment has **not** been started.
- No semantic object classification or signal placement has been performed.

## 6. WP5 Tile Extent Reconciliation — Not Started

- WP5 tile reconciliation has **not** been started.

## 7. P04 Regression Rerun — Not Started

- The P04 regression gate has **not** been rerun against the corrected candidate.
- Locked P04/P05 evaluations remain blocked.

## 8. Unreal/CARLA Runtime Validation — Not Performed

- No runtime validation in Unreal Engine or CARLA simulator has been performed for this campaign.
- The XODR candidates are publish-only and have not been loaded into any simulator.

## 9. External Artifact Dependencies

Some critical artifacts are stored externally and referenced by hash only:

| Logical Name | External Path | Hash |
|-------------|--------------|------|
| BASELINE_CANDIDATE_PINNED.xodr | `carla_full_replay/.../raw_replay_epsg32632_header_pinned.xodr` | `c8419f8c...` |
| HISTORICAL_RUN11_ARTIFACT.xodr | `carla_full_replay/.../auto_aligned_rigid.xodr` | `c765c4da...` |
| MANUAL_GRID0828.xodr | `carla_-main_submission_ready/...` | `a42ddfea...` |
| MANUAL_GRID0821.xodr | `carla_main_governed/...` | `69ee3498...` |

These artifacts are not committed to the repository. Reviewers must have access to the external workspace to validate them.

## 10. Test Suite Limitations

The full repository test suite (`pytest -q`) may be expensive. The following tests are directly relevant:

- `tests/unit/test_geometric_continuity_migration.py` — geometry continuity
- `ultimate_pipeline/tests/unit/test_topology_validation.py` — topology validation

## 11. Hash Collision Disclaimer

All hashes are SHA-256. The semantic hash algorithm excludes the OpenDRIVE header element and normalizes text representation. See `13_HASH_REGISTRY.json` for algorithm specification.

## 12. Working Tree State

At the time of final commit, the working tree may contain additional untracked files (e.g., `.idea/`, `external/`, `audit_output/`). These are not part of this campaign and are explicitly excluded from publication.
