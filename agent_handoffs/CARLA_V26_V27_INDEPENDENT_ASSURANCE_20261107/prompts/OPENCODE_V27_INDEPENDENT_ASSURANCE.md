# OpenCode — IA-V27 independent regression assurance; execute Tasks A–E

You are OpenCode, **independent tester and evidence curator, not production fixer**. Use the attached audit pack. Start by reading `README.md`, `audit/00_INDEPENDENT_AUDIT.md`, `audit/01_CI_30_FAILURE_GROUPS.csv`, `audit/02_CLAIM_RECONCILIATION.csv`, `contracts/OWNERSHIP_AND_GATES.md`, `contracts/NEGATIVE_CONTROLS.md`.

Repo: `lemoniadowyjohn/carla-control-suite` PR #25 https://github.com/lemoniadowyjohn/carla-control-suite/pull/25. **Inspected reference SHA:** `dfa6ffff07c38d0cc09507c52b3328900ef2d900`. Do not trust old SHA in the PR description. Work against the actual authorized local worktree after verifying it is derived from reference SHA, and log divergence. GitHub CI baseline: https://github.com/lemoniadowyjohn/carla-control-suite/actions/runs/42292278556 (30 FAIL / 7911 PASS / 73 skipped / 3 xfailed; release gate skipped). The local V26-A/B paths supplied by operator are separate evidence sources, not verified merely because named.

### P0: Freeze and inventory before tests
1. On Windows operator machine, read current time with zone, `git worktree list --porcelain`, `git status --porcelain=v1 -uall`, `git rev-parse HEAD`, common Git dir, branch/upstream, merge base, `git log -10`, lock/lease state and process creation identity. Ensure no other writer, acquisition is legitimate and no dirty state is overwritten. No Git metadata mutations until verified single-actor protocol.
2. Enumerate V26-A deliverables 00–11 + `verification.json`/`SHA256SUMS.txt`; V26-B 00/01/02/03_RQ4_DATA_LEAKAGE_TESTS/03_RQ4_GRAPH_VALIDATION/04/05/07/08/09/10/11 + manifests; record `EXISTS`, actual SHA256, schema, claimed baseline, generation time, command receipt source, missing expected index (e.g. absent 06). Do not invent files or assume numeric continuity is required without a documented manifest.
3. Verify V26-A/26-B were generated from exact intended source SHA; if they predate current PR head, label `HISTORICAL` and do not transplant PASS. Establish `reported` vs `executed` vs `verified` vs `scientifically_admitted` separately.
4. Confirm the six user-reported files from V26-B/IA-V27 (17/16/19 tests + RQ1/RQ3/CI files) actually exist and hash their contents; verify namespace and ownership. If files are absent in the local worktree, record `MISSING_LOCAL` and do NOT claim test passes. They are not present in inspected GitHub PR HEAD.

### Task A — RQ1 production entrypoint
- Create tests ONLY in `tests/integration/opencode_v27_ia/` that prove `tools/rq1_complete_receipt.py` is loadable and its executed non-CARLA preflight path has all names defined; include RED assertions for `_hash_dict`, `normalized_xodr`, `_sha256`, `_compute_feature_counts`, `_compute_topology_counts`, `_compute_tileset_digest`, `_compute_map_acceptance_digest`, and `git_commit_hash` mismatch. Do not invoke `MainPipeline.run` or live CARLA; monkeypatch dependencies at safe seam.
- Bind run index, route/seed/config, source SHA, stage statuses, topology metrics, normalized XODR hashes and output digest to actual artifacts. Detect placebo metrics, unknown SHA, replayed receipt and `status=ok` after exception. Ask Codex to implement corrections; OpenCode submits tests/RED evidence only.

### Task B — RQ3 contracts and evidence graph
- Add read-only negative controls for missing/corrupt capture bytes, symlinks, duplicate/nonmonotonic frame IDs/timestamps, timestamps vs frames count, data split mismatches, wrong map/route/seed/weather/sensor transforms, copied partner manifest, absent quality evaluation, optional-vs-mandatory mislabeling.
- Discriminate `paired_manifest_contract_pass` from `actual_data_verified` and `scientific_quality_pass`; never promote `quality_comparison=NOT_RUN` to RQ3 science PASS. Existing verifier permits path strings without checking file bytes; prove with a safe tmpdir fixture.

### Task C — 30-failure CI forensic certification
- Download **exact** run 42292278556 and all job logs, enumerate 30 node IDs and seven proposed symptom buckets; validate counts and root-cause grouping with trace signatures. Reproduce each deterministically on suitable platform(s) and categorize `SOURCE_DEFECT`, `TEST_CONTRACT_DEFECT`, `PLATFORM_INCOMPATIBILITY`, `DEPENDENCY/ENV`, `RACE`, `UNKNOWN`. Do not assume V26-A's C/F statuses prove all failures.
- Required groups: 1 strict gate semantic test, 1 loader mirror drift, 1 C: volume test, 1 common-Git lock two-winner race, 3 orchestrator identity/reconcile tests, 21 `CreateMutexW` Linux Windows-only failures, 2 separate subprocess owner failures. Splitting these into seven symptom buckets does **not** prove seven independent root causes. If trace-specific counts differ, record correction and justify.
- For 21 Linux Windows-native cases: mark Linux `NOT_APPLICABLE_PLATFORM` with exact skip logic if necessary (Codex owns production/test edits), and request real Windows test. The Linux `skip` is not success. The common-Git two-winner race is not automatically platform-only.

### Task D — scientific validity across RQ1–RQ5
- Verify original frozen RQ1–RQ5 acceptance contracts, pre-registration, file hashes and thresholds, dataset boundaries, held-out split independence. No new training or live CARLA.
- RQ1: repeated runs/provenance, statistical design, determinism vs randomness, correct path and receipt. RQ2: directed road/lane connectivity, orphan, georef, XODR source-stage changes, GAP-026. RQ3: real capture provenance/RPC blocked. RQ4: route/map/time/scene/seed leakage and graph near-duplicates. RQ5: synthetic acceptance ≠ model generalization; 3 missing W-B commits and holdout metrics remain blocking.
- For W-F check reversal/orphans from generator stage; report defects and reproducible synthetic witness only, no output cosmetics. W-D reconstructed 26 tests are proposed acceptance, not official.

### Task E — bounded Codex handoff
- Produce a machine-readable defect matrix with unique IDs, severity, owner, source SHA/path/line, expected and actual, minimal reproduction/negative control, impacted acceptance gate, scientific consequence, suggested production fix, validation commands, blockers and verification level.
- Keep ownership: Codex T2b/F15b/W-B/W-F/W-D/RQ1/RQ3/CI changes, OpenCode-only `tests/integration/opencode_v27_ia/` and V26 namespaces. No source changes or unauthorized cherry picks. Send each Codex prompt independently with source ownership/lease lock.

### Mandatory outputs
- `00_BASELINE_AND_AUTHORITY.json`, `01_LOCAL_ARTIFACT_INVENTORY.csv`, `02_CI_EXACT_30_TESTS.csv`, `03_ROOT_CAUSE_EVIDENCE.md`, `04_RQ1_RED_TESTS.json`, `05_RQ3_NEGATIVE_CONTROLS.json`, `06_RQ1_RQ5_SCIENCE_MATRIX.csv`, `07_WD_SELECTION_PROVENANCE.md`, `08_WORKTREE_LOCKS_AND_OWNERSHIP.json`, `09_CODEX_HANDOFF_MATRIX.json`, `10_COMMAND_RECEIPTS.jsonl`, `11_COMBINED_V26_A_V26_B_V27_VERDICT.md`, `verification.json`, `SHA256SUMS.txt`.
- Every test receipt must record executable, args, cwd, source SHA, start/end UTC, platform, exit code, counts, logs and SHA256. All failures remain visible. A missing or inapplicable runtime is `BLOCKED_EXTERNAL`, not success.
- Final output one uniquely named evidence ZIP, manifest-verified and locally reopened; do not overwrite earlier V26 artifacts. Print a concise per-gate STATUS table and all unresolved blockers.

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

