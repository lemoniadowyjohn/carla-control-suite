# WP2C Verdict

## CONNECTIVITY_REPAIR_REJECTED

### Gate Results Summary

| Gate | Result | Value |
|------|--------|-------|
| references_to_missing_road_ids = 0 | PASS | 0 |
| references_to_missing_junction_ids = 0 | FAIL | 656 |
| invalid_element_type = 0 | PASS | 0 |
| invalid_contact_point = 0 | PASS | 0 |
| directionally_wrong_reciprocals = 0 | FAIL | 10098 |
| invalid_existing_LaneLink_targets = 0 | PASS | 0 |
| ambiguous_automatic_repairs_accepted = 0 | FAIL | 7144 (6132 independently rejected) |
| unexplained_road_deletion = 0 | PASS | 0 |
| unexplained_road_length_loss = 0 | PASS | 0 |
| unexplained_lane_loss = 0 | PASS | 0 |
| prohibited_geometry_mutation = 0 | PASS | 0 |
| route_fixture_failures = 0 | PASS | 0 |

### Critical Failures

1. **directionally_wrong_reciprocal_links = 10,098**: The repair algorithm created successor links where no valid predecessor exists in the target road, violating OpenDRIVE reciprocity semantics.

2. **ambiguous_automatic_repairs_accepted = 7,144**: 7,144 successor link repairs were applied, but independent validation (distance ≤ 15m, heading diff ≤ 15°) rejected 6,132 (86%) of them. The repair algorithm did not apply geometric validation thresholds.

3. **references_to_missing_junction_ids = 656**: Pre-existing defect from baseline, not remediated by repair.

### Algorithm Defects Identified

- **Predecessor repair asymmetry**: 4,596 proposed predecessor repairs → 0 accepted. The predecessor validation logic in the repair algorithm is defective.
- **Successor repair acceptance without geometric validation**: 7,144 repairs accepted without distance/heading checks, leading to 6,132 invalid links.
- **Directional reciprocity not enforced**: No mechanism to ensure that each successor link A→B has a corresponding predecessor link B←A.

### Required Corrective Actions

1. Fix repair algorithm to validate distance ≤ 15m and heading diff ≤ 15° before accepting any repair
2. Fix predecessor repair validation to match successor repair acceptance criteria
3. Implement reciprocity enforcement: every successor A→B must have predecessor B←A
4. Address 656 junction connections referencing missing junction IDs

### Campaign Impact

WP1 (coordinate correction) is verified. WP2C fails. Campaign verdict: `COORDINATE_VERIFIED_CONNECTIVITY_REJECTED`. Do not proceed to WP3.
