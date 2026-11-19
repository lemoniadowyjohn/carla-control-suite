# Independent OC-D review — REQUEST_CHANGES

## Scope and ancestry

Reviewed exact OC-D SHA `675a0fd2c54c705d57e85772c8d6bee0ec5d156a` in its clean detached worktree. Remote ref verification returned that exact SHA. The stack has 8 commits after production: seven inherited from #52 → #54 → #55 and one new commit. The new commit changes `rq5_provenance.py` and two tests. Its patch ID matches PR #50's diff (`62c805fdf5335226f1e6798d55dad6e5c6bfa1f5`), so #50 is a parallel implementation of the same guard and must not be imported separately with OC-D.

## Independent test results

Environment: Windows, Python 3.12.2, pytest 8.0.1, `PYTHONPATH` cleared, torch 2.2.0+cpu, NumPy 2.5.3, torchvision missing.

Command:

```powershell
$env:PYTHONPATH=''
& 'C:\Users\admin\AppData\Local\Programs\Python\Python312\python.exe' -m pytest -q -p no:cacheprovider -rfEsx tests/unit/test_v111_rq5_v2_split_pretraining_authority.py tests/unit/test_v117_rq5_eval_identity_guard.py tests/unit/test_v121_rq5_reused_checkpoint_claim.py tests/unit/test_v122_rq5_stale_evaluation_report.py
```

Result: **19 passed, 0 failed, 0 skipped**, exit 0. The cases cover v2 missing split/pretraining individually and together, v2 positive-field control, v1 compatibility, diagnostic mode, mismatched evaluator dataset/model identities, checkpoint-reuse non-success, fresh-training positive control, stale report rejection, and unique per-invocation reports.

A separate command for `tests/unit/test_rq5_execution_correctness.py::test_assert_disjoint_splits_flags_identity_overlap` passed **1/1**, exit 0. This confirms the isolated digest-overlap helper test only. The complete `test_rq5_execution_correctness.py` suite was not run in this review; the environment lacks torchvision and emits a torch/NumPy ABI warning. No training was executed.

## Confirmed findings

### OCD-R1 — stale or malformed v2 receipts are admitted (P1)

At `ultimate_pipeline/perception/rq5_provenance.py:681-685`, governed v2 verification only checks that `split_manifest_sha256` is truthy and `pretraining_contract` is truthy. It does not resolve/hash the split path or validate the pretraining schema/content.

Reproduction used a real temporary checkpoint and a v2 mapping with an all-zero split hash, a path to a nonexistent split file, and `pretraining_contract="unverified nonempty garbage"`. Calling `verify_checkpoint_manifest(..., require_provenance=True)` returned `ok=True`, with no failures. Expected result: reject.

The v111 positive test uses the same weak condition: a made-up nonempty hash and `{"initialization":"verified"}` pass. It is a field-presence control, not proof of valid receipt admission.

### OCD-R2 — producer emits an unbound v2 split (P1)

At `ultimate_pipeline/perception/train_launcher.py:715-734`, the standard manifest builder is called with `split_manifest_sha256=None`. That produces a v2 manifest whose required split binding is absent. The new verifier rejects it whenever governed verification is enabled.

### OCD-R3 — fresh-run governed verification is opt-in (P1)

`run_generalization_experiments.py:780` declares `--require_manifest` as `store_true` (default false); at lines 955-958, a fresh training run passes `require_manifest=False` unless the caller explicitly supplies the flag. Reused checkpoints force verification, but a newly trained run can bypass the v2 provenance checks.

## Disposition

**REQUEST_CHANGES.** Do not ingest OC-D into V132 yet. The 19 tests pass but do not test stale/mismatched split receipt rejection and their positive v2 case accepts placeholder fields. OC-A remains integrated in the V132 candidate at commit `49d037696a21cba1ca5763d4dd25de86cc47c4b4`; OC-D is not an ancestor of candidate head `764f0e697b5a8ebd915d8fcc2cb1266bf770df05`.

Candidate and OC-D both descend from production; their merge base is production. Their changed path sets have no filename overlap (60 candidate paths including the V132 reports, 7 OC-D paths from production), but no merge was attempted because OC-D's contract defects are semantic blockers. Exact-head GitHub CI was not verified. No runtime or scientific result is claimed.

## Current GitHub status refresh

Read-only GitHub API queries for the exact OC-A and OC-D SHAs returned zero check runs and zero commit status contexts (the aggregate status field was `pending` because there were no contexts). Pull request lookup for both exact branch heads returned zero PRs. No green CI is claimed.
