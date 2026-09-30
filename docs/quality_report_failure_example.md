# Map Quality Report — Intentional Failure Demonstration

**Gate:** FAIL

This report is deliberately generated from a synthetic degraded scenario to demonstrate rejection behavior. It is not a claim about a private or production map.

## Metrics

| Metric | Value | Threshold |
|---|---:|---:|
| Symmetric Hausdorff | 1.500 m | ≤ 1.000 m |
| SE(2) alignment RMSE | 0.800 m | ≤ 0.500 m |
| Lane-width p95 deviation | 0.300 m | ≤ 0.150 m |
| Topology errors | 2 | ≤ 0 |

## Gate Findings

- Hausdorff distance exceeds geometric threshold.
- SE(2) alignment residual exceeds threshold.
- Lane-width p95 deviation exceeds threshold.
- Topology validation found invalid references/lane links.

## Expected CLI behavior

```bash
carla-map-quality demo --inject-failure --output out/failure
```

Expected process exit code: `2`.

## Provenance

- **fixture:** `synthetic_straight_road_v1`
- **source:** `generated; no proprietary assets`
- **alignment:** `paired-point deterministic SE(2)`
- **mode:** `intentional_failure`
