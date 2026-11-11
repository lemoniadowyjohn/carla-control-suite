# Integration record: `integration/convergence-20261111`

- **Base:** `integration/codex-v24-convergence-20261106` @ `8fcd8c796bf94e2fff0b4ae4d07ccd0fbabbd2a4`
- **Target:** `integration/production-large-map-20260918`, via PR only.
- **Integrator:** Claude (single writer). **Independent reviewer:** Claude reviewer agent (Sonnet family). Verdict: APPROVE, with the one condition addressed in the stale-evidence section below.

## Source-base decision (evidence)

- `tree(d72f57c6) == tree(5a004113) == 1b1f3d0c7926`. The production tip, `d72f57c6`, is a merge commit that adds no content beyond `5a004113`.
- `5a004113` and `1a36b560` (post-pr16) are both ancestors of `8fcd8c79`.

So `8fcd8c79` contains everything that production has. This PR adds nothing to the production side.

## Integrated (24 commits, all `cherry-pick -x`)

| Group | Source | Count |
|---|---|---|
| Research evidence stack | `a9d40c9d acb54176 ae9a6d86 bd76e032 cec071d3 9be0a09e 4f3055bb 361958ca` | 8 |
| Approved candidate (`integration/candidate-approved-20261105b`) | `0b7b0c90 cf8bad82 ab19965b 5de0fcdf bf82d51f 789b5a7a 0843ea64 a0cffdf1 519f213e b81a645f 11089adf 9228d258 d8fc8263 a0634fa4` | 14 |
| Stage-6 diagnostic volume (W-F, Stage-6-scoped) | `b3e2c5a8 48d86d76` | 2 |

## Not integrated (branches and refs retained; nothing deleted)

| Item | Disposition | Reason |
|---|---|---|
| p0-tc-001 `3ac065c4`, `209ec148` | DEFER (design reconciliation) | Semantic conflict with the base's lease-held terminal publication (`main_pipeline.py` `_write_run_status` / `run()` lease, `finalize_run_pack.py`). The two designs compete for the same mechanism, and an owner must choose between them. |
| W-B `d852b333..f07efe97` (9) | DEFER | The prior review verdict was REQUIRES_CHANGES (adjudicate_rq1 admits mixed source_sha / input map / bad timestamps). |
| W-D `fix/rq2-lane-metric-v2-20261105` (2) | DEFER | It must follow W-B, and it changes the ConnectivityGap payload embedded in RQ2 authority. |
| F1 `43ab4f99` | DEFER (defect) | Confirmed bug: renew vacates the lease path, so a concurrent acquire publishes and `_write_payload`'s `os.replace` overwrites the successor. The restore paths have the same problem. |
| GUI `757f86da..3d7665fc` (13) | EXCLUDED | Out of scope per the V24.1 architecture review. |
| gap055 `8015df6a`, `c736a9ce` | ALREADY_EQUIVALENT | Present in the base as `19cdb3a2`, `3c9048be`, `fefe1687`. |
| October branches: `merge/picks-20261015`, `fix/p0-coord-frame-tile-placement-authority-20261001`, `opencode/p1-runtime-capture-20261001`, `b15-rq1b`, `rq1a-execution`, `rq2-authority-validate-20261008` | DEFER (triage) | Not reviewed for this base. They remain archived at `archive/wt-20261111/*`. |

## Stale-evidence notice (reviewer condition)

Commit `2cdfc78f` (source `361958ca`) carries `RQ2_EVIDENCE_RECEIPT.json` with `experiment_receipt.git_sha = 4f3055bbb3f1b9a8e3008d6c71ac3a43f7a92cd0` and `claim_status = BOUNDED`.

- `4f3055bb` is **not an ancestor** of this branch.
- Seventeen later commits (the O13 geometry fixes, the rq3/rq4/rq5 fail-closed changes, the gap070 policy change, and Stage 6) were never replayed against that receipt.

**This receipt is HISTORICAL for this tip. It must not be cited as current RQ2 status.** A fresh RQ2 replay on this branch's HEAD is required before any current RQ2 claim. The receipt bytes are left unmodified, because historical artifacts are immutable.

## Verification

Both full suites were run locally: a bare `pytest` (pytest.ini testpaths), Python 3.12.2, with `--continue-on-collection-errors`.

| Tree | Passed | Failed | Skipped | Collection errors |
|---|---|---|---|---|
| base `8fcd8c79` | 8051 | 62 | 22 | 16 |
| this branch (`6611ec39` + this doc) | 8223 | 45 | 22 | 16 |

How the failures were classified:

- **16 collection errors, identical on both trees: ENVIRONMENT.** `torchvision`, `torch_geometric` and `cryptography` are not installed for the local interpreter. `requirements.txt` pins them, and CI installs them.
- **8 failures only on this branch.** I re-ran them in isolation and sequentially:
  - 7 are in `tests/unit/test_rq5_train_launcher_failsafe.py`, which is new in `fa231de8`/`f559ea35`. They fail at `import torch` because the local NumPy is 2.5.3 against the pinned `numpy==2.2.6`, so torch 2.2.0 cannot initialise. This is ENVIRONMENT: the base cannot import `train_launcher` either.
  - `test_receipt_reconciler::test_lease_job_coupling` passes in isolation. It failed only because I ran both suites concurrently and they interfered.
- **The 25 single-writer failures present only at the base** came from the same concurrent-run interference. In isolation, both trees fail exactly the same 2 tests: `test_receipt_reconciler::test_case08_supervisor_death_handshake` and `test_single_writer_control_plane::test_job_owned_tree_kill`. Those are pre-existing.

**Conclusion: no code regressions were attributable to the 24 integrated commits.** The torch-dependent tests must be confirmed by CI, which uses the pinned requirements. Local results do not count as PASS for them.
