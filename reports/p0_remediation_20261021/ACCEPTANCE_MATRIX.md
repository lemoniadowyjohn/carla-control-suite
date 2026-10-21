# P0 Map Realism Remediation — Acceptance Matrix (scaffold)

Campaign: P0 map realism / physical-correctness remediation
Branch: `repair/map-realism-p0-837a8504` (base SHA `837a8504b624dc90653aef3a48300abb3275e291`)
Map of record (BEFORE subject, immutable): `ingolstadt_perception_map_of_record_20260916_232831.xodr`
sha256 `370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8` (149,799,632 B)
Authoritative audit: `MAP_REALISM_AUDIT_837a8504.md`
Current head at scaffold write: `1e1b090c` (Lane T, Lane Z, Lane B pushes complete)

Status legend: `PASS` (executed evidence, receipts pinned) · `FAIL` · `INCOMPLETE` (inputs absent, tolerated as incomplete — never scored as pass) · `BLOCKED_EXTERNAL` · `PENDING` (run in flight)

## BEFORE state — measured 2026-10-21 (oracle v3 manifest: `stage8_rca_output/p0_before_oracle_v3.json`)
Commit: `8d3fc821`. Scan = read-only against the immutable record map.

| P0 | Measure (authoritative semantics) | BEFORE value | Audit concordance |
|---|---|---|---|
| A | dangling mandatory lane successors (`find_broken_lanes_detailed`, final_integrity) | **0** (checked whole map) | audit's 376 belongs to 20261008/20261014 artifact chain, **not** the record map — direct stage-8 sim: repair+assert PASS 0 failures 4 repairs, post-sim broken 0 (`reports/p0_remediation_20261021/MOR_STAGE8_SIM_FINDING.json`) |
| B | fully-disconnected drivable roads | **0** | audit's 6 orphan IDs (42367/43405/46369/46698/48129/51657) do not exist in the record map (direct text scan NOT FOUND); they belong to the CLOSURE-18 regen family. Diagnostic half-wired class (junction link with no connection membership) = **326** |
| C | connector interface seams |dz|>0.5 m (audit per-side convention) | **866/45,178**, worst dz 2.4184 (jct 3033 conn 68410) | exact audit match (866); audit worst 2.06 cited a different sample |
| C' | per-laneLink bad seams | 776/23,529 | sub-measure of C above |
| D | structure terrain separation | **136 violations / 240 classified** | audit measured 55-structure violations on the artifact chain; record-map population differs |
| E | georeference `has_absolute_origin` | **False** (bare tmerc) | matches audit |

## Lane closures (code work at source stage, all committed & pushed)

| Lane | Scope | Commits | Tests |
|---|---|---|---|
| G | georef absolute authority; fail-closed phase-L; OSM-first signals; oracle+baseline manifests | `3c9ec84c`, `6bcc1112`, `ab2e5037`, `7ef22233` (+issue #15 evidence comment 6305182580) | 46/46 phase-L/georef/signal suites |
| T | lanelink failure taxonomy; P0 oracle authority rewrite (A/B/C/D); terminal-lane ledger (OSM-authoritative: 331 lanes → 210 valid terminal sources + 121 OSM-continuation defects) | `b60125d2` | test_lanelink_builder 7/7 |
| Z | connector boundary elevation reconciliation (Hermite C0 from incident boundary z/grade) wired at stage_05 source | `e2ce6252` | test_connector_elevation_reconciler 7/7; **out-of-tree probe on record map: 866/45,178 → 0/45,178, worst dz 0.0, 743 connectors rewritten, 0 skipped, closed-loop exact** |
| B | FIX-B' namespace patch authority (pinned to external Import.py sha `af0f05f1…`); ue_clean_import_tile / ue_asset_registry_probe / ue_material_slot_report drivers | `1e1b090c` | test_fix_b_import_namespace 5/5; touched-suite 19/19 |

Lane C disposition: the background diagnosis session died in a server restart; its open questions were answered directly with executed experiments (stage-8 sim PASS on record map; connector reconciliation zeroing P0-C). Re-dispatch superseded.

## Candidate qualification (PENDING — regen in flight, `E:\wt_tmp\cand_out`, code head `1e1b090c`)

To be filled on regen completion; every claim requires an executed command receipt.

| Gate | Target | Witness artifact | Status |
|---|---|---|---|
| parse/structural integrity | 0 defects | oracle A/B/E scan on candidate | PENDING |
| lane topology (P0-A) | 0 dangling (`find_broken_lanes_detailed`) | oracle scan | PENDING |
| orphan roads (P0-B gate class) | 0 fully-disconnected | oracle scan | PENDING |
| connector seams (P0-C) | 0 bad interfaces /45,178 | oracle scan post-regen (in-pipeline reconciler ran) | PENDING |
| structure separation (P0-D) | 0 violations (fail-closed) | oracle scan | PENDING |
| georef (P0-E) | absolute tmerc + truthful semantics already fixed in Lane G; georef absolute-authority verdict unchanged | oracle scan | PENDING |
| map acceptance (eps_xy 0.05 m, eps_hdg 0.01 rad frozen) | PASS | planview/continuity gates | PENDING |
| cook | requires `UE4_ROOT` (operator must set `G:\UnrealEngine_4.26_CARLA`), VS2019 v142 | UE4_COOK_RECEIPT | BLOCKED_EXTERNAL |
| load | requires cook + actual RPC response (port listening ≠ success) | load_world receipts | BLOCKED_EXTERNAL (cascade) |
| drive | requires load | route telemetry | BLOCKED_EXTERNAL (cascade) |

## Verdict rubric (pre-registered)

- **MAP_P0_REMEDIATION_PASS**: all static gates PASS at candidate + all Lane closures evidenced.
- **PARTIAL**: static gates PASS but runtime rungs (cook/load/drive) remain host-blocked — static remediation complete, runtime qualification externally escalated.
- **BLOCKED_EXTERNAL**: runtime-only blockers preclude any candidate evidence.
- **FAIL**: any static gate FAIL at candidate with executed receipts.

Runtime success requires an actual RPC response; port/process listening alone is never evidence.
