# Master Verification Prompt -- Systematic Triage (items 1-8)

**Run timestamp:** 2026-09-23T18:40:22Z
**Target ref verified:** `origin/integration/production-large-map-20260918` @ `dc5443fc10725092bf935be32faedaac8cc56f4a` ("ci: add integration/** to push triggers"), fetched fresh at session start (2026-09-23T20:25:15+02:00 commit time).
**Method:** isolated git worktree at `G:\carla-triage-20260923` (`git worktree add G:\carla-triage-20260923 dc5443fc --detach`), read directly off disk. No code changes made to this worktree beyond this report. Every claim below cites file:line read from that checkout.

This triage covers items 1-8 from the coordinator's brief only. It explicitly does NOT re-litigate GAP-021 (osm_to_xodr_wrapper.py proj_string), the writer_lock.py/semantic_diff.py investigation, GAP-015, or the integration/** CI trigger fix -- all owned elsewhere or already closed.

---

## 1. Final artifact authority call graph (master prompt Section 13)

**Claim:** `main_pipeline.py`'s structural mutators (`junction_link_integrity`, `map_hygiene`) run BEFORE acceptance/fingerprint/preflight/determinism evidence generation (GAP-003's fix), and this ordering is still true on the current tip.

**Verdict: VERIFIED**

**Evidence:** `ultimate_pipeline/main_pipeline.py` @ dc5443fc:
- `self._mark_stage("junction_link_integrity")` at line 2307, followed by the actual link-patching call (`run_junction_link_integrity_gate`) at 2309-2316, with `final_out` reassigned at 2316.
- `self._mark_stage("map_hygiene")` at line 2354, `final_out = self._step8h_map_hygiene(final_out)` at 2358 (can delete roads / repair lanes / z-seams per its own docstring at 2359-2363).
- `self._mark_stage("positional_semantics")` at line 2382, `final_out = self._step9_positional_semantics(final_out)` at 2383 -- this is the P0-L reorder that GAP-003's residual_risk flagged as still-open ("stage-4-before-geometry-freeze semantic-placement reorder"); it is now ALSO before evidence generation, i.e. that previously-open half of GAP-003 appears resolved too (consistent with GAP-020's note that the source WIP for this reorder was merged).
- Evidence generation (`self._mark_stage("final_artifact_authority")` at 2391, calling `self._publish_final_artifact_authority(...)` at 2392-2397) runs strictly after all three mutators, against the final `final_out` value and `final_parent` lineage explicitly recorded at line 2357 ("never reconstruct that lineage by mtime").
- Inside `_publish_final_artifact_authority` (defined ~3030-3260): `map_acceptance.json` built at 3167-3181, `map_content_fingerprint.json` at 3192-3207, preflight at 3217, determinism fingerprint at 3223 -- all gated behind `STRUCTURE_FROZEN` capability checks (`depends_on=(STRUCTURE_FROZEN,)` at 3188, 3212, 3220, 3228) and preceded by `_authority_mark_structure_freeze` logic (3037-3090) that explicitly documents (3037-3052) the exact defect GAP-003 fixed.
- A large explanatory comment block at lines 2297-2304 documents the historical bug and where the fix now lives, corroborating the fix is durable/intentional, not accidental ordering.

No further action needed for item 1.

---

## 2. mtime/glob authority sweep (master prompt Section 15)

**Claim:** grep the whole `ultimate_pipeline/` tree for mtime-based "pick the newest file" patterns that could select an AUTHORITATIVE production artifact; GAP-012 fixed one instance (`run_alignment_and_matching.py`) -- find others not yet caught.

**Verdict: PARTIAL -- one new P2 finding in core production config, several lower-severity instances in research/thesis tooling (expected/self-documented), GAP-012's own fix confirmed still in place.**

**New finding (highest-severity of this sweep):** `ultimate_pipeline/config/settings.py:181-213`, function `_resolve_input_xodr_with_fallback`, called at `settings.py:1809` inside `Settings`'s post-init logic:
```python
# line 1801-1811
data_root = os.getenv("UP_DATA_ROOT", "").strip()
if data_root:
    self.BASE_OUTPUT_DIR = str(Path(data_root) / "ultimate_pipeline_out")
    if not os.getenv("UP_INPUT_XODR", "").strip():
        fallback = _resolve_input_xodr_with_fallback(self.BASE_OUTPUT_DIR)
        if fallback:
            self.INPUT_XODR = fallback
```
`_resolve_input_xodr_with_fallback` (settings.py:181-213) scans ALL subdirectories of `BASE_OUTPUT_DIR` for `08_final*.xodr` files and picks the single newest one by `os.path.getmtime` (settings.py:196-206) -- zero SHA256/content/receipt verification, not even the structural pre-filter GAP-012's fix or `run_full_domain_gap.py`'s `_discover_latest_valid_run` use. This is documented as an "HPC fallback" (comment at 1806-1807) that fires whenever `UP_DATA_ROOT` is set but `UP_INPUT_XODR` is not -- i.e. it sets `self.INPUT_XODR`, the actual input the NEXT pipeline run will treat as its source map, purely by mtime. This is the same defect class GAP-012 fixed (in `run_alignment_and_matching.py`, an analysis tool), but here it's in core `config/settings.py` and feeds the production pipeline's own input selection, arguably higher consequence: a stale clock, a rebase, or two concurrent runs writing to the same `UP_DATA_ROOT` could silently point a production run at the wrong prior XODR with no detectable error.
Suggested severity: **P2** (real, but gated behind an env-var combination -- `UP_DATA_ROOT` set + `UP_INPUT_XODR` unset -- that is documented as a cluster-only convenience path, not the default local/CI path).

**GAP-012 fix confirmed still in place:** `ultimate_pipeline/domain_gap/run_alignment_and_matching.py` imports `_repaired_sibling_exists` from `artifact_locator.py` (line 24) and defines `_run_dir_has_completed_output` (line 27) / uses it ahead of raw mtime in `_safe_latest_output_dir` (lines 47-76) and `_find_latest_final_xodr` (78+, `repaired = [c for c in candidates if _repaired_sibling_exists(c)]` at 106) -- structural guard before mtime tiebreak, matching the documented convention.

**Other instances found, assessed lower severity (research/reporting tooling, not core pipeline authority, several self-documented as accepting the limitation):**
- `ultimate_pipeline/run_full_domain_gap.py:3377-3404` (`_discover_latest_valid_run`): mtime-newest among candidates, but pre-filtered to require `tile_metadata.json` + populated `tiles/` + at least one `08_final*.xodr` co-present -- a real structural gate, just not a hash/receipt one. P3.
- `ultimate_pipeline/domain_gap/run_gap_ablation_experiment.py:73-79` and `run_domain_gap_sweep.py:20-25`: both carry an explicit code comment ("mtime-newest matches the already-established convention elsewhere") -- a conscious, if imperfect, choice, not an oversight. P3.
- `ultimate_pipeline/perception/train_launcher.py:57-69` (`_find_latest_dataset`): "best-effort discovery of newest folder that looks like a dataset" for training-data default; feeds perception/RQ5 training runs, not XODR structural authority. P3.
- `ultimate_pipeline/tools/artifact_locator.py:34-36`: explicitly documents having REMOVED an mtime fallback ("Previously: candidates.sort by mtime and return newest - now removed to enforce explicit identity") -- this file is evidence of the correct pattern, not a violation.
- Remaining hits (`tools/run_thesis_experiments.py`, `tools/export_thesis_tables.py`, `tools/compare_runs_determinism.py`, `tools/carla_smoke_suite.py`, `tools/ost_run_protocol_adapter.py`, `tools/osm_stats.py`, `tools/stage_gate_regression.py`, `tools/check_osm_to_carla_determinism.py`, `database/run_archiver.py`, `carla_tools/map_registry.py:1685`, `perception/perception_api.py:110`, `diagnostics/continuity_summary.py:27`, `experiments/thesis/run_*.py`) are all thesis-experiment/reporting/log-discovery scripts operating on already-produced evidence for downstream tabulation, not artifacts that get re-certified as "final". Not individually triaged further given the scope of this pass; flagged as a class for a dedicated follow-up sweep if desired.

**Suggested next action:** open a new GAP entry (e.g. GAP-022) for `config/settings.py::_resolve_input_xodr_with_fallback`, owned separately, adding the same structural-completeness + optional hash-binding guard `run_alignment_and_matching.py` now uses.

---

## 3. XODR primitive validation -- NaN/Inf and schema-unavailable handling (master prompt Section 16)

**Verdict: VERIFIED**

**NaN/Inf handling** -- `ultimate_pipeline/quality/xodr_strict_validator.py`:
- Module docstring (lines 17-20) states the contract explicitly: "all numeric reads go through xodr_numeric strict parsing -- malformed/nonfinite attributes are reported with their MISSING/MALFORMED/NONFINITE outcome and NEVER silently become physical zeros."
- All real validation call sites use `parse_required_float`/`parse_required_int` from `xodr_numeric` (confirmed 14 call sites: lines 342-343, 374, 436-440, 601, 643, 648, 739, 812, 885, 895).
- The legacy fail-open helpers `_f()`/`_i()` (lines 76-97) that DO silently coerce malformed/nonfinite values to a default (0.0/0) are explicitly marked "LEGACY fail-open parse (kept for backward-compatible import only)" / "New validation code MUST use xodr_numeric.parse_required_float instead" -- and grep confirms each is referenced exactly once in the file (their own `def` line): **zero live call sites**. Dead-but-documented, not a live silent-zero path.

**Schema-unavailable handling** -- `ultimate_pipeline/quality/check_xodr_schema.py`:
- `validate_xodr_schema_structured()` (lines 90-174) returns an explicit status enum: `PASS` / `FAIL` / `INCOMPLETE_DEPENDENCY` / `NOT_CONFIGURED`, documented in the docstring as "must never be interpreted as PASS."
- No `xsd_path` configured -> `status="NOT_CONFIGURED"`, `envelope_status="NOT_RUN"` (lines 114-122), never PASS.
- `lxml` unavailable (`etree is None` after the `try/except ImportError` at lines 8-11) -> `status="INCOMPLETE_DEPENDENCY"`, `envelope_status="INCOMPLETE"` (lines 123-131), never PASS.
- XSD file missing on disk -> same `INCOMPLETE_DEPENDENCY` treatment (lines 134-141).
- The legacy `validate_xodr_schema()` wrapper (lines 73-87) explicitly re-documents this in its own docstring: "Unavailable/unconfigured schema validation is NOT a pass: it returns (False, <explicit reason>)."

No further action needed for item 3.

---

## 4. Lane-count classifier evidence (master prompt Section 19)

**Claim:** confirm the "3007/3007 explained, 0 unexplained" classifier uses stronger evidence than naive junction-adjacency (master prompt notes ~70% of roads are junction-connecting, so adjacency alone wouldn't discriminate).

**Verdict: VERIFIED**

**Evidence:** `ultimate_pipeline/quality/classify_lane_count_transitions.py` (431 lines, read in full). The classifier is NOT adjacency-based. Its evidence tiers, in the order actually checked in `_classify_one()` (lines 251-363):
1. `SOURCE_PROVEN` (264-273): one side carries real, unfabricated `osm:`-prefixed provenance (`_osm_provenance`, imported from the sibling module, not fabricated here).
2. `JUNCTION_TRANSITION`, two tiers, both requiring more than "has a junction attribute":
   - `declared_connection` (278-288): the exact `(incomingRoad, connectingRoad)` pair must be declared in an actual `<junction><connection>` element (`_JunctionIndex.declared_connection`, built once from real XML at 213-231), AND `_connection_lane_count_consistent()` (237-248) independently verifies the number of distinct `laneLink/@to` ids on that connection equals the connecting road's own driving-lane count at that edge -- i.e. it cross-checks the declared routing topology actually accounts for the observed lane count, not just that a junction exists nearby.
   - `connector_adjacent` (289-298): requires the road ID to appear in `_JunctionIndex.registered_connectors` -- i.e. it must be actually registered as a `connectingRoad` somewhere in the file's `<junction>` topology (line 225), not merely carry a `junction` XML attribute. A road with a `junction` attribute that is NOT a registered connector falls through (comment at 299-301 explicitly calls this out as "itself suspicious, not an explanation").
3. `RAMP_CONNECTOR_TRANSITION` (303-311): length-heuristic (`RAMP_MAX_LENGTH_M = 25.0`), only reached if neither side is a junction road.
4. `LANESECTION_LOCAL_TRANSITION` (313-331): edge laneSection length <= 5.0m, a genuine local-taper-zone geometric check.
5. `ORDINARY_MERGE`/`ORDINARY_SPLIT` (333-358): requires the extra lane(s)' width to taper to <=34% of its far-end width (`TAPER_WIDTH_RATIO_MAX`, `_taper_ratio()` at 186-204) -- actual per-lane width-function evaluation (`_eval_width`, 157-169, evaluating the real `a+b*ds+c*ds^2+d*ds^3` width polynomial), not a topology guess.
6. `MISSING_PROVENANCE` (360-361) only for `|delta|<=1` with no other evidence; everything else falls to `SUSPICIOUS` (363).

This directly answers the master prompt's concern: adjacency alone is deliberately NOT sufficient here -- both junction tiers require independent structural corroboration (declared connection + lane-count-consistent laneLinks, or actual connector registration), matching what MASTER_GAP_REGISTER.json's GAP-005 entry already claims. Read-confirmed accurate.

No further action needed for item 4.

---

## 5. Domain-gap aggregation contract (master prompt Section 30)

**Verdict: VERIFIED**

**Evidence:** `ultimate_pipeline/domain_gap/domain_gap_aggregator.py`, `DomainGapAggregator.aggregate()` (full file read, 217 lines):
- **Identical normalized components -> composite 0:** `_norm()` (24-35) computes `min(abs(value)/ref, 1.0)`; if `rmse=0` and `kl_divergence=0`, both normalize to `0.0`; composite = `(gw*0 + cw*0) / (gw+cw) = 0.0` (169-190). Confirmed by direct trace of the arithmetic.
- **Composite clamped [0,1]:** each component is clamped to `[0,1]` at the `_norm()` level (the `min(..., 1.0)` at line 33, and `abs()` guarantees >=0); composite is a weighted average of only in-range values (`score/weight_sum`, line 190) so it stays in `[0,1]` by construction. No separate post-hoc clamp exists, but none is needed given the inputs are pre-clamped -- confirmed sound.
- **Disabled component excluded from composite:** only `geometry` and `curvature` ever participate in composite at all (by explicit design -- `composite_metadata.excluded_components` lists `intersection`, `semantic`, `elevation`, `road_classification`, `connectivity` verbatim, lines 201-207); within those two, `if gw > 0 and not g_c.get("disabled") and g_c.get("rmse_norm") is not None` (175) / same pattern for curvature (182) explicitly gates on `disabled`.
- **Zero normalized components -> None + reason string:** `if weight_sum > 0: ... else: out["composite"] = None; out["composite_metadata"] = {"reason": "no normalized components available"}` (189-214) -- exact match to the claimed contract, no fake 0, no crash (whole function is arithmetic on `Optional[float]`, guarded by the same `is not None` checks).

No further action needed for item 5.

---

## 6. CityObjectLabel.Any==255 handling (master prompt Section 32)

**Verdict: VERIFIED**

- **Capture writer accepts 255, doesn't crash:** `ultimate_pipeline/perception/carla_classes.py:17` defines `CARLA_SEMANTIC_ANY_CLASS_ID = 255` (comment at line 13: "verified against the installed carla package"). `assert_label_ids_in_range()` (lines 20-32) computes `bad = arr[(arr < 0) | ((arr > CARLA_SEMANTIC_MAX_CLASS_ID) & (arr != CARLA_SEMANTIC_ANY_CLASS_ID))]` -- 255 is explicitly excluded from the "bad" set even though it exceeds `CARLA_SEMANTIC_MAX_CLASS_ID`. `capture_writer.py` imports this function (line 40) and calls it at line 176 ("fail-closed on out-of-range ids") on every write -- 255 passes through without raising.
- **Evaluation treats 255 as ignore-index:** `ultimate_pipeline/perception/eval_sim_labeled.py`: the IoU/metric function at lines 112-122 takes an `ignore_index` parameter, masks `target != ignore_index` before scoring (122), and is called at line 197 with `ignore_index=CARLA_SEMANTIC_ANY_CLASS_ID` -- 255 pixels are excluded from the error count, not scored as wrong.
- **Training loss uses ignore_index=255:** `ultimate_pipeline/perception/min_train_segmentation.py:119-122`: comment "CARLA's Any(255) sentinel is a legitimate label value (unclassified/...)" directly precedes `loss_fn = torch.nn.CrossEntropyLoss(weight=class_weights, ignore_index=CARLA_SEMANTIC_ANY_CLASS_ID)`.

All three legs of the claim confirmed consistent end-to-end (capture -> eval -> training) using the same shared constant, not three independently-hardcoded `255`s that could drift.

No further action needed for item 6.

---

## 7. Duplicate module drift -- ultimate_pipeline/ vs submission/infrastructure/ (master prompt Section 50)

**Verdict: VERIFIED (policy is real, currently followed; broad divergence elsewhere is BY DESIGN, not drift)**

**Evidence:**
- `tests/phase_q/test_duplicate_module_drift.py` defines the actual enforced contract: `CRITICAL_MIRRORED_FILES` (lines 5-12) lists exactly 6 files (`core/carla_opendrive_loader.py`, `core/xodr_hash_gate.py`, `core/opendrive_gen_diagnostic.py`, `carla_tools/map_identity_guard.py`, `quality/check_carla_opendrive_compat.py`, `tools/load_final_into_carla.py`) and asserts byte-identity (`filecmp.cmp(f1, f2, shallow=False)`) between `ultimate_pipeline/<path>` and `submission/infrastructure/ultimate_pipeline/<path>` for each -- matching this session's memory note (`project_mirror_sync_policy_correction_20260828.md`) exactly.
- Manually re-verified all 6 with `cmp -s` (not relying on the test alone): **all 6 identical**, no drift.
- `diff -rq ultimate_pipeline submission/infrastructure/ultimate_pipeline` shows extensive divergence OUTSIDE the 6-file list (dozens of files differ or exist only in one tree, e.g. `config/settings.py`, `cli.py`, `carla_tools/map_registry.py`, entire extra `dev_tools/`, `database/`, `dashboard/` trees only in the submission mirror). This is EXPECTED under the documented policy (submission/infrastructure/ is a frozen historical snapshot, not a live mirror) and is NOT itself a violation -- the policy only requires the 6 critical files to stay in sync, which they do.
- No stray `build/lib/` copy of any of these modules was found in this checkout (`find . -path "*/build/lib*" -name "*.py"` returned nothing) -- the `build/lib/ultimate_pipeline/topology/junction_model.py` copy mentioned in GAP-014's investigation (dated 2026-07-30) is no longer present.

No further action needed for item 7.

---

## 8. Final readiness evidence binding (master prompt Section 40)

**Verdict: PARTIAL on the target production tip -- and a real, already-implemented, better fix exists but is NOT yet merged (integration debt, same class as GAP-011).**

Checked 3 tools as requested:

**`ultimate_pipeline/tools/verify_final_xodr.py` -- VERIFIED.** `verify_final_xodr()` (line 116+) computes `digest = hashlib.sha256(xodr_path.read_bytes()).hexdigest()` (line 209) directly from the actual file bytes and threads `input_xodr_sha256=digest` through every result branch (lines 216, 240, 260, 281, 306). This is genuine content-hash binding, not filename matching -- no gap here.

**`ultimate_pipeline/tools/final_map_readiness_gate.py` -- PARTIAL, on the dc5443fc tip specifically.**
- `build_final_map_readiness_report()` (272-369) does compute and record its own top-level `xodr_sha256` (line 335, via `safe_sha256_file`).
- `evaluate_connector_report()` (118-211) DOES perform real path+SHA256 cross-verification for the connector sub-report only: `output_sha = report.get("output_sha256")`, compared against `safe_sha256_file(xodr_path)` (lines 185-191) -- but only checked `if len(output_sha) == 64` (187), i.e. silently skipped (no `sha_issue`, no failure) if the connector report simply omits the field. Presence is not enforced, only consistency-when-present.
- **`evaluate_visual_gate_report()` (214+) and `evaluate_perception_status()` (234+) perform NO sha256/binding check at all on this tip** -- `visual_report` and `perception_report` are loaded purely from their (default-derived) file paths (`_default_visual_gate_report`, `_load_json`) and trusted without any cross-hash verification against the XODR under test. This is exactly the "filename matching, not path+SHA256" pattern the master prompt's §40 is concerned about, for 2 of the 4 sub-report types.

**A real, more complete fix for exactly this gap already exists, but is unmerged:** commit `e6052360` ("fix(tools): final-readiness evidence binding with cross-report hash verification", OC-41) adds `_verify_xodr_binding()` and applies it uniformly to ALL FOUR sub-reports (static/connector/visual/perception), plus a new `evidence_manifest` array recording every sub-report's path + SHA256 for audit (diff confirmed directly via `git show e6052360`). A follow-up commit `23913504` ("docs(evidence): OC-41 final-readiness evidence binding RESULTS.json") sits on top of it.
- **Confirmed via `git merge-base --is-ancestor e6052360 dc5443fc`: NOT an ancestor.** `git log --follow` on `final_map_readiness_gate.py` at dc5443fc shows only `aaa54e8e` and `a091a63f` in its history -- e6052360/23913504 are genuinely absent from the target production tip.
- These two commits exist only on the local branch `_oc41_work` (the very checkout this triage session's coordinator started from, per the session's initial git status), which itself tracks `origin/fix/final-readiness-evidence-binding-v3` and is reported "ahead 58, behind 2" of that remote -- i.e. there is also unpushed local-only work beyond just these 2 commits on that branch.
- Note even the unmerged fix's `_verify_xodr_binding()` still treats an absent sub-report `xodr_sha256` as "can't verify, assume compatible" (its own docstring, `return True, ""` when `actual` is empty) -- so it strengthens cross-report consistency-when-present and broadens coverage to all 4 report types, but does not make sha256 presence itself mandatory. Worth noting for whoever reconciles this branch.

**Suggested next action:** this is integration debt, not a design defect -- the fix is already written and (per its commit message) test-verified ("19 existing tests pass; 3 updated"). Recommend tracking as a GAP-011-style follow-up: rebase/verify `origin/fix/final-readiness-evidence-binding-v3` (or cherry-pick `e6052360`+`23913504`) onto `origin/integration/production-large-map-20260918` with a fresh full-suite run, same as the rest of GAP-011's part-b backlog (OC-35/37/41/42/VAP were separately flagged there as "not yet accounted for"). Severity **P2** (real coverage gap for 2 of 4 sub-report types, but `require_visual`/`require_perception` gating and the top-level `xodr_sha256` binding mean a wholesale evidence swap would still require also forging the visual/perception JSON's other fields to pass unnoticed -- not a trivial exploit, just a real audit-trail gap).

---

## Summary

| # | Item | Verdict |
|---|------|---------|
| 1 | Final artifact authority ordering | VERIFIED |
| 2 | mtime/glob authority sweep | PARTIAL -- new P2 finding: `config/settings.py:181-213` (`_resolve_input_xodr_with_fallback`) |
| 3 | XODR NaN/Inf + schema-unavailable validation | VERIFIED |
| 4 | Lane-count classifier evidence strength | VERIFIED |
| 5 | Domain-gap aggregation contract | VERIFIED |
| 6 | CityObjectLabel.Any==255 handling | VERIFIED |
| 7 | Duplicate module drift / mirror policy | VERIFIED |
| 8 | Final readiness evidence binding | PARTIAL -- real fix exists unmerged (`e6052360`/`23913504` on `_oc41_work` / `origin/fix/final-readiness-evidence-binding-v3`), 2 of 4 sub-report types unverified on current production tip |

**6 of 8 fully VERIFIED with no action needed. 2 of 8 PARTIAL, both real and precisely scoped, neither an emergency:**
- **Item 8 is higher priority**: the fix already exists, is reportedly tested, and just needs integration-debt reconciliation (same pattern already well-understood from GAP-011) -- lowest-risk, highest-value follow-up.
- **Item 2** needs a new fix (not yet written) for `config/settings.py::_resolve_input_xodr_with_fallback`, gated behind an HPC-only env-var combination so real-world exposure is lower, but the code pattern is the same class GAP-012 already established as worth fixing.

No fixes were implemented in this pass beyond this report, per the coordinator's instruction to flag rather than implement items 1-8.
