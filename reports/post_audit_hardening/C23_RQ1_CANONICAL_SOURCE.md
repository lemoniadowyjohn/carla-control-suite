# C23 — Make C14 the canonical RQ1 source; retire the unprovenanced `run_11` (audit/reporting layer only)

Repo: `C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main/worktrees/c23-rq1-canonical-20260826`
Branch: `fix/c23-rq1-canonical-source-20260826` (branched from `fix/post-audit-phase-e-junctions-roundabouts-20260803`)
Interp: `.venv/Scripts/python.exe` · `UP_DISABLE_CARLA=1`

## Scope reminder

This task is about the **audit/provenance-reporting layer only**. `run_full_domain_gap.py`'s
`use_authoritative_alignment_bundle` short-circuit (a live, file-gated cache of a frozen alignment
for the canonical `manual_grid0828.xodr` vs `08_final_structural_gap.xodr` pair) was **not touched**,
per the instructions. `thesis_results/structural_gap_v1/run_11/alignment.json` and
`auto_aligned_rigid.xodr` were not deleted, moved, or altered — see "State of `run_11`'s data files"
below for why that's a non-issue in this worktree right now.

## What I found before changing anything

### 1. The actual consumer list (verified by grep, not assumed)

`grep -rn "run_11\|structural_gap_v1"` across the repo (excluding `submission/`, discussed separately)
turned up:

| File | Real coupling to `run_11` | Action |
|---|---|---|
| `ultimate_pipeline/tools/audit_thesis_topic_contract.py` | **Real.** `_main_payload()` builds the entire `run11` audit section from `thesis_results/structural_gap_v1/run_11/*`. | **Fixed** (this session) — added `superseded_by`, `superseded_by_detail`, and an explicit `resolved_via_supersession` entry in `unresolved_or_unverified`. |
| `ultimate_pipeline/run_full_domain_gap.py` | **Real, load-bearing, but currently dormant.** Lines 4712–4753: `use_authoritative_alignment_bundle` is gated behind `Path(...).is_file()` checks on `thesis_results/structural_gap_v1/run_11/{alignment.json,auto_aligned_rigid.xodr}`. Those files **do not exist anywhere in this worktree** (confirmed — `thesis_results/` is gitignored, line 316 of `.gitignore`, and was never present as tracked content at any reachable commit's HEAD; it was force-added once in `116f5500` on a now-unreachable history branch and has not existed at HEAD since). Also `cities/ingolstadt/manual_grid0828.xodr` and `artifacts/final_runs/scenario_b_audit/contract_run/08_final_structural_gap.xodr` (the two paths that must match for the guard to even be considered) don't exist either. So the guard currently, correctly, always evaluates `False` and falls back to `GeoAligner.estimate_from_xodr(...)`. | **Not touched** (as instructed). Verified the guard logic in both directions — see "Live short-circuit verification" below. |
| `ultimate_pipeline/tests/unit/test_run_full_domain_gap_reproducibility.py` | **False positive from the original prompt draft.** Read the whole file: it tests `validate_reproducibility_preconditions()` and `_cli_main()` using `tmp_path / "run_11"` purely as an arbitrary directory *name* in a synthetic fixture. It never imports, reads, or asserts against the real `thesis_results/structural_gap_v1/run_11` data, and never touches `use_authoritative_alignment_bundle`. **No coupling to retire.** | **Not touched** — correctly out of scope. |
| `ultimate_pipeline/experiments/thesis/run_all_experiments.py` | **Confirmed absent**, as your own prior check found. Only reference is `DEFAULT_RQ2_EVIDENCE = Path("thesis_results/structural_gap_v1/run_01/full_report.json")` — `run_01`, not `run_11`, and it's RQ2 evidence, not RQ1. | **Not touched** — no `run_11` coupling exists here. |
| `reports/post_audit_hardening/C19_THESIS_ASSEMBLY/rq_tables.json` | **Already correct — no `run_11` reference at all.** All 6 RQ1 rows (`local_lane_width_gap`, `local_curvature_gap`, `local_road_length_ratio_auto_over_manual`, `local_junction_ratio_auto_over_manual`, `local_road_count_ratio_auto_over_manual`, `local_auto_footprint_kept_fraction`, `whole_map_construction_layers_excluded_from_local_gap`, `whole_map_road_type_coverage_gap_context`) already cite the **C14/local_registration** pinned pair (`sha256: 69b1f520...` for auto, artifact path under `campaigns/ingolstadt_cooked_perception_v1/...`) as their source. This part of the task (**"make C14 the canonical RQ1 entry in rq_tables.json"**) was **already done** by an earlier session (commits `d11f262b`, `f9e0902c` — "local registration — crop auto to Grid0828 footprint" / "export local structural gap framing"). Nothing to change here. | **Not touched** — already canonical. |
| `ultimate_pipeline/tools/extract_elevation_stats.py` | **Real, previously missed by the prompt draft.** Line ~403 hardcoded: `"thesis_results/structural_gap_v1/run_11/full_report.json remains the authoritative structural thesis result."` embedded in the `thesis_impact` field of `build_report()`'s output payload — a stale claim not caught by the original consumer list. | **Fixed** (this session). |
| `ultimate_pipeline/tools/compute_missing_run11_metrics.py` | **Real but legitimate/orthogonal.** This tool *recomputes governed supplementary metrics for `run_11`'s own addendum* (conservative fit-metric boundary), operating on `run_11` as its explicit subject, not making an "RQ1 canonical result" claim. Docstrings already say things like "preserves only the prior conservative run_11 fit-history boundary" — i.e. it's honest about being a `run_11`-specific tool, not a general RQ1 source. | **Not touched** — legitimately scoped to `run_11` itself; not a provenance-claim surface needing supersession language. |
| `ultimate_pipeline/tools/reconcile_run11_authority.py` | Same category as above — combines `run_11` + `run_03` + `run_12` + curvature-basis + determinism artifacts into a `run_11/full_report_combined.json` convenience bundle. Explicitly says in its own `provenance.notes`: *"Convenience artifact only. It does not replace the authoritative source artifacts... run_11 remains the geometry authority"* — this is a `run_11`-internal reconciliation tool, not an RQ1-authority claim outside `run_11`'s own scope. | **Not touched** — same reasoning as above. |
| `ultimate_pipeline/tools/validate_thesis_run.py`, `pack_thesis_run.py` | Reference `structural_gap_v1/run_01` (packing/validating layout conventions), not `run_11` specifically, and make no "authoritative result" claims about RQ1. | **Not touched** — no `run_11`-provenance claim present. |
| `submission/**` (`README.md`, `appendix_reproducibility.tex`, `results/structural_gap_run11/*`) | **A separate, frozen, dated (April 2026) thesis-submission snapshot** — added wholesale in one commit (`a091a63f`), with its own vendored copy of `ultimate_pipeline` under `submission/infrastructure/`, its own RQ numbering (RQ2 = structural gap here, not RQ1), and no live tool (`audit_thesis_topic_contract.py`, `rq_tables.json`) reads from or writes to it. Editing a frozen submission package's historical numbers would misrepresent what was actually submitted. | **Deliberately not touched** — out of scope; not a live consumer of the audit/reporting layer this task targets. |

### 2. State of `run_11`'s data files (load-bearing finding)

`thesis_results/` does not exist anywhere in this worktree (nor in the main worktree
`C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main`, checked directly). It is gitignored
(`.gitignore:316`). `git log --all` shows the `run_11` bundle was committed once
(`116f5500 data(results): add governed run_11 evidence bundle`) but `git cat-file -e HEAD:...` confirms
none of those files exist at the current HEAD of this branch — they must be materialized out-of-band
(e.g. by re-running the pipeline) on whichever machine actually exercises the live short-circuit. This
means, in this worktree, the `use_authoritative_alignment_bundle` short-circuit is currently **dormant**
(correctly falls back to live `GeoAligner` estimation), not "live" in the sense of being exercised by any
test or run right now — but its *code* and *gating logic* are fully intact and were not modified.

## What I changed and why

### `ultimate_pipeline/tools/audit_thesis_topic_contract.py`

Added (inside `_main_payload()`, the legacy `run_11` audit section — did **not** touch
`_current_rq_tables_audit`, confirmed by diff and by the passing
`test_current_rq_tables_audit_untouched_and_still_passes` test):

1. Module-level constants `RUN11_SUPERSEDED_BY = "C14_RQ1_STRUCTURAL_GAP"` and
   `RUN11_SUPERSEDED_BY_DETAIL` (a human-readable pointer to
   `reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/`).
2. `run11.superseded_by` / `run11.superseded_by_detail` fields in the payload — so any consumer reading
   the audit JSON sees explicitly which result is canonical for RQ1, independent of whether `run_11`'s
   files happen to be present on the machine running the audit.
3. An explicit `unresolved_or_unverified` entry:
   `{"topic": "run11_provenance_gap", "status": "resolved_via_supersession", "detail": "..."}` — so the
   missing-provenance flags (`source_available=False`, `governed_addenda.*=False`,
   `coverage_context_present=False`, `fit_metric_exact_source_revision_status="missing"`,
   `full_network_vs_local_claim_boundary_present=False`) are never silently dropped from the audit's
   "things that need attention" list; they're now explicitly resolved-not-ignored.

I chose option **(a)** from the task ("mark superseded_by=C14") rather than **(b)** ("regenerate
governed addenda") because `run_11` is not a live *result* entrypoint for RQ1 reporting anymore (C14 is)
— it is only a live *alignment-cache* dependency for `run_full_domain_gap.py`, which the task explicitly
separates from the audit/provenance question and told me to leave alone. Regenerating `run_11`'s
governed addenda would be pointless busywork on a result nothing reads anymore.

### `ultimate_pipeline/tools/extract_elevation_stats.py`

Extracted the hardcoded `thesis_impact` string in `build_report()` into a module-level
`THESIS_IMPACT_NOTE` constant and updated its content from pointing at
`thesis_results/structural_gap_v1/run_11/full_report.json` to
`reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/C14_RQ1_REPORT.md`. This was a real stale claim the
original prompt draft's consumer list missed (this tool wasn't in the "consumers to reconcile" list) —
found via the repo-wide grep in step 1.

### Not changed (verified in scope, decided against changing)

- `run_full_domain_gap.py` — untouched, `git diff --stat HEAD` shows zero changes.
- `ultimate_pipeline/core/carla_utils.py` — untouched (owned by a concurrent session), zero changes.
- `_current_rq_tables_audit` in `audit_thesis_topic_contract.py` — untouched; its own test
  (`test_current_rq_tables_audit_untouched_and_still_passes`) re-verifies `ok=True`, 0 violations against
  the real `rq_tables.json` after my changes to the sibling `_main_payload()` function.
- `reports/post_audit_hardening/C19_THESIS_ASSEMBLY/rq_tables.json` — already canonical-C14-sourced for
  all RQ1 rows; no edit needed.
- `thesis_results/structural_gap_v1/run_11/{alignment.json,auto_aligned_rigid.xodr}` — not deleted,
  moved, or altered (they don't exist in this worktree to begin with).
- `compute_missing_run11_metrics.py`, `reconcile_run11_authority.py`, `validate_thesis_run.py`,
  `pack_thesis_run.py` — legitimately `run_11`-scoped internal tools, not RQ1-authority claims; no
  supersession language needed.
- `submission/**` — frozen, dated, independently-numbered thesis-submission snapshot; not a live
  consumer of `audit_thesis_topic_contract.py` or `rq_tables.json`.

## TDD

Two new test files, both RED before the fix (import errors / assertion failures) and GREEN after:

- `ultimate_pipeline/tests/unit/test_audit_thesis_topic_contract_run11.py` (4 tests):
  `test_run11_reports_explicit_supersession_by_c14`,
  `test_run11_missing_provenance_not_silently_dropped_from_unresolved_list`,
  `test_run11_superseded_flag_does_not_depend_on_source_presence`,
  `test_current_rq_tables_audit_untouched_and_still_passes`.
- `ultimate_pipeline/tests/unit/test_extract_elevation_stats_thesis_impact.py` (2 tests):
  `test_thesis_impact_note_points_at_c14_not_run11`,
  `test_thesis_impact_note_still_scopes_this_tool_as_supplementary`.

RED confirmed via `pytest -v` before implementation (3 assertion failures + the C19-gate test already
passing standalone); GREEN confirmed after (6/6 passed).

## Live alignment-bundle short-circuit — verification performed

Since the real `run_11` bundle files don't exist in this worktree, I verified the **exact guard
predicate** copied from `run_full_domain_gap.py` lines 4722–4731 behaves correctly in both directions,
using a throwaway probe script (not committed — `thesis_results/` is gitignored, files were written and
deleted within the same command, confirmed via `ls`/`git status` afterward that nothing was left behind):

1. **Current worktree state** (bundle files absent): guard predicate evaluates
   `use_authoritative_alignment_bundle = False` → correctly falls back to
   `GeoAligner.estimate_from_xodr(...)`. Also confirmed the path-identity comparison itself
   (`Path(reference_xodr).resolve() == canonical_manual_xodr and ...`) evaluates `True` when passed the
   canonical pair paths, so the *only* reason the guard is `False` right now is the `.is_file()` checks
   on the (absent) bundle files — i.e., the gating logic is working exactly as designed, not accidentally
   broken.
2. **With bundle files present** (temporarily materialized placeholder `alignment.json` +
   `auto_aligned_rigid.xodr` at the real path, deleted immediately after): guard predicate evaluates
   `use_authoritative_alignment_bundle = True`, confirming the short-circuit activates correctly the
   moment the frozen bundle exists on disk — unaffected by any change in this session.

```
With bundle files present: use_authoritative_alignment_bundle = True
CONFIRMED: guard correctly activates when the frozen run_11 bundle files exist on disk.
Cleaned up temp probe files.
```

`git status --short` after cleanup showed no stray files under `thesis_results/`.

## Audit output — before vs after

**Before** (`unresolved_or_unverified` — `run_11`'s provenance gap not present at all, silently
dropped):
```json
"unresolved_or_unverified": [
  {"topic": "visual_qa_runtime_verification_this_pass", "status": "missing_runtime_evidence", ...}
]
```

**After** (explicit resolution entry added; `run11.superseded_by` present):
```json
"run11": {
  "superseded_by": "C14_RQ1_STRUCTURAL_GAP",
  "superseded_by_detail": "RQ1's canonical result is now reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/ ...",
  "source_available": false,
  ...
},
"unresolved_or_unverified": [
  {"topic": "visual_qa_runtime_verification_this_pass", "status": "missing_runtime_evidence", ...},
  {"topic": "run11_provenance_gap", "status": "resolved_via_supersession", "detail": "..."}
]
```

`current_rq_tables_audit` unchanged: `"ok": true, "violations": [], "row_count": 16`.

## Full-suite verification

```
UP_DISABLE_CARLA=1 .venv/Scripts/python.exe -m pytest -q
========== 1063 passed, 1 skipped, 97 warnings in 168.60s (0:02:48) ==========
```

Zero failures, zero errors.

## Commit

Explicit-pathspec commit(s) only, on branch `fix/c23-rq1-canonical-source-20260826`. Not pushed. See
final commit SHA reported to the requester.

## Verdict

`RQ1_CANONICAL_SOURCE_RECONCILED status=complete` — C14/local_registration was already canonical in
`rq_tables.json`; the audit/reporting-layer gap (silently-unaddressed `run_11` provenance flags, plus one
missed stale-claim consumer in `extract_elevation_stats.py`) is now explicitly resolved via supersession
in both places. `run_full_domain_gap.py`'s live alignment-bundle short-circuit is confirmed intact and
untouched, in both its dormant (files absent) and active (files present) states.
