# DSV09 — Ledger Refresh + AG Staleness Map

**Model:** DeepSeek V4 Light · **Mode:** BOUNDED WRITE (AGENT_TASK_LEDGER.md ONLY) + READ-ONLY scan · **Task ID:** DSV09-LEDGER
**Branch:** `integration/governed-map-quality-20260729` · **Base SHA:** `7506128da4e3bd56e0bb8a010cb0abd03f7ab7d0`
**Writer lock:** `DSV09-LEDGER` (acquired via canonical `WriterLock.acquire`; released after push)
**Verdict:** `LEDGER_REFRESHED_STALENESS_MAPPED`

## 1. Ledger corrections applied (exactly as coordinator-specified)

| Row ID | New status | New note |
|---|---|---|
| DSV01 | RESOLVED | VISUAL_DONORS_MAPPED; best visual pipeline carla_main_governed@deb261bf; report DSV01_visual_donor_matrix |
| DSV02 | RESOLVED | XODR_DONORS_MAPPED; best OSM->XODR donor codex-full-pipeline-rerun@6b250621; report DSV02_xodr_donor_matrix |
| C44V01 | RESOLVED | CRS_CONTRACT_READY after C55V01a recert; CRS=EPSG:32632; report C44V01_coordinate_contract |
| C55V01a (new row, split from C55V01) | RESOLVED | CRS_CONTRACT_READY_CANDIDATES_STAGED @ d6cd4e0b; OSM b9e07465, XODR ff2a05e7 (EPSG:32632), VISUAL=CARLA_GENERATED_ROAD, vertical=LOCAL_FLAT_ZERO; B2 LFS-closed @64139d3b |
| C55V01b (new row, split from C55V01) | BLOCKED | structural validation+freeze of new XODR; prereq Codex 5.5 quota + Claude authorization; B4 gates any cook |
| P4 | BLOCKED | REQUIRES_BASE_CORRECTION; B1/B2/B3 CLOSED (B2 via LFS @64139d3b, B3 CARLA_GENERATED_ROAD); ONLY B4 (cook toolchain) OPEN; re-gate after B4 |

All rows matched by ID with the standard `| ID | Task | Status | Notes |` structure; no structural mismatches encountered (no guessing needed). Only `AGENT_TASK_LEDGER.md` was modified.

## 2. AG staleness map (READ-ONLY — for Claude coordinator's later refresh; NOT edited)

### `reports/architecture_gate/AG07_verdict.md` — 8 stale statements
| File:line | Statement | Why stale |
|---|---|---|
| AG07_verdict.md:7 | governance commits "do **not** close B2/B3/B4. The gate still blocks on" | B2 closed @64139d3b, B3 closed (CARLA_GENERATED_ROAD) |
| AG07_verdict.md:8 | "missing authoritative inputs (B2 CRITICAL, B3)" | inputs now pinned/decided |
| AG07_verdict.md:34 | B2 row "Authoritative XODR not pinned \| CRITICAL" | XODR pinned ff2a05e7 + LFS-tracked |
| AG07_verdict.md:35 | B3 row "Authoritative FBX / visible-road source absent \| HIGH" | CARLA_GENERATED_ROAD decision recorded |
| AG07_verdict.md:40 | "B2 (CRITICAL) + B3 + B4 remain open ... B2 alone ... dispositive" | only B4 open |
| AG07_verdict.md:57 | "missing authoritative inputs [B2 CRITICAL, B3]" | resolved |
| AG07_verdict.md:73 | "AUTHORITATIVE XODR: UNKNOWN — must-resolve (B2)" | now ff2a05e7 |
| AG07_verdict.md:74 | "AUTHORITATIVE VISUAL INPUT: ABSENT — must-resolve (B3)" | CARLA_GENERATED_ROAD ratified |
| AG07_verdict.md:91-92 | "[CLOSED] B1 ... OPEN: B2 ... B3 ... B4" | B1/B2/B3 closed; ONLY B4 open |

### `reports/architecture_gate/AG03_target_architecture.md` — 4 stale statements
| File:line | Statement | Why stale |
|---|---|---|
| AG03_target_architecture.md:4 | "do not exist in a pinned form ... (see blockers B2/B3 in AG07)" | B2/B3 closed |
| AG03_target_architecture.md:28 | "Authoritative XODR \| UNKNOWN → must-resolve \| BLOCKER (B2)" | pinned ff2a05e7 |
| AG03_target_architecture.md:29 | "Authoritative FBX/visual input \| ABSENT → must-resolve \| BLOCKER (B3)" | CARLA_GENERATED_ROAD decision |
| AG03_target_architecture.md:46-47 | "Pin an authoritative XODR ... resolves B2" / "Provide FBX ... or select CARLA_GENERATED_ROAD ... resolves B3" | both done |

### `reports/architecture_gate/AG05_unreal_parameters.md` — 2 stale statements
| File:line | Statement | Why stale |
|---|---|---|
| AG05_unreal_parameters.md:15 | "Authoritative XODR (pinned, tracked, hashed) — B2" | now satisfied (ff2a05e7 @64139d3b) |
| AG05_unreal_parameters.md:16 | "Authoritative FBX *or* recorded CARLA_GENERATED_ROAD decision — B3" | now satisfied (decision ratified) |

### `reports/architecture_gate/AG04_coordinate_contract.md` — 1 stale statement
| File:line | Statement | Why stale |
|---|---|---|
| AG04_coordinate_contract.md:11 | "governed by authoritative XODR (unpinned → B2)" | XODR pinned + CRS contract recertified EPSG:32632 (C44V01/C55V01a) |

### `reports/architecture_gate/AG06_implementation_contract.md` — 1 stale statement (borderline)
| File:line | Statement | Why stale |
|---|---|---|
| AG06_implementation_contract.md:35 | "B2 authoritative XODR pinned; B3 FBX/visible-road decision recorded; B4 toolchain available — for the cook campaign only" | B2/B3 now true (B4 still false); list is a precondition list, treat as informational |

### `reports/architecture_gate/UNREAL_COOKING_PARAMETERS.md` — NOT stale (verified current)
- :88 B2 → `ff2a05e7…` candidate, pending independent structural review (C55V01b) — correct.
- :89 B3 → `CARLA_GENERATED_ROAD` selected — correct.
- :90 B4 → still open — correct.

## 3. Scope of this batch's write

- Modified: `AGENT_TASK_LEDGER.md` only (tracked file).
- Added: `reports/new_campaign/DSV07_measurement_reconcile.{md,json}`, `DSV08_determinism_diff.{md,json}`, `DSV10_manifest_completeness.{md,json}`, `DSV09_ledger_refresh.{md,json}`.
- Not touched: `reports/architecture_gate/*` (AG refresh owned by the Claude coordinator), campaigns, ultimate_pipeline, agent_sync.yaml.
