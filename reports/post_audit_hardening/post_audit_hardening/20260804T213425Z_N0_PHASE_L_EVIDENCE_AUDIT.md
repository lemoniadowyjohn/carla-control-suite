# N0 Phase L Evidence Audit

**Run ID:** 20260804T213425Z
**Audit Timestamp:** 2026-08-04T21:34:25Z
**Phase L Evidence Dir:** reports/post_audit_hardening/20260804T210232Z
**Phase L Verdict:** L_ALL_PASS
**Phase L Commit:** f5aabc0a4f170e564aa03efcb906966880859a9f
**Phase L Branch:** fix/post-audit-phase-e-junctions-roundabouts-20260803

## Verdict

**N0_PHASE_L_EVIDENCE_REJECTED**

## Critical Findings

### N0-FINDING-001: Wrong map loaded in Phase L (CRITICAL)

Phase L validated the built-in CARLA map **Town10HD_Opt** instead of the accepted Ingolstadt candidate **raw_xodr_run_1_epsg32632_header_pinned.xodr**.

| Field | Phase L Value | Accepted Candidate |
|-------|--------------|-------------------|
| Map name | Carla/Maps/Town10HD_Opt | INGOLSTADT_COOKED_PERCEPTION_V1_RAW_XODR |
| OpenDRIVE SHA-256 | 5d883b799f634030... | ff2a05e7b00b8fc1... |
| OpenDRIVE size | 1,857,682 bytes | 82,318,919 bytes |
| Road count | 88 (topology) / 108 (OD) | 32,710 |
| Junction count | 82 (topology) / 9 (OD) | 3,646 |

**Impact:** Phase L L_ALL_PASS verdict is invalid - the wrong map was validated.

### N0-FINDING-002: Road count discrepancy unexplained (CRITICAL)

The campaign reports 32,710 roads but Phase L reported 88 roads (from topology segments). The runtime OpenDRIVE has 108 roads. Neither matches the campaign figure.

Phase L L6 counted unique road_ids from CARLA topology segments, not total roads in OpenDRIVE.

### N0-FINDING-003: Junction count discrepancy unexplained (CRITICAL)

The campaign reports 3,646 junctions but Phase L reported 82 junctions from topology. The runtime OpenDRIVE has 9 junctions.

### N0-FINDING-004: OpenDRIVE size discrepancy (HIGH)

Runtime OpenDRIVE is 1.8MB but accepted candidate is 82MB - a 45x difference.

## Checks Passed

- N0-CHECK-001: CARLA server is running and responsive
- N0-CHECK-002: Phase L evidence files exist and are well-formed
- N0-CHECK-003: Phase L commit matches expected branch
- N0-CHECK-004: CARLA process PID is fresh (not stale)

## Checks Failed

- N0-CHECK-005: Runtime map identity matches accepted candidate
- N0-CHECK-006: Runtime road count matches campaign
- N0-CHECK-007: Runtime junction count matches campaign
- N0-CHECK-008: Runtime OpenDRIVE SHA-256 matches accepted candidate
- N0-CHECK-009: L3 parser logs are from actual CARLA runtime
- N0-CHECK-010: L5 visual defect regression has actual evidence
- N0-CHECK-011: L7 drivability has actual vehicle test evidence
- N0-CHECK-012: L9 sensor validation has actual sensor captures
- N0-CHECK-013: L10 performance has actual measurements
- N0-CHECK-014: L11 old-vs-new has actual comparison data