# Independent Review Request — RQ3->RQ5 Handoff Repair

- Worktree: `E:\wt\repair-map-realism-p0-837a8504`
- HEAD: `363a1868455cab0c33ce9584d6f4b09d594f74e3`
- Branch: `repair/map-realism-p0-837a8504` (8 commits ahead of remote)
- Author: single engineer (only writer); **INDEPENDENT_REVIEW_NOT_RUN**
- Date: 2026-10-21

## Repaired P0 defects (exact)

1. **Manifest-builder false PASS** (`ultimate_pipeline/perception/experiment_map_pair_authority.py`).
   Root cause: the builder validated only the map pair and then emitted `manual_arm`/`auto_arm`
   containing map identity only — no `REQUIRED_ARM_IDENTITY_KEYS` — while promoting
   `pair_valid=True` / `PAIRED_INGOLSTADT_CAPTURE`. Remediation: `MAP_PAIR_ELIGIBLE`,
   capture-arm completion, strict comparability and the final paired claim are now separate
   stages; the candidate is validated by the existing strict contract and the claim is promoted
   only after every predicate succeeds. `invalid_reasons` are preserved; the claim is downgraded
   when invalid; `route_manifest_path` is bound to the supplied verified artifact.

2. **Cross-arm pairing** (`tests/unit/test_task1_2_cross_arm_sync.py`): 23/23 PASS.
   The two previous failures were fixture-only (`sha` vs the schema's `sha256`); the frozen
   schema was not relaxed. Pairing uses the frozen `pair_frame_index`, never raw CARLA frame id.

3. **Failure-reason preservation** (`ultimate_pipeline/perception/rq3_capture_contract.py`):
   manifest-level reasons now propagate into `validate_pair_manifest` output and the claim is
   downgraded to `UNPAIRED_CAPTURE` whenever full validity is false.

4. **Canonical capture integration** (`ultimate_pipeline/perception/record_route_fixed.py`):
   new `run_strict_rq3_capture` / `run_strict_capture_entrypoint` (`--strict-rq3`) invoke
   `capture_transaction`, `rq3_frame_set` and `rq3_rq5_handoff_adapter` from the real runner and
   fail the process on any invariant violation.

5. **Terminal adversarial controls**: 10/10 offline injections block authoritative completion.

6. **Regression**: 99 executed / 99 PASS / 0 FAIL / 0 SKIP, all exit codes 0.

## Outstanding blockers (must remain open)

- `RQ3_PAIRED_DATASET_NOT_ADMITTED` — no paired Ingolstadt runtime capture exists.
- `INDEPENDENT_REVIEW_NOT_RUN` — single engineer only; reviewer must confirm before admission.
- `CARLA_SERVER_STARTUP_PASS` — blocked by shader-fatal boot, ALargeMapManager AV and the
  20 GiB storage gate. Python 3.12 isolation is verified (`import carla` PASS), server is not.
- `CONTINUOUS_DRIVING` vs `POSE_REPLAY` policy — remains explicitly escalated to scientific
  authority; no default mode was invented.
- Full-map Ingolstadt regeneration not authorized (storage gate unmet); no map regeneration run.

## Evidence preserved

- `reports/CARLA_RUNTIME_QUALIFICATION_c69b60d2_20261021/` and
  `E:\CARLA_RUNTIME_QUALIFICATION_c69b60d2_20261021\` — untouched.
- `HOST_CORRECTED_INVENTORY.json`, `PYTHON312_CARLA_ENVIRONMENT.json` — untouched.
- Frozen thesis material — untouched.

## Reproducible commands

```bash
py -m pytest ultimate_pipeline/tests/unit/test_task1_2_cross_arm_sync.py -v --tb=line          # 23 passed
py -m pytest ultimate_pipeline/tests/unit/test_experiment_manifest_negative_controls.py -q    # 8 passed
py -m pytest ultimate_pipeline/tests/unit/test_rq3_frame_set.py -q                             # 23 passed
py -m pytest ultimate_pipeline/tests/unit/test_capture_transaction_rollback.py -q             # 19 passed
py -m pytest ultimate_pipeline/tests/unit/test_rq3_builder_false_pass_regression.py -v        # 12 passed
py -m pytest ultimate_pipeline/tests/unit/test_canonical_runner_integration.py -q             # 3 passed
py -m pytest ultimate_pipeline/tests/unit/test_strict_runner_integration.py -q                # 1 passed
py -m pytest ultimate_pipeline/tests/unit/test_rq3_terminal_adversarial_tests.py -v          # 10 passed
py -c "import carla; print(carla.__version__)"                                              # client PASS
```

## Verdict requested (do not self-issue)

- `RQ3_HANDOFF_READY_FOR_INDEPENDENT_REVIEW`
- `RQ3_HANDOFF_PARTIAL_EXACT_BLOCKERS` (current state; this report supports PARTIAL)
- `RQ3_HANDOFF_FAILED_VERIFICATION`

Do **not** issue `RQ3_HANDOFF_SOFTWARE_VERIFIED`, do **not** admit the paired dataset, and do
**not** describe the RQ3 handoff as "Phase 6 complete".
