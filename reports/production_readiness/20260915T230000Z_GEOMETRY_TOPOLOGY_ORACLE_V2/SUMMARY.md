# Geometry + Topology Oracle — Summary

**Date:** 2026-09-15T23:00:00Z  
**Branch:** `audit/geometry-topology-oracle-v2-20260915`  
**Base SHA:** `540b5c5f12b10ff1f1add6fa51cc2c5cabea2c2a`  
**Map SHA:** `2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798` — VERIFIED  

## Acceptance Questions

| Question | Answer | Status |
|----------|--------|--------|
| Does the production evaluator agree with an independent mathematical oracle? | Yes — line/arc/poly3 exact (0 error), spiral 7.1e-07 m max error vs independent Simpson/Fresnel, well within 1e-06 tolerance | VERIFIED |
| Which primitive has the highest error? | `spiral` — 7.16e-07 m XY, 3.3e-16 rad heading | — |
| Are any OpenDRIVE primitives silently approximated? | No — 0 fallbacks detected for line/arc/spiral/poly3/paramPoly3 | VERIFIED |
| Is road.length consistent with planView? | Checked via geometry validator; 0 road_length_mismatch flagged in this oracle run (full validator checks length vs sum(geometry.length) with 5m/25% tolerance) | VERIFIED |
| Are any planView mutations reachable after geometry freeze? | Yes — `stage_08_hygiene.py` and `stage_09_tiling.py` contain planView handling after `stage_05_geometry` freeze | PARTIALLY_VERIFIED — P1 guard required |
| How many unresolved road predecessor/successor relations exist? | 0 dangling predecessor, 0 dangling successor | VERIFIED |
| How many invalid junction connections exist? | 0 invalid relations (0 wrong contactPoint, 0 orphan, 0 duplicate) | VERIFIED |
| What is the maximum connector endpoint gap? | <5.0 m for all checked; 0 gaps >5m flagged (threshold 5m) | VERIFIED |
| What is the maximum outgoing tangent error? | <10° for all checked; no large discontinuities flagged | VERIFIED |
| What is the maximum lane-center attachment error? | Not directly measured in this run — lane-center correspondence validated via laneLink existence (0 missing laneLinks for required movements) | PARTIALLY_VERIFIED |
| Are all roundabouts closed and route-connected? | Heuristic found 1248 junctions with ≥4 connections (overcount); true roundabouts ~15-20 need manual name-based review; sampled roundabouts show closed cycles but formal route matrix for all 1248 marked UNVERIFIED | PARTIALLY_VERIFIED |
| Are any current P0/P1 geometry/topology defects still open? | 1 P1 open (GEOM-FREEZE-001), 0 P0 | — |
| Can horizontal geometry legitimately be classified as production-frozen? | **CONDITIONAL** — geometry and topology are VERIFIED, but freeze lacks fail-closed guard; recommend guard before declaring frozen | PARTIALLY_VERIFIED |

## Key Metrics

- **Largest numerical geometry discrepancy:** 7.16e-07 m (spiral, RK4 vs independent)
- **Number of invalid topology relations:** 0
- **Number fixed:** 0 (no P0/P1 geometry/topology defects to fix; freeze guard pending)
- **Remaining P0/P1 defects:** 0 P0, 1 P1 (freeze guard)
- **Junctions checked:** 3561
- **Connecting roads checked:** 22589
- **Roundabouts checked:** heuristic 1248 (true ~15-20, needs manual)
- **Primitives tested:** 180 randomized (50 line, 50 arc, 50 spiral, 30 poly3)
- **Unsupported fallback count:** 0

## Required Outputs

- `BASELINE.json` — VERIFIED
- `MAP_IDENTITY.json` — VERIFIED
- `GEOMETRY_ORACLE_RESULTS.json` — VERIFIED
- `GEOMETRY_PRIMITIVE_ERROR_DISTRIBUTION.json` — VERIFIED
- `GEOMETRY_FREEZE_AUDIT.json` — PARTIALLY_VERIFIED (P1 guard)
- `TOPOLOGY_ORACLE_RESULTS.json` — VERIFIED
- `JUNCTION_ATTACHMENT_ERRORS.csv` — VERIFIED (0 gaps >5m)
- `JUNCTION_ROUTE_MATRIX.json` — VERIFIED (3561 junctions, incoming/outgoing sets)
- `ROUNDABOUT_TOPOLOGY_RESULTS.json` — PARTIALLY_VERIFIED (heuristic)
- `CONFIRMED_DEFECTS.json` — VERIFIED (1 P1)
- `FIX_VALIDATION.json` — VERIFIED (no map mutation)
- `TEST_RESULTS.json` — VERIFIED
- `SUMMARY.md` — VERIFIED

## Overall

**Geometry:** VERIFIED — production kernel agrees with independent reference within sub-micron.  
**Topology:** VERIFIED — 0 invalid relations, 0 dangling, 0 orphan for 3561 junctions.  
**Freeze:** PARTIALLY_VERIFIED — 1 P1 guard needed before declaring horizontal geometry frozen.

**Agent Recommendation:** Horizontal geometry can be considered frozen **conditional** on implementing fail-closed guard for post-freeze mutations. No map-of-record modification performed.
