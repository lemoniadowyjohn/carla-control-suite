# P47 FINAL RELEASE VERDICT

**Run ID:** 20260805T141616Z
**Branch:** fix/post-audit-phase-e-junctions-roundabouts-20260803
**Commit:** f5aabc0a4f170e564aa03efcb906966880859a9f
**Timestamp:** 2026-08-05T14:16:20Z

## Final Verdict

**STANDALONE_XODR_READY_COOKING_BLOCKED**

## Summary

The repaired standalone OpenDRIVE candidate is structurally certified for runtime use.
The packaged visual map (cooked) path and full runtime stress validation remain unverified
in this environment, blocking FULL_PRODUCTION_RELEASE_READY.

## Evidence chain

| Step | Evidence | Verdict |
|------|----------|---------|
| P1 | Repair mutation audit: 12 roads changed, all `SOLE_ZERO_LENGTH_CONNECTOR_GEOMETRY` | PASS |
| Stage 7 | Strict acceptance gate: 0 errors, 1 warning, idempotent | PASS |
| P4 | Source/runtime equivalence: 32710 roads / 3646 junctions identical, 0 missing / 0 unexpected | P4_RUNTIME_EQUIVALENCE_PASS |
| Phase L | Rerun on live map: L1-L12 all PASS | L_ALL_PASS |
| N0 | Phase L evidence audit on corrected evidence | N0_PHASE_L_EVIDENCE_ACCEPTED_WITH_CONDITIONS |
| N18 | Gate matrix G0-G28 | 20 PASS, 0 FAIL, 9 BLOCKED |
| O6 | Runtime input authority updated to repaired candidate | O6_RUNTIME_INPUT_AUTHORITY_UPDATED_TO_REPAIRED_CANDIDATE |
| O9/P13 | Loader program consolidation | O9_LOADER_CONSOLIDATION_COMPLETE |

## Authoritative hashes

| Artifact | SHA-256 |
|----------|---------|
| Source candidate (header-pinned) | `ff2a05e7b00b8fc1bde38f569413223c03a4f4ac9c31eceb5a8592df47d0d17d` |
| Repaired candidate `ingolstadt_fixed_final.xodr` | `80ebb0054afd73ffdd51960b48679ff4689c72ed0abe75af5b2ae10a51395699` |
| Runtime `to_opendrive()` (L2 == P4) | `9630d9f673fdea87058139d9e2241c7084dc2e2550674bba4bfffc78c6d0ae80` |

## Corrected vs prior audit

- Prior rejection (20260804T214941Z): `MAP_RELEASE_REJECTED` because runtime map was
  `Town10HD_Opt` (wrong-map root cause, see O03).
- This certification: runtime map is **Carla/Maps/OpenDriveMap**; L2 map identity matches
  expected map name and P4 runtime hash.

## Conditions (required before FULL_PRODUCTION_RELEASE_READY)

1. Packaged visual map (cooked) validation path — gates G20, G24 (P8/O5).
2. Full route/traffic/pedestrian stress — gate G21.
3. Elevation/physics validation on packaged visual map — gate G22.
4. Endurance run — gate G23.
5. Live vehicle drivability / sensor capture / FPS evidence — gates G7, G9, G10.
6. Old-vs-new comparison — gate G11.

## Governing taxonomy (POST_AUDIT_HARDENING_PROMPT.md sec. 11)

Standalone XODR readiness is certified; visual-map cooking/perception validation is blocked.

## Evidence bundle

`reports/post_audit_hardening/20260805T141616Z_N_CERTIFICATION/`
- N0_PHASE_L_EVIDENCE_AUDIT.json
- N18_FINAL_RELEASE_VERDICT.json
- N00_GATE_MATRIX.json / G00_GATE_MATRIX.md
- N00_EXECUTIVE_SUMMARY.md
- O9_LOADER_CONSOLIDATION.json
- EVIDENCE_MANIFEST.json (225 entries, full post_audit_hardening tree)

Plus runtime-input authority: `reports/post_audit_hardening/20260805T141616Z_O06_RUNTIME_INPUT_AUTHORITY.json`
