# ParamPoly3 Canonical Evaluator

## Verdict

PASS for the independent component and controlled read-only integration.

- Both `pRange="normalized"` and `pRange="arcLength"` are implemented.
- Position, first derivative, second derivative, tangent heading, and signed curvature use the required chain rule.
- No canonical failure path converts ParamPoly3 to Line.
- The only retained canonical production consumer is the read-only curvature metric.
- Mixed-use and mutation/reconstruction consumers remain on their frozen production formulas.
- Independent semantics review verdict: **APPROVE**.

## Prerequisites

| Prerequisite | Evidence | Result |
|---|---|---|
| I01 | `reports/line_arc_independent_execution.md`: 1,796 passed, 66 skipped, 0 failed | PASS |
| I02 | `reports/geometry_line_arc_integration.json`: every phase passed; verdict PASS | PASS |

## Mathematics

For normalized mode, `p=s/length` and `dp/ds=1/length`. For arc-length mode, `p=s` and `dp/ds=1`.

The local cubic is evaluated directly:

```text
u = aU + bU p + cU p^2 + dU p^3
v = aV + bV p + cV p^2 + dV p^3
```

World position uses the geometry origin and heading. Heading is `hdg0 + atan2(dv/ds, du/ds)`. Curvature uses:

```text
k = (du/ds * d2v/ds2 - dv/ds * d2u/ds2)
    / ((du/ds)^2 + (dv/ds)^2)^(3/2)
```

For normalized mode the second derivatives include `(1/length)^2`. Curvature is parameterization invariant, but the chain rule is still applied explicitly.

Bounds are analytical, not sampled: the rotated world `x(p)` and `y(p)` cubics are formed, their quadratic derivatives are solved, and in-domain extrema plus both endpoints define the axis-aligned bounds.

## Typed failures

| Condition | Exception |
|---|---|
| Missing or empty `pRange` | `MissingPRangeError` |
| Unsupported `pRange` | `UnsupportedPRangeError` |
| Zero, negative, or nonfinite length | `InvalidParamPoly3LengthError` |
| Nonfinite coefficient | `NonFiniteCoefficientError` with coefficient name |
| Zero tangent | `DegenerateTangentError` |
| Nonfinite or out-of-domain station | `InvalidEvaluationRangeError` |

The facade preserves these types under `STRICT`, supports explicit `CLAMP`, and permits deliberate extrapolation only under `EXTRAPOLATE`.

## API

- `evaluate_param_poly3`
- `sample_param_poly3`
- `param_poly3_endpoint`
- `param_poly3_curvature_at`
- `param_poly3_bounds`
- `ParamPoly3Evaluator` using `GeometrySegment` and `EvaluationPolicy`

All functions are exported from the canonical root package.

## Analytical evidence

`tests/unit/test_opendrive_geometry_parampoly3.py` contains 70 passing tests covering:

- straight, lateral-offset, quadratic, and cubic curves;
- positive and negative curvature;
- normalized and arcLength modes;
- translated and rotated origins;
- analytical and finite-difference derivatives and curvature;
- zero tangent and every malformed-record failure;
- endpoint inclusion and retained interior sampling stations;
- exact interior cubic bounds extrema;
- sampling-refinement convergence;
- strict, clamp/extrapolation facade behavior;
- 12 hashed repository fixtures at five stations each.

Result: **70 passed, 0 failed**.

## Repository fixtures

Manifest: `tests/fixtures/opendrive/parampoly3/manifest.json`

- Schema version: 4
- Selection: six evenly distributed records per source, not first-record selection
- Every fixture includes parent XODR SHA-256, road ID, geometry index, coefficients, `pRange`, length, and five frozen expected production outputs.
- Expected outputs come from the pre-migration formulas preserved at commit `711580a3045be04fab606a6cb7d0a5c38b828440`, not from canonical code.
- Tests recompute each actual parent XODR hash before evaluating fixtures.

| Parent | SHA-256 | Mode | Fixtures |
|---|---|---|---:|
| `auto_master.xodr` | `8439eea4ad63f0949d2fcd506266bc8b7c2b669546c55363760e0f3711916d80` | normalized | 6 |
| `manual_grid0828.xodr` | `932d5ef7e7024c123ced88fc7ac81915dbd9b7e6b0e08fa1ae5402e9c360d140` | arcLength | 6 |

## Full-map comparison

Machine-readable evidence: `reports/parampoly3_comparison.json`

Baseline provenance:

- Commit: `711580a3045be04fab606a6cb7d0a5c38b828440`
- Pose source: `ultimate_pipeline/quality/check_geometric_continuity.py`
- Curvature source: `ultimate_pipeline/domain_gap/curvature_gap.py`
- Frozen adapter: `opendrive_geometry/parampoly3_legacy_baseline.py`
- The adapter imports no canonical evaluator code.

| Metric | Result |
|---|---:|
| Records discovered | 21,174 |
| Normalized records | 13,742 |
| ArcLength records | 7,432 |
| Malformed records | 0 |
| Evaluations compared | 105,870 |
| Max / p95 position difference | `4.547473508864641e-13 m` / `0 m` |
| Max / p95 heading difference | `1.7763568394002505e-15 rad` / `4.440892098500626e-16 rad` |
| Max / p95 curvature difference | `2.842170943040401e-14 1/m` / `5.551115123125783e-17 1/m` |
| Nonfinite outputs | 0 |
| Degenerate records | 0 |

All differences are classified as floating-point evaluation-order and heading-normalization effects. No behavioral disagreement exists for valid repository records.

## Controlled integration

The partial batch present at task start had delegated three consumers before compliant evidence existed. After comparison and review:

- `curvature_gap.py` remains delegated because it is read-only.
- `check_geometric_continuity.py` remains on frozen formulas because the same helper feeds `recompute_geometry_starts_chained_inplace`, an XML mutation path.
- `geometry_math.py` remains on frozen formulas because `xodr_cropper_gps` is a mixed-use XODR consumer.
- `xodr_junction_links.py`, `xodr_carla_hardener.py`, junction reconstruction, LaneLinks, elevation fitting, and CARLA paths were not migrated.

## Regression evidence

| Suite | Result |
|---|---|
| ParamPoly3 analytical + repository fixtures | 70 passed |
| ParamPoly3 and immediate consumer regressions after mixed-use restoration | 115 passed |
| Canonical/consumer matrix | 2,388 passed, 78 skipped |
| Isolated geo-alignment suite | 13 passed |
| Repository-configured `-m "not carla"` suite | 405 passed, 1 skipped |
| Python compilation of changed modules | PASS |

Warnings were limited to existing missing optional settings paths and dependency deprecations.

## XML immutability

Both comparison sources retained the exact SHA-256 values embedded in the fixture manifest and comparison report. The comparison and fixture tools parse XML read-only and write only JSON evidence. No structural XML mutation occurs.

## Independent review

The independent reviewer initially rejected circular comparison evidence. The evidence was replaced with a canonical-independent frozen baseline from immutable git history, source hashes were verified against actual XODRs, five fixture stations were added, facade typing was corrected, and mixed-use consumers were removed from canonical migration. The final reviewer verdict is **APPROVE semantics**, with no blocking findings.
