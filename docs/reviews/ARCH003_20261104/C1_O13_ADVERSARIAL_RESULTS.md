# C1 / O13 adversarial results (ARCH-003 tasks 2-3)

## C1 — PRELIMINARY review of uncommitted work in progress (not an acceptance review)

**Scope:** `git diff` in `E:/wt/fix-gap070-connector-snap-safety-c1-20261104` (base `2cee039f`),
read-only. Codex may still be editing. **These comments must be re-checked against the final
commit.**

| ID | Severity | Location | Finding | Required change | Test |
|---|---|---|---|---|---|
| C1-01 | OK | `ultimate_pipeline/pipeline_stages/stage_05_geometry.py` (`_run_junction_connector_snap`) | Default changed from `"1"` to `"0"`; docstring explains the lane-border reason. Supported by ARCH-003 L-01/L-03. | — | `test_connector_snap_is_disabled_by_default_and_records_policy` (in progress) |
| C1-02 | **P1** | same function, disabled branch | The disabled report states `"residual_count": 0` and `"connectors_examined": 0`. Read downstream, **"0 residuals" hides the 3,700+ U-turn and 114 non-U-turn lane-level discontinuities** that remain with the snap off. Violates "defects unchanged by default-off must remain visible". | Use `"residual_count": null` and `"residuals_measured": false`. **Better:** in the disabled path, run a report-only diagnostic (lane-centre continuity or `_count_junction_issues`) without mutating, and report its counts. | assert that the disabled report does not contain `residual_count == 0` unless it was measured |
| C1-03 | **P1** | same function, enabled branch | Opt-in through `UP_ENABLE_JUNCTION_CONNECTOR_SNAP=1` still runs the **unhardened** `2cee039f` Hermite refit (3,375 degenerate refits; ARCH-X8-X9 F-01). Nothing refuses it under `THESIS_STRICT` or `RELEASE_PROFILE`, so the label "experimental opt-in only" is not enforced. | Refuse (raise) when opt-in is combined with THESIS_STRICT or a release profile, unless an explicit, logged `UP_ALLOW_UNQUALIFIED_SNAP=1` is also set. Record `"qualification": "UNQUALIFIED_EXPERIMENTAL"` in the report. | negative test: strict + opt-in raises; non-strict opt-in records UNQUALIFIED |
| C1-04 | P2 | same function | The disabled branch writes `junction_connector_snap_report.json` with a plain `open()`, while Stage-6 reports were made atomic in this PR series. | use the repo's atomic JSON writer | — |
| C1-05 | P2 | tests | The negative tests from ARCH-002 §B are not present yet (B1-B3 lane-border not moved, B11 no threshold raise, B12 default asserted). Only B12 is partially covered. | add B1-B3 and B11 | — |
| C1-06 | INFO | historical evidence | The docstring removes the 2026-09-12 reference to `CONNECTOR_SNAP_WIRING_EVIDENCE.json` (8,746 → 5,183 issues). That evidence must stay intact; it is frozen. A note that it measured a reference-line metric that scores lane-border placement as a defect belongs in a new addendum, not an edit. | confirm no `reports/` file is modified | `git diff --stat -- reports/` is empty |

**Status: C1 not yet reviewable for acceptance.** Re-run this table on the C1 commit.

## O13 — `NOT_RUN` (the validator does not exist)

All 14 false-PASS attacks from `docs/reviews/ARCH002_20261104/ARCH002_ADVERSARIAL_TEST_MATRIX.md` §C stay
PENDING. ARCH-003 adds these four, so 18 must pass before O13's output can gate X8:

| # | Attack | O13 must report |
|---|---|---|
| C15 | Curved lane border: a connector whose `to` lane width varies (cubic `b, c ≠ 0`), so the lane-centre point at s = 0 differs from a constant-width estimate | lane-centre gap computed with the width polynomial, not width `a` alone |
| C16 | Legal U-turn: shared-reference twin roads, with a connector whose lanes are on the correct side and links consistent | no "reversal". Gap and kink measured at lane level and reported as U-turn class. |
| C17 | Junction mediation: incoming road linked to the junction through `predecessor` (its start), not its end | the incoming end is chosen from the road `link` to *this* junction id, not by nearest distance |
| C18 | `contactPoint="end"` connection | entry is evaluated at the connector's end, and the lane direction is handled; never silently skipped as "OK" |

**Pre-declared release blockers for O13:**
- PASS for an unevaluated primitive (C6);
- PASS with non-finite values (C7);
- a fixed-resolution "simple" verdict without stating the sampling resolution (C3).
