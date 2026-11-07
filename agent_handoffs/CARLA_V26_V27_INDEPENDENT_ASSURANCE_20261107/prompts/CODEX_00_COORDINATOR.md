# Codex — production workstream coordinator (plans and assignments, no source edits)

Baseline PR: https://github.com/lemoniadowyjohn/carla-control-suite/pull/25; inspected head SHA `dfa6ffff07c38d0cc09507c52b3328900ef2d900`. Read all audits and ownership contracts in this ZIP. Follow OpenCode findings only when paired with actual byte evidence and reproducible test nodeid. You are not allowed to declare V26-A/B local evidence reviewed until its files are accessible and verified.

1. Freeze true GitHub and local worktree SHAs; capture clean/dirty/worktree/branch/lock/lease inventory; check that AUTH-01..10 actually authorize planned operations, especially AUTH-08 before candidate b. Do not erase worktrees or reset any branch.
2. Partition production source ownership into **nonoverlapping** tasks: `CODEX_T2B`, `CODEX_F15B`, `CODEX_WB_RQ5`, `CODEX_WF_GEOMETRY`, `CODEX_WD_INTEGRATION`, `CODEX_RQ1_RQ3`, `CODEX_CI_GATES`. If any two edit same path, stop concurrency and serialize dependency order; create a dependency graph with exact base/parent SHA.
3. Per worker require a task-specific isolated existing or newly approved worktree, clean branch, explicit human/authorized writer claim and common-Git lock for metadata ops. No two Codex writers or OpenCode touches to same source area. Worker reads only its owned prompt plus shared contracts, while coordinator integrates results by proof, not optimistic summaries.
4. Request one pre-fix RED reproducible test per distinct issue and ensure it fails with **expected assertion**. Implement bounded production changes; rerun target tests and all relevant regressions on actual SHA. For each task create commit(s) only on authorized isolated branch; never push to main/integration, force-push, merge or claim approval.
5. Return independent per-task ZIPs / branch SHAs, full stdout/stderr logs (redacted), test counts and exit, evidence manifests and precise BLOCKED statements for runtime/science unverified. Then hand off to independent OpenCode/Claude review; avoid approving own work.

**Dispatch order:** T2b lease/concurrency + F15b artifact integrity before broad integration. RQ1/RQ3 production fixes and CI semantic/mirror fixes can be isolated in distinct disjoint worktrees. W-F generator geometry precedes W-D acceptance. W-B RQ5 final source chain precedes any scientific evaluation. Candidate b remains AUTH_PENDING.

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

