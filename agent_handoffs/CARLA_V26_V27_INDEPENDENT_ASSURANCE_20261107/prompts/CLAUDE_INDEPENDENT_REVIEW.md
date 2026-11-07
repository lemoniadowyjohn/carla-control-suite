# Independent Claude / human review — adversarial release audit, no self-approval

You are a separate reviewer, not the producing agent. Review actual exact finalized candidate SHA and its GitHub run(s), NOT the historical `dfa6ffff07c38d0cc09507c52b3328900ef2d900` unless it is still HEAD. No code modification, no merge and no real CARLA.

1. Verify all source hashes/parentage and approval/ownership records, absent test laundering and role separation; inspect Codex vs OpenCode file ownership including `tests/integration/opencode_v27_ia`.
2. Independently reproduce at least one negative control each for RQ1 undefined names, RQ3 forged capture-file identity, QualityGate truthy string, common-Git two-winner race, and final-XODR GAP-026 tampering. Mark inability as BLOCKED; never infer success.
3. Re-classify all 30 original CI failures against tracebacks: real source/contract vs Windows/Linux platform vs concurrency. Verify no skipped Linux Windows-native case was counted as Windows PASS.
4. Audit T2b atomic ownership, F15b certification and byte hash lineage, RQ1/RQ3 full path semantics, W-F generator-stage directed topology/georef, W-B RQ5 data leakage and unfinished commits, W-D original 26-test suite authority.
5. Distinguish contract_valid, offline_tested, scientific_admitted, CARLA_RPC_verified, UE4_cooked, release_approved. A test saying PASS with quality_comparison=NOT_RUN is contract-level at most.
6. Check authentic AUTH-08 for candidate b; absent => not publishable. Inspect any threshold changes, final XODR patches, historical evidence overwrite, host-specific assumptions, branch/candidate SHA mismatches.
7. Return SHA-bound review with severity/blocker IDs, minimal reproductions, exact paths/lines, tests actually run, source evidence and independent verdict. Allowed `REQUIRES_CHANGES`, `BLOCKED`, `OFFLINE_ACCEPTED_WITH_EXTERNAL_BLOCKERS`; never automatically APPROVE or claim production-ready.

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

