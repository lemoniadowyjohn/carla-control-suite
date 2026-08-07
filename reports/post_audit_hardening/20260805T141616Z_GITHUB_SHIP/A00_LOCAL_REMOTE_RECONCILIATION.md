# A00 Local-Remote Forensic Reconciliation

## Git Provenance Summary
- **Local HEAD:** `f5aabc0a4f170e564aa03efcb906966880859a9f`
- **Remote Branch:** `fix/post-audit-phase-e-junctions-roundabouts-20260803`
- **Remote Branch SHA:** `d6013b1c1f5106499af8655c34633895837449d8`
- **Relationship:** Local branch is ahead of origin by 4 commits. No remote-only commits. No divergence.
- **Fast-Forwardable:** Yes, fast-forward is safe and possible.

## Working Tree Status
```
## fix/post-audit-phase-e-junctions-roundabouts-20260803...origin/fix/post-audit-phase-e-junctions-roundabouts-20260803 [ahead 4]
 D reports/post_audit_hardening/20260804T135407Z/10_TEST_COLLECTION_REPORT.md
 D reports/post_audit_hardening/20260804T135407Z/18_OSM2WORLD_BLENDER_REPORT.md
 D reports/post_audit_hardening/20260804T135407Z/23_NEGATIVE_CONTROL_REPORT.md
 D reports/post_audit_hardening/20260804T135407Z/EVIDENCE_MANIFEST.json
 M ultimate_pipeline/core/carla_opendrive_loader.py
 M ultimate_pipeline/quality/check_carla_opendrive_compat.py
 M ultimate_pipeline/run_full_test.py
 M ultimate_pipeline/tools/load_final_into_carla.py
?? .githooks/
?? .idea/
?? P03_REPAIR_MUTATION_LEDGER.csv
?? P04_REPAIR_MUTATION_SUMMARY.json
?? P05_UNEXPECTED_MUTATIONS.csv
?? POST_AUDIT_HARDENING_PROMPT.md
?? _a0_gather.py
?? _p1_repair_audit.py
?? _p4_runtime_evidence.json
?? _run_p4_equiv.py
?? _stage1_inventory.json
?? _stage1_inventory.py
?? _stage1b_check_geoms.py
?? _stage5_repair.py
?? _stage5_repair_report.json
?? _stage7_acceptance.py
?? _stage7_acceptance_results.json
?? _stage7_gate_check.py
?? _verify_native.py
?? _verify_repair.py
?? _write_p4_evidence.py
?? audit_output.zip
?? audit_output/
?? campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_fixed_final.xodr
?? campaigns/ingolstadt_cooked_perception_v1/candidate/verify_final_xodr_report.json
?? carla_governed/
?? check_raw_run1.py
?? create_a1_registries.py
?? create_reconciliation_reports.py
?? examine_bad_roads.py
?? external/
?? generate_audit.py
?? nul
?? phase_l_validation.py
?? phase_q/
?? reports/C01_carla_runtime_audit.json
?? reports/C01_carla_runtime_audit.md
?? reports/R01_final_integration_gate.md
?? reports/claude_independent_governance_review/
?? reports/codex55_safety/
?? reports/deepseek_governance_inventory/
?? reports/delta_base_verification/
?? reports/opencode_batch_20260802/14B_CLOSURE_EVIDENCE.zip
?? reports/post_audit_hardening/20260804T135530Z/
?? reports/post_audit_hardening/20260804T185347Z/
?? reports/post_audit_hardening/20260804T203529Z/
?? reports/post_audit_hardening/20260804T204003Z/
?? reports/post_audit_hardening/20260804T204419Z/
?? reports/post_audit_hardening/20260804T205730Z/
?? reports/post_audit_hardening/20260804T205920Z/
?? reports/post_audit_hardening/20260804T210232Z/
?? reports/post_audit_hardening/20260804T213425Z_N0_PHASE_L_EVIDENCE_AUDIT.json
?? reports/post_audit_hardening/20260804T213425Z_N0_PHASE_L_EVIDENCE_AUDIT.md
?? reports/post_audit_hardening/20260804T214216Z_N1_RUNTIME_MAP_IDENTITY.json
?? reports/post_audit_hardening/20260804T214256Z_N0_PRIMARY_VS_DERIVED_EVIDENCE.csv
?? reports/post_audit_hardening/20260804T214410Z_N2_SOURCE_RUNTIME_EQUIVALENCE.json
?? reports/post_audit_hardening/20260804T214459Z_N10_PERFORMANCE.json
?? reports/post_audit_hardening/20260804T214459Z_N11_NEGATIVE_CONTROLS.json
?? reports/post_audit_hardening/20260804T214459Z_N12_DETERMINISM.json
?? reports/post_audit_hardening/20260804T214459Z_N13_RELEASE_PACKAGE.json
?? reports/post_audit_hardening/20260804T214459Z_N14_OLD_VS_NEW.json
?? reports/post_audit_hardening/20260804T214459Z_N3_PROCESS_AND_PORT_AUDIT.json
?? reports/post_audit_hardening/20260804T214459Z_N4_SPATIAL_COVERAGE.json
?? reports/post_audit_hardening/20260804T214459Z_N5_ROUTE_STRESS.json
?? reports/post_audit_hardening/20260804T214459Z_N6_VEHICLE_PHYSICS.json
?? reports/post_audit_hardening/20260804T214459Z_N7_TRAFFIC_STRESS.json
?? reports/post_audit_hardening/20260804T214459Z_N8_SENSOR_VALIDATION.json
?? reports/post_audit_hardening/20260804T214459Z_N9_VISUAL_COLLISION_ALIGNMENT.json
?? reports/post_audit_hardening/20260804T214540Z_N15_FINAL_RELEASE_CERTIFICATION.json
?? reports/post_audit_hardening/20260804T214630Z_N17_GATE_MATRIX.csv
?? reports/post_audit_hardening/20260804T214709Z_N00_EXECUTIVE_SUMMARY.md
?? reports/post_audit_hardening/20260804T214807Z_N01_REPOSITORY_AND_ARTIFACT_IDENTITY.json
?? reports/post_audit_hardening/20260804T214807Z_N02_PHASE_L_EVIDENCE_AUDIT.json
?? reports/post_audit_hardening/20260804T214853Z_N16_OLD_VS_NEW_COMPARISON.csv
?? reports/post_audit_hardening/20260804T214941Z_N16_OLD_VS_NEW_COMPARISON.csv
?? reports/post_audit_hardening/20260804T214941Z_N18_FINAL_RELEASE_VERDICT.md
?? reports/post_audit_hardening/20260804T215104Z_COMMAND_TRANSCRIPT.txt
?? reports/post_audit_hardening/20260804T215143Z_EVIDENCE_MANIFEST.json
?? reports/post_audit_hardening/20260804T215143Z_N15_RELEASE_PACKAGE.json
?? reports/post_audit_hardening/20260804T221702Z_O00_EXISTING_PROGRAM_INVENTORY.csv
?? reports/post_audit_hardening/20260804T221723Z_O01_CAPABILITY_MATRIX.md
?? reports/post_audit_hardening/20260804T221723Z_O02_PHASE_L_CALL_GRAPH.md
?? reports/post_audit_hardening/20260804T221723Z_O03_WRONG_MAP_ROOT_CAUSE.json
?? reports/post_audit_hardening/20260804T221755Z_O04_CANDIDATE_LINEAGE.json
?? reports/post_audit_hardening/20260804T221755Z_O05_CANDIDATE_LINEAGE.md
?? reports/post_audit_hardening/20260804T221755Z_O06_RUNTIME_INPUT_AUTHORITY.json
?? reports/post_audit_hardening/20260804T221856Z_O07_RUNTIME_STRATEGY.md
?? reports/post_audit_hardening/20260804T221856Z_O08_LOADER_HARDENING.py
?? reports/post_audit_hardening/20260804T223515Z_O04_CARLA_CRASH_EVIDENCE.json
?? reports/post_audit_hardening/20260805T115947Z_P4_RUNTIME_EQUIVALENCE/
?? reports/post_audit_hardening/20260805T120340Z/
?? reports/post_audit_hardening/20260805T122525Z/
?? reports/post_audit_hardening/20260805T141616Z_N_CERTIFICATION/
?? reports/post_audit_hardening/20260805T141616Z_O06_RUNTIME_INPUT_AUTHORITY.json
?? reports/source_visual_closure/
?? run_n0_audit.py
?? run_n_certify.py
?? submission_files.txt
?? ultimate_pipeline/reports/post_audit_hardening/
?? vehicle.
?? work/
?? worktree_files.txt
?? worktrees/
```

## Commit Log (Recent 10)
```
f5aabc0a evidence: J5R Phase J re-run with J5_ALIGNED verdict (20260804T185517Z)
004d8360 fix: coordinate_control.py math import for _nearest; J5R A4 complete - J5 ALIGNED verified
65aa0978 test: J5R A3b regression test - declared reproduces J5 defect, native aligns with OSM
538ca447 phase-m: J5R coordinate fix - native F1 CRS contract, single authority
d6013b1c phase-m: mandatory tests 6.1/6.3/6.5 + EVIDENCE_MANIFEST; enable pyproj-gated skipif test; add FBX provenance sidecar
a386ba90 phase-j: OSM2World+Blender/FBX enrichment evidence (J1-J8)
7c636d8c phase-i: tiling strategy + tile equivalence passes (curve-aware bounds, junction-cut prevention, fail-closed)
63b7eb5d phase-h: governed signal enrichment passes (speed limits, zones, turn lanes)
db044e13 phase-g: G8 acceptance gate passes, Phase G complete
f1fb448b phase-g: G7 roadMark semantics passes
```

## Reconciliation Verdict
- **Sync Verdict:** `GITHUB_SHIP_VERIFIED` (reconciliation shows clean fast-forward lineage)
- **Action Plan:** Commit Phase O/P/Q code and selected reproducible evidence in logical batches, then fast-forward push.
