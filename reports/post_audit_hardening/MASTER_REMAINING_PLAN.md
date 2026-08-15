# Master Remaining Plan

Date: 2026-08-15

This file records the remaining thesis/completion work after E1/E1B/E2, harness hardening, A1, A2, A3, A4, and the methodology-gap audit.

## Highest-Value Code Items

| ID | Area | Status | Purpose |
| --- | --- | --- | --- |
| C5 | Lane-width fidelity | Implemented in this change | Remove the constant 6.0 m auto-map lane-width confound before RQ1 structural comparison. |
| C1 | Auto map of record | Pending | Pin `352c9003` / successor by digest and provenance. |
| C2/B3 | Manual map registry and loadability | Pending | Bring the manual reference onto the branch, content-address it, and verify or repair loadability. |
| C6 | Object/prop density | Pending | Increase XODR-representable props beyond 66 where grounded. |
| C3 | OSM input guard | Pending | Fail closed on HTML/error/empty OSM in the main entry. |
| C4 | Auto-map provenance | Pending | Record OSM/DEM/config sha, pipeline commit, and bbox. |
| B1 | Determinism study | Pending | Produce one deterministic/natural-randomization verdict for R2/R5. |
| B2 | Calibration placement | Pending | Promote `calib_data.json` into the canonical sensor tree and lock rig semantics. |
| B4 | Auto-vs-manual RQ1 result | Pending after B3/C5 | Run structural comparison on pinned, loadable maps. |

## Non-Code Gates

These cannot be closed by offline Codex work:

1. Unreal cook of both maps with the same visual assets.
2. Live CARLA capture with the same `calib_data.json` rig and fairness protocol.
3. Real Ingolstadt dataset path for R8.
4. Experiment design: splits, seeds, frame counts, baselines, and controls.
5. Claim boundary: unlabeled real evaluation measures domain shift/uncertainty, not real-world accuracy.

## Current Priority

C5 is now addressed at the code/tooling level and a new width-faithful E2-derived candidate was produced as an uncommitted artifact. The next code dependency for RQ1 is B3/C2: pin and verify the manual reference before running B4.
