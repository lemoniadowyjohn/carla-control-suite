# GAP-026 Residual Analysis (Post-M2)

**Date**: 2026-10-11
**Authority**: M2.5/M3.5 Topology Convergence

---

## M2 Improvement Summary

| Metric | Before (GAP-026 Oracle) | After M2 Fix | Change |
|--------|------------------------|--------------|--------|
| Total FAIL | 2,992 | **459** | -84.7% |
| Severe Distance (>3m) | 832 | **141** | -83.0% |
| Severe Angle (>12°) | 451 | (not reported) | — |
| Unique Severe Defects | 1,131 | (not reported) | — |
| New Failures on Previous Passes | 0 | 0 | ✅ |

**M2 Fix**: Junction lane-width harmonizer (`junction_lane_width_harmonizer.py`) — connector lanes inherit matched incoming lane widths, eliminating the 0.25m tier discontinuity (3.0 vs 3.5m).

---

## Residual 459 — Required Partitioning

**Status**: NOT YET RECOMPUTED on current pipeline with Stage-8 mutations removed.

**Required action**: Recompute exact residuals AFTER Stage-8 mutation removal but BEFORE any new geometry fix.

### Hypothesized Residual Clusters (from GAP-026 Oracle data)

| Cluster | Hypothesized Cause | Est. Count | Evidence |
|---------|-------------------|------------|----------|
| Connector reference-geometry gaps | Mismatch between connector road geometry and incoming road at junction interface | ~200 | Connector roads have independent geometry (paramPoly3) not aligned to incoming road endpoint |
| Heading flips | Connector road heading differs from incoming road at junction boundary | ~100 | ParamPoly3 geometry on connectors can have heading offset |
| Lane-section/width interaction | Residual width mismatches for multi-lane connectors or asymmetric configurations | ~80 | Harmonizer only handles single-lane connectors; multi-lane cases may have residual |
| Junction contactPoint mismatch | start vs end contactPoint not correctly handled for all junction types | ~50 | contactPoint determines which boundary laneSection is used |
| Roundabout-specific | Complex multi-connection roundabouts with geometry continuity issues | ~30 | Roundabouts have multiple incoming/connecting roads |

**Total hypothesized**: ~460 (matches 459 residual)

---

## Verification Required

Per M2.5/M3.5 spec Section 6:

> Recompute those exact residuals AFTER Stage-8 mutation removal but BEFORE any new geometry fix.
> Partition by proven cause.
> Focus especially: connector reference-geometry gaps, heading flips, remaining lane-section/width interaction.
> For each cluster: count, max distance, max angle, geometry type, generator stage.
> Determine whether one bounded upstream connector-geometry correction can remove the dominant residual.

**No generalized geometry rewrite allowed.** Implement only if a concrete generator mechanism explains the cluster.

**Target**: `GAP026_UNEXPLAINED_RESIDUAL = 0` — every case classified and current acceptance policy explicitly permits it.

---

## Next Steps (Blocked on Convergence Branch)

1. Create convergence branch with Stage-8 mutations removed
2. Run pipeline to Stage 7 output with M2 fix applied
3. Run GAP-026 checker on Stage 7 output
4. Partition 459 residuals by proven generator mechanism
5. If dominant cluster has concrete generator fix → implement bounded upstream correction
6. If no concrete mechanism → bound explicitly with scientific justification

---

## Current Blockers

- Stage-8 lane topology mutations still active (must be removed first per Section 4)
- Convergence branch not yet created (Section 7)
- Fresh regeneration not yet run (Section 8)

---

## Artifacts

- M2 Commit: `0f3c360133eeed959dcc8a871a15e7b1f366dbf6`
- M2 Module: `ultimate_pipeline/lanes/junction_lane_width_harmonizer.py`
- M2 Tests: `tests/unit/test_gap026_junction_lanelink_generator.py` (16 adversarial tests)
- GAP-026 Oracle Classification: `reports/GAP026_FINAL_CLASSIFICATION.md`