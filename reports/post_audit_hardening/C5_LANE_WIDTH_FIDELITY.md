# C5 Lane-Width Fidelity

Date: 2026-08-15

## Verdict

`LANE_WIDTH_CONFUND_REMOVED_GREEN_WITH_FALLBACK_CAVEAT`

The constant 6.0 m driving-lane placeholder is removed from the E2 drivable candidate without changing roads, junctions, signals, objects, elevation, G19 length invariants, or strict/preflight error status.

This is not a full OSM lane-count reconstruction. The generated candidate uses recovered OSM highway metadata where available and a documented 3.5 m fallback elsewhere because the E2 XODR does not carry direct OSM way metadata for most roads.

## Inputs And Output

| Artifact | Path | sha256 |
| --- | --- | --- |
| Parent E2 candidate | `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_drivable.xodr` | `352c9003e653027f41ecda5ef11f59a11b07b0ce7294ea1d7d21e4bcc7e63c52` |
| C5 output candidate | `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_drivable_width_faithful.xodr` | `928e5b2397c9eb85448542178766ce8093f4f4457dabf4a7e2c86952b5898b2b` |
| Policy run report | `reports/post_audit_hardening/C5_LANE_WIDTH_POLICY_RUN.json` | committed |

The C5 output candidate is a large `.xodr` artifact and is intentionally not committed.

## Lane-Width Evidence

| Metric | Parent E2 | C5 output |
| --- | ---: | ---: |
| Driving width records | 34,679 | 34,679 |
| Unique driving widths | 2 | 4 |
| 6.0 m placeholders | 34,675 | 0 |
| Min driving width | 3.2 m | 3.0 m |
| Mean driving width | 5.999677 m | 3.476975 m |
| Median driving width | 6.0 m | 3.5 m |
| Max driving width | 6.0 m | 3.75 m |

Final distribution:

| Width | Count |
| ---: | ---: |
| 3.0 m | 462 |
| 3.25 m | 2,355 |
| 3.5 m | 31,777 |
| 3.75 m | 85 |

Policy source coverage is per road:

| Source | Roads |
| --- | ---: |
| Recovered OSM highway metadata | 3,335 |
| Documented fallback | 29,375 |

## Preservation Evidence

| Metric | Parent E2 | C5 output |
| --- | ---: | ---: |
| Roads | 32,710 | 32,710 |
| Junctions | 3,646 | 3,646 |
| Signals | 3,467 | 3,467 |
| Objects | 66 | 66 |
| Elevation records | 418,243 | 418,243 |
| Non-zero elevation records | 418,243 | 418,243 |
| G19 length-invariant violations | 0 | 0 |
| Strict validator errors | 0 | 0 |
| XML uniqueness issues | 0 | 0 |
| Preflight status | ok | ok |
| Preflight errors | 0 | 0 |
| Preflight warnings | 80,265 | 80,265 |

## Code Changes

- Added `ultimate_pipeline.enrichment.lane_width_policy`: shared OSM/fallback lane-width policy.
- Extended `ultimate_pipeline.enrichment.osm_meta_index` to preserve `highway`, `lanes`, and `width` tags.
- Changed CARLA OSM converter defaults from 6.0 m to 3.5 m.
- Wired the policy into `LaneGenerator` and `LaneRepair`, including a stage-7 `lane_width_policy_report.json`.
- Replaced `ultimate_pipeline.tools.repair_lane_widths` with a governed file-level repair tool that writes a new candidate and JSON report.
- Added `tests/unit/test_lane_width_policy.py`.

## Tests

- C5 targeted red state: `5 failed` before implementation, then `1 failed, 5 passed` before the file-tool fix.
- C5 targeted final: `6 passed in 0.11s`.
- Baseline full suite before C5: `688 passed, 49 warnings in 50.33s` (post-A4).
- Full suite after C5: `694 passed, 49 warnings in 161.53s`.

## Escalate To Claude

- Residual fallback coverage is high: 29,375 of 32,710 roads lack direct width-relevant OSM provenance in the E2 XODR. The 6.0 m confound is removed, but RQ1 should report width-source coverage or add a C5B road-to-OSM matching pass.
- Lane counts are not reconstructed. The auto map still mostly models simplified lane topology; B4 should avoid interpreting remaining lane-count differences as pure map-generation fidelity.
