# OC-01 Correction (V129 O2)

**Scope:** Corrects false skew claim in OC-01 records. Test-only oracle contribution; no OC-01 duplicate code ported.

## Corrected fact (real calibration)
- Source: `ultimate_pipeline/sensors/calib_data.json` (SHA-256 `d3ff2660b11ca56d16c6185e82d1b4c7fa94c5db27bb3469558442d79f4e97d9`)
- **Real `K_undistortion` skew is `0.0` for all 6 cameras** (back_left, left, front_left, front_right, right, back_right), verified by direct parse of `K_undistortion`.

## OC-01 false claim (retired/corrected)
- OC-01 commit messages/docstrings/tests (e.g. `ab983c55`, `ea2d3ac8`, `fix/oc01-intrinsic-receipt-binding` lineage) asserted non-zero skew for `left` (-0.726012) and `right` (+0.543263).
- Those values originate from the **raw distorted `K`** matrix, not `K_undistortion`. The thesis/contract context requires using `K_undistortion` (ignoring raw distorted `K` for the oracle/realized intrinsics); therefore the OC-01 skew claim was false and must not be relied upon.

## Independent oracle (V129)
- `opencode/v129-intrinsics-oracle-tests` adds `tests/unit/test_v129_intrinsics_oracle.py` asserting per-camera `fx, fy, fy/fx, cx-W/2, cy-H/2, skew=0` (tolerance 1e-3) derived from **`K_undistortion` only** (never raw `K`), against the real `calib_data.json`.
- Oracle values per `G:\CARLA_RECOVERY\handoff\CLAUDE_QA_V128\OPENCODE_PROGRESS_REVIEW.md` (back_left/left/front_left/front_right/right/back_right). Raw `K` skew differs for left/right but is explicitly not used as oracle source.

## Status
- OC-01 duplicate implementation/receipt binding (`ultimate_pipeline/sensors/intrinsic_realization.py`, `calibration_contract.intrinsic_receipt_binding`) **not ported** (retired as written; PR #65 is schema authority). This correction supersedes OC-01 skew assertions for V129 records.