# Codex prompts — remaining hard tasks (2026-10-23)

Run them in order, one at a time (single writer). Each continues on the Claude branch after the C1 fix
round has landed and been reviewed. Do NOT run Codex while a Claude or OpenCode writer is active in
the same worktree.

## Shared preamble (paste at the top of every prompt)

```
Repo lemoniadowyjohn/carla-control-suite, rules in AGENTS.md.
Worktree: E:/wt/claude-hard-tasks-20261023   Branch: fix/claude-hard-tasks-20261023
First report `git rev-parse HEAD`, `git log --oneline 1e902986..HEAD`, `git status --porcelain`.
Abort if the tree is dirty.
Set GIT_LFS_SKIP_SMUDGE=1 for every git command. E: has ~3.5 GB free; never download LFS objects,
never write files >5 MB, never fill the disk (simulate ENOSPC with injected errors only).
Python: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/.venv/Scripts/python.exe ; pytest -p no:cacheprovider.
FORBIDDEN: push, merge, rebase, reset, stash, checkout of other branches, branch deletion, editing
configs/rq3_protocol_freeze_v1.json or configs/rq5_protocol_freeze_v1.json, modifying anything
under reports/, changing map-of-record pins/registry, regenerating or promoting maps, starting CARLA.
Only `git add` / `git commit` are allowed.
Preserve each file's EOL and BOM bytes (core.autocrlf=false; check `file <path>` before and after).
`git diff -w --ignore-cr-at-eol --stat HEAD~1 HEAD` must equal `git diff --stat HEAD~1 HEAD`.
Write the regression tests first and show them FAILING on the pre-fix code (paste the tail), then fix.
Known environment limitation: in this no-LFS worktree ~20 tests in ultimate_pipeline/tests/unit fail
with MapRegistryDriftError / LFS-pointer errors. Classify them as INCOMPLETE (environment) and do not
"fix" them. Never weaken an assertion.
Return: commit SHA, diff stats (plain and EOL-insensitive), failing-first tails, final pytest tails,
residual risks. Never write PASS for a command you did not run.
```

---

## Run order and parallelism (updated)

Codex runs X0 → X1 → X2 → X3 in `E:/wt/claude-hard-tasks-20261023`. It can run IN PARALLEL with
OpenCode (`OPENCODE_REMAINING_PROMPT_20261023.md`), because the two touch disjoint files and separate
worktrees. **Start X0 only after the Claude C1 fix round has committed**: `git status --porcelain` must be
empty and `git log` must show a "G02c" commit on top of `119da123`. If it doesn't, wait and do not touch
the tree.

## X0 — integrate the OpenCode branch snapshot (do this first)

```
[preamble]
FACTS: OpenCode branch experimental/verified-fixes-20261022 @ 1953107d has 10 commits on 1e902986
(O0–O7, O2, C1 addendum). This branch (fix/claude-hard-tasks-20261023) has the Claude C1 commits
(66304b81, 119da123, plus the G02c fix round). `git merge-tree --write-tree 1953107d HEAD` conflicts in
exactly 2 files: ultimate_pipeline/perception/rq3_evidence_gate.py and
ultimate_pipeline/tests/unit/test_rq3_artifact_content_verification.py.
TASK (the merge is explicitly authorised for this task only; this overrides "no merge" in the preamble):
1. `git merge --no-ff 1953107d -m "merge: OpenCode O0-O7 snapshot into Claude C1 branch (X0)"`.
2. Resolve rq3_evidence_gate.py by taking THIS branch's version (Claude C1/G02c is a superset of
   OpenCode's addendum). Then check that every behaviour OpenCode's commits b17b0672 and 1953107d
   intended is still enforced:
   - committed must be a real bool True;
   - missing modality is rejected;
   - empty or missing session_id is rejected when expected_session_id is set.
   Run OpenCode's tests for those (find them with `git show --stat b17b0672 1953107d`). If any fails,
   make the smallest change in rq3_evidence_gate.py that satisfies both test sets. Never delete a test
   from either side.
3. Resolve test_rq3_artifact_content_verification.py by keeping BOTH sides' tests. Use Claude's signed
   receipt fixture. For test_artifact_integrity_checks, keep whichever isolation fix passes, and make
   sure every step's assertion is still present.
4. Verify: pytest -q on test_rq3_review_receipt_binding.py, test_rq3_artifact_content_verification.py,
   every OpenCode test file added in 1e902986..1953107d, test_realism_augmentor_apply.py and
   test_frame_set_intersection.py.
   `git diff --stat 68868f76 HEAD -- submission/ cities/` must be empty (O6/O7 kept).
   EOL check on the two resolved files.
Return the merge SHA, the conflict resolutions (what was taken from which side) and the test tails.
```

## X1 — C5: atomic XODR / report writes, ENOSPC fail-closed (CHAT-03)

```
[preamble]
FACTS (verified):
- ultimate_pipeline/core/file_utils.py:25 write_xodr() calls tree.write(path, ...) directly on the
  target path. A disk-full or interrupted write leaves a TRUNCATED XODR under the final name.
  core/odr_io.save_xodr wraps it; there are 42 save_xodr( call sites.
- `git grep -n ENOSPC -- 'ultimate_pipeline/**/*.py'` is empty.
- Stage 6 (ultimate_pipeline/pipeline_stages/stage_06_links.py) writes the XODR via save_xodr
  (lines ~483, 608, 653) and JSON reports via plain open(...,"w") + json.dump (~245, 343, 581, 707, 724).
- Atomic JSON helpers already exist; reuse one pattern rather than inventing:
  ultimate_pipeline/utils/finalize_run_pack.py:155 _atomic_write_text,
  ultimate_pipeline/tile_validation/step10_tile_qa_worker.py:24 _atomic_write_json.
TASK:
1. Make write_xodr atomic: write to a temp file in the SAME directory (NamedTemporaryFile with
   delete=False, or path + ".tmp-<pid>"), flush, os.fsync, close, then os.replace(tmp, path). Fsync the
   directory where the platform supports it (skip on Windows). On ANY exception, remove the temp file
   and re-raise; the pre-existing target must stay byte-identical. Output bytes for a successful write
   must be IDENTICAL to today's (RQ1 byte-determinism). Prove it by hashing a fixture written by the
   old and the new code.
2. Add ultimate_pipeline/core/atomic_io.py with atomic_write_text / atomic_write_json (same semantics),
   or reuse an existing helper by moving it there. Route Stage 6's JSON report writes through it.
3. Stage 6 must not report success after a failed write: an OSError (incl. errno.ENOSPC) in any stage-6
   write propagates. Under THESIS_STRICT it is never swallowed by a try/except that only prints.
   List every swallowing except you change, with file:line.
4. Stale artifacts: if a stage-6 output path exists from an earlier run and the current run fails before
   replacing it, downstream must not consume it as this run's output. Implement the cheapest correct
   guard: write a run-scoped completion marker (run_id + sha256 of the output) only after a successful
   replace, and make Stage 7's loader check it when THESIS_STRICT is on. Find Stage 7's input path in
   stage_07_lanes.py. If this is more than ~40 lines, implement the marker write only and report the
   consumer side as RESIDUAL.
TESTS (new ultimate_pipeline/tests/unit/test_atomic_xodr_writes.py):
- monkeypatch the write step to raise OSError(errno.ENOSPC) mid-write -> exception propagates, target
  unchanged (byte-compare), no temp files left in the directory.
- successful write bytes == legacy tree.write bytes for the same tree.
- Windows-safe: replacing an existing target works.
- Stage 6 report helper: ENOSPC -> raises, no partial JSON.
Run the existing tests that touch file_utils/odr_io/stage_06 (`git grep -l "write_xodr\|save_xodr\|stage_06" -- '*test*.py'`).
Commit: "fix(io): atomic XODR/report writes; ENOSPC fails closed (C5/CHAT-03)".
```

## X2 — C4: access-metadata enrichment fails closed (CHAT-02)

```
[preamble]
FACTS (verified):
- ultimate_pipeline/pipeline_stages/stage_04_enrichment.py:345-362 and
  stage_09_positional_semantics.py:243-257 wrap apply_access_metadata_from_osm(root, s.OSM_FILE) in
  `except Exception as e: print("⚠️ ... failed"); vreport.add(..., "error", ...)`. The stage continues.
- ultimate_pipeline/enrichment/access_restriction_metadata.py:216 attach_access_metadata():
  `road = road_map.get(road_id); if road is None: continue`. Matches whose xodr_road_id does not exist
  are dropped silently and never counted.
- The metadata is provenance-only (USERDATA_KEY vector); lane/routing behaviour is unchanged
  ("routing_or_lane_behavior_changed": False).
TASK:
1. Distinguish corruption from absence. A legitimate "0 accepted matches" stays a recorded non-failure.
   These are corruption:
   (a) OSM file missing or unreadable;
   (b) a match whose xodr_road_id is not in the XODR;
   (c) a match with empty/non-numeric osm_way_id or empty tags;
   (d) after writing, a USERDATA_KEY vector whose value does not parse back into the expected fields.
   Raise a new AccessMetadataError for each, with counts and examples in the message. Add
   "unresolved_road_ids" and "malformed_matches" counters to the report.
2. In stage 04 and 09: when THESIS_STRICT is on, or the release profile is governed (reuse the
   stage-6 helper `_stage6_governed_containment(settings)` logic, or the existing settings flag used for
   that), AccessMetadataError and FileNotFoundError propagate. In DEVELOPMENT, keep warn-and-continue
   but record status "error" plus the counters. Do not change any other enrichment step in those stages.
3. Stage 09 re-applies "postfreeze": it must not silently produce fewer records than stage 04 for the
   same OSM. If the counts differ, record both counts and raise under THESIS_STRICT.
TESTS (new ultimate_pipeline/tests/unit/test_access_metadata_fail_closed.py), small synthetic
XODR + OSM fixtures:
- unresolved road id -> AccessMetadataError;
- malformed match -> error;
- missing OSM under strict -> raises, under DEVELOPMENT -> recorded error;
- 0 matches -> success with 0 records;
- a valid match round-trips through the userData vector.
Run the existing access-metadata tests (`git grep -l access_restriction_metadata -- '*test*.py'`).
Commit: "fix(enrichment): access metadata fails closed on corruption (C4/CHAT-02)".
```

## X3 — L3-fix: remove the unannounced unconditional laneLink wipe in Stage 7

```
[preamble]
FACTS (verified, measured on a real run):
- Production stage_07_lanes.py runs BOTH:
  - ~line 274-284: repair_outer_to_inner_mispaired_lane_links (GAP-026, commit 2a886117, reviewed).
    It changes a connection only when that strictly reduces failing links, and never replaces a
    non-empty set with an empty one.
  - ~line 405-425: LaneLinkBuilder.regenerate_lane_links(root). This DELETES every junction laneLink and
    rebuilds them inner-first, which undoes the GAP-026 result.
- The second call was added by commit 0c08412f, whose title ("P0-B orphan_road_repair + P0-D
  structure_elevation_repair source modules") does not mention it. It was never reviewed.
- Measured on reports/rq1_trial_runs/run_01/20261007_214826_524342/06_continuity_*.xodr (main checkout,
  read-only): 722/22,588 connections changed, 822 laneLinks swapped, 389 incoming lanes lost all links.
  Typical example: netconvert's 2-lane incoming road feeding a 1-lane connector via the OUTER lane (-2)
  is reassigned to the INNER lane (-1), e.g. J1/C3 42284->51811 {(-2,-1)} -> {(-1,-1)}.
TASK:
1. Read `git show 0c08412f -- ultimate_pipeline/pipeline_stages/stage_07_lanes.py` and
   `git log --oneline -- ultimate_pipeline/lanes/lanelink_builder.py`. Confirm the facts.
2. Remove the unconditional regenerate_lane_links call from Stage 7. Keep the GAP-026 conditional
   remap and the downstream infer_lane_successors_from_topology unchanged. If the stated purpose of
   0c08412f ("infer_lane_successors_from_topology sees fully populated junction laneLinks") needs
   connections that have ZERO laneLinks to be filled, call LaneLinkBuilder ONLY for connections with
   zero driving laneLinks, never touching a connection that already has links. Implement that as a new
   function in lanelink_builder.py, e.g. fill_missing_lane_links(root), with its own failure report.
3. Do NOT change GAP-026 or GAP-048 policies or tolerances. Do not modify any XODR on disk.
TESTS (new ultimate_pipeline/tests/unit/test_stage7_preserves_lanelinks.py):
- a synthetic junction where the incoming outer lane (-2) is linked to a 1-lane connector: after the
  Stage-7 lane-link step the link is still (-2,-1). This must FAIL on the current code; show it.
- a connection with zero laneLinks gets filled.
- a connection with existing links is byte-identical after the step.
Then, read-only, re-run the measurement: load 06_continuity_*.xodr (main checkout path above) in
memory, apply the new Stage-7 lane-link logic, and report how many connections changed (expected: only
zero-link ones). Do not save the XODR.
Commit: "fix(lanes): stop unconditional laneLink wipe in Stage 7; fill only empty connections (L3)".
```

---

## Not for Codex (operator decisions, already documented)

- **L4 (OSM identity):** proven feasible. `netconvert --osm-files X --opendrive-output Y --output.original-names true`
  (SUMO 1.24.0 at `C:\Sumo\sumo-win64extra-1.24.0\sumo-1.24.0\bin\netconvert.exe`) writes
  `<userData code="sumoId" value="<osm_way_id>"/>` per road (negative = reverse direction). Today the
  pipeline converts with CARLA `Osm2Odr` (`ultimate_pipeline/osm/osm_to_xodr_wrapper.py:254`), which
  loses the IDs, and netconvert only repairs XODR->XODR (`topology/sumo_repair.py:49`). Switching the
  converter changes every generated map, so it needs an operator decision plus a governed regeneration.
- **C2** (expected-counts source), **L5**, and the 16.6 MB dump: operator decisions.
