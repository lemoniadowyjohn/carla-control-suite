# C24 — Curvature Robust Metric

## Finding
RQ1 already fixed the original curvature-stub defect, but the scalar `curvature_gap`
remained a 30-bin histogram-L1 metric whose value can move when one extreme curvature
sample stretches the histogram range. That makes it a bounded signal, not a precise scalar.

## Fix
Added `curvature_wasserstein_gap` as a companion metric in
`ultimate_pipeline/domain_gap/gap_analyzer.py`.

- Uses absolute curvature samples.
- Drops non-finite/non-numeric values fail-safe.
- Computes Wasserstein distance and normalizes by `0.2 1/m`.
- Keeps the historical `curvature_gap` unchanged for comparability.

## Evidence
Pinned pair:

- Auto: `69b1f52016ebdc3e643616f86161d85789624c94d48e5caf56c53004d534de6e`
- Manual Grid0828: `5eaece230e02f6c1b2075db851894870790e86ac64710abb3465bcfc533e9b0c`

Whole-map RQ1:

- `curvature_gap`: `0.09311717328016497`
- `curvature_wasserstein_gap`: `0.07413802792389068`

Local Grid0828-footprint RQ1:

- `local_curvature_gap`: `0.223946700153908`
- `local_curvature_wasserstein_gap`: `0.07398195152408996`

Interpretation: the local histogram-L1 gap is sharper because bin occupancy differs inside
the cropped manual footprint, but the range-robust Wasserstein distance remains modest and
consistent with the whole-map value. The defensible RQ1 claim is still road-network
completeness (`4.5x` length, `6.0x` junctions, `6.1x` roads), not a large curvature-domain
gap.

## Tests
Focused verification:

```text
33 passed, 3 warnings
```

Command:

```powershell
$env:UP_DISABLE_CARLA='1'; .\.venv\Scripts\python.exe -m pytest tests\unit\test_curvature_wasserstein_gap.py tests\unit\test_gap_analyzer_xodr_to_xodr.py tests\unit\test_domain_gap_metrics.py tests\unit\test_export_thesis_tables.py tests\unit\test_local_registration.py -q
```

## Verdict
CURVATURE_ROBUST_METRIC_GREEN
