# P12 REVIEW-EVIDENCE-001 — Adversarial Evidence Review

Date: 2026-08-02
Target: evidence claims introduced by P05–P10, re-checked adversarially against
the authoritative XODR
(`campaigns/ingolstadt_cooked_perception_v1/candidate/raw_xodr_run_1_epsg32632_header_pinned.xodr`)
and repository state at HEAD `dba89fc0`.

## Checks (all executed against real data, not fixtures)

### C1 — Seam fixer does not fabricate corrections on the real map
`fix_elevation_seams` on the authoritative XODR:
- seams checked: 45 632, already consistent: 45 632, fixed: 0, max_delta: **0.0 m**
- Verified: raw candidate is already C0 at road boundaries; the fixer
  correctly reports nothing to fix instead of inventing corrections.

### C2 — Signal enrichment is idempotent on the real map
Insertion of a grounded record on road `39830` (real road id):
- first run: inserted=1; second run: matched=1, inserted=0; total `<signal>`
  count stays 1 → idempotent.
- Adversarial probe with nonexistent road id `"1"` was **rejected**
  (invalid placement) → fail-closed behavior confirmed, not silent skip.

### C3 — Curve-aware road bounds are finite on real geometry
`road_bounds_curve_aware` over the first 200 roads of the map:
- 0 non-finite bounds; all extrema computed via P05 evaluators.

### C4 — Tile-QA release gate present and effective
`stage_09_tiling.py` now gates the `UP_ALLOW_TILE_QA_FAIL` bypass behind
`release_mode` (THESIS_STRICT / STRICT_QUALITY_GATES / STRICT_TILE_SEMANTICS)
and `ALLOW_TILE_QA_SKIP`; release profiles always raise on tile QA failure.

## Verdict
**PASS** — committed evidence claims survive adversarial re-check on real data.
