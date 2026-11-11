# OpenCode master execution prompt — post-PR#16 remediation (2026-10-23)

> Paste everything below the line into an OpenCode session that runs the default **build** (primary)
> agent. It dispatches subagents **by name** through the task tool. Do not use `opencode run --agent
> <subagent>`; it silently falls back to build. If you use `opencode run`, close stdin (`< /dev/null`).
> Detailed per-task text for O1–O7 and C1–C5 also lives in `OPENCODE_CODEX_BLOCKER_PROMPTS_20261023.md`.
> If this file and that one disagree, this file wins.

---

## ROLE

You are the OpenCode **coordinator** for repo `lemoniadowyjohn/carla-control-suite`, working under
`AGENTS.md`. You own scope and integration. You do not write code yourself: dispatch exactly ONE
`implementer` at a time, then ONE `reviewer` (fallbacks `reviewer_alt` → `reviewer_alt2`) for every
commit. Tasks marked **[CODEX]** are too hard or too design-heavy for the free pool. For those, do NOT
dispatch an implementer. Write the handoff file described in §6 and continue with the next
non-Codex task. Tasks marked **[DECISION]** stop until the operator answers.

## 0. GROUND TRUTH (verified by Claude audit 2026-10-23, re-verify; do not trust)

- Production `origin/integration/production-large-map-20260918` = `d72f57c6` (PR #16 merged
  14:31 from `5a004113`, **without** G01/G02/G03/G05).
- Fix commits exist locally only: `61769519` (G05), `a3773070` (G01), `020063d9` (G02), `1e902986` (G03).
  `origin/experimental/verified-fixes-20261022` = `5a004113`.
- Worktree `E:/wt/repair-map-realism-p0-837a8504` @ `1e902986` is DIRTY with uncommitted edits from a
  previous run (realism_augmentor.py, rq3_capture_contract.py [whole-file EOL churn],
  rq3_rq5_handoff_adapter.py [EOL churn], test_rollback_audit.py [IndentationError at line 18 that
  aborts collection of all 8246 tests]). It also has untracked `cities/ingolstadt/...` (byte-identical to
  `68868f76`) and untracked helper scripts `fix_*.py`, `test_o4.py`, `verify_fixes*.py`.
- Freeze hashes (must never change): rq3 `5aa8ae248b26ed1bcc053ae1b70b5a508e3fd05b5cab4bb68debc495f44b98bd`,
  rq5 `db7155fef00787ee615767f309df0247248381e18911d571741bbfa1030fcb8d`.
- `git merge-tree --write-tree d72f57c6 1e902986` merges cleanly.
- Disk: C: about 1.4 GB free, E: about 4.1 GB free. Never trigger real disk-full; inject errors instead.

## 1. HARD RULES (apply to you and every subagent)

1. Single writer. One implementer at a time, one commit per task, then review. Never run while a Codex
   or Claude writer is active on this worktree. Ask the operator if unsure.
2. Forbidden: push, force-push, merge, rebase, reset, stash, deleting branches, editing
   `configs/rq3_protocol_freeze_v1.json` / `configs/rq5_protocol_freeze_v1.json`, modifying any
   existing file under `reports/` (historical artifacts), changing map-of-record pins or registry,
   promoting a map, and starting CARLA or CarlaUE4. Allowed git writes: `git switch -c`, `git add`,
   `git commit`.
3. Preserve each file's line endings and BOM. For every commit,
   `git diff -w --ignore-cr-at-eol --stat HEAD~1 HEAD` must equal `git diff --stat HEAD~1 HEAD`.
4. Regression tests come first. A new negative test must FAIL on the pre-fix code; paste that output,
   then the passing output.
5. No PASS without executed commands. Python:
   `C:/Users/admin/PycharmProjects/gpt4/pythonProject3/.venv/Scripts/python.exe`; pytest always with
   `-p no:cacheprovider`. Never weaken or skip a test to get green. A sparse checkout or missing input
   = `INCOMPLETE`, never PASS.
6. Do not commit helper scripts (`fix_*.py`, `test_o4.py`, `verify_fixes*.py`). Report their contents,
   then delete them in O0.
7. Every agent report ends with the JSON in §5. Free-model output is held to the same evidence bar.

## 2. SETUP (coordinator, before any task)

```
cd E:/wt/repair-map-realism-p0-837a8504
git rev-parse HEAD            # expect 1e902986…
git status --porcelain=v1
git worktree list --porcelain | findstr /C:"repair-map-realism-p0-837a8504"
git fetch origin && git rev-parse origin/integration/production-large-map-20260918   # expect d72f57c6…
git switch -c fix/post-pr16-remediation-20261023      # new branch; keeps the working-tree edits
```
If HEAD or origin differ from §0, STOP and report.

## 3. TASK QUEUE (strict order)

Legend: **[OC]** OpenCode implementer → reviewer. **[CODEX]** write a handoff, do not implement.
**[DECISION]** stop and ask the operator. **[OPERATOR]** list only.

### Phase A — repair the tree and land what is already done

**A0 [OC] Repair the in-progress edits.** *(Superseded by A0′ in "Update 2026-10-23" below. Run A0′ instead.)*
- Fix the `IndentationError` in `ultimate_pipeline/tests/unit/test_rollback_audit.py`.
- Revert EOL churn so that `rq3_capture_contract.py` and `rq3_rq5_handoff_adapter.py` keep HEAD's
  line endings. Keep only the intended semantic changes. If an edit's intent is unclear, revert it and
  list it in the report.
- Report and delete the untracked helper scripts.
- Gate: bare `pytest -p no:cacheprovider -q` must COLLECT. Paste the `collected N items` line and the
  final summary. Commit `chore: repair in-progress edits (A0)`.

**A1 [OC] O6 restore inputs.** `git checkout 68868f76 -- cities/ingolstadt/dem/dem_ing.tif
cities/ingolstadt/osm/buildings.geojson`. Gate: `git hash-object` equals `git rev-parse 68868f76:<f>` for
both. They were deleted by `f0c83285`, which is also on production.

**A2 [OC] O7 revert mirror edits.** `git checkout 68868f76 --` the 3 files under
`submission/infrastructure/ultimate_pipeline/` (core/validation_report.py, main_pipeline.py,
quality/pipeline_health_summary.py). None is in `CRITICAL_MIRRORED_FILES`. Gate:
`tests/phase_q/test_duplicate_module_drift.py` passes; `git diff --stat 68868f76 HEAD -- submission/`
is empty.

**A3 [OC] O1 residual hardcoded paths** (`rq3_rq5_handoff_adapter.py:256` WRITE path,
`test_experiment_manifest_negative_controls.py`, `test_rollback_audit.py`). Use
`resolve_approved_root()` and the `RQ3_TEST_ROOT` pattern. Tests must write to tmp, never into
`reports/`. Gate: `git grep -n "repair-map-realism-p0-837a8504" -- '*.py'` is empty except
assertion strings.

**A4 [OC] O2 integrity fixture.** In `test_rq3_artifact_content_verification.py`, change
`_sha(ROOT / name)` to `_sha(DELIV / name)`. Gate: the 4-module RQ3 command gives 71 passed, 0 failed.

**A5 [OC] O3 EOL restore** of `ultimate_pipeline/augmentation/realism_augmentor.py` (UTF-8 BOM + LF,
as in `68868f76`; only the `apply()` hunk may differ).

### Phase B — RQ5 blockers (CHAT-09)

**B1 [OC] O8 `is_main` ordering.** In `train_launcher.py`, line 437 reads `is_main` before line 441
assigns it (introduced by `4ca15683`, live on production). Move `_init_ddp` and `is_main` above the
`_revoke_stale_success` block. Test with stubs for `enforce_dataset_acceptance` → `{"accepted": True,
"total_paired_frames": 1}` and for `_init_ddp`, plus a sentinel to stop before training. It must fail
first with `UnboundLocalError`.

**B2 [OC] O9 random-init backbone.** In torchvision 0.24.1, `fcn_resnet50(weights=None)` loads
`ResNet50_Weights.IMAGENET1K_V1`. That violates both freezes ("random initialization; no pretraining").
- Pass `weights_backbone=None` in `train_launcher.py:309`, `min_train_segmentation.py:207`,
  `eval_sim_labeled.py:237` and `eval_real_unlabeled.py:290`.
- `rq5_provenance.verify_random_initialisation` must check the observed kwargs and raise if either is
  non-None, instead of writing the literal `"weights_backbone_argument": None`.
- Test: monkeypatch `torchvision.models._api.WeightsEnum.get_state_dict` to raise; no factory may
  call it.
- List every committed receipt or manifest that claims random init. Do not edit them.

### Phase C — gate hardening

**C1-lite [OC] G03 strict coercion (O4)** and **G04 `apply()` honours config (O5)**, as specified in
the blocker-prompts file, as separate commits.

**C1 [CODEX] G02 review-receipt binding + fail-open defaults.** Handoff must include these reproductions:
(a) receipt digest = RGB frame digest; (b) all three digests = capture member frames, no content_index;
(c) receipt content `{"review":"REJECTED"}`; (d) a member without `modality` counted as rgb;
(e) a member without `committed` treated as committed; (f) an empty or missing `session_id` skips the
stale-session check. All six give admission or `(True, [])` at `1e902986`. Requirements: a dedicated
`review_receipt` role, parsed verdict, reviewer ≠ capture identity, reviewed-SHA binding, pairwise-distinct
digests. CHAT-01 also asks for a cryptographic trust root, signature, expiry and revocation. Record that
as an explicit residual if it is not built.

**C2 [DECISION→CODEX] Wire G03 into `run_strict_rq3_capture`** (`record_route_fixed.py:3541`).
Today no production caller uses `_validate_frame_set_consistency`. The freeze (rq3 line 80) says
"exact frame counts bound via dataset manifest hashes at execution". Recommended rule, which needs
operator approval: expected counts come from a pre-capture manifest whose hash is bound into the
capture receipt. Ask before handing off.

**C4 [CODEX] CHAT-02 Stage04/Stage09 access metadata fails closed.** `stage_04_enrichment.py:347-361`
and `stage_09_positional_semantics.py:243-257` catch the failure and only warn.

**C5 [CODEX] CHAT-03 Stage06 ENOSPC / torn writes.** There is no `ENOSPC` handling anywhere in
`ultimate_pipeline/`. Needs atomic write + fsync + `os.replace`, and no positive receipt after a failure.

### Phase L — successor/predecessor topology (new findings, 2026-10-23)

Facts (all reproduced by the audit at `d72f57c6`):
- Road-level links originate in the external OSM→SUMO netconvert→XODR conversion. The XODR keeps
  **no OSM way ID**: 32,267 roads, 0 carry an orig/sumo/osm road identity (all names are `""`). After
  conversion, nothing can tie an XODR road to its OSM way except spatial matching.
- The only OSM link cross-check (`quality/osm_road_link_topology.py`, run 2026-09-14 on map-of-record
  `2ca342d8`) matched 134/32,267 roads (0.4%). Of 28 checkable boundaries, 13 disagreed (46%). It is
  NOT wired ("advisory").
- **Stage 3 `topology/orphan_road_repair.py` (P0-B), on production, default `UP_ORPHAN_SNAP_M=25.0`**
  (docstring says 5.0), creates road links from proximity alone:
  1. `_road_endpoints` applies `math.radians()` to an OpenDRIVE heading that is already in radians.
     A north-pointing 100 m road from (0,0) gets end (100.0, 2.7) instead of (0, 100). Near-straight arcs
     also do `hdg += length`. paramPoly3 and spiral are treated as lines.
  2. It always writes `<successor>`, even when the orphan's START matched (`best_target_orphan_idx` is
     computed and ignored).
  3. It never writes `contactPoint` (`best_target_is_start` is ignored). Downstream
     `lane_successor_topology._get_road_successor` and `fix_missing_lane_successors` then **default a
     missing contactPoint to "start"**, silently.
  4. No reciprocal link is written on the target, so topology is asymmetric.
  5. Targets include junction connector roads (anything in `junction_roads`) and roads whose end is
     already linked to a junction.
  6. No heading, elevation or OSM check. A parallel road 20 m away (other carriageway or overpass) gets
     linked.
  7. It is wrapped in `try/except` "non-fatal" despite the "fail-closed" docstring. Raising the snap to
     25 m to reduce residuals is a tolerance raise (cf. the GAP-026 rule).
- **Stage 7 `lanes/lanelink_builder.py` wipes every junction `laneLink`** (`conn.remove(ll)`) and
  rebuilds them by lane ordering (inner-first). It has zero OSM inputs. That discards the lane
  connections netconvert derived from OSM (connections, turn restrictions, `turn:lanes`). OSM
  `turn:lanes` only reaches userData hints (`turn_lanes_writer`), and `turn_restriction_audit` is
  advisory. Road-level allowed movements survive, because netconvert omits prohibited connections, but
  lane-to-movement assignment is not OSM-derived.
- Healthy parts, keep them: `enrichment/lane_successor_topology.py` (topology-only, unique-proof,
  no geometric guessing); intra-road `check_lane_section_successors` (nearest lane centre at a section
  boundary inside one road).

**L1 [OC] Make P0-B orphan repair safe** (source stage, `topology/orphan_road_repair.py` +
`stage_03_topology_repair.py`):
- Use `ultimate_pipeline.geometry.opendrive_geometry_kernel.endpoint` for endpoints (all primitives,
  radians).
- Write `predecessor` when the orphan's start matched and `successor` when its end matched. Always set
  `contactPoint` from the target endpoint.
- Write the reciprocal link on the target. If that target slot is already occupied, do NOT link; record
  the residual as `target_endpoint_occupied`.
- Never target junction-internal roads (`junction != "-1"`).
- Require heading continuity (direction-aware, |Δheading| ≤ 30°) and |Δz| ≤ 1.0 m using the elevation
  profile. Otherwise record a residual with a reason.
- Restore the default snap to 5.0 m. `UP_ORPHAN_SNAP_M` above 5.0 is allowed only when `THESIS_STRICT`
  is off, and every link made beyond 5 m must be logged.
- An exception inside the repair must propagate when `THESIS_STRICT` is on (no silent "non-fatal").
- Every created link goes into the report (orphan, endpoint, target, contactPoint, distance, Δheading,
  Δz).
- Tests (each must fail first): the three audit reproductions (north road endpoint; start-match →
  predecessor + contactPoint + reciprocal; parallel road 20 m → not linked), a junction-connector target
  is refused, an occupied target slot is refused, and paramPoly3 endpoint correctness.
- Do NOT regenerate or promote any map.

**L2 [OC] Missing `contactPoint` must not default to "start".** In
`enrichment/lane_successor_topology.py`, `fixes/fix_missing_lane_successors.py`,
`quality/check_lane_connectivity.py` (and any `get("contactPoint", "start")` on a **road-type** link):
- A road-type link without `contactPoint` is a defect. Do not infer lane successors through it; report it
  as `road_link_contactpoint_missing`.
- Add a validation-only check `quality/check_road_link_reciprocity.py`: every road→road link has a
  contactPoint; if A links to B at B's start, B's predecessor must point back to A (or through a junction).
  Run it in Stage 8 as report + gate, failing only under `THESIS_STRICT`.
- Tests: missing contactPoint, asymmetric pair, valid pair, junction-mediated pair.
- Then run the new check read-only on the newest available real stage output (for example
  `reports/rq1_trial_runs/run_01/20261007_214826_524342/06_continuity_*.xodr` and `07_lanes_*.xodr`,
  untracked in the main checkout). Report the counts. Do not modify those files.

**L3 [CODEX + DECISION] Junction laneLinks vs OSM.** The handoff must first produce a read-only
measurement on a real stage-6/stage-7 pair:
- the number of connections whose laneLinks changed between netconvert output and LaneLinkBuilder;
- `turn_restriction_audit` agreement before vs after.
Then propose one of:
- (i) preserve valid netconvert laneLinks and only fill missing ones;
- (ii) constrain the inner-first pairing with OSM `turn:lanes` where correspondence is EXACT/HIGH;
- (iii) keep the status quo, with a documented rationale.

Read the GAP-026 / GAP-048 history first (the inner-first remap was deliberate). Operator decides.

**L4 [CODEX] Restore OSM identity through conversion.** Find the external conversion command
(netconvert version and flags, from docs or reports), then test on a SMALL OSM fixture whether
`--output.original-names` (or that version's equivalent) puts the OSM way or edge IDs into the
OpenDRIVE output. If it does, propose carrying the IDs into road `userData`, and an exact-ID mode for
`osm_road_link_topology.py` to replace the 0.4%-coverage spatial match. No full-map regeneration and no
map-of-record change. That stays operator-only via the registry.

**L5 [DECISION] Wire `osm_road_link_topology` as advisory telemetry** only after L4 gives exact IDs.
At 0.4% coverage it is noise.

### Phase D — verification and handoff to operator

**D1 [OC reviewer, read-only] Full suite on the final branch HEAD:** bare
`pytest -p no:cacheprovider -q` from a clean tree (`git status` empty apart from ignored files).
Report exact counts and every failure, each classified as product, environment or pre-existing.
Classify a failure as pre-existing only if the same test fails on `d72f57c6` in a separate clean
checkout. If no such checkout is available, mark the comparison `NOT_RUN`. Never stash or switch
branches in this worktree to compare.

**D2 [OC reviewer] Freeze hashes** at HEAD equal §0. `git log d72f57c6..HEAD --stat` has no
`reports/` modifications and no files over 5 MiB.

**D3 [OPERATOR] list** (do NOT execute; print it):
1. `git push origin fix/post-pr16-remediation-20261023` (new branch; normal push).
2. Open a PR to `integration/production-large-map-20260918` (base `d72f57c6`). The title must state that
   production currently has the G01/G02 false-pass and the `is_main` crash.
3. CI green on the PR head before merge. Package CHAT-10: exact-head CI had zero runs before.
4. Local stale branch: `git tag archive/502dda26-stale-proto-20261022 502dda26`; then, in
   `F:/carla-control-suite-worktrees/session-batch1-full-verify-20260913` with a clean status:
   `git reset --keep origin/integration/production-large-map-20260918`. NEVER force-push `502dda26`.
5. Decide on `stage8_rca_output/p0_before_gate_sweep/lane_count_changes.json` (16.6 MB, over policy):
   remove or waive.
6. Answer the [DECISION] items: C2 counts source, L3 option, L5.
7. Not code (stay BLOCKED): CARLA/native runs, netconvert full-map run, GPU/VRAM, H: unlock, v8.3 base
   ZIP, external signed review (package CHAT-00, 04, 05, 06, 08, 11, 12, 13, 14).

### OWNERSHIP SPLIT 2026-10-23 (overrides everything below and above)

The former **[CODEX]** tasks C1 (full G02 incl. the C1 addendum), C4, C5, L3 and L4 are now
implemented by **Claude Code** in a SEPARATE worktree `E:/wt/claude-hard-tasks-20261023`, branch
`fix/claude-hard-tasks-20261023` (from `1e902986`). OpenCode must NOT edit these files:
`ultimate_pipeline/perception/rq3_evidence_gate.py`,
`ultimate_pipeline/perception/record_route_fixed.py`,
`ultimate_pipeline/tests/unit/test_rq3_artifact_content_verification.py`,
`ultimate_pipeline/pipeline_stages/stage_04_enrichment.py`,
`ultimate_pipeline/pipeline_stages/stage_06_links.py`,
`ultimate_pipeline/pipeline_stages/stage_09_positional_semantics.py`,
`ultimate_pipeline/enrichment/access_restriction_metadata.py`,
`ultimate_pipeline/lanes/lanelink_builder.py`,
`ultimate_pipeline/pipeline_stages/stage_07_lanes.py`, and
`ultimate_pipeline/core/file_utils.py`.

In A0′, **revert** the uncommitted `rq3_evidence_gate.py` edits (`git checkout HEAD -- <file>`). Do not
commit the C1 addendum; Claude re-implements it with tests. Skip C1, C4, C5, L3 and L4; do not write
handoff files for them. The O2 integrity-fixture fix (A4) touches
`test_rq3_artifact_content_verification.py`, so it moves to Claude as well. Skip A4.
The operator merges the two branches later.

### Update 2026-10-23 (after the second false "COMPLETE" report) — these REPLACE or ADD to the tasks above

**A0′ [OC] (replaces A0) Salvage the uncommitted work into per-task commits.** As of the last check
the tree has 0 new commits and these uncommitted edits:
- C1-addendum checks in `rq3_evidence_gate.py`. They work; keep them.
- O4 in `rq3_capture_contract.py`. It works, but it RAISES `ValueError`. Change it to append
  `expected_count_invalid:sensor:<name>` / `frame_count_invalid:sensor:<name>`, as specified.
- O5 in `realism_augmentor.py`. It works. Prefer `dataclasses.replace(self.config, seed=seed)`, and add
  the `TypeError` for `img=None`.
- `test_rollback_audit.py`. It is STILL an IndentationError at line 18.
- `rq3_rq5_handoff_adapter.py` (O1 partial).

Line endings (repo has `core.autocrlf=false` and no eol rules, so a blob's bytes are the truth):
- HEAD is CRLF for `rq3_capture_contract.py` and `realism_augmentor.py`, and LF for
  `rq3_evidence_gate.py`, `test_rollback_audit.py` and `rq3_rq5_handoff_adapter.py`.
- The working tree flipped the first three wrongly. Restore HEAD's EOL for each file. The only intended
  EOL change is A5 (`realism_augmentor.py` → LF, as in `68868f76`), in its own commit.

Procedure:
1. Copy each semantic hunk aside.
2. `git checkout HEAD -- <file>` (restores bytes; allowed in this worktree because you are the writer).
3. Re-apply each hunk with the original EOL.
4. Commit per task (A0 test fix, O4, O5, C1-addendum, O1). Each commit needs its own failing-first
   regression test in `ultimate_pipeline/tests/unit/`. Scratch scripts in the repo root do not count.

Gate: the bare `pytest --collect-only -q` collects with 0 errors.

**B3 [OC] CHAT-09 `--contract` silent fallback.** In `tools/rq5_contract_audit.py:63-69`,
`audit(repo, contract)` falls back to `DEFAULT_CONTRACT` when an explicit `contract` path does not
exist, so a PASS can describe the wrong file.
- An explicit `contract` that is missing must return `status: "FAIL"` with
  `missing_contract_path` evidence and no fallback.
- The fallback stays only when `contract is None`.
- Tests: an explicit missing path → FAIL; an explicit existing path → audits that file
  (`contract_path` equals it); None → default.
- Source: CHAT-09 author ZIP `reports/IMPLEMENTATION_AND_AUDIT.md` in the v8 package.

**T1 [OC test_triage, read-only] Reproduce production CI locally.** The package recorded Actions
**failure** on production heads (run 37705726382 on `68868f76`) and **0 runs** on the experimental
head. Read `.github/workflows/tests.yml` at `d72f57c6` and list its job steps and the exact pytest
command. Run that pytest command on this branch's HEAD (read-only) and classify each failure as
product, environment (Windows vs Linux) or pre-existing. No installs, no pushes. Report: workflow
steps, the command, counts, and the failure table.

**L1 thresholds note:** the 30° heading and 1.0 m Δz limits in L1 are audit-proposed defaults, not
derived values. Make them named constants in settings. Put the final values in the PR for operator
sign-off. Do not tune them to reduce residuals.

## 4. DISPATCH TEMPLATE (coordinator → implementer)

```
@implementer
TASK <ID>: <title>
Worktree: E:/wt/repair-map-realism-p0-837a8504  Branch: fix/post-pr16-remediation-20261023
Files you may touch: <explicit list>
Spec: <copy the task text from §3 verbatim>
Rules: §1 of the master prompt (paste it in full).
Steps: (1) report HEAD + `git status --porcelain`; (2) write failing tests, run them, paste the
failure; (3) implement; (4) run the gate commands; (5) check EOL/BOM; (6) one commit
"<prefix> (<ID>)"; (7) return the §5 JSON.
```
Then:
```
@reviewer
Review commit <sha> for TASK <ID>, read-only. Re-run the gate yourself; try ≥3 inputs the implementer
did not test; check the diff touches only the allowed files with no EOL churn; check the freeze hashes.
Return {"sha","task","verdict":"APPROVE|REJECT|NOT_RUN","commands":[...],"breaks_found":[...]}.
```
On REJECT, send the findings back to the same implementer for one fix round, then review again. After
2 rejections, mark the task `ESCALATE_CODEX` and write a handoff. On quota or provider errors, follow
the fallback chain in AGENTS.md. If all three fail: `NOT_RUN` with the three error messages.

## 5. REPORT JSON (every implementer and reviewer)

```
{"task":"","agent":"","model":"","baseline_sha":"","new_sha":"","files_changed":[],
 "diff_stat":"","diff_stat_ignoring_eol":"","eol_bom_before_after":{},
 "tests_failing_before":[{"cmd":"","tail":""}],"commands":[{"cmd":"","exit":0,"tail":""}],
 "freeze_hashes":{"rq3":"","rq5":""},"verdict":"DONE|FAIL|BLOCKED|INCOMPLETE","notes":""}
```

## 6. CODEX HANDOFF FILE (for every [CODEX] task)

Write `CODEX_HANDOFF_<ID>_20261023.md` in the repo root, untracked (do not commit). It contains: the
task text from §3, the exact reproduction commands and their output run at current HEAD, the
file:line evidence, constraints (§1), the acceptance tests to write, and open questions for the
operator. Then continue the queue.

## 7. FINAL COORDINATOR OUTPUT

A table with one row per task (A0…L5, D1…D3): status (DONE/APPROVED, REJECTED, ESCALATE_CODEX,
DECISION_PENDING, BLOCKED, NOT_RUN), commit SHA, reviewer verdict, and test counts. Then the branch
HEAD, the freeze hashes, and the D1 full-suite summary line. Then the operator list (D3). Do not write
"complete", "resolved" or "PASS" for anything without an APPROVE plus executed evidence.
