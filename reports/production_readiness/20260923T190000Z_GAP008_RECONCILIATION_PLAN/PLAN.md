# GAP-008 Geometry-Authority Reconciliation Plan

**Author**: Gemini (dispatched by the production-readiness coordinator, 2026-09-23)
**Baseline**: `f876c01974d5117a475b2cb52c04504e612288fc` — verified via `git rev-parse origin/integration/production-large-map-20260918`
**Status**: PLAN ONLY — not implemented, not scheduled. Requires explicit sign-off before any phase begins.

This is a written plan only, produced in response to GAP-008 in
`reports/production_readiness/20260918T000000Z_PRODUCTION_CLOSURE/MASTER_GAP_REGISTER.json`. No code has been
changed. Fresh worktree used for reads: `G:\carla-gap015-fresh-20260923` (detached HEAD, 3498 files).

## 1. Inventory — two independent canonicals, zero shared imports

- `ultimate_pipeline/geometry/opendrive_geometry_kernel.py:1` — 97 lines, dataclass `Pose(x,y,heading,curvature)`,
  API `pose_at_s(geometry,s)`, `endpoint()`, `sample()`, `bounding_box()`, `project_point()` — all primitives via
  `_local()` → `_primitive()` at `opendrive_geometry_kernel.py:21`. Last touched 2026-09-15.
  - Callers: ~30 active production callers (grep `opendrive_geometry_kernel` → 50 hits, 74 total incl. reports).
    Distinct `ultimate_pipeline/**/*.py` excluding tests: `visualization/map_plotter.py:18`,
    `topology/topology_validation.py:15`, `topology/junction_connector_rebuild.py:14`,
    `geometry/parampoly3_tangent_repair.py:26`, `map_fixes/xodr_junction_links.py:39`,
    `lanes/lanelink_builder.py:6`, `quality/check_dem_coverage.py:50`, `domain_gap_gnn/graph_builder.py:14`,
    `enrichment/elevation_importer.py:880`, etc.
    `reports/production_readiness/.../CANONICAL_GEOMETRY_MIGRATION.json:4` already marks this as canonical.
- `opendrive_geometry/` at repo root — 4 files, modular:
  - `opendrive_geometry/primitives.py:19` `evaluate_line/arc/spiral/poly3/paramPoly3`, `sample_*`, `*_bounds`,
    `*_curvature_at` (570 lines), adaptive Simpson spiral `SPIRAL_ARC_TOL=1e-9 SPIRAL_MAX_DEPTH=24` at
    `primitives.py:351`.
  - `opendrive_geometry/evaluator.py:27` `RangePolicy` STRICT/CLAMP/EXTRAPOLATE at `evaluator.py:27`,
    `EvaluationPolicy`, `LineArcEvaluator`/`ParamPoly3Evaluator` wrappers at `evaluator.py:73`, `evaluator.py:135`.
  - `opendrive_geometry/model.py:48` `Pose2D`, `Bounds2D`, `GeometrySegment` at `model.py:106`, `Vec2` at `model.py:7`.
  - `opendrive_geometry/freeze.py:18` `freeze_road_geometry`, `freeze_document`, `compute_freeze` GEO-FRZ-001 at
    `freeze.py:26`. Last touched 2026-08-02.
  - Callers: ~8 active production callers (grep from `opendrive_geometry` → 59 hits, ~8 distinct
    `ultimate_pipeline/**/*.py`): `visualization/map_plotter.py:14`, `visualization/map_diff.py:20`,
    `tiling/tile_equivalence.py:27` (freeze), `enrichment/coordinate_control.py:145`,
    `enrichment/crosswalk_schema.py:26`, `domain_gap/map_stats_xodr.py:12`, `tools/phase_i_tiling_strategy.py:340`,
    `tools/phase_g3_cross_section.py:47`.
- No cross-imports confirmed: `opendrive_geometry_kernel.py` never imports `opendrive_geometry/*` and vice versa —
  GAP-008's original proof still holds at this baseline.

## 2. Feature parity matrix

| Primitive | Kernel (`opendrive_geometry_kernel.py:27`) | Root (`primitives.py`) |
|---|---|---|
| line | exact `s,0,0` at `kernel:31` | exact `x0+s*cos` at `primitives.py:19` |
| arc | exact `sin(k*s)/k` at `kernel:33` | exact inv curvature at `primitives.py:32` |
| spiral | RK4 fixed-step `n=max(16, ceil(s/0.25)*4)` at `kernel:61` | adaptive Simpson tol `1e-9` fail-closed at `primitives.py:372` |
| poly3 | exact cubic at `kernel:38` | exact `primitives.py:494` + strict `NonFiniteCoefficientError` at `primitives.py:489` |
| paramPoly3 | `pRange` arcLength/normalized + `ValueError` at `kernel:45` | `MissingPRangeError`/`UnsupportedPRangeError`/`InvalidParamPoly3LengthError` at `primitives.py:131`, `allow_extrapolation` flag at `primitives.py:184` |
| range s | strict `0<=s<=length` else `ValueError` at `kernel:29` | `RangePolicy.STRICT/CLAMP/EXTRAPOLATE` at `evaluator.py:61` |
| bounds | sampling spacing 0.25 at `kernel:85` | analytic extrema (poly3/paramPoly3) at `primitives.py:540`/`primitives.py:283`, sampled+margin (spiral) at `primitives.py:470` |
| freeze | none | `freeze.py:42` SHA-256 per-geometry + per-road + GEO-FRZ-001 |

## 3. Cross-oracle audit

- `tests/opendrive_geometry/test_kernel_cross_oracle.py:1` — 17 cases only: `test_spiral_agrees` 5×s at `:44`,
  `test_poly3_agrees` 4×s at `:54`, `test_parampoly3_agrees` 8×(2 pRange ×4 s) at `:65`. Agreement `1e-6` (spiral)
  / `1e-9` (poly3/paramPoly3) but:
  - No line/arc (covered elsewhere via `tests/opendrive_geometry/test_existing_implementations.py:8` and
    `adapters.py:56`).
  - No out-of-range, no `pRange=None`/`""`, no `allow_extrapolation`, no `curvStart`/`curvEnd` edge, no
    `length<=0`, no non-finite coefficients.
  - Does not enforce single authority — `test_kernel_cross_oracle.py:18` header explicitly says "This does NOT
    resolve the architectural duplication."
  - Two real tests run at this baseline: the full suite includes 17 passed from this file, but no CI gate blocks
    future drift (a new primitive implementation can diverge silently until someone adds a case).

Residual drift risk remains MEDIUM as in `MASTER_GAP_REGISTER.json:109`, not mitigated to LOW.

## 4. Recommendation

Keep `ultimate_pipeline/geometry/opendrive_geometry_kernel.py` as long-term single authority — already designated
canonical in `CANONICAL_GEOMETRY_MIGRATION.json:4`, 30 vs 8 callers means lower migration churn, last touched 2
weeks ago vs 6 weeks ago. But port missing capabilities from `opendrive_geometry/` into the kernel (or via thin
delegation) rather than wholesale caller migration to root.

Rationale: migrating 8 callers to kernel < migrating 30 to root; the kernel is pipeline-critical (topology, lanes,
tiling, DEM). Root's strengths (adaptive error control, `RangePolicy`, explicit errors, freeze) are engineering
quality worth preserving — bring them over.

Chosen convergence target: single math core = `opendrive_geometry_kernel` (migrate spiral from RK4 to adaptive
Simpson to get fail-closed guarantees), plus freeze and `RangePolicy` as optional kernel wrappers. This yields one
numerical truth with one error model.

## 5. Concrete migration plan (L3/L4 — isolated worktree, single writer)

**Phase 0 — lock & expand oracle** (1 day, no behavior change, docs-only):
- Expand `test_kernel_cross_oracle.py` from 17 → 60+ cases: add line/arc at `x0/y0/hdg0 ≠0`, spiral high curvature
  `curv 0.3`, poly3 near-zero discriminant, paramPoly3 both pRanges + `s=0`, `length/2`, `length`, `length+eps`
  with STRICT/CLAMP/EXTRAPOLATE, `pRange=None` error path, non-finite coeffs.
- Add `tests/opendrive_geometry/test_single_authority_enforcement.py` that fails if `opendrive_geometry/primitives.py`
  defines any of `evaluate_*` without `from ultimate_pipeline.geometry.opendrive_geometry_kernel import`
  delegation (simple AST check).
- Run baseline bare pytest at this SHA → capture as reference.

**Phase 1 — create shared core** (2 days, risky, needs review):
- Extract `_spiral_integration.py` in `ultimate_pipeline/geometry/_core/` implementing adaptive Simpson at
  `SPIRAL_ARC_TOL=1e-9` (copy `primitives.py:372` verbatim). Both `kernel:61` and `primitives.py:402` import it —
  eliminates divergent spiral math while preserving the API. No caller change, diff is internal. Verify the 60-case
  oracle still `1e-9`.
- In `kernel.py` add `EvaluationPolicy` wrapper (copy `evaluator.py:33`) and `_validate_evaluation_s()` at
  `kernel:29` to support CLAMP/EXTRAPOLATE for DEM callers (`check_dem_coverage.py:50`, `elevation_gap.py:166`) —
  currently those callers work around the strict check with a manual clamp. Keep default STRICT so existing 30
  callers stay unchanged.
- In `kernel.py` add typed errors (`GeometryOutOfRangeError`, `MissingPRangeError`, etc.) mirroring
  `opendrive_geometry/errors.py` or re-export them — deprecate bare `ValueError` in favor of explicit types at
  `kernel:18`, `kernel:47`.

**Phase 2 — delegate root primitives** (2 days):
- Make `opendrive_geometry/primitives.py:184` `evaluate_param_poly3` a thin wrapper:
  `from ultimate_pipeline.geometry.opendrive_geometry_kernel import pose_at_s as _k` + convert args — delete
  duplicate cubic math at `primitives.py:167` but keep validation at `primitives.py:131` then delegate. Same for
  `evaluate_line/arc/spiral/poly3`. Keep `freeze.py` and `model.py` as-is (no math duplication).
- `opendrive_geometry/evaluator.py:73` etc. delegate to the kernel's new policy-aware `pose_at_s` rather than
  direct primitives.
- At this point both import paths resolve to the same floating-point code — drift becomes impossible, yet both
  package names still work (no caller break).

**Phase 3 — incremental caller migration** (1 week, low-risk, per-boundary):
- Migrate the 8 root callers to the kernel in ownership batches, not file-count: `visualization/*` (2 files),
  `tiling/tile_equivalence.py`, `enrichment/*` (2 files), `tools/*` (2 files),
  `domain_gap/map_stats_xodr.py`. Each batch: `grep -l "from opendrive_geometry"` → replace with
  `from ultimate_pipeline.geometry.opendrive_geometry_kernel import ...` + pytest per batch (full bare pytest
  expected clean, verify `tile_equivalence` freeze still passes via
  `tests/opendrive_geometry/test_geometry_freeze.py:13`).
- Leave `opendrive_geometry/` package as a deprecated re-export shim (with `DeprecationWarning` on import) for one
  release to avoid breaking external planning/SRE checks that grep for a bare `import opendrive_geometry`
  (`reports/line_arc_production_integration.md:9`).

**Phase 4 — deprecate & freeze** (1 day):
- Move `freeze.py:26` GEO-FRZ-001 to `ultimate_pipeline/geometry/freeze.py` (copy verbatim, keep the old location
  as a re-export). Update `tile_equivalence.py:38` import.
- Add a deprecated marker in `opendrive_geometry/__init__.py:1` and update `MASTER_GAP_REGISTER.json:104` to
  `fixed` with the new fixing commit.

**Phase 5 — enforcement**:
- Add a CI gate: `pytest tests/opendrive_geometry/test_kernel_cross_oracle.py test_single_authority_enforcement.py`
  must pass; add a pre-commit grep that fails on a new `from opendrive_geometry.primitives import` without kernel
  delegation.
- Update `MASTER_GAP_REGISTER.json:105` status: `deferred` → `fixed`, counts: `deferred` -1, `fixed` +1, document
  `evidence_artifact`: `tests/opendrive_geometry/test_kernel_cross_oracle.py` (60 cases, 1e-9) + delegation diff.

**Effort & risk**: L3 (deferred → fixed is cross-module, 38 callers) → parallel scout (caller inventory) +
evidence_auditor (oracle coverage) + reviewer (delegation design) read-only, then one implementer, xhigh only if
touching freeze. Estimated 7–10 dev-days, plus one full pytest per phase (~1000s each). No map-of-record or CARLA
runtime risk. Rollback is a `git revert` of the delegation commits — caller APIs unchanged, so revert is clean.

**Open questions**:
1. Confirm adaptive Simpson `1e-9` is acceptable for the kernel's 30 callers vs. the current RK4 (cross-oracle
   says yes, but need one production-XODR end-to-end diff: run `check_dem_coverage` on
   `campaigns/ingolstadt_cooked_perception_v1/source/manual/Grid0828.xodr` before/after).
2. Does any root caller rely on `EXTRAPOLATE` outside `[0,length]` for real pipeline logic, or only in tests? Audit
   via `grep -n "allow_extrapolation"` on the current tip.
