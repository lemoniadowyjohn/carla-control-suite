# C23–C27 — governed prompts for the remaining verified issues

Convention (same as C6–C22): work on branch `fix/post-audit-phase-e-junctions-roundabouts-20260803`; TDD
(RED→GREEN) for all code; EXPLICIT-PATHSPEC commits; carry conservative claim boundaries; **do NOT touch
`ultimate_pipeline/core/carla_utils.py`** (actively worked on by another session); **no dependency on live CARLA**
(mock it / use synthetic data). Each issue below was verified open this session (evidence cited).

| Prompt | Target | Type | Evidence it's real |
|---|---|---|---|
| **C23** retire/reconcile legacy `run_11` → C14 canonical RQ1 | Claude, high | judgment | `audit_thesis_topic_contract` flags `run11.source_available=False`, `fit_metric…='missing'`, all `governed_addenda=False` |
| **C24** range-robust curvature metric (Wasserstein) | Codex 5.5, medium | mechanical | curvature_gap = 0.093 @\|κ\|≤1.0 vs 0.25 @\|κ\|≤0.5 — histogram-L1 is range-sensitive |
| **C25** multipolygon-building loader | Codex 5.5, medium | mechanical | `osm_polygon_loader.py` only iterates `root.findall("way")` — skips `<relation type=multipolygon>` |
| **C26** local-registration hardening (hull + building position) | Claude, high | judgment | `local_registration.py` uses a bbox footprint; auto buildings on 1 container road (excluded) |
| **C27** perception chain offline readiness (mocked CARLA) | Codex 5.5, xhigh | mechanical/tests | capture→train→eval modules exist but only `test_perception_dataset_roundtrip` covers them |

---

## C23 — Make C14 the canonical RQ1 source; retire the unprovenanced `run_11`  *(Claude, judgment)*

**Problem (verified):** `python -m ultimate_pipeline.tools.audit_thesis_topic_contract --out <f>` reports the legacy
structural-gap `run_11` (`thesis_results/structural_gap_v1/run_11`) as unprovenanced: `source_available=False`,
`coverage_context_present=False`, `fit_metric_exact_source_revision_status="missing"`,
`full_network_vs_local_claim_boundary_present=False`, all three `governed_addenda=False`. Meanwhile RQ1 now has a
provenanced result on the **pinned pair**: `reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/` (whole-map gap +
curvature fix + `local_registration.json` with the 4.5–6× road-network finding). Two RQ1 sources, one stale.

**Consumers to reconcile (verified):** `ultimate_pipeline/experiments/thesis/run_all_experiments.py`,
`ultimate_pipeline/run_full_domain_gap.py`, `ultimate_pipeline/tests/unit/test_run_full_domain_gap_reproducibility.py`,
and the C19 tables (`reports/post_audit_hardening/C19_THESIS_ASSEMBLY/rq_tables.json`).

**Task (judgment per consumer — do NOT blindly delete):**
1. Make C14 (+ local_registration) the canonical RQ1 entry in the C19 rq_tables + audit.
2. For `run_11`: either (a) mark it `superseded_by=C14` in the audit so its missing-provenance flags are no longer an
   *unaddressed* gap, or (b) regenerate its governed addenda if it is still a live entrypoint. Decide per consumer;
   `run_full_domain_gap.py` may be a live path — keep it working.
3. Update `audit_thesis_topic_contract.py` so `run_11` gaps are either resolved or explicitly marked superseded (no
   silent unresolved flags).

**Verify:** the audit reports no unresolved `run_11` gap (superseded or provenanced); full suite green; RQ1 table
points at the pinned-pair result. Commit report `C23_RQ1_CANONICAL_SOURCE.md`.

---

## C24 — Range-robust curvature distance (Wasserstein), alongside the L1 gap  *(Codex, mechanical)*

**Problem (verified this session):** `gap_analyzer._l1_hist_gap` bins over a **data-dependent** `[min,max]` range, so
the curvature gap is range-sensitive: **0.093** at |κ|≤1.0 but **0.25** at |κ|≤0.5, and a single outlier stretches
the range. Not a stable scalar.

**Task (TDD):** add `curvature_wasserstein_gap` to `ultimate_pipeline/domain_gap/gap_analyzer.py` — Wasserstein-1
(`scipy.stats.wasserstein_distance`) on the two `|curvature_samples|` sets, normalized to [0,1] by a fixed physical
scale (e.g. divide by a reference κ such as 0.2 /m and clamp). **Keep** the existing `_l1_hist_gap` curvature_gap
(report BOTH, labeled). TDD: identical distributions → 0; a shift → proportional & monotone; **robust to a single
outlier** (adding one κ=37 sample barely changes it, unlike L1). Wire it into `compare_xodr_to_xodr` output and the
C14 curvature section.

**Claim boundary:** report it as "range-robust distributional distance," and keep the raw L1 gap for continuity.
**Verify:** RED→GREEN; on the real pair the Wasserstein value is stable across |κ| bounds where L1 was not.
Commit report `C24_CURVATURE_ROBUST_METRIC.md` + updated `C14` curvature note.

---

## C25 — Consume OSM multipolygon-relation buildings in `osm_polygon_loader`  *(Codex, mechanical)*

**Problem (verified):** `ultimate_pipeline/enrichment/osm_polygon_loader.py` builds polygons only from
`root.findall("way")` (line ~106) — OSM `<relation type="multipolygon">` buildings are silently skipped (the C7
report estimated ~19 relation-buildings, ~0.3%, unconsumed).

**Task (TDD):** additively extend the loader to assemble multipolygon-relation buildings: for each `<relation>` whose
tags include `type=multipolygon` and a building tag, stitch member ways by role (`outer` → exterior ring(s),
`inner` → holes), close rings, and emit building polygon(s). Keep the existing `<way>` path unchanged. TDD with a
small `.osm` fixture containing one multipolygon building (outer + inner) → assert it loads with the hole. Then run
on the pinned Ingolstadt OSM and confirm the building count increases by ~the expected relation count.

**Caveat:** handle degenerate/unclosed relations by skipping with a warning (fail-open on a bad relation, never
crash the load). **Verify:** RED→GREEN; real-OSM building count rises; existing loader tests still pass.
Commit report `C25_MULTIPOLYGON_BUILDINGS.md`.

---

## C26 — Harden RQ1 local registration (convex-hull footprint + building-position probe)  *(Claude, judgment)*

**Context:** `ultimate_pipeline/domain_gap/local_registration.py` (this session) crops the auto map to Grid0828's
**bounding box** and excludes buildings (auto's 5,686 are all on one container road, s=0/t=0 → not spatially
croppable).

**Task (two judgment calls):**
1. **Tighter footprint:** replace the bbox with the **convex hull** of Grid0828's planView geometry (transformed to
   auto-local), so the crop matches the true footprint rather than an over-inclusive rectangle. TDD the hull crop;
   report how the cropped road count/length shift vs the bbox version and whether the 4.5–6× finding holds.
2. **Building-position probe:** investigate whether the auto building `<object>`s carry recoverable per-building
   position (an `<outline>` with `<cornerRoad>`/`<cornerLocal>`, or absolute x/y in `userData`). If recoverable, add
   local building cropping so building density CAN be compared in-footprint; if not, formalize the exclusion with the
   evidence. Document the outcome in `C14`.

**Claim boundary:** if the hull materially changes the ratios, report both (bbox vs hull). **Verify:** TDD green;
`local_registration.json` + C14 updated. Commit report `C26_LOCAL_REG_HARDENING.md`.

---

## C27 — Perception chain offline readiness (mocked CARLA), so RQ2/RQ3/RQ5 run first-time-right  *(Codex, xhigh)*

**Context:** RQ2/RQ3/RQ5 are gated on the operator GPU-driver fix (see `C20_GPU_TDR_20260821`). The chain modules
exist — `perception/capture_writer.py`, `perception/min_train_segmentation.py`, `perception/eval_sim_labeled.py`,
`perception/eval_real_unlabeled.py` — but are thinly tested (only `tests/unit/test_perception_dataset_roundtrip.py`).
When the GPU is fixed we want the capture→train→eval chain to run correctly immediately, not surface bugs then.

**Task (TDD, all offline — mock CARLA / synthetic arrays; do NOT touch carla_utils.py):**
1. `capture_writer`: assert it writes `rgb/` + `semseg_raw/` with **raw semantic ids** (not colorized) and correct
   `Any=255` handling, from synthetic frames.
2. `min_train_segmentation`: train a few steps on a tiny synthetic labeled dataset → a checkpoint; assert loss
   decreases and the checkpoint loads.
3. `eval_sim_labeled`: compute **mIoU** on a synthetic labeled pair with a known confusion → assert the expected mIoU.
4. `eval_real_unlabeled`: compute entropy/confidence/Fréchet **shift** (not accuracy) on synthetic images → assert
   ranges + that identical distributions give ~0 shift.

**Claim boundary:** these are readiness/contract tests on synthetic data — they prove the chain *runs correctly*, not
that any RQ result exists (that still needs real captures post-GPU-fix). **Verify:** the 4-stage chain runs end-to-end
on synthetic data in CI; full suite green. Commit report `C27_PERCEPTION_READINESS.md`.
