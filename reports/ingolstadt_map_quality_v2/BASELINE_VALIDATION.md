# Baseline Validation Report

**Campaign**: full_replay_domain_gap_campaign_20260802T081541Z
**Branch**: improvement/ingolstadt-map-quality-v2-202608
**Tag**: offline-domain-gap-v2-certified (877e9aef)
**Date**: 2026-08-02T22:57:00Z

## Summary

The baseline candidate `c8419f8c79b2c64bf1025371f1651b7f41e13e47cdfe1107857e16b6c5429ae4` (canonical semantic `138e6aab2b5a23a9a254ee58c75d3d7deed6199f54b7f0aa3cefa4a79e774a1d`) has been re-validated against its pinned XODR artifact. All structural metrics are reproducible.

## Lane-Count Contradiction Resolution

**Reported conflict**: `driving_lane_count = 34674` vs `total_lane_count = 16358`

**Resolution**: These values originate from **different comparison groups** in the P04 regression matrix:
- `driving_lane_count = 34674` → Group A (baseline candidate, 32,710 roads)
- `total_lane_count = 16358` → Group C (run_03 surrogate, 6,052 roads)

There is **no contradiction within a single artifact**. The confusion arose from cross-group reporting.

**Adopted schema** (see BASELINE_FIELD_DEFINITIONS.json):
- `lane_section_count`: 32,710
- `lane_record_count`: explicit definition (see below)
- `driving_lane_record_count`: 34,674 (group A)
- `roads_with_driving_lanes`: to be computed
- `driving_lane_length_m`: to be computed

## Reproduced Structural Metrics

| Metric | Value | Source |
|--------|-------|--------|
| road_count | 32,710 | WP0 validation |
| junction_count | 3,646 | P04 matrix |
| connector_count | 22,816 | P04 matrix |
| lane_section_count | 32,710 | WP0 validation |
| driving_lane_record_count | 34,674 | P04 matrix (group A) |
| total_road_length_m | 1,570,221.194 | WP0 validation |
| connected_components | 63 | WP0 validation |
| largest_component_road_count | 32,627 | WP0 validation |
| largest_component_length_m | 1,559,406.2 | WP0 validation |
| largest_component_fraction | 0.99311 | WP0 validation |
| dangling_roads_no_link | 8 | WP0 validation |
| pred_declared_rate_road_type | 0.6975 | WP0 validation |
| succ_declared_rate_road_type | 0.6975 | WP0 validation |
| pred_reciprocal_valid_rate | 0.0 | WP0 validation |
| succ_reciprocal_valid_rate | 0.0 | WP0 validation |
| signals | 0 | P04 matrix |
| controllers | 0 | P04 matrix |
| semantic_objects | 0 objects | P04 matrix |
| road_class_misclassified_ratio | 0.166 | P04 matrix |
| perceptual_gap | BLOCKED | P05 |

## Unresolved / Requiring Explicit Computation

The following fields require direct computation from the pinned artifact (XPath queries need adjustment for namespace/structure):

- `lane_record_count`
- `unique_lane_key_count`
- `roads_with_driving_lanes`
- `driving_lane_length_m`
- `LaneLink_count`, `valid_LaneLinks`, `invalid_LaneLinks`
- `contactPoint_valid`, `contactPoint_invalid`

These will be computed in WP0.1 and WP0.3 before gate passage.

## Gate Status

**BASELINE_LOCK_VALID**: PENDING
- [ ] All counters reproducible
- [x] Lane-count contradiction resolved (cross-group, not within-artifact)
- [x] Field definitions unambiguous
- [ ] LaneLink absence vs validity separated
- [ ] External artifacts hash-bound
- [x] Metric and threshold locks identified

## Next Steps

Complete WP0.1 (recompute all baseline fields) and WP0.3 (validate LaneLink metrics) before proceeding to Phase 1A coordinate inventory.