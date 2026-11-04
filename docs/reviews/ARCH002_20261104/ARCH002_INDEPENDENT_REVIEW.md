# ARCH-002 — Independent adversarial review of the "hardened" GAP-070 geometry (2026-11-04)

**Reviewer:** Claude (Opus 5.5), read-only. No source, map, branch or evidence was changed, and CARLA
was not started.
**Verdict: `REQUIRES_SOURCE_HARDENING`** (`ARCH002_X8_READINESS_VERDICT.json`).

## 0. The inputs to review do not exist yet

| Input | Expected | Found |
|---|---|---|
| Codex C1 patch and tests | a commit on a C1 branch | worktree `E:/wt/fix-gap070-connector-snap-safety-c1-20261104` exists on branch `fix/gap070-connector-snap-safety-c1-20261104` at **`2cee039f`** (the unhardened candidate). **0 commits and 0 uncommitted changes.** |
| OpenCode O13 validator | `tools/check_connector_curve_invariants.py` + tests | **not present** in any worktree or branch |
| ARCH_X8_X9 review | `docs/reviews/ARCH_X8_X9_20261104/` | present (local, untracked) |
| Candidate baseline | `2cee039f` | present (GitHub) |
| Integration baseline | `1a36b560` | present (GitHub) |
| Stage-5 source | sha256 `45c52059ec5b7d8d1e5f2f90a2f814bde465a923e7e77768c5f5e660790c721c` | present locally; **verified** (sha256sum, 138,932,131 bytes). **Not on GitHub.** |

Objectives **B** (audit C1) and **C** (audit O13) therefore **could not be executed**. They are
marked `NOT_RUN — input missing`, not passed. `ARCH002_ADVERSARIAL_TEST_MATRIX.md` gives the exact
negative tests to run against C1 and O13 once they exist. Objectives **A** and **D** were executed.

## A. Reproduction of the original failure (second, independent method)

The ARCH_X8_X9 numbers came from analytic paramPoly3 derivatives (`x7_geom_audit.py`, N = 800). For
this review they were recomputed with a different method, `x7_crosscheck_kernel.py`:
- the geometry is sampled **only** through the canonical kernel `pose_at_s` (N = 2,000 per refit);
- arc length = the sum of sample chords;
- a direction reversal = consecutive displacement vectors with a negative dot product;
- self-intersection = shapely `is_simple`.
The candidate was `2cee039f`, run in memory on the stage-5 input above.

| Claim (ARCH_X8_X9) | Method 1 (analytic, N=800) | Method 2 (kernel, N=2000) | Verdict |
|---|---|---|---|
| 3,375 unsafe U-turn refits | 3,375 | 3,375 | **CONFIRMED** |
| 2,734 stationary/reversal points | 2,734 (`|r′| < 1e-6·L`) | **3,367** of 3,375 U-turns reverse direction | **CORRECTED.** The 2,734 depends on the cut-off; the robust count is 3,367 reversing. Both are severe. |
| 423 self-intersections | 423 | 426 | **CONFIRMED, with sampling dependence** (± 3); report it as ≥ 423 |
| 344 large length mismatches (> 10%) | 344 | 344 | **CONFIRMED.** Max arc/length is **4.02** (ARCH_X8_X9 said "worst 3.7×" for the top-curvature examples; the overall maximum is 4.02) |
| Excessive movement on short connectors | "≈ 8 m" for 68739 (inferred) | **10.5 m** measured (`entry_error_before_m`) on a 2.99 m road. 26 refits move more than their own length; 132 move more than 5 m; the maximum is 14.0 m | **CORRECTED** (larger than stated) |
| Non-U-turn refits have no cusps or loops | 0 / 0 | 0 / 0 | **CONFIRMED** |

## A+. New finding: the snap's premise is false (it undoes correct lane-border placement)

`evidence/x7_displacement.py` and `evidence/lane_border_check.py`, read-only, on the stage-5 input
before any snap:

- **4,024 of the 4,025** snap moves equal, to within 1 cm, a cumulative lane width of the incoming
  road. The most common moves are 3.25 m (2,671), 3.0 m (575), 3.5 m (574), 7.0 m (71), 3.75 m (59),
  6.5 m (30), 10.5 m (18) and 2.75 m (12).
- Over **all** 22,588 junction connectors, before the snap:
  - **19,195 (85%) start exactly (≤ 1 cm) on the inner border of their `laneLink` *from* lane** on
    the incoming road;
  - **0 start on the incoming road's reference point**, except where that point *is* the from-lane's
    inner border (from-lane = ±1).
- For the 650 non-U-turn refits, the move equals that inner-border offset (651 matches, including one
  of the U-turn group).

**Interpretation.** The connector reference lines are deliberately placed on the inner border of the
lane they continue. A connector that carries traffic from lane −2 starts one lane width (3.25 m) to
the side, and its lane −1 then continues the incoming lane −2 exactly. That is lane-level continuity
by construction.

The snap (`junction_connector_snap.py`) treats any start more than 2 m from the incoming reference
point as "displaced" (`:382`). That selects exactly the connectors fed from an outer lane, and moves
their reference line onto the incoming reference line. **This shifts every lane of those connectors
sideways by one or more lane widths.** The merged snap does this too (it rotates in place, `:289` on
`1a36b560`); the candidate adds the Hermite refit on top.

**Consequences.**
1. GAP-070's real damage is larger than the exit-kink count. On the 650 non-U-turn refits the snap
   most likely introduces **lane-level** discontinuities of whole lane widths. No current metric
   measures this (ARCH_X8_X9 F-08).
2. The "entry mismatch" metric (`_count_junction_issues`, 4,092 at stage 5) compares reference
   lines, so it scores correct lane-border placement as a defect. **It is largely a false-positive
   metric.** The 2026-09-12 decision to enable the snap by default relied on it (8,746 → 5,183).
3. Hardening the Hermite refit (C1 as specified in the ARCH_X8_X9 backlog) treats the symptom. The
   minimal source-stage remedy is to **stop snapping lane-border-placed connectors**, which on this
   map means the snap should not act at all: set `UP_ENABLE_JUNCTION_CONNECTOR_SNAP` default `"0"`
   (`stage_05_geometry.py:103`), and keep the tool for report-only diagnosis. X8 arm C (snap
   disabled) is then the candidate, not just the control.

**Not yet verified (stated plainly):**
- that lane-centre continuity actually holds before the snap and breaks after it. That needs the
  lane-centre check (F-08) including laneOffset, width polynomials and the connector's own lanes;
  `lane_border_check.py` only tests the reference point against the from-lane inner border;
- the lane-level consistency of the 3,393 connectors that match neither pattern (mostly U-turns,
  e.g. 51810: 3.25 m from both the reference point and the inner border). Those are lane −1 → −1
  U-turns placed one lane width away; their correctness is **unverified**;
- CARLA traversability of any variant (GAP-077 still blocks runtime).

## B. Audit of Codex C1 — `NOT_RUN` (no patch exists)
The checks to apply are in `ARCH002_ADVERSARIAL_TEST_MATRIX.md` §B. **Recommendation to redirect C1
before it starts coding:** its primary change should be the snap default (or a lane-border-aware
"already continuous" classification that skips those connectors), not the Hermite refit. U-turn
exclusion, the arc-length gates and the displacement bound remain necessary **only if** the operator
keeps any snapping enabled.

## C. Audit of OpenCode O13 — `NOT_RUN` (no validator exists)
The false-PASS inputs are pre-specified in `ARCH002_ADVERSARIAL_TEST_MATRIX.md` §C. One release
blocker is pre-declared there: a validator that returns PASS for a primitive it cannot evaluate.

## D. What is resolved and what is open

| Item | Status | Evidence |
|---|---|---|
| Snap-induced exit kink (~53°, 3,373) | **Root cause known; NOT fixed.** The merged snap is still default ON on `1a36b560`; the candidate replaces the kink with degenerate geometry | ARCH_X8_X9 F-01/F-02; §A here |
| Physically feasible connectors after the snap | **NOT achieved** by `2cee039f`: 3,375 degenerate, 344 length-inconsistent, 28 with radius < 2 m among the others | §A |
| Lane-level continuity | **Most likely broken by the snap** (merged and candidate) for the snapped outer-lane connectors; unmeasured at lane-centre level | §A+ |
| Pre-existing Osm2Odr U-turn geometry (radius ≈ 1.6 m, 3,949 U-turns at stage 01) | **OPEN, unrelated to the snap.** Drivability needs an operator decision on the minimum radius and a CARLA check | ARCH_X8_X9 summary item 3 |
| GAP-079 reversed 0.1 m stubs | **OPEN.** Inventory only; X9b part 2 in progress (smoke test passed, no results committed) | `06a31ed1` (local branch) |
| CARLA traversability | **NOT demonstrated** (GAP-077) | — |

## E. X8 readiness: `REQUIRES_SOURCE_HARDENING`

X8 must not run until the source change exists and has been reviewed. Running it now would only
measure the known-bad configurations. Minimum path:
1. **Source change (Codex or a Sonnet implementer, small):** snap default OFF, or a lane-border-aware
   skip, with failing-first tests:
   - a lane −2 → −1 connector placed on the inner border of lane −2 is not moved;
   - a connector actually displaced off every lane border is still reported;
   - the U-turn case is not moved.
2. **O13 + a new lane-centre continuity checker (report-only)** to measure §A+ at lane level.
3. **X8** with arms C (snap off, now the candidate), A (merged snap) and, optionally, a hardened
   snap. Add a lane-centre continuity comparison, and run the full ARCH_X8_X9 invariant matrix.
4. **Resources:** ≥ 15 GB free on one non-quarantined drive. This is also blocking today (E: 1.1 GB
   free at the time of this review).
5. **Evidence:** archive the stage files (C0 package), so the findings can be reproduced remotely.
