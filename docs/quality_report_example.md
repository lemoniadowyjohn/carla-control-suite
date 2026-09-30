# Map Quality Report

**Gate:** PASS

## Metrics

| Metric | Value | Threshold |
|---|---:|---:|
| Symmetric Hausdorff | 0.033 m | ≤ 1.000 m |
| SE(2) alignment RMSE | 0.021 m | ≤ 0.500 m |
| Lane-width p95 deviation | 0.050 m | ≤ 0.150 m |
| Topology errors | 0 | ≤ 0 |

## Gate Findings

- No threshold violations.

## Provenance

- **reference:** `synthetic curve generated in examples/run_quality_demo.py`
- **observed:** `deterministically perturbed synthetic curve`
- **asset_policy:** `no proprietary map assets`
