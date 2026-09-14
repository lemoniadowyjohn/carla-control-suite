# Codex PROMPT JJ: regenerate domain-gap results against the CURRENT pinned map

## Context

The user asked (2026-09-14) what the current domain-gap / map-quality results
are and what needs improvement. An investigation this session found that
**every domain-gap comparison artifact on disk is stale** — none of them
compare the *current* pinned map-of-record
(`campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260905_202847.xodr`,
sha256 `2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798`)
against the manual ground truth (`.../source/manual/Grid0828.xodr`):

- `submission/results/structural_gap_run11/{full_report_combined.json,
  supplementary_metrics.json, summary.csv}` compares an auto candidate named
  `08_final_structural_gap.xodr` — a different artifact, and its object
  counts (0 barriers/buildings/poles/trees) strongly suggest a
  pre-enrichment snapshot, not a representative current candidate. Its own
  `fit_metric_provenance` field says the geometry-RMSE fit is "not
  reverified" and was "carried forward from prior patch output."
- `reports/post_audit_hardening/C14_RQ1_STRUCTURAL_GAP/local_registration.json`
  and `C26_LOCAL_REG_HARDENING.md` compare a different, older auto candidate
  (`ingolstadt_perception_map_of_record_20260819_160350.xodr`, 2026-08-19 —
  more than 3 weeks stale relative to the current 2026-09-05 pin).

Neither file reflects the current pinned map, and this session alone landed
~10 real bug fixes in the domain-gap computation code itself since the
`run_11`/C14/C26 artifacts were produced (schema-order corruption in
`GeoAligner.apply_to_xodr`, a point-duplication bug in the alignment
fallback extractor, a stale-header-bbox bug, a KL-divergence
density-vs-probability-mass bug in `CurvatureGap`, a header-offset rebase
fix in `deterministic_alignment.py`, plus numerous paramPoly3-blindness
fixes in earlier sessions this week). **Nobody has a current, trustworthy
read on where map quality actually stands right now.**

## Task

1. Confirm the exact current pinned map-of-record path and sha256 (do not
   assume the path/hash above is still current — verify against whatever
   pin-of-record mechanism this repo uses, e.g. `campaigns/*/MANIFEST*` or
   similar, before running anything).
2. Run (or wire and run) `ultimate_pipeline/run_full_domain_gap.py`'s
   whole-map comparison between that current pinned auto map and
   `Grid0828.xodr`, producing a fresh, dated result artifact under
   `reports/production_readiness/<TIMESTAMP>_FRESH_DOMAIN_GAP_REGEN/`
   (follow this session's established `YYYYMMDDTHHMMSSZ_DESCRIPTION/`
   directory convention). This is a real, long-running pipeline stage --
   budget real time for it; do not fabricate or interpolate numbers if it
   cannot complete (see repo memory `project_c0_clean_regen_pinned.md` for a
   documented prior incident about fabricated-memory-content that must not
   be repeated).
3. Report the full set of gap metrics from this fresh run: geometry RMSE
   (whole + matched-subset), Hausdorff, curvature KL-divergence + mean/std,
   road-length/coverage ratio, connectivity valid-rates
   (predecessor/successor/lane-link), semantic gap, road-classification
   gap, object density (buildings/poles/trees/barriers), tile IoU (if
   computed), elevation gap status. For each metric, note whether it moved
   meaningfully versus the stale `run_11`/C14/C26 numbers and, if so, in
   which direction.
4. Specifically re-examine the connectivity metric. The stale `run_11`
   artifact showed `predecessor_valid_rate`/`successor_valid_rate` = 0.0
   (manual = 1.0) and `road_lane_link_valid_rate` = 0.0 vs 1.0 — a
   near-total-failure reading that is very likely an artifact of either the
   stale/mismatched auto candidate or a since-fixed bug (this session fixed
   numerous junction/lane-link bugs in prior work), not a reflection of
   current reality. Confirm or refute this directly with the fresh run
   rather than assuming either way.
5. Do NOT treat this task as license to also regenerate or touch
   `submission/results/structural_gap_run11/*` or any file under
   `submission/` — per this repo's established policy
   (`project_mirror_sync_policy_correction_20260828` in memory), only 6
   specific CRITICAL_MIRRORED_FILES may ever be touched in
   `submission/infrastructure/`, and `submission/results/` is not in scope
   for this task at all. Your fresh artifact is a NEW, separately-labeled
   report, not a replacement for anything already cited in a thesis
   artifact.
6. Update `docs/research/THESIS_TO_CURRENT_PROGRESS.md` (or whatever is the
   current equivalent -- verify the file still exists at that path) with a
   clearly-dated new row/note pointing at the fresh artifact, without
   altering or removing the existing authoritative RQ2 hull-comparison
   number unless your fresh whole-map run gives specific, well-reasoned
   grounds to reconsider which comparison method should be authoritative
   (if so, flag this explicitly for human review rather than silently
   swapping which number is "the" result).

## Constraints

- New commits only, never amend. Never force-push. Never skip hooks.
- Do not promote anything to `auto_map_of_record`.
- Do not touch `submission/` beyond what's explicitly allowed above.
- Full test suite via bare `pytest` must stay green.
- If `run_full_domain_gap.py` hits an environment blocker (missing DEM,
  missing dependency, etc.), report the exact blocker rather than working
  around it silently or substituting synthetic data.
- Push your branch and report status; do not merge into
  `integration/session-batch1-20260912` yourself.
