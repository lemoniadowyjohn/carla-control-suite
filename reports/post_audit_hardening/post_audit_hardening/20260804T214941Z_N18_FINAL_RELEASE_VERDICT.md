# N18 Final Release Verdict

**Run ID:** 20260804T214941Z
**Timestamp:** 2026-08-04T21:49:41.892467+00:00
**Branch:** fix/post-audit-phase-e-junctions-roundabouts-20260803
**Commit:** f5aabc0a4f170e564aa03efcb906966880859a9f

## Verdict: MAP_RELEASE_REJECTED

### Reason

Phase L validated the wrong map (Town10HD_Opt, a built-in CARLA map) instead of the accepted Ingolstadt candidate (raw_xodr_run_1_epsg32632_header_pinned.xodr). The N0 audit rejected Phase L evidence, and the N1 identity gate confirmed the wrong map was loaded.

### Key Evidence

- Runtime map: Town10HD_Opt (108 roads, 9 junctions, 1.8MB OpenDRIVE)
- Accepted candidate: Ingolstadt (32,710 roads, 3,646 junctions, 82.3MB OpenDRIVE)
- Road count discrepancy: 108 vs 32,710 (303x difference)
- Junction count discrepancy: 9 vs 3,646 (405x difference)
- OpenDRIVE SHA-256 mismatch

### Gate Results

- 2 gates passed (G0, G4)
- 22 gates failed (G1-G3, G5-G23)
- 0 gates blocked
- 0 gates not applicable

### Recommendation

1. Load the correct Ingolstadt candidate in CARLA
2. Re-run Phase L validation on the correct map
3. Re-run Phase N certification from N1 onwards
4. Do not proceed with thesis experiments or domain-gap reruns until Phase N returns a release-certification verdict
