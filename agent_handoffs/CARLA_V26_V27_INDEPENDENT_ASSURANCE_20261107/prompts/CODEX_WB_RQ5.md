# Codex W-B — RQ5 remaining three commits, no training

Reported worktree `F:/carla-worktrees/rq5-sightb-20261009`, PARTIALLY_COMPLETE with 3 commits pending; verify branch graph and actual commit IDs, neither invent nor guess them. Baseline inspected PR head `dfa6ffff07c38d0cc09507c52b3328900ef2d900`.

First audit state: list all completed/pending commits with SHA, parent, files, run receipts, training data and frozen RQ5 contract. If the three commits do not exist, mark source gaps and propose bounded independent commits; do not fabricate history. Identify whether W-B changes overlap F15b/T2b/W-F; serialize overlaps.

Implementation only in approved RQ5 production ownership. Add deterministic unit and integration tests proving model/data pipeline is wired to real inputs, feature dimensions, no train/test leakage (scene/map/time/route/seed and derived graph), checkpoint provenance, model inference errors, baseline equivalence, held-out evaluation contract and ablation methodology. No new training, data downloading, paid calls or live CARLA. Any empirical generalization/CI cannot be called PASS from synthetic fixture tests. Return code SHAs, RED/GREEN receipts, `RQ5_SCIENTIFIC_STATUS=NOT_ADMITTED` unless actual authorized held-out results exist; identify specific data/runtime blockers.

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

