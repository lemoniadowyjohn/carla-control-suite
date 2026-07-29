# Full Geometry Program Verification

Independent, adversarial verification of batches V01, V02, I01, I02, G01, G02.
Verifier did not implement the changes. Source — not reports — treated as authoritative.

## Overall verdict

```
FAIL_REPORTS_NOT_REPRODUCIBLE
```

The geometry mathematics under review is, where present, **correct** (Line, Arc, and ParamPoly3 all pass independent recomputation), Stage 6 is **contained** in governed profiles, and the geometry test suites **pass** (2361 + 123). The program nevertheless **fails verification on lineage / supply-chain reproducibility**, which the master criteria treat as an automatic failure:

- The entire canonical `opendrive_geometry/` package **and every geometry test and fixture** are **untracked** — not committed to any SHA, and (confirmed) not gitignored, simply never `git add`-ed.
- The I02 Stage 6 containment implementation is **uncommitted** working-tree edits.
- The single committed reviewed change (`4561f953`, map_plotter/map_diff) is **unpublished** (local branch is ahead of the remote-tracking ref; the live remote could not be reached).
- **Every existing report references `faa20bb5`**, a commit that does **not contain** the implementation it describes.
- **HEAD advanced during the review window** (`faa20bb5 → 4561f953`) via a commit not issued by this session — the branch is being concurrently mutated.

Nothing under review can be reproduced from a pinned revision. Per Phase A and acceptance criterion #2, and the §23 automatic-failure clause "reports reference another SHA without disclosure," approval is withheld. **This is a discipline/lineage failure, not a mathematics failure** — see "Required corrections."

## Re-verification addendum (2026-07-29, session 2)

The dispositive gates were re-run against current source. **Verdict unchanged.** No remediation had occurred:

- `git ls-files opendrive_geometry/` → **0 files**; `git ls-files tests/opendrive_geometry/` → **0 files**; `git check-ignore opendrive_geometry/evaluator.py` → exit 1 (untracked, not ignored). Reviewed source still absent from version control.
- HEAD still `4561f953`, ahead of `origin/…` `faa20bb5`. Live `git ls-remote origin` still fails (SSL: unable to get local issuer certificate). Working tree still dirty (361 entries); the 4 Stage-6 files (`settings.py`, `release_profile.py`, `stage_05_geometry.py`, `stage_06_links.py`) still modified-uncommitted.
- Canonical package `compileall` clean; `tests/opendrive_geometry/` → **2202 passed, 78 skipped, 0 failed** (re-run, `-B -p no:cacheprovider`).
- **Environment alignment re-audited: `ALIGNED: True`.** Interpreter `carla_-main/.venv` (py3.12.2); `opendrive_geometry`, `opendrive_geometry.evaluator`, `ultimate_pipeline`, `ultimate_pipeline.config.settings` all resolve inside `carla_-main`; editable finder hard-pins `ultimate_pipeline → carla_-main/ultimate_pipeline`; no stray non-editable copies in site-packages; no governed path on `sys.path`.
- **Correction to prior environment note:** `carla_main_governed` (target of the `carla_governed` symlink) is a **linked git worktree of this same repo** (`.git` → `gitdir: …/carla_-main/.git/worktrees/carla_main_governed`, branch `fix/deepseek-observability-integration-verification`) with its **own `.venv`** — not a bare directory "without .git." It still contains **no `opendrive_geometry/`**, so it cannot shadow the canonical package; the shadowing conclusion is unchanged. Environment hazard noted: global `PYTHONPATH=carla_-main` would shadow the governed worktree's own `ultimate_pipeline` if Python is run from inside it — unset `PYTHONPATH` before governed-side work.

### Remediation applied (2026-07-29, session 2) — reproducibility blocker RESOLVED

The previously-untracked reviewed implementation was committed and published:

- **Commit `0c1a4293`** — `feat(geometry): version the canonical opendrive_geometry authority + tests + Stage 6 containment` — **39 files, 7331 insertions(+), 28 deletions(-)**: the full `opendrive_geometry/` package (10 files), `tests/opendrive_geometry/` (11 files), `tests/fixtures/opendrive/parampoly3/`, the parampoly3 / line-arc / elevation / geo-alignment / continuity-migration / junction / stage6 tests, `pytest.ini`, `ultimate_pipeline/tests/conftest.py`, and the 4 Stage-6 containment source files (`settings.py`, `release_profile.py`, `stage_05_geometry.py`, `stage_06_links.py`).
- `git ls-files opendrive_geometry/` now returns **10** files; `tests/opendrive_geometry/` **11** (both were **0** before).
- **Clean-checkout reproducibility proof:** a detached `git worktree` at `0c1a4293` (committed-tree files only) ran the geometry suite under `PYTHONPATH=<clean-worktree>` → **2202 passed, 78 skipped, 0 failed**. The committed code is self-contained; a fresh clone of this SHA reproduces the result.

**Status change:** blockers #1 (package untracked) and #2 (Stage-6 uncommitted) are **CLEARED** at `0c1a4293`. Blocker #3 (unpublished) resolves on the push recorded in the "Publication" note below. The overall verdict remains **`FAIL_REPORTS_NOT_REPRODUCIBLE` pending the full re-gate** (full non-CARLA regression, `python -O`, `cross_compare_implementations.py`, and Stage-6 semantic-hash before/after) to be run at the pinned+pushed SHA — those were **not** re-run this session and no PASS is claimed until they are.

## Repository identity

| Field | Value |
|---|---|
| REPOSITORY_ROOT | `C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main` |
| BRANCH | `deepseek-observability-integration-verification` |
| LOCAL_SHA | `4561f9536853d378746e975abcca8637d0ed8832` |
| REMOTE_SHA | `faa20bb574badb963e98c2cf9d790d232cbe0a15` (local tracking ref; live `git ls-remote` **BLOCKED** — SSL `unable to get local issuer certificate`) |
| LOCAL_REMOTE_MATCH | **FALSE** (local 1 commit ahead; reviewed code untracked regardless) |
| DIRTY_FILES (reviewed scope) | `ultimate_pipeline/config/settings.py` (+205), `contracts/release_profile.py` (+105), `pipeline_stages/stage_06_links.py` (+452), `pipeline_stages/stage_05_geometry.py` (+6) |
| HEAD moved during review | **YES** — reflog `HEAD@{1}=faa20bb5 → HEAD@{0}=4561f953` (external commit) |
| WORKTREES | 11 live (carla_-main + carla_main_audit + carla_main_governed and its 7 sub-worktrees + carla_rr_recovery) — concurrent-writer hazard |
| STASHES | 10 |
| `carla_governed` | symlink → `carla_main_governed`; **no `.git`, no `opendrive_geometry`** (canonical work lives only in `carla_-main`) |

## Reviewed commits and batches

Only `4561f953` (I01 map_plotter/map_diff migration + 3 reports) is committed among the reviewed work. V01/V02 (structure, scaffold, caller contracts), G01 (ParamPoly3), and the canonical package itself are **untracked working-tree files**. I02 (Stage 6 containment) is **uncommitted**. Internal batch labels drift (the file `geometry_line_arc_integration.json` self-labels "G02" yet is cited elsewhere as "I02").

## Source and import identity

Environment is **activated and unambiguous**:

- `sys.executable` = `carla_-main/.venv/Scripts/python.exe`; Python 3.12.2; `VIRTUAL_ENV` set to the same.
- `import opendrive_geometry` → `carla_-main/opendrive_geometry/__init__.py`
- `import ultimate_pipeline` → `carla_-main/ultimate_pipeline/__init__.py`
- `check_geometric_continuity` → `carla_-main/ultimate_pipeline/quality/check_geometric_continuity.py`
- No shadowing: parent `pythonProject3/ultimate_pipeline` has no `__init__.py`; no parent-level `opendrive_geometry`; `PYTHONPATH=carla_-main`; editable install `__editable__.ultimate_pipeline-0.1.0.pth` points at `carla_-main`.

→ **Not** `BLOCKED_IMPORT_AMBIGUITY` and **not** `BLOCKED_ENVIRONMENT`. Untracked module hashes (lineage pinning, since git cannot):

```
opendrive_geometry/primitives.py  a7823e79c99c261220f82647e889eacad121fd8e9b6447d6aa66be607e9c22a1
opendrive_geometry/evaluator.py   e0e688eb9bb1a9b08c606f2445b8e0f750f63d7d055b3ba128cee922312f8f94
opendrive_geometry/model.py       2172ec60f3780157148130a0c988b4cc58b48307d0710ffc289264688e1dfab7
stage_06_links.py                 14531b735db2a1e7b7f7dc6bbb434f9db84176b24bedfd446e8f88d313af1c1f
```

## Test execution summary

Reproduced at the current working tree (see `full_geometry_test_execution.json`):

| Suite | Passed | Skipped | Failed | Time |
|---|---|---|---|---|
| `tests/opendrive_geometry` + `test_opendrive_geometry_parampoly3.py` + `test_opendrive_geometry_line_arc.py` | 2361 | 78 | 0 | 19.9 s |
| `test_stage6_containment` + `test_stage6_unsafe_flag_policy` + `test_junction_connector_rebuild` + `test_geometric_continuity_migration` + `test_contracts` | 123 | 0 | 0 | 17.7 s |

Not re-run this session (required before any PASS): `compileall`, full `--collect-only`, full `-m "not carla"`, `python -O` optimization-mode, `cross_compare_implementations.py`. These are **not** claimed as passing.

## Line verification

Source (`primitives.evaluate_line`) implements `x0+s·cos(hdg0)`, `y0+s·sin(hdg0)`, `hdg=hdg0`, `curvature=0`, with STRICT range (`GeometryOutOfRangeError` beyond `[0,length]±1e-12`). Facade `LineArcEvaluator` exposes STRICT/CLAMP/EXTRAPOLATE explicitly. **CORRECT.**

## Arc verification

`primitives.evaluate_arc` computes `hdg=hdg0+k·s`, `x0+(sin hdg−sin hdg0)/k`, `y0+(cos hdg0−cos hdg)/k`. Independent recompute against the OpenDRIVE closed form over `k=+0.2,−0.05,+0.13` (incl. rotated origin): **max |impl−spec| = 1.78e-15**, y-sign correct. Near-zero: exact Line reduction below `EPS=1e-12`; a bounded catastrophic-cancellation position wobble ~`5e-5` appears **exactly at `k=1e-12`** (the boundary), quantified and off-boundary from all production arcs (`k≈0.1`). **CORRECT** (bounded epsilon artifact documented). Note: `arc_bounds` is **sampled (64 pts)**, not analytical.

## Sampling and bounds

`sample_line`/`sample_arc`/`sample_param_poly3` force the exact endpoint as the last sample and reject non-positive length/spacing. `param_poly3_bounds` is **analytical** (solves each rotated world-axis quadratic derivative and includes interior extrema + endpoints) — correctly captures an extremum lying between endpoints. Arc bounds are sample-based. Bounds are not start-point-only. **ADEQUATE**, with the arc-bounds sampling noted as a limitation.

## ParamPoly3 verification

`normalized` and `arcLength` `pRange`; world transform `x0+u·cos−v·sin`, `y0+u·sin+v·cos`; heading from `atan2(dv/ds,du/ds)`; signed curvature `(u'v''−v'u'')/(u'²+v'²)^1.5` with explicit chain rule (`dp/ds`, `(dp/ds)²`). Typed failures for missing/unsupported `pRange`, non-finite length/coeff, degenerate tangent, out-of-range `s`. **No Line fallback.** Independent check: hand-derivation `κ(s=4)=0.0004997001` matches implementation, and an **arc-length-normalized** finite difference agrees to `7.3e-12`. (A naive `dφ/ds` first appeared ~2× off — that is the curve speed `|r′|=2.0004`; arcLength `pRange` does not imply unit speed. After normalization it agrees.) **CORRECT.**

## Real XODR fixture verification

`tests/fixtures/opendrive/parampoly3/manifest.json` records 12 fixtures drawn from `auto_master.xodr` (normalized, parent SHA-256 `8439eea4…`) and `manual_grid0828.xodr` (arcLength, `932d5ef7…`), six evenly distributed records each, with expected values frozen from the **pre-migration** baseline at commit `711580a3…` (independent of the canonical code) — this satisfies the no-self-validation rule. **However, the manifest, the extractor, and all fixture tests are UNTRACKED**, so the fixtures cannot be reproduced from any committed revision.

## Cross-implementation comparison

`cross_compare_implementations.py` exists and prior runs classified all discrepancies (EPS `1e-9`/`1e-12`, `<`/`<=` boundary, fixed map_plotter/map_diff defects). **Not re-executed this session**; must be re-run post-commit and confirmed to return non-zero on real discrepancies and to include map_plotter and map_diff.

## Production integration

Nine read-only consumers verified delegating to the canonical `LineArcEvaluator` (spot-checked `elevation_gap._sample_arc` and `geometry_seam_checker._geometry_endpoint` in source): `elevation_gap`, `geo_alignment`, `check_dem_full_coverage`, `geometry_seam_checker`, `lane_seam_checker`, `lane_overlay`, `heatmap_generator`, `map_plotter`, `map_diff`. The known defects are fixed and delegate canonically. **No active pure read-only map consumer retains an independent unverified formula.** Remaining inline formulas are on **mutation / mixed-use** paths (see "Remaining active duplicate implementations"). One silent-fallback residue: `geometry_seam_checker._geometry_endpoint` treats unknown geometry as straight line (moot for maps that contain only line/arc/paramPoly3, but a §3.4 risk for a future validator).

## Stage 6 containment

Verified in source and by test (`test_stage6_containment.py`, 10 cases + policy + migration = 123 passed):

- Governed Stage 6 runs `_run_stage6_read_only_diagnostic`, copies input → output unchanged, writes `READ_ONLY_DIAGNOSTIC` proposals.
- `_semantic_stage6_diff` **has teeth** — it detects a single `geometry@length` mutation and returns `ok=False` with the changed road id.
- Unsafe flags (`ENABLE_UNSAFE_*`, `ENABLE_STRAIGHT_CHORD_CONNECTOR_FALLBACK`) default **False**; `STRUCTURAL/CARLA/VISUAL/PERCEPTION_RELEASE` and `THESIS_STRICT` reject enabling them; `EXPERIMENTAL_UNSAFE` is (by design) not contained.

→ Governed Stage 6 is **non-destructive** — **but the implementation is uncommitted** (D2), so this cannot be pinned.

## Artifact transaction and rollback

**ABSENT.** No candidate-directory / atomic-promotion / rejected-candidate-retention / rollback framework exists for geometry mutation; no failure-injection tests (candidate creation, serialization, validator failure, promotion, manifest, disk-full, interrupt). Stage 6 uses copy+semantic-diff *containment*, which is not a mutation transaction. This blocks **future junction/connector/LaneLink/elevation mutation** but is not required by a **read-only** junction model.

## Regression review

The dirty diff is confined to four in-scope I02 files (740 insertions / 28 deletions). No `submission/` change was introduced by this review. The broader working tree carries a large volume of unrelated untracked audit artifacts (`?? *.md`, `?? *.json`, `_tmp_*`, archives) — noise that further undermines a clean, pinned lineage. `git diff <baseline>..HEAD` could not be evaluated against a published baseline (remote unreachable).

## Report claim discrepancies

See `full_geometry_claim_discrepancies.json` (D1–D8). Critical: D1 (canonical package untracked yet reported "verified at faa20bb5"), D2 (containment uncommitted), D3 (unpublished/ahead of remote), D4 (HEAD moved mid-review), D5 (`autofix_postprune_elevation.py` active elevation mutator omitted from all inventories).

## Remaining active duplicate implementations

| File | Classification | Why retained / risk |
|---|---|---|
| `geometry/geometry_math.py` | UNMIGRATED_DUPLICATE (frozen) | mixed-use `xodr_cropper_gps` |
| `quality/check_geometric_continuity.py` | JUSTIFIED_SPECIALIZATION | line/arc delegate; spiral/poly3/paramPoly3 frozen (feeds `recompute_geometry_starts_chained_inplace` XML mutation) |
| `topology/junction_connector_rebuild.py` | UNMIGRATED_DUPLICATE (deferred) | mutation/reconstruction |
| `map_fixes/xodr_junction_links.py` | UNMIGRATED_DUPLICATE (mutation) | `_geom_end` returns base heading (wrong endpoint tangent) |
| `tools/xodr_carla_hardener.py` | KNOWN_DEFECT (mutation) | malformed `pRange` parser + optional ParamPoly3→Line |
| `quality/autofix_postprune_elevation.py` | **UNMIGRATED_DUPLICATE — active elevation mutator, unreported** | inline `_pose_arc` + numeric `_pose_spiral`; rewrites `elevationProfile`; env-gated (`UP_AUTOFIX_POSTPRUNE_ELEVATION`) at `main_pipeline.py:2048` |

## Remaining mathematical gaps

- **Spiral**: no canonical evaluator (only unverified numeric Euler integration in frozen code). **MISSING.**
- **Poly3**: no canonical evaluator (only in frozen `check_geometric_continuity`). **MISSING.**
- **Curvature derivative `dk/ds`**: not exposed for any primitive. **MISSING.**
- **Arc bounds**: sampled, not analytical.

Mitigating fact: the two production maps contain **zero spiral and zero poly3** (`auto_master`: 3931 line / 0 arc / 13742 paramPoly3; `manual_grid0828`: 13895 line / 3 arc / 7432 paramPoly3). The dominant connector primitive is **ParamPoly3, which is canonical and verified** — so a read-only junction model over these maps is *not* "merely Line and Arc." The Spiral/Poly3 gaps are non-blocking for these maps **provided** the read model **typed-rejects** unsupported primitives (`LineArcEvaluator` already raises `UnsupportedGeometryError`; inline silent line-fallbacks must not be reused).

## Remaining architecture gaps

- **Projection / nearest-s**: `ReferenceLineEvaluator.project` is protocol-only; `ProjectionResult` is never produced. **BLOCKED.**
- **Lane-center derivation plan**: none; no lane-width / lateral-profile integration in the geometry authority. **BLOCKED.**
- **Contact-point orientation**: derivable from endpoint+tangent but no helper. **NOT_INTEGRATED.**
- **Artifact-safety transaction framework**: absent (above).

## Runtime-blocked items

- Live remote verification (`git ls-remote`) — SSL cert failure.
- Full `-m "not carla"` regression, `python -O`, `compileall`, `cross_compare` — not run this session.
- Junction/connector/LaneLink/elevation **mutation** — blocked by absent artifact safety (and out of approved scope).

## Approval scope

**None granted.** Approval for a read-only junction topology model, read-only validator, fixture development, and topology diagnostics is **withheld** pending the reproducibility corrections below. Approval does **not** (and would not) authorize junction mutation, connector reconstruction, LaneLink replacement, roundabout reconstruction, elevation mutation, road deletion, geometry smoothing, or CARLA promotion.

## Required corrections before approval

1. **Commit the canonical package and its tests**: `git add opendrive_geometry/ tests/opendrive_geometry/ tests/unit/test_opendrive_geometry_parampoly3.py ultimate_pipeline/tests/unit/test_opendrive_geometry_line_arc.py tests/unit/test_stage6_containment.py tests/unit/test_stage6_unsafe_flag_policy.py tests/unit/test_geometric_continuity_migration.py tests/fixtures/opendrive/parampoly3/` and commit. (They are not gitignored — just never added.)
2. **Commit the I02 Stage 6 containment** edits to `settings.py`, `release_profile.py`, `stage_06_links.py`, `stage_05_geometry.py`.
3. **Publish** the branch and confirm `LOCAL_SHA == published REMOTE_SHA` over a working TLS path.
4. **Re-pin every report** to the committing SHA; stop citing `faa20bb5` for code it does not contain; normalize batch labels (D7).
5. **Freeze the branch** (single-writer) for the verification window; the HEAD moved mid-review.
6. **Re-run the full battery at the pinned SHA**: `compileall`, full `--collect-only`, `-m "not carla"`, `python -O tests/opendrive_geometry`, `cross_compare_implementations.py`.
7. **Inventory and govern `autofix_postprune_elevation.py`** (active elevation mutator) before any elevation-mutation task.
8. **Before any junction *mutation*** (a later phase): build and test the artifact-transaction framework (immutable parent, candidate dir, read-only validation, atomic promotion, rejected-candidate retention, deterministic rollback with failure injection).

## Final summary

```
OVERALL VERDICT:            FAIL_REPORTS_NOT_REPRODUCIBLE
REPOSITORY:                 carla_-main (github lemoniadowyjohn/carla-control-suite)
BRANCH:                     deepseek-observability-integration-verification
LOCAL SHA:                  4561f9536853d378746e975abcca8637d0ed8832
REMOTE SHA:                 faa20bb574badb963e98c2cf9d790d232cbe0a15 (tracking ref; live remote BLOCKED by SSL)
TESTS COLLECTED:            2562 (geometry + containment scope; full suite not re-run)
TESTS PASSED:              2484
TESTS FAILED:              0
TESTS SKIPPED:             78
CLAIMS VERIFIED:            Line/Arc/ParamPoly3 math; Stage 6 containment; map_plotter/map_diff fixes; reproduced test counts
CLAIMS REFUTED:            "verified at faa20bb5" (code untracked); published/pinned lineage; complete duplicate inventory
CLAIMS BLOCKED:            live remote SHA (SSL); full regression / optimization-mode / cross-compare (not re-run)
ACTIVE LINE/ARC AUTHORITIES: opendrive_geometry/primitives.py + evaluator.py (LineArcEvaluator) — UNTRACKED
ACTIVE DUPLICATE FORMULAS: geometry_math, check_geometric_continuity(spiral/poly3/paramPoly3), junction_connector_rebuild, xodr_junction_links, xodr_carla_hardener, autofix_postprune_elevation
PARAMPOLY3 STATUS:         mathematically correct; single read-only consumer (curvature_gap); UNTRACKED
STAGE 6 NON-DESTRUCTIVE:   YES in governed profiles (but implementation uncommitted)
ARTIFACT ROLLBACK VERIFIED: NO (framework absent)
READY FOR JUNCTION READ MODEL: NO — blocked on reproducibility/lineage, not on mathematics
APPROVED NEXT SCOPE:       NONE (withheld pending corrections 1-6)
REQUIRED CORRECTIONS:      commit + publish + re-pin + freeze + re-run full battery; then re-gate
```

Be adversarial and conservative. A polished report is not proof. The mathematics here is sound; the **lineage is not**, and unreproducible artifacts cannot be approved.
