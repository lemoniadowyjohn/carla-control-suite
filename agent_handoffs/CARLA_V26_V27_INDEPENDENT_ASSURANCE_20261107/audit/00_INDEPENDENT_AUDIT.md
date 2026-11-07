# Independent audit — V26-A / V26-B / IA-V27

## Source boundary and confidence
Read on 2026-11-07 via the connected GitHub repository `lemoniadowyjohn/carla-control-suite` at PR head `dfa6ffff07c38d0cc09507c52b3328900ef2d900`. Local `G:/`, `C:/`, `E:/`, `F:/` files are **not available in this environment**. Exact local pass counts, source divergence, receipt SHA256 sums and worktree lease states **cannot be certified** from this review. V26-A/B are user-reported, not GitHub-published review evidence on the inspected PR head.

### Checked PR and CI
- PR #25: draft, open, unmerged; base `integration/post-pr16-final-20261102`; 67 changed files; no submitted PR review returned.
- PR body incorrectly calls `a952f377a36eba9840cdbd7549401cac7d314c97` HEAD. Actual PR HEAD: `dfa6ffff07c38d0cc09507c52b3328900ef2d900`. V22 handoff files also contain past provenance, which needs historical/current labels.
- GitHub Actions exact-SHA push run `https://github.com/lemoniadowyjohn/carla-control-suite/actions/runs/42292278556`: completed **failure**; 7 jobs, 5 success, 1 failed (`offline tests`), 1 skipped (`offline release gate`). The `fetch_commit_workflow_runs` PR-event-only convenience API returned no workflows; raw Actions/check-runs records DID show this push run. Do not interpret a filtered empty result as no CI.
- Offline pytest: `collected 8016 items / 1 skipped`, final `30 failed, 7911 passed, 73 skipped, 3 xfailed, 293 warnings` in 747.58 s. The terminal outcomes add to 8017 (7911+30+73+3), consistent with the 8016 collected test items plus one collection-time skip. Preserve the original pytest categories rather than relabeling them.

## Evidence-backed findings and adversarial requirements

### CRITICAL RQ1 production receipt entrypoint appears non-executable
Source: `tools/rq1_complete_receipt.py` at `dfa6ffff07c38d0cc09507c52b3328900ef2d900`. Function `_compute_settings_hash()` calls undefined `_hash_dict` before the pipeline invocation and outside the exception handler. The file additionally references names without definitions/imports: `normalized_xodr`, `_sha256`, `_compute_feature_counts`, `_compute_topology_counts`, `_compute_tileset_digest`, `_compute_map_acceptance_digest`, and `git_commit_hash` (defined helper is `_git_commit_hash`). These are source-level unresolved names (verify with a no-CARLA isolated test), not proof of a completed runtime reproduction. The V22 publication report's claim that RQ1 receipt generation was fixed is inconsistent with inspected HEAD. A source-only/isolated unit harness must prove no pre-execution NameError, exact run identity, no placeholder fields, stable hashes and no false-PASS on failures. Codex owns production fixes; OpenCode owns RED reproduction and acceptance tests.

### HIGH RQ3 verifier PASS is narrower than any scientific PASS
Source: `tools/rq3_dataset_manifest_verifier.py` at `dfa6ffff07c38d0cc09507c52b3328900ef2d900`. `_check_capture_files()` only checks whether a provided string/path field is nonempty; it neither requires `capture_files` nor verifies existence/digest/containment. `_check_quality_evaluated()` flags only an explicit dict with `performed=False`; an absent quality record is allowed. With matching paired manifest keys, `verify()` can return `status=PASS` while `quality_comparison=NOT_RUN`; the five existing tests explicitly expect that behavior. Treat this solely as **limited paired-manifest contract PASS**, NEVER perception quality or RQ3 scientifically admitted. Add negative tests for missing/forged files, symlinks, corrupted bytes, empty/misaligned timestamps, absent quality evidence and copied/forged pairing metadata. Preserve legacy contract verdict meaning or make the status namespace explicit; do not silently convert an old status to scientific PASS.

### HIGH CI quality gate regression has contradictory expectation
Test: `ultimate_pipeline/tests/unit/test_quality_gate_manager.py::test_finalize_gate_non_falsey_ok_is_truthy_pass` passes `{"ok":"yes", "status":"pass"}` and expects PASS. Production `QualityGateManager._finalize_gate` relies on `normalize_gate_result`, apparently enforcing stricter semantics. Investigate intended contract and add RED controls for string `"yes"`, `"false"`, `1`, `[]`, `None`; never weaken fail-closed behavior merely to make this one outdated truthiness test green. Also review `from_legacy_bool(value)` in `ultimate_pipeline/contracts/stage_contracts.py`, which uses `bool(value)` and could accept truthy nonbool input if any caller violates type discipline (a potential hazard; actual exploit path unverified).

### HIGH submission mirror drift
`tests/phase_q/test_duplicate_module_drift.py` fails because `ultimate_pipeline/core/carla_opendrive_loader.py` differs from `submission/infrastructure/ultimate_pipeline/core/carla_opendrive_loader.py`. Determine authoritative source and run path, inspect semantic diff, correct through Codex-approved source/mirror workflow. No blind `cp` from unverified copy.

### HIGH concurrency / lease integrity
`tests/unit/test_common_git_lock.py::test_concurrent_acquire_has_exactly_one_winner` observed TWO winners, not one. Production `ultimate_pipeline/governance/single_writer/common_git_lock.py` uses `O_EXCL` initially but stale-lock cleanup can unlink a freshly created/incompletely published lock (TOCTOU), with PID and owner identity weaknesses. Treat as true candidate race until repeated independent repro disproves it. **Never mark as platform-only without evidence.** T2b owns production lease logic; OpenCode tests in own namespace only. For `tests/unit/test_orchestration_hardening.py`, three identity/reconciliation failures require exact per-test repro, not de-scoping.

### Platform-specific CI test mismatch
The repository's `scripts/control_plane.py` explicitly depends on Windows kernel32 named mutexes and sets `_kernel32=None` on non-Windows, while `tests/unit/test_single_writer_arbitration.py` calls `lease.acquire()` without Win32 eligibility gating. 21 failures show `AttributeError: 'NoneType' object has no attribute 'CreateMutexW'`. Two more subprocess/owner assertions are plausibly downstream of unavailable mutex behavior; inspect their full tracebacks. Run the **actual Windows concurrency tests on an authorized Windows runner**; skip only explicitly Windows-native tests on Linux with a recorded platform requirement. A Linux skip is NOT a Windows PASS.

`tests/unit/test_carla_import_supervision.py::TestStorageGate::test_real_volume_measures_free_space` assumes volume `C:` on Linux. Its test setup is platform specific; validate legitimate storage semantics on the respective OS without relaxing fail-closed volume measurements.

### Scientific acceptance and governance
- 17 RQ2 + 16 RQ4 + 19 RQ5 = 52. Mathematical sum is coherent, but a stated count without receipts and content is **unverified**. Synthetic fixtures establish harness logic, not actual map topology, dataset independence or ML performance.
- 'V26-A/B completed' conflicts with 'completing remaining deliverables' and 'IA-V27 active'. Separate file existence, verification of hashes, test execution and scientific acceptance; each gets its own status.
- Candidate b `AUTH_PENDING` means no publication. AUTH-08 cannot be inferred from AUTH-01 through AUTH-10 generally; require exact signed authorization text, scope, expiry, target repo/branch and permitted act.
- W-D **RECONSTRUCTED_ACCEPTANCE_CANDIDATE** is not the original 26-test suite. There is no authority to claim equivalence without recovered selection or owner approval.
- W-B three remaining commits not applied => production RQ5 generalization not complete. No synthetic unit suite can substitute for model weights, held-out evaluation, ablations or reproducibility.
- T2b, F15b, W-F and W-D remain separately owned release blockers. OpenCode must not edit Codex paths or cherry-pick unresolved specialist branches.
- W-F / GAP-026: no final-XODR cosmetic masking; generator-stage, causal topology correction only; no acceptance tolerance raise; independent geometry and downstream conversion invariants.
- No live CARLA or scientific runtime success without actual RPC response and operator permission. A socket-open or generated receipt with no RPC is NOT `LIVE_VERIFIED`.
- Do not rewrite historical artifacts or overwrite logs. Check source hash, file digest, emitted report, subprocess exit code, test nodeids, counts, timestamp, environment and authorization.

## Verdict
**REQUIRES_CHANGES / SCIENTIFICALLY_NOT_ADMITTED.** Exact CI failure is confirmed, unresolved source-level defects are present, local V26 claims have not been validated and specialist release blockers remain. An OpenCode negative-control pack followed by bounded Codex fixes and independent review is the next legitimate phase. No merge, push to protected integration, live CARLA, production release or automatic approval.

## Evidence links
- PR: https://github.com/lemoniadowyjohn/carla-control-suite/pull/25
- exact-head CI: https://github.com/lemoniadowyjohn/carla-control-suite/actions/runs/42292278556
- source examples: https://github.com/lemoniadowyjohn/carla-control-suite/blob/dfa6ffff07c38d0cc09507c52b3328900ef2d900/tools/rq1_complete_receipt.py ; https://github.com/lemoniadowyjohn/carla-control-suite/blob/dfa6ffff07c38d0cc09507c52b3328900ef2d900/tools/rq3_dataset_manifest_verifier.py ; https://github.com/lemoniadowyjohn/carla-control-suite/blob/dfa6ffff07c38d0cc09507c52b3328900ef2d900/ultimate_pipeline/governance/single_writer/common_git_lock.py
