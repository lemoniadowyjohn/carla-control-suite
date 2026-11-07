# Codex — production RQ1 receipt and RQ3 manifest verifier repairs

Owned paths subject to coordinator permission: `tools/rq1_complete_receipt.py`, `tools/rq3_dataset_manifest_verifier.py`, and their *Codex-owned* unit tests. OpenCode's new IA-V27 tests are read-only acceptance inputs, not editable. Exact inspected head `dfa6ffff07c38d0cc09507c52b3328900ef2d900`.

P0 RQ1: source currently references unresolved `_hash_dict`, `normalized_xodr`, `_sha256`, `_compute_feature_counts`, `_compute_topology_counts`, `_compute_tileset_digest`, `_compute_map_acceptance_digest`, `git_commit_hash` (while helper is `_git_commit_hash`). Reproduce via non-CARLA isolated test, demonstrate before-fix failure, fix all execution paths. Do not just predefine dummy defaults; derive metrics from actual artifacts and reject missing. Verify status/return code consistency, pinned source identity, normalized XODR stage creation, source-vs-output digest, stage-by-stage manifests, deterministic run index, UTC provenance, no legacy historical rewrites. Ensure failed pipeline never produces successful receipt.

P1 RQ3: paired schema matching is not capture existence or quality evidence. `_check_capture_files` currently only checks nonempty strings when optional list present; `_check_quality_evaluated` tolerates absent record; a matched pair can PASS while `quality_comparison=NOT_RUN`. Preserve legitimate contract-level pairing semantics, introduce explicit data-byte verification and scientific-evaluation status as SEPARATE gates. Verify capture files within trusted root, canonical path/symlink traversal, digest, format/dimensions, frame/timestamp matching, ordered frames and required modality; reject duplicated/forged path assertions, dataset split leakage and map/route/sensor identity mismatch. Do not misclassify synthetic test PASS as scientifically admitted; version schema/outputs as needed.

Tests must first reproduce negative outcomes with synthetic tmpdirs, then pass after fixes, with no real CARLA or new training. Return PR branch/commit, code+test diff, full exit code/logs, backwards compatibility and immutable SHA receipts; independent OpenCode/Claude review needed.

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

