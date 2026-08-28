# E1 Crash-Safe Elevation Repair

## Result

- Verdict: `CRASH_SAFE_LENGTH_REPAIR_PASS`
- Input: `reports/post_audit_hardening/20260804T050000Z/candidate_h_signal_enrichment.xodr`
- Output: `reports/post_audit_hardening/20260814T000000Z_E1_CRASH_SAFE_ELEVATION/candidate_h_elevated_enriched_crash_safe.xodr`
- Input sha256: `8050ade947111513af7fb4042a41b788b12fbee876d150e1c75f7113bfff7cd7`
- Output sha256: `ed2b8529ae400b3ef4259603c9935765f2966b25f44a2090e097b0a812987ac7`

## Repair

- Rule: C3 full-precision road length repair.
- For each road with planView geometry, set `length = repr(max(declared_length, max(geometry.s + geometry.length)) + 1e-3)`.
- Roads length-adjusted: `32710`
- Existing source artifact was not modified.

## Evidence

| Metric | Before | After |
|---|---:|---:|
| G19 length violations | 767 | 0 |
| Roads checked | 32710 | 32710 |
| Roads | 32710 | 32710 |
| Junctions | 3646 | 3646 |
| Signals | 3467 | 3467 |
| Objects | 0 | 0 |
| Crosswalk objects | 0 | 0 |
| Roads with elevation profile | 32710 | 32710 |
| Elevation segments | 418243 | 418243 |
| Nonzero elevation segments | 418243 | 418243 |

Structured report: `E1_CRASH_SAFE_ELEVATION_REPAIR.json`.

## Boundary

This is an offline candidate-generation artifact only. It does not certify the map, does not flip runtime gates, and still needs live CARLA load/drivability/perception evidence before promotion.

