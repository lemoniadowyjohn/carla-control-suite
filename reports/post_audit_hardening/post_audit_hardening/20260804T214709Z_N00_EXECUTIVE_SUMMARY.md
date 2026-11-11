# Phase N Adversarial Runtime Certification - Executive Summary

**Run ID:** 20260804T214709Z
**Audit Timestamp:** 2026-08-04T21:47:09.450530+00:00
**Branch:** fix/post-audit-phase-e-junctions-roundabouts-20260803
**Commit:** f5aabc0a4f170e564aa03efcb906966880859a9f
**Final Verdict:** MAP_RELEASE_REJECTED

## Critical Finding

Phase L validated the **wrong map**. The CARLA server was running the built-in
Town10HD_Opt map instead of the accepted Ingolstadt candidate
(raw_xodr_run_1_epsg32632_header_pinned.xodr).

| Metric | Phase L (Town10HD_Opt) | Accepted Candidate (Ingolstadt) |
|--------|------------------------|----------------------------------|
| Road count | 108 | 32,710 |
| Junction count | 9 | 3,646 |
| OpenDRIVE size | 1.8 MB | 82.3 MB |
| OpenDRIVE SHA-256 | 5d883b79... | ff2a05e7... |

## Gate Results

- G0 (Repository identity): PASS
- G1 (Phase L evidence credibility): FAIL
- G2 (Runtime map identity): FAIL
- G3 (Source/runtime equivalence): FAIL
- G4 (Clean-server validation): PASS
- G5-G23: FAIL (all subsequent gates)

## Recommendation

MAP_RELEASE_REJECTED. The Phase L certification was invalid because the wrong
map was loaded. The Ingolstadt candidate must be loaded in CARLA and the full
Phase N certification must be re-run from N1 onwards.
