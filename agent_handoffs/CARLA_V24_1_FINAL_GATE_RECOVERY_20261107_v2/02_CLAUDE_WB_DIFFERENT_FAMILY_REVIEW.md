# CLAUDE (or independently proven other provider family) — W-B exact-commit read-only security/science review

**Assignment:** complete the missing *different-provider-family* W-B independent approval, not implementation or a casual scan. If the running model provider family cannot be independently established as distinct from the source author/Codex reviewer, report `PENDING_REVIEW_PROVIDER_IDENTITY` and stop short of approval. Do not assert a model is Claude merely because the prompt says Claude.

## Fixed targets (verify local bytes)
- Repo: `lemoniadowyjohn/carla-control-suite` local W-B worktree; full commit `f07efe9765232615b5ebc42ade94b3459bc3d52a`; expected Git tree `2078f556ff51832f7c86005b12e9b50acdcd51d0`; clean worktree reported by operator.
- Seven-file suite at that SHA: operator-reproduced **100 passed, zero failed, six warnings**, exit 0, 28.05s; original log `G:/tmp/v241-wb-finalization-repro.log`. No external source implies this log was examined; read it directly.
- Four revised test call sites explicitly pass `invocation_id` and `started_at_utc`; old test assertions reportedly unchanged. Prior Codex reviewer approved, but cannot satisfy this independent-family gate.
- W-B audit root `G:/audit/CODEX_V24_FINAL_CONVERGENCE/`: 17 manifest entries reportedly hash-verified.

## Read-only steps
1. Capture provider family, active model ID (when available), reviewer principal/session, declared conflicts, UTC, host, worktree full path/branch, full commit and tree, source clean/dirty, parent commit SHA and raw diff. Hash all files reviewed. If no local source or exact SHA/tree mismatch: `BLOCKED_SOURCE_IDENTITY`.
2. Review the **entire W-B provenance change chain**, not only the four test call sites. Enumerate production modules, fixtures and direct/transitive receipt consumers. Prove fixed `invocation_id` and `started_at_utc` match real intended contract: nonempty/typed/formatted as specified, stable within run, disambiguated across run/dataset/model/map/seed, not fabricated at invocation boundary, and cannot be retroactively replaced by stale/future evidence. Reject ambiguous defaults and mixed source identities.
3. Confirm the four tests change **only necessary call arguments** without deletion, xfail, skip, relaxed assertions, removed checks or reduced pytest selection. Compare original and new test behavior. Distinguish the W-B code implementation parent from final test-adjustment commit.
4. Exercise or inspect negative controls for missing/malformed run identity, backdated/future start, copied identity with different payload/seed/region/model, replay, duplicate run ID, mismatched checkpoint/manifest Git SHA, tampered receipt, symlink/path escape, and incomplete provenance. Expected *rejected fixture* is a successful control only when assertion passes and exit code is 0; a failing pytest node is NOT PASS.
5. Inspect exact 100-test raw log and warning nodeids. Five warnings concern missing **optional** worktree-local settings paths: confirm they do not turn required settings into silent defaults or change test result; one `torch_geometric.distributed` deprecation: confirm upstream-only and no near-term break. Classify each separately and confirm zero new warnings hidden by filters. The previous 2+2+2 warning categorization conflicts with this report; reconcile using raw log.
6. Check full 17-entry audit manifest and associated primary evidence only as needed to support review; never change it. If resource limits prevent running tests, explicitly state review is *static/source+receipt* only and avoid claims about independent runtime reproduction.

## Approval criteria
- The source commit/tree identity is exact, source tests retain their assertions, required run-identity contract is enforced at production boundaries, material negative controls are adequate, no unresolved critical/high provenance flaw, and previous focused results are correctly scoped.
- Reviewer provider family must be provably distinct from the Codex implementation/reviewer family. Interrupted DeepSeek review never qualifies.
- Approve W-B at exact SHA only. This DOES NOT approve W-F, W-D, V24.1 integration, RQ5 scientific generalization, release, or candidate-b publication.

## Required result
Write new, immutable `WB_CROSS_FAMILY_VERDICT.md` and `WB_CROSS_FAMILY_VERDICT.json` with fields: `reviewer_provider_family`, `model_id`, `independent_of_codex` (proof), `reviewed_commit`, `reviewed_tree`, `parents`, `files_examined_sha256`, `negative_controls`, `test_receipt`, `warning_dispositions`, `findings_severity`, `blocked_tests`, `review_scope`, `verdict` = `APPROVE_EXACT_WB_SHA` / `REQUIRES_CHANGES` / `PENDING_REVIEW`, UTC and hashed evidence references. Do not self-approve code, publish or modify any source files.
