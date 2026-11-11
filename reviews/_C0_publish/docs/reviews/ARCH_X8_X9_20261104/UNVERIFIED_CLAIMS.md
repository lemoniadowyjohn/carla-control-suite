# Claims that are not remotely verified

## 1. Claims that need local-only inputs (`LOCAL_REPRODUCED_NOT_REMOTE_VERIFIED`)
All of these need the stage files (see `PROVENANCE.json`). They were executed locally, and at least
the first two were reproduced from the published scripts.

| Claim | Input | Script |
|---|---|---|
| 4,025 refits; 3,375 zero-chord U-turns; arc/length 0.50 for all U-turns | 05 | `x7_geom_audit.py`, `x7_crosscheck_kernel.py` |
| 3,367 U-turn refits reverse direction; 2,734 stationary points (cut-off `1e-6·L`) | 05 | both |
| 423 / 426 self-intersections | 05 | both |
| 344 of 650 other refits have arc/length off by > 10%; max 4.02; 28 with radius < 2 m (3 before); 81 with doubled peak curvature | 05 | `x7_geom_audit.py` |
| Start moves p50 3.25 m, max 14.0 m; 26 larger than the connector length; 68739 moved 10.5 m | 05 | `x7_displacement.py` |
| 4,024 / 4,025 moves equal a cumulative incoming lane width | 05 | `x7_displacement.py` |
| 19,195 / 22,588 connectors start on their from-lane inner border; 0 on the reference point otherwise | 05 | `lane_border_check.py` |
| U-turn connectors: 3,949 / 3,944 / 3,944 at stages 01 / 02 / 05 (3,521 / 3,507 / 3,507 coincident) | 01, 02, 05 | `uturn_count.py` |
| Pre-snap U-turn peak curvature ≈ 0.61 m⁻¹ (radius ≈ 1.6 m) | 05 | `x7_geom_audit.py` (kernel baseline, N=60 per geometry) |
| GAP-079: 58 / 81 stubs, all with declared routing | 01, 02 + `stub_inventory.json` (local branch) | `x9check.py` |
| Stage 03 and stage 05 are byte-identical | 03, 05 | `sha256sum` |

## 2. Claims that are inferences, not measurements
- "The snap breaks lane-level continuity for the outer-lane connectors". This is inferred from the
  reference-point vs lane-border positions. **Lane-centre continuity before and after the snap was
  not measured** (ARCH_X8_X9 F-08).
- "The U-turn connectors (3,393 that match neither pattern) are lane-consistent". This is
  **unknown**.
- "GAP-070's ~53° kinks are the 3,375 U-turn refits". This rests on matching counts (3,373 vs 3,375)
  and the rotation mechanism (−atan(½)). No one-to-one id match between the kink list and the refit
  list was run.
- "The 2026-09-12 enable-by-default decision relied on a false-positive metric". This follows from
  the metric's definition and the lane-border result; the 2026-09-12 inputs were not re-measured.

## 3. Claims that depend on other agents' reports (not re-run here)
- The candidate receipt's figures (entry 4,092 → 67, end 4,043 → 560, exit kinks 351 → 349). These
  were re-measured once earlier, in a separate session, not in this package.
- The producing commit of run `20261007_214826_524342` (`22cf39ab`), taken from the run's metadata.
- X9b part 2 progress (Codex smoke test passed; no results committed).

## 4. Explicitly not claimed
- That any GitHub CI run reproduced these numbers.
- CARLA loadability or traversability of any variant (GAP-077 blocks runtime).
- That C1 or O13 exist or were reviewed. **They do not exist yet**; ARCH-002 §B and §C are NOT_RUN.
