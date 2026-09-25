# Multi-Agent Engineering Harness

Use the smallest amount of agent work that can safely answer the task. The
main agent owns scope, integration decisions, and the final result. Spawn
subagents only for independent work, and ask them to return concise findings
with file references and commands run.

## Routing

| Task level | Typical work | Agent policy |
| --- | --- | --- |
| L0 | One-file mechanical change or direct question | Main agent only. |
| L1 | Locate code, classify a failure, inspect logs | One `scout` or `test_triage` agent. |
| L2 | Bounded implementation with known ownership | One `implementer`; optionally one read-only `reviewer`. |
| L3 | Cross-module change, research evidence, map-quality gate | Parallel `scout` + `evidence_auditor` + `reviewer`; one implementer only after synthesis. |
| L4 | Map-of-record, release gate, provenance, or runtime-risk work | Read-only discovery first, exactly one writer in an isolated worktree, then an independent reviewer. |

## Coordination Rules

- Do not run concurrent writers against the same branch, worktree, or files.
- Use read-only subagents for exploration, test triage, evidence collection,
  and reviews. The main agent assigns a single implementation owner after it
  has reconciled their findings.
- A subagent may not merge, reset, delete, start CARLA, alter map-of-record
  pins, or rewrite frozen evidence.
- For L3/L4 tasks, preserve the baseline SHA, worktree, command output,
  focused-test result, and artifact hashes in the implementation report.
- Treat unavailable full-map inputs or a sparse-checkout test limitation as
  `INCOMPLETE`, never as a pass.

## Model and Effort Budget

- `scout` and `test_triage`: Luna / low or medium for fast, repeatable,
  read-heavy work.
- `evidence_auditor` and `reviewer`: Terra / high for provenance, regression,
  and design-risk assessment.
- `implementer`: Terra / high for bounded edits; xhigh only for L4 work after
  the main agent has a concrete implementation plan.

For a complex task, ask agents to divide work by ownership boundary, not by
arbitrary file count. Wait for all read-only findings before starting a write.


## Project Authority

- Active engineering authority is `integration/production-large-map-20260918`. Do not use GitHub's current default `main` as a production baseline unless a task explicitly targets historical lineage.
- Resolve automatic/manual map identities through `ultimate_pipeline.carla_tools.map_registry.verify_pinned_map`.
- For filesystem I/O, prefer the verified `resolved_path` returned by the registry receipt. Declared/relative paths are provenance labels, not a second filesystem authority.
- Never select a map, OSM file, FBX set, receipt, or experiment artifact by newest mtime, glob order, directory order, or filename date.
- `submission/` and frozen historical evidence are immutable. Add new evidence instead of rewriting prior results.
- A promoted XODR must never be cosmetically patched in place. Fix the earliest responsible generator stage, regenerate a candidate, rerun gates, and promote only after review.
- GAP-026 or any future quality signal must not be closed by raising tolerances, deleting failing laneLinks, or weakening a gate. Separate checker defects from generator defects with independent evidence.
- Live-CARLA success requires actual client RPC (at minimum server/client version and map enumeration). A running process or listening port alone is not runtime PASS.
- CARLA Large Map import must use one whole-map XODR and the governed visual tile set. Keep diagnostic/report JSON outside CARLA's import-discovery tree unless the importer contract explicitly requires it.

## Worktree Hygiene

Before any L3/L4 write or integration:

1. Run `git worktree list --porcelain`.
2. For every worktree, record path, branch, HEAD, lock/prunable state, and `git status --short --branch`.
3. Do not integrate from a worktree containing unexplained modified, staged, conflicted, or untracked production files.
4. Preserve useful uncommitted work before cleanup; never use `git reset --hard`, `git clean -fdx`, worktree removal, or branch deletion as a convenience.
5. One writer owns one subsystem/worktree at a time. Read-only reviewers may inspect concurrently.
6. Retire stale worktrees only after the branch/commit/evidence they contain has been classified as merged, superseded, archived, or deliberately abandoned.
7. Re-run `git worktree list --porcelain` and status checks after merges to prove the coordinator and implementation worktrees are clean.

A remote GitHub branch being clean does not prove local worktrees are clean.

## Evidence and Test Claims

- Report exact commands and counts. `PASS` means the command actually completed successfully.
- Distinguish unit/static integration, full offline suite, GitHub CI, live CARLA runtime, Unreal import/cook, and scientific experiment evidence; success at one layer does not imply success at the next.
- If a test times out, classify it as `TIMEOUT/INCOMPLETE` until the harness-vs-deadlock cause is established.
- If evidence was generated against an older XODR/Git SHA/toolchain, mark it `STALE_OR_UNBOUND` rather than carrying the PASS forward.
- Documentation-only changes may update current operational truth but must not silently alter historical evidence or frozen research claims.
