# OpenCode task plan — 2026-11-04

Paste the **COORDINATOR** block below, followed by ONE task block, into an OpenCode session running
the default **build** agent. Run the tasks one at a time, in order: **X7b → O8 → O9 → O10 → O11**.
X7b uses the X7 worktree; O8–O11 use the integration worktree. Never run two at once (single writer).
Each task ends with a reviewer APPROVE; after each one, paste the result to Claude for verification.

Selection rule: small, fully specified, and not blocked by disk, CARLA or an operator decision.
Investigation-heavy work (X8 regeneration, X9 stubs) stays with Codex.

---

## COORDINATOR (paste first, every time)

```
You are the OpenCode coordinator under AGENTS.md. Never write code yourself: dispatch exactly ONE
@implementer, then ONE @reviewer (on quota/provider errors: reviewer -> reviewer_alt -> reviewer_alt2;
if all three fail, report NOT_RUN). Never write COMPLETE or PASS without a commit SHA, pasted test
output and a reviewer APPROVE.
RULES FOR EVERY SUBAGENT
- Verify the task's worktree, branch and starting HEAD first (`git rev-parse --short HEAD`,
  `git status --porcelain`). Abort if they differ or a tracked file is modified. Leave pre-existing
  untracked files alone (D1_full_suite_output.txt, EXPERIMENTAL_BRANCH_PR_READINESS.md,
  run_identity.json, ultimate_pipeline_out/).
- Python: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/.venv/Scripts/python.exe
- DISK IS NEARLY FULL ON C:. Before any python, set TMP and TEMP to E:\wt\_oc\systmp (mkdir -p).
  Always run pytest as: python -m pytest -p no:cacheprovider --basetemp=E:/wt/_oc/bt ...
  Delete E:/wt/_oc when finished. Run only the focused test files named in the task, never the full
  suite. Set GIT_LFS_SKIP_SMUDGE=1.
- FORBIDDEN:
  - push, merge, rebase, reset, stash, checkout/switch, branch deletion;
  - editing configs/*protocol_freeze*.json;
  - modifying or deleting ANY existing file under reports/ (you may only ADD new files where the
    task says so);
  - touching any .xodr; changing map pins or the registry;
  - starting CARLA;
  - raising a tolerance or threshold; removing, loosening or skipping an assertion.
- Only `git add <explicit paths>` + ONE commit per task. Preserve EOL/BOM (check `file <path>` before
  and after; `git diff -w --ignore-cr-at-eol --stat` must equal `git diff --stat`).
- When the task changes behaviour, write the test first and paste its FAILING output, then the fix,
  then the passing output.
- Commit messages end with the model name.
REVIEWER (read-only, no edits, no git writes): re-run the task's tests yourself; check that only the
allowed files changed with no EOL churn; diff against the starting HEAD and confirm no assertion was
weakened; try >= 2 inputs the implementer did not test. Return APPROVE or REJECT with commands and output.
FINAL OUTPUT: task id, commit SHA, reviewer verdict, test counts, files changed.
```

---

## X7b — fix the two snap tests X7 broke (do this first)

The full task text is in `NEXT_PROMPTS_X7B_X8_X9_20261104.md` (the "X7b — OpenCode" block). In short:
- Worktree `E:/wt/fix-gap070-connector-snap-exit-20261103`, branch `fix/gap070-connector-snap-exit-20261103`,
  HEAD `03aaccd4`. Tests only.
- Add an exit road plus the link that declares it to the fixtures of
  `test_snap_classifies_unambiguous_displaced_inferred_and_snaps` and
  `test_snap_allows_ambiguous_when_opted_in` in `tests/unit/test_junction_connector_classifier.py`.
  Keep every assertion.
- Add `test_snap_skips_connector_without_exit_anchor`: snapped 0, `skipped_missing_exit_anchor` 1,
  planView byte-identical.
- Run the 3 snap test files: `tests/unit/test_junction_connector_classifier.py`,
  `tests/unit/test_stage05_connector_snap_wiring.py`,
  `ultimate_pipeline/tests/unit/test_junction_connector_snap.py`. Before: 2 failed. After: all pass.
- Commit: `test(gap070): classifier fixtures declare the exit road required by the X7 snap`.

---

## O8 — guard: every `ValidationReport.add()` call passes the level first

```
TASK O8. Worktree E:/wt/repair-map-realism-p0-837a8504, branch integration/post-pr16-final-20261102,
starting HEAD 46708baa.
Files you may touch: ONE new test file, tests/unit/test_validation_report_call_order.py.
CONTEXT: ValidationReport.add(self, level, stage, message)
(ultimate_pipeline/core/validation_report.py:90) files an entry under errors/skipped/success only
when level is one of those words; anything else goes to warnings. Commit 56efb2cb fixed 26 call sites
in ultimate_pipeline/pipeline_stages/ that passed (stage, level, message). Nothing stops the mistake
from coming back.
TEST: walk every .py file under ultimate_pipeline/ (skip tests/ dirs) with `ast`. For every call whose
func is an Attribute named `add` on a receiver ending in `vreport` (self.vreport.add, vreport.add):
- the first positional argument must be a string Constant in {"error", "warning", "success",
  "skipped"};
- report file:line for every violation.
Calls whose first argument is not a constant (a variable) must be listed explicitly in an ALLOWLIST
in the test with a one-line reason each. Start with an empty allowlist and add only what you actually
find, verifying each one by reading the code.
Also assert the test finds at least 20 vreport.add calls (guards against the walker silently matching
nothing).
FAILING FIRST: run the new test against 56efb2cb~1 by writing a tiny throwaway script under
E:\wt\_oc that runs the same check over `git show 56efb2cb~1:<path>` sources. Show it reports the 26
reversed calls. Do not check out anything.
Commit: "test(report): guard level-first ValidationReport.add() calls".
```

---

## O9 — stop a test writing `run_identity.json` into the repository root

```
TASK O9. Worktree E:/wt/repair-map-realism-p0-837a8504, branch integration/post-pr16-final-20261102,
starting HEAD = O8's commit.
Files you may touch: the ONE test file that is the culprit (and, only if unavoidable, a conftest.py
fixture). No product code.
CONTEXT: ultimate_pipeline/core/terminal_authority.py:109-122 writes run_identity.json into the
out_dir it is given. A file with "out_dir": "." keeps appearing in the repository root after test runs
(see the untracked run_identity.json in this worktree; do NOT delete it, it is pre-existing). Some test
passes out_dir="." or relies on the current directory.
STEPS:
1. Find the culprit. `git grep -n "write_run_identity\|run_identity" -- 'tests/*.py'
   'ultimate_pipeline/tests/*.py'` (start with tests/adversarial/test_terminal_authority.py). Confirm
   it by running candidate test files from a scratch cwd, e.g. `cd E:/wt/_oc/cwdprobe && python -m
   pytest <abs path>`, and checking whether run_identity.json appears in that cwd. Paste the evidence.
2. Fix the test to use tmp_path (or monkeypatch.chdir(tmp_path)) so nothing is written outside
   pytest's temp dir. Keep all assertions.
3. Add a regression assertion in that test file that the cwd contains no run_identity.json after the
   test (compare before and after).
4. Show the file appears in the probe cwd before the fix and does not after.
Commit: "test(terminal-authority): keep run_identity.json inside tmp_path".
```

---

## O10 — gap-register addendum 2 (status updates with evidence; new file only)

```
TASK O10. Worktree E:/wt/repair-map-realism-p0-837a8504, branch integration/post-pr16-final-20261102,
starting HEAD = O9's commit.
Files you may touch: NEW files only, under
reports/production_readiness/20261104T000000Z_GAP_REGISTER_ADDENDUM_2/
(GAP_REGISTER_ADDENDUM_2.json + .md). Do NOT edit the existing addendum (20261103T000000Z_...).
CONTEXT: read reports/production_readiness/20261103T000000Z_GAP_REGISTER_ADDENDUM/GAP_REGISTER_ADDENDUM.json
for the schema and status vocabulary (fixed / open / blocked_external), and the GAP-070 files in that
directory and in reports/production_readiness/20261103T000000Z_GAP070_STAGE_BISECTION/
(README.md, ROOT_CAUSE_JUNCTION_CONNECTOR_SNAP.md).
WRITE status-update entries (verify every SHA with `git cat-file -e <sha>` and read each diff before
citing it; never mark something fixed without the fixing SHA):
- GAP-075 (ValidationReport.add order): open -> fixed by 56efb2cb (26 call sites) plus O8's guard
  test SHA.
- The carla offline-stub residual noted under the conftest/test_batch1 entry: fixed by 6885dfc2
  (require_real_carla). Find its GAP id in the addendum.
- GAP-070 update: root cause = default-on junction connector snap
  (tools/junction_connector_snap.py, called from stage_05_geometry.py), reproduced in memory
  (kinks 351 -> 3,720; ~53 deg 4 -> 3,373; 4,025 snapped). Evidence: 46708baa
  ROOT_CAUSE_JUNCTION_CONNECTOR_SNAP.md.
  Remediation candidate: branch fix/gap070-connector-snap-exit-20261103 (X7, 03aaccd4 + X7b SHA);
  measured entry start mismatches 4,092 -> 67, exit kinks 351 -> 349. Status stays OPEN until a
  governed regeneration (X8) is done.
- NEW id (next free after GAP-078): ~0.1 m reversed connector stubs (170-180 deg bucket: 90 at
  01_sanitized, 111 from 02_sumo_fixed on); separate from the snap; status open; next step X9.
- GAP-076 (OSM identity) and GAP-077 (CARLA hang): unchanged; add a one-line "still open, owner:
  operator" note.
Validate that the JSON parses and that per-status counts match.
Commit: "docs(gap-register): addendum 2 — status updates 2026-11-04".
```

---

## O11 — usage doc for the RQ3 crop tool (docs only)

```
TASK O11. Worktree E:/wt/repair-map-realism-p0-837a8504, branch integration/post-pr16-final-20261102,
starting HEAD = O10's commit.
Files you may touch: ONE new file, docs/research/RQ3_AUTO_MAP_CROP_TOOL.md.
Read tools/rq3_crop_auto_to_manual_footprint.py and ultimate_pipeline/domain_gap/footprint_crop.py
(docstrings and argparse) and write a short usage doc covering:
- purpose: a same-place auto-map counterpart of Grid0828 for RQ3 paired capture;
- inputs, resolved ONLY via map_registry (auto_map_of_record, manual_grid0828);
- the CLI flags and their safety refusals (no out-dir inside campaigns/ or on pinned paths; non-empty
  dir needs --overwrite-scratch);
- the selection rules (any_point vs centroid, buffer_m; hull boundary points are excluded);
- junction closure, link pruning, controller preservation, top-level accounting;
- the manifest fields and the 7 hard checks (status PASS only if all pass).
Include the verified real-map result: 3,584 roads, 450 junctions, sha256 b2bc2712…, 0 dangling
references, covers 100% of Grid0828, 93% of road length inside the hull. Note that one 4.48 km road
(49556) is kept whole, and that CARLA load is NOT yet verified.
Run the docs/link checks the repo has, if any (grep tests for "docs/research"), and
ultimate_pipeline/tests/unit/test_footprint_crop.py to confirm nothing breaks.
Commit: "docs(rq3): usage notes for the auto-map footprint crop tool".
```

---

## Not for OpenCode (and why)

| Item | Why not |
|---|---|
| X8 governed regeneration | Codex-sized; needs ≥ 15 GB free, so blocked on disk |
| X9 netconvert stubs | investigation-heavy; Codex |
| X5 / X6 | need explicit operator approval first |
| CARLA pilot | only the operator or main agent may start CARLA; currently hangs at the RPC handshake |
| Deleting the old copies on G | operator decision (deletion) |
| Merging the production PR | operator (GitHub web UI) |
