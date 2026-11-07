# Codex W-D — integration preview and 26-test selection authority

W-D is BLOCKED on a 26-test selection whose original definition is not recovered. The existing `RECONSTRUCTED_ACCEPTANCE_CANDIDATE` must NOT be described as original 26/26 PASS, not even if candidate tests pass. Integration owner approval or original selection recovery is mandatory. Baseline `dfa6ffff07c38d0cc09507c52b3328900ef2d900`.

First recover original manifest from commits/PR/logs/evidence; record source and SHA of exact 26 nodeids, intended versions, platform, coverage, prior receipt. If unrecoverable, publish an explicit proposed set with justification, tag `RECONSTRUCTED_ACCEPTANCE_CANDIDATE`, ask integration owner to approve it, and leave original gate BLOCKED.

Plan a dry-run integration dependency DAG: T2b/F15b governance; RQ1/RQ3 fixes; W-F geometry; W-B RQ5; CI tests; source mirror sync. Produce file overlap detector, parent SHA/merge-base, cherry-pick dry-run conflict evidence, rollback. No actual cherry-pick/merge into integration without separate approval; no production implementation edits outside specifically assigned W-D orchestration. Run approved offline acceptance and full regression with exact exit status, preserving skips/unknowns. Output W-D verdict explicitly distinct from release, scientific and runtime gates.

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

