# ARCH-002 adversarial test matrix

Status column: **RUN** = executed in this review, with the result shown. **PENDING** = the input
does not exist yet (C1 and O13), so the test is specified here to run as soon as it does. A PENDING
row is not a pass.

## A. Reproduction of the original failure (candidate `2cee039f`, stage-5 sha256 `45c52059…`)

| # | Test | Status | Result |
|---|---|---|---|
| A1 | Count zero-chord U-turn refits (analytic) | RUN | 3,375 |
| A2 | Same, kernel-only sampling | RUN | 3,375 |
| A3 | Direction reversals in U-turn refits (kernel) | RUN | 3,367 / 3,375 |
| A4 | Stationary points `|r′| < 1e-6·L` (analytic) | RUN | 2,734 (depends on the cut-off) |
| A5 | Self-intersections, N=800 analytic vs N=2000 kernel | RUN | 423 vs 426 (depends on sampling) |
| A6 | Arc/length off by more than 10% (non-U-turn) | RUN | 344 / 650; max 4.02 |
| A7 | Start displacement per refit | RUN | p50 3.25 m, p99 7.0 m, max 14.0 m; 26 move more than their own length |
| A8 | Moves equal to a cumulative incoming lane width (±1 cm) | RUN | 4,024 / 4,025 |
| A9 | Original connector start on the from-lane inner border (all connectors) | RUN | 19,195 / 22,588; 0 on the reference point otherwise |

## B. Negative tests for Codex C1 (PENDING: no patch exists)

Every test must **fail before** C1 and **pass after** it. Fixtures are minimal synthetic OpenDRIVE
unless a real road id is named. For the real ids, extract the road and its neighbours from
stage-5 `45c52059…`.

| # | Input | Expected after C1 |
|---|---|---|
| B1 | Connector from lane −2, reference line on the inner border of lane −2 (3.25 m off the reference point) | **not moved**; planView byte-identical; counter `skipped_lane_border_continuous` = 1 |
| B2 | Same as B1, but the start is off **every** lane border by 0.7 m | reported as displaced; if snapping is still enabled, refit gates apply |
| B3 | Shared-reference U-turn (real 51810 with 47570/42130) | not moved; `skipped_uturn_shared_reference` = 1; routing and links unchanged |
| B4 | Short connector, 3 m long, needing a 10.5 m move (real 68739) | refused (guard) or not selected; never refit with a stretched `length` |
| B5 | A refit whose arc length differs from `length` by more than 1e-4 relative | rejected; original planView restored byte-for-byte |
| B6 | A refit with a zero-speed point (synthetic `bU = L`, `cU = −L`) | rejected and restored |
| B7 | A refit that self-intersects (synthetic loop) | rejected and restored |
| B8 | Incoming touch at its `start`; exit linked with `contactPoint="end"` | required tangents flipped by π; heading error ≤ 1e-6 rad, or skipped; never a reversed tangent |
| B9 | A refit whose endpoints are exact but whose interior curvature exceeds the original peak | rejected (conservative default) |
| B10 | Residual visibility: after a full run, every skip and reject reason is counted in the report, and the totals add up (snapped + every skip = examined) | the report balances |
| B11 | No tolerance raised: `git diff` shows no increase in `max_gap_m`, `EXIT_HEADING_DISCONTINUITY_DEG` (30.0) or any validator constant | true |
| B12 | Default flag state documented and tested: `UP_ENABLE_JUNCTION_CONNECTOR_SNAP` default (if C1 changes it) | a test asserts the default |

## C. False-PASS attempts against OpenCode O13 (PENDING: no validator exists)

O13 is report-only, but its flags feed X8 gates, so a false negative is a release blocker.

| # | Attack input | O13 must report |
|---|---|---|
| C1 | paramPoly3 needle `bU = L, cU = −L, d = 0` (zero chord) | stationary point = true; arc/length = 0.5; not simple (if sampled finely) |
| C2 | Near-needle with `v` noise 1e-7 (no exact zero speed) | **direction reversal** = true. A speed-threshold-only detector misses it; this is the A3 vs A4 gap |
| C3 | A cubic whose loop is smaller than the sampling step (a tiny curl at p ≈ 0.5, radius 1 mm) | adaptive or analytic detection. A fixed-N sampler must not report "simple" without a resolution statement |
| C4 | `pRange="arcLength"` paramPoly3 with `length` ≠ the true arc length | arc mismatch flagged (the parameter range must not be assumed normalized) |
| C5 | A `spiral` primitive (the kernel supports it) with a very large curvature rate | curvature evaluated through the kernel, not finite-difference aliasing; finite values |
| C6 | An unknown primitive (e.g. `<poly3>` missing attributes, or an unsupported tag) | **status UNVERIFIED, never PASS** (pre-declared blocker) |
| C7 | NaN or Inf in `length`, `x`, `hdg` or a coefficient | flagged invalid; no exception that hides the road; never PASS |
| C8 | Heading wrap: tangent jumps from +179.9° to −179.9° | not counted as a reversal (wrap-aware difference) |
| C9 | Legal reversed reference line: a road whose lanes are all positive ids, linked exit → incoming | **not** flagged as a driving reversal (reference-line orientation is legal) |
| C10 | A true reversal: lane direction opposes the routing | flagged |
| C11 | Zero-length geometry (`length = 0`) | flagged degenerate; no division by zero |
| C12 | Multi-geometry road with a G0 gap between geometries | the gap is reported (not only the end-to-end chord) |
| C13 | Curvature normalization: the analytic κ uses derivatives with respect to p; check `κ = |x′y″ − y′x″| / |r′|³` (p-invariant) against a known arc of radius R | |κ − 1/R| ≤ 1e-9 |
| C14 | Threshold policy: run with no thresholds configured | outputs measurements and "threshold: unset"; never a pass/fail invented by the tool |
