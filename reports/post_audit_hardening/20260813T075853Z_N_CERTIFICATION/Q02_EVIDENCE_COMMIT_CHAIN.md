# Q02 - Evidence Commit Chain

Generated: 2026-08-13T07:59:00.790263+00:00
Branch: fix/post-audit-phase-e-junctions-roundabouts-20260803

Commit roles are distinguished as:

- **implementation** - pipeline/functional changes
- **evidence-generation** - run reports / evidence manifests
- **publication** - release verdicts / certification commits
- **package-build** - cooked package / packaging commits

| Commit | Role | Subject |
|--------|------|---------|
| 0149d1cc4583 | implementation | fix: resolve duplicate module drift in carla_opendrive_loader between canonical root and submission mirror |
| a2f09541e736 | publication | C3/R16: freeze C3 perception protocol + P8 package build blocked (parent = C2 freeze 54e08381, distinct review_anchor_commit for C1 lineage; final commit, no trailing refresh) |
| 54e08381d686 | publication | C2-R2/R15: freeze C2 3D-package packet + manifest + R15B v2 (corrected; parent_commit == immediate git parent e554da2c, distinct review_anchor_commit for C1 lineage; final commit, no trailing refresh) |
| e554da2ce1cd | evidence-generation | C2-R2 remediation: commit Part 1-3 evidence (visual layer SOURCE_ADDED_VISUAL_LAYER, per-feature residual decomposition, full-map mesh) + 3 stage scripts; raw meshes gitignored, byte-exact disk shas tracked in status JSONs |
| 36432027bf9b | package-build | C2-C/R15: freeze C2 3D-package packet + manifest + R15B v2 (offline-only; full-map OBJ residuals, projection freeze 10/10, crosswalk corner alignment, C2B split ledger; raw OBJ/mtl/logs gitignored, hashes in status json) |
| b667130d3bae | package-build | C2-B: decompose ALREADY_PRESENT 5071 -> 1334 road-adjacent sidewalk-lane matched (per-feature lane proof) + 3737 standalone PACKAGE_MESH/NAVMESH; verify ALL PASS (split==5071) |
| 57925ff766c3 | unknown | C2-A4: parity attestation (remote==28417538, LFS oids match local); flip residual-gap checks to present<=authority (66 cornerLocal-only crosswalks); verify ALL PASS |
| 284175388521 | unknown | C2-A: govern + promote accepted C1 candidate (perception_candidate=248ffbbe...); retire stale ff2a05e7 pointer; identity-guarded governed payload |
| 8b400351d136 | unknown | C1: generate candidate from accepted parent and freeze R14 (c1_freeze_20260809T000000Z_C1) |
| 5f98a666a311 | publication | Finalize repository-bound tag-anchored C0-R freeze |
| 38e0522c9232 | publication | Finalize tag-anchored C0-R freeze |
| 98dae075a700 | unknown | R13: refresh freeze head refs to carrying commit 0a5a6460 |
| 0a5a64603d6c | unknown | R13: self-consistent A-sweep (exclude detector + self-record) [25104180+685e403e clone batch] |
| 685e403e7e98 | publication | R13 freeze: finalize packet with freeze commit reference |
| 69d040255d20 | unknown | R13 freeze: R13O review freeze + R13Z registry + updated Claude C0 packet (STOP A boundary) |
| 25104180066a | unknown | R13: terminal C0-R prep - branch metadata reconciliation, governed-payload identity guard, digest v2/v13 discriminators, semantic-parent authority v2, crosswalk fixtures + subtype authority + handoff + object counts, pedestrian source authority, mutation allowlist + parent hard gate, R13C/R13F docs, tests (2669 pass) |
| a08bed5e8cad | evidence-generation | R1+R2: reuse audit matrix; canonical v2 traffic-control digests; freeze semantic parent v2 |
| 0fe195ef0585 | unknown | Restore C0 gate and quarantine provisional perception artifacts |
| 74fb5b4d5902 | evidence-generation | Stage 16: commit N22/N23 gate reports + perception governed payload (LFS pointer) |
| 3eede5b43309 | publication | Stage 15 (commit): promote perception candidate ingolstadt_perception_final.xodr (LFS); PQ closure pending->false |
| b9d51fe7ae20 | publication | Stage 15-16-20: govern + promote perception candidate, N22/N23 validation, offline verdict |
| 2ec8927ac42a | unknown | Stage I-N: crosswalk + pedestrian semantic enrichment with integrity gates |
| 44c5e22a7a05 | unknown | Stage D0: provenance, untracked classification, reuse matrix, OSM crossing recompute + tests |
| c99adb314d4f | evidence-generation | Add consolidated G-Q closure report + all-stage verification gate |
| 1556561b0f7b | publication | Stage P-Q: final release closure (release held; live gates J-N blocked by missing CARLA server) |
| d517fb33ca10 | unknown | Stage J-Q: attempt live build-in smoke + governed-payload load; BLOCKED (no CARLA server binary) |
| 44ab0f7ebdc2 | package-build | Produce Stage I packaged-map evidence (offline); record residual perception gaps |
| 3e4e2d9acf5c | unknown | Govern exact CARLA load payload; fix coordinate_contract + set-slice bugs (Stage H) |
| 21ffc321bd4a | unknown | Replay Phase H signal enrichment onto repaired candidate (Stage G) |
| 3ef4fbfd3a98 | unknown | Verify GitHub push with remote SHA and file hashes |
| b16730a5af7f | publication | Publish standalone Ingolstadt certification evidence |
| 11479d0fafa8 | publication | Consolidate CARLA loading and certification entry points |
| b3396b2e6344 | publication | Re-certify Phase L and Phase N on Ingolstadt runtime |
| 0cdf9f14c2fd | unknown | Promote repaired Ingolstadt runtime candidate |
| c36e6f7779e2 | unknown | Harden CARLA OpenDRIVE loading and runtime identity |
| f5aabc0a4f17 | publication | evidence: J5R Phase J re-run with J5_ALIGNED verdict (20260804T185517Z) |
| 004d8360529a | implementation | fix: coordinate_control.py math import for _nearest; J5R A4 complete - J5 ALIGNED verified |
| 65aa0978310e | implementation | test: J5R A3b regression test - declared reproduces J5 defect, native aligns with OSM |
| 538ca447d8d2 | implementation | phase-m: J5R coordinate fix - native F1 CRS contract, single authority |
| d6013b1c1f51 | evidence-generation | phase-m: mandatory tests 6.1/6.3/6.5 + EVIDENCE_MANIFEST; enable pyproj-gated skipif test; add FBX provenance sidecar |
| a386ba901291 | evidence-generation | phase-j: OSM2World+Blender/FBX enrichment evidence (J1-J8) |
| 7c636d8caa8c | implementation | phase-i: tiling strategy + tile equivalence passes (curve-aware bounds, junction-cut prevention, fail-closed) |
| 63b7eb5d40a3 | implementation | phase-h: governed signal enrichment passes (speed limits, zones, turn lanes) |
| db044e139b1c | implementation | phase-g: G8 acceptance gate passes, Phase G complete |
| f1fb448bd8b4 | implementation | phase-g: G7 roadMark semantics passes |
| 32cfc9feb845 | implementation | phase-g: G6 junction laneLink validation passes, 116 links repaired |
| 2500bc768e79 | implementation | phase-g: G5 lane classification passes, restricted->driving reclass |
| 076f6503faaf | evidence-generation | phase-g: G4 lane continuity audit passes |
| 60568c6939aa | unknown | Phase G G3: cross-section reconstruction - 338964 samples, 0 defects, 11/11 fixtures pass, drivable width p50 6m/max 30m, 43 stub roads documented (PHASE_G_CROSS_SECTION_PASS) |
| 01c16c95ac9f | unknown | Phase G G2: lane width/border/laneOffset polynomial validation - local-s evaluation, 760671 samples, 0 negative/inversion/overlap/gap, max width 6.07m, max derivative 0.21 m/m (PHASE_G_POLYNOMIAL_VALIDATION_PASS) |
| a92e05cb287c | unknown | Phase G G1: lane inventory - 32710 sections, 84781 lane records, 34674 driving lanes, unique keys resolved (road,section_s,lane), all schema checks pass (PHASE_G_LANE_INVENTORY_PASS) |
| 8ebe0afb942d | unknown | Phase G G0: Phase F handoff and freeze - F7-approved F5 candidate registered, 10 protected identity hashes + lane-topology baseline, F7 path/sha verified line-ending-tolerant (PHASE_G_INPUT_ACCEPTED) |
| f96ee0f86419 | evidence-generation | chore(lfs): track post_audit_hardening work-copy XODRs via LFS |
| 9da9a96530c6 | evidence-generation | chore(lfs): track post_audit_hardening candidate XODRs via LFS |
| 3b29cfc2b56e | publication | Phase F F7: final elevation verification gate - F5 offset-solver candidate verified (32710 roads, 32710 profiles, 0 flat/zero), continuity max 3.04m < 5m bound, whitespace-normalized geometry hash matches pinned, Phase E record validated (PHASE_F_ELEVATION_VERIFIED) |
| 11e055d53ccf | evidence-generation | Phase F F6: seam + grade repair across the map - bounded quadratic-falloff seam fixer, 44910/45632 seams fixed, 57 reported-not-forced (0.12%), planView preserved (F6_SEAM_REPAIR_PASS) |
| 28addd955a3c | unknown | Phase F F5: bounded elevation offsets — graph-relaxation link-offset solver, 45632 seams, max 5.13m->3.04m, 0 over-threshold, slopes preserved (F5_BOUNDED_OFFSETS_PASS) |
| 31dcdb453f20 | unknown | Phase F F4: piecewise elevation profiles from DEM profile chains — CubicSpline C0/C1 per road centreline, scipy, 32710 roads, 0 deferrals, F1/F2 gates (F4_PIECEWISE_PROFILES_PASS) |
| c22d47e796e2 | unknown | Phase F F3: structure classification — F1 CRS contract, classification OK (32710/roads, 306/ways), deck_linear policy, unknown resolved by fail_closed (F3_STRUCTURE_CLASSIFICATION_PASS) |
| fc951ae8f764 | evidence-generation | Phase F F2: policy-driven fallback authority - strict default, audit mode records without mutating, endpoint no-data is a structured violation, 32-test matrix and strict+audit evidence (F2_STRICT_AND_AUDIT_PASS) |