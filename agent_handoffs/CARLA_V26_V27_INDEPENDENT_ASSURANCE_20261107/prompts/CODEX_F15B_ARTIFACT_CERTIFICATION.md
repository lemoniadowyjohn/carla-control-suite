# Codex F15b — provenance-locked artifact certification

Worktree reported `F:/wt-gap055-base` (verify), owned artifact authority domain, particularly `ultimate_pipeline/contracts/artifact_authority.py` and its specialist tests. Baseline PR head `dfa6ffff07c38d0cc09507c52b3328900ef2d900`. Do not edit T2b, W-F, W-B or OpenCode namespaces.

Audit the actual artifact certification path for path traversal, symlink escape, mutable files between hash/consume, absent vs empty output, wrong run_id/seed/commit/branch, stale timestamps, missing stage, manifest lineage DAG, incomplete terminal status and reuse/replay of a valid digest with changed contents. Separate file existence, byte hash, schema validity, authority, and scientific admission.

Add RED adversarial tests for each: corrupted artifact contents after receipt, path outside root, symlink replacement, duplicate artifact IDs, invalid version, incomplete/hash-mismatched mandatory list, no final atomic fsync/rename, rollback from interrupted finalization, foreign worktree SHA. Fix bounded production code fail-closed; no blanket exceptions; never silently turn NOT_RUN into PASS. Verify with tests and independent source check; maintain compatibility or versioned migration with receipts. Provide exact SHA, command logs, hash manifest, rollback, unresolved external/runtime gates.

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

