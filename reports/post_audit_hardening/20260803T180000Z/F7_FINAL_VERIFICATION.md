# F7 — Phase F full-map elevation verification

- run_id: `20260803T180000Z`
- verdict: **PHASE_F_ELEVATION_VERIFIED**

## Sub-phase verdicts

| phase | verdict |
|---|---|
| f1 | PASS |
| f2 | F2_STRICT_AND_AUDIT_PASS |
| f3 | F3_STRUCTURE_CLASSIFICATION_PASS |
| f4 | F4_PIECEWISE_PROFILES_PASS |
| f5 | F5_BOUNDED_OFFSETS_PASS |

## Final candidate (offset-solver, F5)

- path: `candidate_f5_bounded_offsets.xodr`
- sha256: `e7e15693cda4aab7f42cffe88a52934e29531a070178f1614db2320db3824ad8`
- roads: 32710
- roads with elevationProfile: 32710
- flat/zero profiles: 0
- planView geometry hash (ws-normalized): `33495bd9d9f0e8ac...` matches pinned: True

## Elevation continuity

- links checked: 45632
- residual issues (>1.0 m): 88
- max residual delta: 3.036 m (bound 5.0 m)

## Checks

- phase_e_record_matches_pinned: PASS
- final_geometry_matches_pinned: PASS
- road_count_preserved: PASS
- all_roads_have_profiles: PASS
- no_flat_zero_profiles: PASS
- f1_pass: PASS
- f2_strict_and_audit_pass: PASS
- f3_structure_identity_pass: PASS
- f4_piecewise_profiles_pass: PASS
- f5_bounded_offsets_pass: PASS
- f5_offset_within_bound: PASS
- continuity_max_bounded: PASS
- horizontal_integrity_preserved: PASS

The offset-solver candidate (F5) is the verified final elevation candidate: its global graph relaxation correctly resolves the map's cyclic / multi-predecessor junction topology.  The local seam fixer (F6) is available for acyclic networks but over-blends endpoints already adjusted by F5 on junctioned graphs, so F5 is gated as final.  Residual inter-road seams are bounded and reported fail-closed — no elevation is invented beyond the offset solver's deterministic result.