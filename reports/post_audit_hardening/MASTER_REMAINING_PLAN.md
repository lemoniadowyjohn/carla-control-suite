# Master Remaining Plan

Date: 2026-08-15

This file records the remaining thesis/completion work after E1/E1B/E2, harness hardening, A1, A2, A3, A4, and the methodology-gap audit.

## Highest-Value Code Items

| ID | Area | Status | Purpose |
| --- | --- | --- | --- |
| C0 | Auto map regeneration | New required gate | Re-run the fixed pipeline so the map artifact of record actually contains C5/D1/D2/class-policy-era fixes. |
| C5 | Lane-width fidelity | Implemented in this change | Remove the constant 6.0 m auto-map lane-width confound before RQ1 structural comparison. |
| C1 | Auto map of record | Pending after C0 | Pin the regenerated candidate by digest and provenance; do not pin stale `352c9003`/older artifacts by default. |
| C2/B3 | Manual map registry and loadability | Pending | Bring the manual reference onto the branch, content-address it, and verify or repair loadability. |
| C6 | Object/prop density | Pending | Increase XODR-representable props beyond 66 where grounded. |
| C3 | OSM input guard | Pending | Fail closed on HTML/error/empty OSM in the main entry. |
| C4 | Auto-map provenance | Pending | Record OSM/DEM/config sha, pipeline commit, and bbox. |
| B1 | Determinism study | Pending | Produce one deterministic/natural-randomization verdict for R2/R5. |
| B2 | Calibration placement | Implemented via D2 in this change | Promote `calib_data.json` into the canonical sensor tree and lock rig semantics. |
| B4 | Auto-vs-manual RQ1 result | Pending after B3/C5 | Run structural comparison on pinned, loadable maps. |
| D1 | Visual vertical datum | Implemented; D1b partial review required | DEM-warp the supplemental OSM2World environment mesh so visual objects share the road network's elevation source. |
| D2 | Sensor calibration semantics | Implemented in this change | Resolve the `use_K_undistortion` / `ignore_K,D` contradiction and lock effective CARLA intrinsics. |
| D3 | Alignment transform verifier | Pending | Prove mesh/XODR/Unreal/CARLA transform is applied exactly once. |
| D4 | Cook scaffold | Pending | Add UE4.26/CARLA 0.9.16 dry-run cook automation structure for the operator/toolchain step. |
| D5 | Fair capture protocol | Pending | Pin same-assets/same-rig capture config for auto and manual maps. |

## Non-Code Gates

These cannot be closed by offline Codex work:

1. Unreal cook of both maps with the same visual assets.
2. Live CARLA capture with the same `calib_data.json` rig and fairness protocol.
3. Real Ingolstadt dataset path for R8.
4. Experiment design: splits, seeds, frame counts, baselines, and controls.
5. Claim boundary: unlabeled real evaluation measures domain shift/uncertainty, not real-world accuracy.

## Current Priority

C5 is addressed at the code/tooling level and a new width-faithful E2-derived candidate was produced as an uncommitted artifact. D1 is addressed at the code/tooling level and a DEM-elevated visual OBJ was produced as an uncommitted artifact, but D1b found an at-grade residual tail that needs review before cook. D2/B2 is addressed at the contract/test level with canonical calibration placement and locked cTv/vTl semantics. The next gating dependency is C0/C1: regenerate the auto map through the fixed pipeline and pin that regenerated candidate as the auto map of record. After that, the next RQ1 dependency is B3/C2: pin and verify the manual reference before running B4. The next visual dependency is D3 before D4 cook dry-run scaffolding.
