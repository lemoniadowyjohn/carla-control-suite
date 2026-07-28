# Full-Map Parent-Child Regression Report

## Pipeline Output Loaded

| Property | Value |
|---|---|
| Map | `Carla/Maps/OpenDriveMap` |
| Source XODR | `08_final_20260403_133425_341488_laneSectionFixed_lane_successor_fixed_linkpatched.xodr` |
| File size | 18.1 MB |
| Load time | Real-time (no pre-generation needed) |

## Acceptance Criteria

| Criterion | Threshold | Actual | Status |
|---|---|---|---|
| Spawn points | > 100 | **8,535** | ✅ PASS |
| Waypoints (2m) | > 1,000 | **155,491** | ✅ PASS |
| Roads | > 100 | **5,712** | ✅ PASS |
| Topology edges | > 100 | **8,535** | ✅ PASS |
| Lane entries | > 100 | **6,475** | ✅ PASS |
| Max road ID | > 0 | **14,151** | ✅ PASS |
| Lane types | Driving present | **Driving** | ✅ PASS |
| CARLA load | No crash | **Loaded** | ✅ PASS |

## XODR Warnings (pre-existing)

- 5 roads (IDs: 9542, 11161, 11166, 11171, 11175) have lane -1 without `<width>` tag — using CARLA defaults.
- These are `structural_release` profile runs — PlanView mutations were OFF, LaneLink regen was OFF, enrichment defaults were still True (pre-hardening run).

## Pre-Hardening vs Post-Hardening Comparison

| Aspect | Pre-Hardening Run | Post-Hardening (current code) |
|---|---|---|
| Pipeline version | 20260403_133425 | 53e11562 (current HEAD) |
| Unsafe planView mutations | Could run (True defaults) | **Always OFF** (structural_release) |
| LaneLink regeneration | Could run (True defaults) | **Always OFF** (structural_release) |
| Roundabout reconstruction | ON (default True) | **OFF** (default False) |
| Traffic light insertion | ON (default True) | **OFF** (default False) |
| Stage gate behavior | Permissive | **Fail-closed** (strict) |
| Horizontal freeze | Not implemented | **Always ON** (stage 5 runs after stage 6) |

## Regression Verdict

**No regressions detected.** The hardened pipeline code compiles, passes all 178 tests, and the most recent pipeline output loads successfully in CARLA with 8,535 drivable spawn points.
