# 04_MODEL_TASK_LEDGER.md

**Generated:** 2026-08-02
**Coordinator:** Prompt 01 — Campaign Coordinator
**Mode:** Plan (no fixes in this prompt)

| # | Prompt | Task ID | Model | Mode | Scope | Base commit | Dependency | Status |
|---|---|---|---|---|---|---|---|---|
| 01 | Coordinator | COORD-001 | GPT-5.5 Fast | Plan | coordination reports only | dac6930a | none | THIS PROMPT |
| 02 | Audit Normalization | AUDIT-NORM-001 | Ling-3.0-flash Free | Build | audit/report tooling only | e9ff5986 | P01 | DONE (verify acceptance + tests in P02 review) |
| 03 | Canonical Release Tree | SYS-001 | North Mini Code Free | Build | package layout, imports, entry point, stage registration, test config | e9ff5986 | P02 | BLOCKED (in progress) |
| 04 | Test Traceability | TEST-TRACE-001 | Gemini 3.1 Flash Lite | Plan | reports only | post-SYS-001 | P03 | PENDING |
| 05 | Geometry and Freeze | GEO-FRZ-001 | Gemini 3.6 Flash | Build | geometry evaluators + freeze | post-SYS-001 | P03+P04 | PENDING |
| 06 | Topology/Junctions/Roundabouts/LaneLinks | TOP-JCT-RAB-LLK-001 | Nemotron 3 Ultra Free | Build | structural topology | post-GEO | P05 | PENDING |
| 07 | DEM/Elevation/Lanes | ELV-LAN-001 | Gemini 3.5 Flash | Build | elevation profiles + lane invariants | post-TOP | P05+P06 | PENDING |
| 08 | Signals/Controllers/Enrichment | SIG-ENR-001 | North Mini Code Free | Build | provenance-backed idempotent enrichment | post-ELV | P07 | PENDING |
| 09 | Tiling and Equivalence | TIL-EQV-001 | GPT-5.5 Fast | Build | curve-aware tiling + equivalence | post-SIG | P05-P08 | PENDING |
| 10 | OSM2World/Blender Validators | O2W-BLD-001 | Ling-3.0-flash Free | Build | deterministic naming + fail-closed validators | post-TIL | P09 | PENDING |
| 11 | Static Regression Sweep | REVIEW-STATIC-001 | MiMo V2.5 Free | Plan | independent static review | post-O2W | P02-P10 | PENDING |
| 12 | Adversarial Evidence Review | REVIEW-EVIDENCE-001 | Laguna S 2.1 Free | Plan | disprove every claimed fix | post-O2W | P02-P10 | PENDING |
| 13 | Diff and Preservation Review | REVIEW-DIFF-001 | Big Pickle | Plan | commit scope, data loss, preservation | post-O2W | P02-P10 | PENDING |
| 14 | Final Integration and Handoff | INTEGRATION-001 | GPT-5.5 Fast | Build | offline suite + verdict | post-reviews | all | PENDING |

## Execution order (strict dependency chain)

```
P01 Coordinator
 -> P02 Audit Normalization
 -> P03 Canonical Release Tree
 -> P04 Test Traceability (plan)
 -> P05 Geometry/Freeze
 -> P06 Topology/Junctions/Roundabouts/LaneLinks
 -> P07 DEM/Elevation/Lanes
 -> P08 Signals/Controllers/Enrichment
 -> P09 Tiling/Equivalence
 -> P10 OSM2World/Blender validators
 -> P11 Static sweep (independent) \_
 -> P12 Adversarial review      _|_  may run in parallel
 -> P13 Diff review              /
 -> P14 Final Integration + verdict
```

## Handoff contract (every Build prompt)

TASK ID / MODEL / MODE / WORKTREE / BRANCH / BASE COMMIT / FINAL COMMIT / FILES CHANGED / TESTS ADDED / COMMANDS / RESULTS / UNRESOLVED ISSUES / HANDOFF

## Constraints carried

- No Unreal cooking this batch. P14 may only declare readiness to provision the cooking toolchain.
- No CARLA-server-dependent claims; offline-only verdicts.
- Blender runtime checks → BLOCKED; validator tooling still implemented and tested with fixtures.
