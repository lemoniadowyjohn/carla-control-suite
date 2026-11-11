# Blocker-resolution prompts — 2026-10-23

> **STATUS CHANGE 2026-10-23 14:31:** PR #16 was merged into
> `origin/integration/production-large-map-20260918` = `d72f57c6`, from `5a004113`, i.e. WITHOUT
> G01/G02/G03/G05. Production now has the G01/G02 false-pass (reproduced: terminal=FAILED +
> fabricated digests + bare "APPROVED" -> EXPERIMENTAL_EVIDENCE_AUTHORITATIVE), the hardcoded
> `E:\wt` APPROVED_ROOT, the relaxed G03 rule, the deleted DEM/buildings inputs, the 3
> submission-mirror edits and the 16.6 MB dump. Freeze files ARE on production now (G06 is done by
> the merge, so 502dda26 is redundant). The follow-up PR base is now **d72f57c6**.
> `git merge-tree d72f57c6 1e902986` merges cleanly.

Source: Claude independent audit of `experimental/verified-fixes-20261022` @ `1e902986`
vs base `68868f76` (verdict FAIL / REQUEST_CHANGES, 2026-10-23T11:56:42Z).

Run order is strictly serial (single-writer policy). Every writer task works in
the SAME worktree `E:/wt/repair-map-realism-p0-837a8504` on branch
`experimental/verified-fixes-20261022`, one commit per task, and stops after it.
Before you dispatch the next writer, run the reviewer prompt (R) on that commit.

| # | Task | Agent | Why there |
|---|------|-------|-----------|
| O1 | G05 residual hardcoded paths | OpenCode `implementer` | mechanical |
| O2 | Fix pre-existing `test_artifact_integrity_checks` fixture | OpenCode `implementer` | mechanical |
| O3 | Revert LF→CRLF churn in `realism_augmentor.py` | OpenCode `implementer` | mechanical |
| O4 | G03 strict type coercion | OpenCode `implementer` | small, fully specified |
| O5 | G04 `apply()` honours instance config | OpenCode `implementer` | small, fully specified |
| C1 | G02 review-receipt binding redesign | **Codex** | design + adversarial security reasoning |
| C2 | Wire G03 into a production path | **Codex** | investigation-heavy call-path tracing |
| C3 | G06 integration-branch reconciliation (read-only plan) | **Codex** | git-history surgery, high blast radius |
| R  | Review after each writer commit | OpenCode `reviewer` (→`_alt`→`_alt2`) | independent of `big-pickle` |

Not delegable (operator only): pushing, creating/merging the PR, CARLA runs,
H: unlock, storage/VRAM, external sign-off, upstream CARLA/UE4 builds, v8.3 ZIP.

---

## Shared preamble (paste at the top of EVERY prompt)

```
You are working under AGENTS.md in repo lemoniadowyjohn/carla-control-suite.
Worktree: E:/wt/repair-map-realism-p0-837a8504
Branch: experimental/verified-fixes-20261022 (verify `git rev-parse HEAD` first and
report it; abort if the branch is not checked out or the tree has tracked
modifications).
Python: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/.venv/Scripts/python.exe
Always run pytest with `-p no:cacheprovider`.

HARD RULES
- You are the ONLY writer. Do not touch files outside the task's file list.
- Do NOT push, force-push, reset, rebase, merge, stash, checkout another branch,
  delete branches, or start CARLA.
- Do NOT modify configs/rq3_protocol_freeze_v1.json or
  configs/rq5_protocol_freeze_v1.json, and do not modify commit 9e777a27 or anything in reports/.
- Preserve each file's existing line endings and BOM (check with `file <path>`
  before and after; the diff must show no whole-file churn).
- One commit, message prefix given in the task, ending with your model name.
- No PASS without executed commands. Paste the exact commands and the last 15
  lines of their output. If a test fails, report FAIL and stop. Do not weaken
  the test to make it pass.

REPORT FORMAT (return only this):
{ "task": "...", "baseline_sha": "...", "new_sha": "...",
  "files_changed": [...], "git_diff_stat": "...",
  "line_endings_before_after": {...},
  "commands": [{"cmd": "...", "tail": "..."}],
  "verdict": "DONE|FAIL|BLOCKED", "notes": "..." }
```

---

## O1 — G05 residual hardcoded paths (OpenCode implementer)

```
TASK O1. Commit prefix: "fix(rq3): G05b -"
The audit found that "E:/wt/repair-map-realism-p0-837a8504" is still hardcoded in:
  - ultimate_pipeline/perception/rq3_rq5_handoff_adapter.py:256 (an open(..., "w") WRITE)
  - ultimate_pipeline/tests/unit/test_experiment_manifest_negative_controls.py
  - ultimate_pipeline/tests/unit/test_rollback_audit.py
Find every occurrence: `git grep -n "repair-map-realism-p0-837a8504" -- '*.py'`.

Fix:
1. In the adapter, replace the literal with
   `resolve_approved_root() / "reports" / "phase5_deliverables" / "RQ3_TO_RQ5_HANDOFF_CONTRACT.json"`
   imported from ultimate_pipeline.perception.rq3_evidence_gate. If the function
   that writes is called from tests, add an optional `out_path` parameter that
   defaults to that value so tests can write to tmp_path, never into reports/.
2. In the two tests, derive the root as
   `Path(os.environ.get("RQ3_TEST_ROOT") or Path(__file__).resolve().parents[3])`,
   the same pattern as test_rq3_artifact_content_verification.py.
3. Add one regression test asserting that `git grep`-style scanning of those 3
   files finds no "E:/wt" or "E:\\wt" literal (read the files with pathlib).

Verify:
  git grep -n "repair-map-realism-p0-837a8504" -- '*.py'   (must be empty, except the new regression test's assertion string)
  pytest -q <the 3 touched test files + test_rq3_artifact_content_verification.py>
  git status --short reports/   (must be empty: nothing was written into reports/)
```

## O2 — Pre-existing integrity-test fixture bug (OpenCode implementer)

```
TASK O2. Commit prefix: "fix(rq3-tests): integrity fixture -"
ultimate_pipeline/tests/unit/test_rq3_artifact_content_verification.py::test_artifact_integrity_checks
fails with FileNotFoundError: it hashes `ROOT / name`, but the files live at
`ROOT / "reports/phase5_deliverables" / name` (=`DELIV / name`). The artifact
"path" field already says reports/phase5_deliverables/<name>.

Fix ONLY the test: every `_sha(ROOT / name)` and `_sha(ROOT / "RQ3_PATCH_MANIFEST.json")`
becomes `_sha(DELIV / ...)`. Do not change rq3_evidence_gate.py. Do not change
the assertions.
First confirm the 3 files are tracked: `git ls-files reports/phase5_deliverables/RQ3_PATCH_MANIFEST.json
reports/phase5_deliverables/RQ3_BUILDER_FALSE_PASS_REMEDIATION.json
reports/phase5_deliverables/RQ3_CROSS_ARM_23_TEST_RECEIPT.json`. If any is missing,
report BLOCKED. Do not create them.

Verify: pytest -q ultimate_pipeline/tests/unit/test_rq3_artifact_content_verification.py
  -> expected 6 passed, 0 failed.
Then the 4-module command:
  pytest -q ultimate_pipeline/tests/unit/test_rq3_builder_false_pass_regression.py
    ultimate_pipeline/tests/unit/test_rq3_paired_capture_contract.py
    ultimate_pipeline/tests/unit/test_rq3_frame_set.py
    ultimate_pipeline/tests/unit/test_rq3_artifact_content_verification.py
  -> expected 71 passed, 0 failed (audit baseline was 70 passed / 1 failed).
```

## O3 — Revert line-ending churn (OpenCode implementer)

```
TASK O3. Commit prefix: "chore(augmentation): restore LF line endings -"
Commit 5a004113 converted ultimate_pipeline/augmentation/realism_augmentor.py
from LF to CRLF (295/295-line diff). The only real change is `pass` ->
`return RealismAugmentor(AugmentationConfig(seed=seed)).apply_random(img)`.

Restore the base encoding (UTF-8 with BOM, LF) while keeping that one change.
  git show 68868f76:ultimate_pipeline/augmentation/realism_augmentor.py | file -   (expect: BOM, no CRLF)
Convert CRLF->LF on the current file only (python: read bytes, replace b"\r\n" with b"\n", write bytes).
Check .gitattributes for an eol rule that would re-convert the file. Report it, but do not edit it.

Verify:
  git diff -w --ignore-cr-at-eol 68868f76 HEAD -- ultimate_pipeline/augmentation/realism_augmentor.py  (only the apply() hunk)
  git diff --stat 68868f76 HEAD -- ultimate_pipeline/augmentation/realism_augmentor.py  (~1 insertion / 1 deletion)
  pytest -q ultimate_pipeline/tests/unit/test_realism_augmentor_apply.py
```

## O4 — G03 strict type coercion (OpenCode implementer)

```
TASK O4. Commit prefix: "fix(rq3): G03b -"
In ultimate_pipeline/perception/rq3_capture_contract.py::_validate_frame_set_consistency
the audit proved that int() coercion accepts bad expectations:
  expected 5.9 vs actual 5 -> valid ; expected True vs actual 1 -> valid ;
  expected 0 vs actual 0 -> valid (zero-frame capture accepted).
Replace the int() coercion with strict checks:
  - expected value must be `type(v) is int` (rejects bool, float, str) and > 0;
    otherwise append "expected_count_invalid:sensor:<name>".
  - actual value must be `type(v) is int` and >= 0; otherwise "frame_count_invalid:sensor:<name>".
Keep all existing error codes and behaviour otherwise.
Add tests to ultimate_pipeline/tests/unit/test_rq3_paired_capture_contract.py:
  5.9, True, "5", 0, -1 as expectations -> invalid; an exact int match -> still valid.
First show that each new negative test FAILS against the current code (run it
before editing the source and paste the output), then implement, then show that it passes.

Verify: the 4-module command from O2, plus test_frame_set_intersection.py.
```

## O5 — G04 apply() honours instance config (OpenCode implementer)

```
TASK O5. Commit prefix: "fix(augmentation): G04b -"
RealismAugmentor.apply(self, img, seed) currently builds a fresh
RealismAugmentor(AugmentationConfig(seed=seed)), so it silently discards the
instance's prob_*, ranges and external_hook.
Change it to `dataclasses.replace(self.config, seed=seed)`. If seed is None,
use self.config unchanged. Keep it deterministic per seed. Do not seed global RNGs.
Also reject img=None with a clear TypeError instead of an AttributeError deep inside.
Tests (ultimate_pipeline/tests/unit/test_realism_augmentor_apply.py):
  - an instance with all prob_*=0.0 -> apply(img, 42) returns an array equal to img
    (this FAILS on current code; show that first);
  - same seed -> same output; different seed -> different output (default config);
  - apply(None, 1) raises TypeError.
Preserve the file's line endings as left by O3.
Verify: pytest -q ultimate_pipeline/tests/unit/test_realism_augmentor_apply.py
```

---

## C1 — G02 review-receipt binding redesign (Codex, high effort)

```
[shared preamble]
TASK C1. Commit prefix: "fix(rq3): G02b -"
CONFIRMED BYPASS (Claude audit, reproducible): evaluate_strict_evidence in
ultimate_pipeline/perception/rq3_evidence_gate.py admits authoritative evidence when
  (a) review_receipt_sha256 = sha256 of an RGB capture frame (no receipt exists);
  (b) review/dataset/capture digests = the rgb/semantic/lidar member frames, content_index=None;
  (c) the "receipt" file's content is {"review":"REJECTED"}.
Root cause: lines ~315-321 only check that the digest equals SOME verified
member's sha256. Role, content, verdict and reviewer identity are never checked.

Step 1 (read-only, report before editing): find the existing receipt schemas in
the repo (git grep -n "review_receipt\|INDEPENDENT_REVIEW\|receipt_schema" and
reports/phase5_deliverables/*REVIEW*). Report the field names a real
independent-review receipt carries today. If none exists, say so and propose a
minimal schema. Do NOT invent provenance for existing files.

Step 2 (implement, minimal):
  - A review receipt must be supplied as a dedicated artifact with role
    "review_receipt", which is excluded from capture modalities and must not
    share a digest with any capture member, dataset_content or capture_receipt.
  - Its bytes must parse as JSON with verdict == "APPROVED", a reviewer identity
    field that differs from the capture/implementer identity field, and a reviewed SHA
    that equals the dataset_content_sha256 (or the implementation SHA, per the
    schema found in step 1).
  - dataset_content_sha256, capture_receipt_sha256 and review_receipt_sha256 must be
    pairwise distinct and must not equal any rgb/semantic/lidar member digest.
  - Fail closed with distinct reason codes for each case.
Step 3: add the three bypasses (a)(b)(c) as regression tests in
test_rq3_artifact_content_verification.py. Show them FAILING on the current code
first, then passing. Keep a fully valid control that is still admitted.
Step 4: run the 4-module command from O2 and report exact counts.
Out of scope: signature/crypto verification (note it as residual risk).
```

## C2 — Wire G03 into a production path (Codex, medium/high)

```
[shared preamble]
TASK C2. Read-only investigation first. Edit only if Step 1 finds a single obvious owner.
_validate_frame_set_consistency (rq3_capture_contract.py) has ZERO non-test callers
(`git grep -n _validate_frame_set_consistency`). The G03 strictness therefore
protects no runtime path.
Step 1: trace the strict-RQ3 capture flow (the --strict-rq3 entrypoint wired in
commit 2c3a5d86; capture_transaction, rq3_frame_set, rq3_rq5_handoff_adapter,
evaluate_frame_completeness). Report the exact function where per-sensor frame
counts are judged complete today, with file:line, and whether it has its own
(possibly relaxed) count logic. Also report where expected counts could come from
(frozen protocol? capture plan?). Do NOT read the expected values from
configs/rq3_protocol_freeze_v1.json unless that file already defines them; never edit it.
Step 2: if there is one clear call site, route it through
_validate_frame_set_consistency with explicit expected_counts, plus a test proving
that a truncated capture (3/5 frames) now fails the strict path. If ownership is
ambiguous or expected counts have no authoritative source, STOP and return
BLOCKED with the call-path map. Do not guess.
```

## C3 — G06 integration-branch reconciliation (Codex, READ-ONLY plan)

```
[shared preamble, except: this task is READ-ONLY. No commits, no branch edits.]
TASK C3. Produce a reconciliation plan only.
Facts from the audit:
  - origin/integration/production-large-map-20260918 = 68868f76 (no rq3 freeze; has rq5 freeze db7155fe…)
  - LOCAL integration/production-large-map-20260918 = 502dda26, parent 65eb0f14,
    which is 273 commits BEHIND 68868f76; 68868f76 is NOT an ancestor of 502dda26.
    502dda26's tree has the rq3 freeze (5aa8ae24…98bd) but NO rq5 freeze.
  - head 1e902986 already contains the rq3 freeze byte-identically (via 9e777a27),
    so merging the PR would deliver it to the base anyway.
  - base..head = 97 commits / 1036 files, not 6/12. 19a48fb0 is not in head
    (head has 5a004113, same subject, different patch-id).
Verify each fact with git commands and paste the outputs.
Then answer:
  1. Is 502dda26 needed at all, given the PR carries the freeze? (Expected: no.)
  2. Safe disposal of the stale local branch without losing 502dda26: tag it
     (e.g. archive/502dda26-stale-proto-20261022), then the operator runs
     `git branch -f integration/production-large-map-20260918 origin/integration/production-large-map-20260918`.
     List the exact commands. Do NOT execute them.
  3. Does 5a004113 differ semantically from 19a48fb0? Show `git range-diff` or a diff of
     the two patches and classify the differences.
  4. Does 1e902986 merge cleanly into 68868f76? Use
     `git merge-tree --write-tree 68868f76 1e902986` (does not touch the worktree). List conflicts.
  5. Whether the 6 RQ3 fix commits can be cherry-picked onto 68868f76 alone.
     Expected: no, rq3_evidence_gate.py does not exist at 68868f76. Prove it with
     `git ls-tree 68868f76 -- ultimate_pipeline/perception/rq3_evidence_gate.py`.
Return the plan as JSON: facts[], answers[], operator_commands[], risks[].
```

---

## R — Reviewer after each writer commit (OpenCode reviewer → reviewer_alt → reviewer_alt2)

```
You are a READ-ONLY adversarial reviewer under AGENTS.md. Do not edit, commit or push.
Worktree E:/wt/repair-map-realism-p0-837a8504. Review commit <NEW_SHA> (task <ID>).
1. `git show --stat <NEW_SHA>`: confirm only the task's files changed and there is
   no line-ending churn (`git diff -w --ignore-cr-at-eol <NEW_SHA>~1 <NEW_SHA> --stat`
   must equal the plain stat).
2. Re-run the task's verification commands yourself. Never copy the implementer's counts.
3. Try to break the fix with at least 3 inputs the implementer did not test.
4. Confirm that the freeze hashes are unchanged:
   git show <NEW_SHA>:configs/rq3_protocol_freeze_v1.json | sha256sum  -> 5aa8ae24…98bd
   git show <NEW_SHA>:configs/rq5_protocol_freeze_v1.json | sha256sum  -> db7155fe…cb8d
Return {"sha","verdict":"APPROVE|REJECT|NOT_RUN","commands":[...],"breaks_found":[...]}.
On quota or provider errors, the dispatcher moves to the next fallback agent. If all 3 fail, report NOT_RUN.
```

---

## Addendum (second audit pass, 2026-10-23): fixes found in the wider 97-commit PR

### O0 — BEFORE you commit anything: repair the in-progress writer state (OpenCode implementer)

```
[shared preamble]
TASK O0. The worktree has UNCOMMITTED edits from an in-progress run:
  M realism_augmentor.py, rq3_capture_contract.py (1966-line diff), rq3_rq5_handoff_adapter.py (523-line diff),
  test_rollback_audit.py, plus untracked fix_*.py / test_o4.py helper scripts.
Problems the audit measured on those edits:
  (1) test_rollback_audit.py line 18 raises IndentationError. That aborts collection of ALL 8246 tests
      (bare `pytest` -> "Interrupted: 1 error during collection").
  (2) rq3_capture_contract.py and rq3_rq5_handoff_adapter.py show whole-file line-ending churn.
Fix both before committing. Line endings must match HEAD (`git show HEAD:<f> | file -`).
`git diff -w --ignore-cr-at-eol --stat` must equal `git diff --stat`.
Do not commit the fix_*.py / test_o4.py helper scripts. Delete them only after reporting their contents.
Verify: the bare `pytest -p no:cacheprovider -q` must at least COLLECT (paste the "collected N items" line and the final summary).
```

### O6 — Restore deleted pinned source inputs (OpenCode implementer)

```
[shared preamble]
TASK O6. Commit prefix: "fix(inputs): restore source inputs deleted by f0c83285 -"
Commit f0c83285 ("P0-E: enforce origin-anchored CRS ...") also deleted, unrelated to its subject:
  cities/ingolstadt/dem/dem_ing.tif        (1,711,684 bytes at 68868f76)
  cities/ingolstadt/osm/buildings.geojson  (3,862,929 bytes at 68868f76)
Both are still referenced at head by scripts/regen_map_of_record.py:340,
scripts/measure_candidate_acceptance.py:57, ultimate_pipeline/config/settings.py:828 (DEM_FILENAME),
campaigns/ingolstadt_cooked_perception_v1/source/INPUTS_MANIFEST.json:23, and phase_f* tools.
Restore them byte-identically: `git checkout 68868f76 -- <both paths>`.
Verify: `git hash-object <f>` equals `git rev-parse 68868f76:<f>` for both; `git diff --stat 68868f76 HEAD -- cities/` is empty.
If a manifest records a sha256 for either file, check that it matches and report the result.
```

### O7 — Revert unauthorized submission-mirror edits (OpenCode implementer)

```
[shared preamble]
TASK O7. Commit prefix: "revert(submission): restore non-critical mirror files -"
Policy: never sync into submission/infrastructure/ except the 6 CRITICAL_MIRRORED_FILES
(tests/phase_q/test_duplicate_module_drift.py). Commit f34a12e6 modified 3 files, NONE of which are on that list:
  submission/infrastructure/ultimate_pipeline/core/validation_report.py
  submission/infrastructure/ultimate_pipeline/main_pipeline.py
  submission/infrastructure/ultimate_pipeline/quality/pipeline_health_summary.py
`git checkout 68868f76 -- <those 3>`. Do not touch ultimate_pipeline/ (the live copies keep f34a12e6's changes).
Verify: `git diff --stat 68868f76 HEAD -- submission/` is empty; pytest -q tests/phase_q/test_duplicate_module_drift.py passes.
```

### C1 addendum — fail-open defaults in verify_artifact_set (add to the Codex C1 task)

```
Also fix, with tests that fail first, in rq3_evidence_gate.verify_artifact_set (all reproduced by the audit):
  - a member with NO "modality" field is silently counted as "rgb" (default "rgb") -> must be rejected;
  - a member with NO "committed" field is treated as committed (default True) -> must be rejected;
  - with expected_session_id="S1", a member whose session_id is "" or missing skips the stale-session
    check -> must be rejected.
Reproduction: 3 members, the first without modality/committed -> verify_artifact_set returns (True, []).
```

### Operator decision — oversize regenerable dumps in the PR

New in this PR, over the repo's own `files <= 5MB` evidence policy (c69b60d2):
`stage8_rca_output/p0_before_gate_sweep/lane_count_changes.json` (16,610,443 bytes, the only file over 5 MiB;
`elevation_seam_report.json` is 5,171,705 bytes, just under 5 MiB but over 5 MB). They are regenerable debug output and embed
`E:\wt\...` absolute paths. They are new files, not historical artifacts, so removing them before
merge does not break the no-overwrite rule. Your call: drop them, or record a size waiver.

### Still INCOMPLETE — full suite on a CLEAN 1e902986

The audit's bare-pytest run measured the dirty worktree, not the commit. A clean full-suite result
for the PR head does not exist yet. Get one from CI after the push, or from a separate clean worktree
once disk space allows (C: 1.4 GB free, E: 4.1 GB free).

---

## Addendum 2 — items from the v8 verification package (F:\pulpit\CARLA_INDEPENDENT_EXECUTABLE_VERIFICATION_CHAT00-14_20261022_v8) that are NOT implemented

### O8 — CHAT-09 P0: `is_main` used before assignment (OpenCode implementer)

```
[shared preamble]
TASK O8. Commit prefix: "fix(rq5): CHAT-09 is_main ordering -"
ultimate_pipeline/perception/train_launcher.py:437 reads `is_main` and :441 assigns it.
The bug came in with 4ca15683 (which merged with PR #16), so it is on production d72f57c6.
Reproduced by the audit: with enforce_dataset_acceptance stubbed, main() raises
"UnboundLocalError: cannot access local variable 'is_main'" @ line 437. Every real training launch crashes there.
Fix: move `ddp_enabled, rank, world_size = _init_ddp(args.ddp)` and `is_main = (rank == 0)` ABOVE the
`if is_main: _revoke_stale_success(out_dir)` block. Change nothing else.
Test (must FAIL before the fix, show that): stub enforce_dataset_acceptance to return
{"accepted": True, "total_paired_frames": 1} and _init_ddp to return (False, 0, 1); call main() with
--dataset <tmp> --out-dir <tmp>/out; assert no UnboundLocalError and that a pre-existing <out>/SUCCESS.txt was revoked.
Stub anything after that point, or stop it with a sentinel exception, so no real training runs.
```

### O9 — CHAT-09: explicit `weights_backbone=None` + honest pretraining receipt (OpenCode implementer)

```
[shared preamble]
TASK O9. Commit prefix: "fix(rq5): CHAT-09 random-init backbone -"
Both frozen protocols (rq3 and rq5 freeze, line 15) require "random initialization; no pretraining".
In torchvision 0.24.1, fcn_resnet50(weights=None) still defaults weights_backbone=ResNet50_Weights.IMAGENET1K_V1.
The audit showed it calls get_state_dict for IMAGENET1K_V1. All four factories are affected:
  ultimate_pipeline/perception/train_launcher.py:309
  ultimate_pipeline/perception/min_train_segmentation.py:207
  ultimate_pipeline/perception/eval_sim_labeled.py:237
  ultimate_pipeline/perception/eval_real_unlabeled.py:290
Also, rq5_provenance.verify_random_initialisation writes the literal "weights_backbone_argument": None
without checking it, which is a false provenance claim.
Fix:
  1. Pass weights_backbone=None explicitly at all four call sites.
  2. verify_random_initialisation must take the actual constructor kwargs (or inspect the call)
     and raise PretrainingContractError unless weights is None AND weights_backbone is None.
     Record the observed values, not literals.
Tests (fail first): monkeypatch torchvision.models._api.WeightsEnum.get_state_dict to raise;
building the model via each factory must NOT call it. verify_random_initialisation must reject
weights_backbone=ResNet50_Weights.IMAGENET1K_V1.
Do NOT edit the freeze files. Do NOT retrain anything.
Report: list any committed training receipt or model_manifest that recorded weights_backbone_argument=None
(git grep in reports/, campaigns/, datasets/). Those claims are now known to be false. List them; do not edit them.
```

### C4 — CHAT-02: Stage04/Stage09 access metadata must fail closed (Codex)

```
[shared preamble]
TASK C4. Read-only design first, then a minimal fix.
At d72f57c6, stage_04_enrichment.py:347-361 and stage_09_positional_semantics.py:243-257 wrap
apply_access_metadata_from_osm in try/except and only print "⚠️ ... failed" / record "error".
CHAT-02 requires fail-closed validation that rejects malformed or unresolved way/lane/turn metadata.
Step 1: map what apply_access_metadata_from_osm writes, which downstream consumers read it, and
which failures are legitimately "no data" (0 records) versus corruption (malformed IDs, unresolved
way->road mapping). Report this with file:line.
Step 2: make corruption raise; keep a real "0 applicable records" as a recorded non-failure;
validate the written metadata (ids resolve to existing roads/lanes) before the stage reports success.
Add negative tests: malformed, unresolved way id, stage swallowing an exception.
Do not change generator stages beyond these two call sites (generator fixes at source stage only).
```

### C5 — CHAT-03: Stage06 ENOSPC / torn-write receipts (Codex)

```
[shared preamble]
TASK C5. `git grep -n ENOSPC d72f57c6 -- 'ultimate_pipeline/**/*.py'` is EMPTY. Nothing handles disk-full.
stage_06_links.py has no fsync/atomic-replace. CHAT-03 requires: atomic write (tmp + fsync + os.replace +
directory fsync where the platform supports it), failure on ENOSPC/partial write, and no positive QA receipt after
an interrupted or torn write (a stale receipt from a previous run must not be reused).
Step 1: identify the Stage6 outputs and the shared positive receipt/quality gate that consumes them (file:line).
Step 2: add a small atomic-write helper (reuse an existing one if the repo has it; grep for os.replace/fsync first),
route Stage6 outputs and their receipt through it, and make the gate reject a missing or stale receipt.
Tests: inject OSError(errno.ENOSPC) mid-write -> stage fails, no receipt, the previous file is intact;
a stale receipt whose run_id does not match -> rejected.
```
(Note: C: has 1.4 GB free, so a real disk-full run is easy to trigger by accident. Use injected errors only.)

---

## Operator-only steps (after O0–O9, C1, C2, C4, C5 are APPROVED)

1. Push: `git -C E:/wt/repair-map-realism-p0-837a8504 push origin experimental/verified-fixes-20261022`
   (fast-forward from 5a004113; never `--force`).
2. Run C3's operator_commands to archive and reset the stale local integration branch.
3. Open the PR with an honest scope statement: 97+ commits / 1036+ files, not 6/12.
   Either request a full-scope review, or split the 9e777a27 lineage into its own PR first.
4. CI must go green on the pushed head before merge.
