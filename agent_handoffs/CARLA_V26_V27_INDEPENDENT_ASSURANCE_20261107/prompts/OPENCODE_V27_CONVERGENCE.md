# OpenCode — post-Codex IA-V27 convergence and independent certification

Run ONLY after Codex provides exact candidate SHAs and immutable receipts for each owned workstream. Read the main OpenCode prompt and all contracts first.

1. Freeze current PR #25 SHA (`dfa6ffff07c38d0cc09507c52b3328900ef2d900` was the inspection baseline; do not assume unchanged), current integration base, each Codex branch/commit parent, and current CI run/check conclusion. Reconcile expected parentage with `git merge-base --is-ancestor` on each branch, record return code and no source merge. Verify no competing writer.
2. Compare each Codex changed path against task-specific ownership allowlist; reject production edits made by OpenCode, swapped RQ5 vs W-F source, unauthorized threshold edits, final XODR edits, unaudited mirror changes, unapproved test deletion and receipt rehash.
3. Re-run RED/GREEN regressions from actual V26/IA-V27 files and Codex suites; test independent holdout/negative controls. A local green result cannot override a hosted exact-SHA red CI job; rerun hosted CI on the integrated candidate SHA if authorized.
4. Reconcile 30 original CI nodeids to 30 current statuses (PASS / PLATFORM_BLOCKED / NOT_EXECUTED / FAIL / SUPERSEDED_WITH_PROOF); no shrinking tests, broad skips, `xfail` laundering or suppressing tracebacks.
5. Build an integration-preview plan with deterministic cherry-pick dependency DAG, conflicts, shared-file collisions, rollback and pre/post hashes. Do **not** cherry-pick production edits or publish without integration-owner permission.
6. Reconcile W-D 26-test selection against original reference, or label RECONSTRUCTED_ACCEPTANCE_CANDIDATE pending owner approval. Candidate b stays AUTH_PENDING without exact AUTH-08.
7. Apply research admission matrix per RQ1–RQ5; test count alone never establishes scientific admission. Preserve frozen thresholds and no live CARLA.
8. Return `CONVERGENCE_VERDICT.json`, full blocker matrix, exact-SHA CI links, all commands/exits, root-vs-candidate diffs, worktree lock ledger and independent review request. Final allowed status: `OFFLINE_CERTIFIED_WITH_BLOCKERS`, `REQUIRES_CHANGES` or `BLOCKED`; `PRODUCTION_READY` requires separate operator gate.

## Non-negotiable working contract
- Do not force-push, merge, auto-approve, auto-deploy, publish candidate b or change protected `main`/`integration`.
- No live CARLA/UE4, cooking, high-cost experiments or new model training without explicit operator authorization; synthetic-only offline work is allowed.
- The final XODR cannot be cosmetically modified; GAP-026 cannot be hidden by raising tolerance; geometry corrections only at generating source stage with provenance.
- Do not edit or overwrite historical artifacts, original V25/V26 reports, receipts, or anyone else's worktree. Use unique output directories with new run IDs and SHA256 manifests.
- Single writer per worktree and per shared Git-metadata mutation. Audit locks and actual process start identity first; if inconsistent STOP/BLOCKED.
- Every PASS must have command, exact cwd, executable/tool version, return code, collected/passed/failed/skipped/xfailed, input/output hashes, actual test nodeids, and exact commit SHA; unexecuted commands => NOT_EXECUTED.
- No false platform classification: one failing test on Linux does not establish success on Windows. Evidence for live or external runtime requires actual authorized RPC response, not an import or socket.
- If a command could alter production, invoke providers, real CARLA, or paid resources: **do not execute it** without a precise separate authorization grant.
- Never make OpenCode production changes or Codex edits to OpenCode-only test paths. See `contracts/OWNERSHIP_AND_GATES.md`.

