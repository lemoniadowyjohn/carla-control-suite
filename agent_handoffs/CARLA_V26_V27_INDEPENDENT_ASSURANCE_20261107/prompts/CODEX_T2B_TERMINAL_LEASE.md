# Codex T2b — terminal writer lease and shared Git-metadata race

Owned worktree user-reported: `E:/wt/prod_68868f76`; verify its actual existence, branch and SHA; do not create competing edits if another owner is active. Analyze `ultimate_pipeline/governance/single_writer/common_git_lock.py`, related T2b terminal authority and `scripts/orch_core.py`, `scripts/control_plane.py` only when explicit ownership permits. Baseline PR head `dfa6ffff07c38d0cc09507c52b3328900ef2d900`.

Confirmed CI: `test_concurrent_acquire_has_exactly_one_winner` had TWO winners; 3 orchestration identity/lease tests failed; 23 single writer arbitration tests failed under Linux, 21 showing missing Windows kernel32. Linux runtime lacks Win32 mutex authority by design.

Before implementation: produce 10–50 process concurrent race RED tests, temp-repo-only, delay/partial publish, two readers, crash, PID reuse, stale file replacement, TTL boundary, symlink temp path, common Git worktree path, handoff, lease release and owner creation-time mismatch. Use a deterministic barrier and repeat on Linux and native Windows. Never test against production mutex/domain.

Repair only with ownership: strong OS-native exclusive primitive on Windows for actual mutators; make Git metadata lock atomic against stale-lock unlink vs fresh publisher (lock identity, nonce, compare/delete, recovery), ensure separate publish state, host-UTC, stable inode/lock identity as appropriate, owner pid+creation time, escalation of unreadable state to BLOCKED; no recursive privilege/in-process bypass. Do not introduce a dangerous fake cross-platform lock accepted for production. Clarify lease vs evidence JSON and enforce fenced, idempotent release.

Require zero dual-owner in stress tests; Windows-native test actual Win32 mutex; Linux CI honest skips where native only (no PASS claiming Windows path), plus platform-agnostic common Git race tests RUN on Linux. Record per-OS exact nodeids and failures. Do not merely suppress or reclassify race. T2b output: patch, paired RED/GREEN receipts, source files list, lease state machine, rollback, security review, BLOCKED if Windows unavailable.

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

