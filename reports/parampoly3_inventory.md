# ParamPoly3 Implementation Inventory

## Scope and prerequisites

- Inventory date: 2026-07-29
- Canonical package: repository-root `opendrive_geometry`
- I01: PASS, evidenced by `reports/line_arc_independent_execution.md`
- I02: PASS, evidenced by `reports/geometry_line_arc_integration.json`
- Secondary package `ultimate_pipeline/opendrive_geometry`: no ParamPoly3 evaluator is registered; it is not the canonical package.
- Submission mirror: excluded from runtime, but used as corroborating preserved source.

## Evaluators and samplers

| File | Function | Active callers | pRange support | Parameter normalization | Position | First derivative | Second derivative | Heading | Curvature | Sampling | Endpoint | Bounds | Fallback |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `opendrive_geometry/primitives.py` | `evaluate_param_poly3` | Public API; `ParamPoly3Evaluator`; analytical tests | `normalized`, `arcLength`; missing/other rejected | normalized: `p=s/length`; arcLength: `p=s` | Cubic local `u,v`, rigid transform to world | `du/ds`, `dv/ds` with `dp/ds` | Computed by shared polynomial kernel | World tangent via `atan2(dv/ds,du/ds)` | N/A | N/A | Via dedicated API | Via dedicated API | None; typed failure |
| `opendrive_geometry/primitives.py` | `param_poly3_curvature_at` | Public API; read-only `curvature_gap`; analytical tests | Both modes, strict validation | Same as evaluator | N/A | Full chain rule | `d2u/ds2`, `d2v/ds2` with `(dp/ds)^2` | N/A | Signed `(u'v''-v'u'')/(u'^2+v'^2)^(3/2)` | N/A | N/A | N/A | None; degenerate tangent is typed |
| `opendrive_geometry/primitives.py` | `sample_param_poly3` | Public API; `ParamPoly3Evaluator`; tests | Both modes | Delegates each station | Canonical | Canonical | Canonical | Canonical | N/A | Metric station spacing; retains final interior sample | Exact endpoint appended/replaced | N/A | None |
| `opendrive_geometry/primitives.py` | `param_poly3_endpoint` | Public API; sampler; tests | Both modes | Evaluates `s=length` | Canonical | Canonical | N/A | Tangent at endpoint | N/A | N/A | Yes | N/A | None |
| `opendrive_geometry/primitives.py` | `param_poly3_bounds` | Public API; `ParamPoly3Evaluator`; tests | Both modes | Domain is `[0,1]` or `[0,length]` | Rotated world cubic coefficients | Solves each world-axis quadratic derivative | Implicit in derivative roots | N/A | N/A | No sampling approximation | Endpoints included | Exact axis-aligned cubic extrema | None |
| `opendrive_geometry/evaluator.py` | `ParamPoly3Evaluator.pose_at/curvature_at/endpoint/sample/bounds` | Canonical facade; tests | Both modes; no default `pRange` | Delegates canonical primitives | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | `STRICT`, `CLAMP`, `EXTRAPOLATE` policy only; never Line |
| `opendrive_geometry/parampoly3_legacy_baseline.py` | `legacy_pose`, `legacy_curvatures` | Evidence generator and immutable fixtures only | Legacy behavior: arcLength exact, all other/missing treated normalized for pose; curvature missing treated arcLength | Legacy formulas frozen from commit `711580a3045be04fab606a6cb7d0a5c38b828440` | Yes | `du/dp,dv/dp` | Curvature path only | Tangent, normalized angle; zero tangent uses base heading | Absolute curvature; skips denominator `<1e-12` | Five parameter samples | Pose supports endpoint | No | Legacy behavior preserved for comparison only |
| `ultimate_pipeline/quality/check_geometric_continuity.py` | `_param_poly_eval`, `_pose_param_poly3` | `_pose_for_geometry`; continuity checks; `recompute_geometry_starts_chained_inplace` XML repair | Legacy both-mode convention | normalized or arcLength | Yes | `du/dp,dv/dp` | No | Tangent; base heading for small tangent | No | Called at requested station | Used by road/seam endpoints | No | Unknown geometry elsewhere can fall back to Line; ParamPoly3 itself does not |
| `ultimate_pipeline/geometry/geometry_math.py` | `_parse_parampoly3_coeffs`, `sample_parampoly3_points` | `elevation_gap`, `geo_alignment`, `xodr_cropper_gps` | Both; legacy missing defaults arcLength | `p=p_max*t` | Yes | No | No | No | No | Caller-provided normalized fractions | If caller includes `t=1` | No | Missing element returns origin |
| `ultimate_pipeline/domain_gap/curvature_gap.py` | `_sample_parampoly3_curvatures` | `_extract_curvatures`, `CurvatureGap.compute` | Both modes | Canonical station conversion | N/A | Canonical | Canonical | N/A | Absolute canonical signed curvature | Even stations | Included when requested | No | Invalid/degenerate samples are omitted; no Line conversion |
| `ultimate_pipeline/map_fixes/xodr_junction_links.py` | `_geom_end` | `_road_endpoints` in junction-link mutation workflow | Both; missing defaults normalized | Endpoint `p=1` or `p=length` | Yes | No | No | Incorrectly returns base heading | No | No | Position only | No | Non-ParamPoly3/non-Line returns start pose |
| `ultimate_pipeline/tools/xodr_carla_hardener.py` | `_parampoly3_check_and_repair`, `_curv_proxy` | `harden_xodr` when ParamPoly3 sanity is enabled | Broken/placeholder `pRange` parsing | Samples a nominal `[0,1]` domain | Local `u,v` only | Finite differences | No | No | Proxy only | Five fixed fractions | Nominal | No | Optional destructive ParamPoly3-to-Line replacement; deliberately not migrated |
| `compute_frechet.py` | `sample_road` | One-off `run()` analysis script | ArcLength only in practice; ignores XML `pRange` | Uses metric `p` for every record | Yes | No | No | No | No | Metric spacing | Intended | No | Other primitives treated as Line |

## Active caller classification

| Consumer | Classification | Integration decision |
|---|---|---|
| `ultimate_pipeline/domain_gap/curvature_gap.py` | Read-only metric | Canonical delegation retained after full-map classification and independent review |
| `ultimate_pipeline/quality/check_geometric_continuity.py` | Mixed read-only and XML-repair caller | Not migrated; frozen production formulas retained |
| `ultimate_pipeline/geometry/geometry_math.py` | Mixed read-only and XODR-cropper caller | Not migrated; frozen production formulas retained |
| `ultimate_pipeline/map_fixes/xodr_junction_links.py` | Mutation/reconstruction | Not migrated |
| `ultimate_pipeline/tools/xodr_carla_hardener.py` | Mutation with optional Line fallback | Not migrated |
| `compute_frechet.py` | Inactive one-off analysis | Not migrated |

## Notable legacy disagreements

- Continuity pose formulas agree on valid repository records to machine precision, but legacy code silently normalizes unsupported or missing `pRange`, clamps ranges, and supplies a base heading for a degenerate tangent.
- The legacy curvature sampler returns absolute curvature and drops near-degenerate samples. The canonical API returns signed curvature and raises a typed failure.
- `_geom_end` does not derive endpoint heading from the tangent.
- `xodr_carla_hardener` contains a malformed `pRange` parser and an optional ParamPoly3-to-Line mutation. It is explicitly outside this component integration.
- `compute_frechet.py` misinterprets normalized records as arcLength.

No reconstruction, junction topology, LaneLink, elevation fitting, CARLA behavior, or structural XML mutation was added by this batch.
