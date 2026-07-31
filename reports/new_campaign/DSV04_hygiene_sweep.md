# DSV04 — Clean-Base & Evidence-Tracking Hygiene Sweep

**Model:** DeepSeek V4 Light · **Mode:** READ-ONLY · **Task ID:** DSV03-06-REPORTS
**Branch:** `integration/governed-map-quality-20260729` · **Base SHA:** `64139d3b2560cb7f00061092f22b481adf963af8`
**Verdict:** `HYGIENE_GAPS_FOUND` (base clean + evidence tracked; ledger rows stale — see §4)

## 1. Evidence tracked — ALL TRACKED, zero `??` orphans

| Evidence group | Files | Tracked? |
|---|---|---|
| DSV01/DSV02 donor matrices | `reports/visual_structural_reconciliation/DSV01_visual_donor_matrix.{md,json}`, `DSV02_xodr_donor_matrix.{md,json}` | ✅ |
| C44V01 execution | `reports/visual_structural_reconciliation/C44V01_alignment_results.json`, `C44V01_coordinate_contract.{md,json}` | ✅ |
| R0–R9 reconciliation series | `reports/visual_structural_reconciliation/{00_current_truth,01_worktree_subsystem_matrix,02_artifact_lineage,03_visual_donor_matrix,04_xodr_donor_matrix,05_coordinate_contract_decision,06_fbx_reuse_decision,07_new_xodr_campaign_plan,08_delegation_plan,09_final_coordinator_verdict}.{md,json}` + `R00_worktrees.{md,json}` | ✅ |
| CLAUDE donor decision | `reports/visual_structural_reconciliation/CLAUDE_donor_decision.{md,json}` | ✅ |
| Delegation prompts | `reports/delegation_prompts/visual_xodr_campaign/{DSV01,DSV02,C44V01,C55V01}*.md` | ✅ |
| C55V01a reports | `reports/new_campaign/C55V01a_{crs_recert,donor_decision,final_status,osm,raw_xodr,visual}.{md,json}` | ✅ |
| AG03A road decision | `reports/architecture_gate/AG03A_visible_road_decision.md` (+ AG03_target_architecture.md) | ✅ |

30+35 tracked files; nothing in these paths appears as `??`.

## 2. Tracked-state clean — no stray uncommitted tracked modifications

`git status --porcelain=v2` (full tree): **zero tracked-modified entries**. The only `??` entries are pre-existing untracked noise (never staged per ledger rule 4): `.githooks/`, `.idea/`, `carla_governed/`, `external/`, `nul`, `vehicle.`, `reports/C01_carla_runtime_audit.{json,md}`, `reports/R01_final_integration_gate.md`, `reports/claude_independent_governance_review/`, `reports/codex55_safety/`, `reports/deepseek_governance_inventory/`, `reports/delta_base_verification/`, `reports/source_visual_closure/`, `ultimate_pipeline/tools/junction_connector_rebuild.py`.

## 3. Preservation invariants — UNTOUCHED (fresh SHA256 baseline)

| Invariant path | SHA256 (fresh) | Size (B) | Git state | vs DSV02 record |
|---|---|---|---|---|
| `submission/results/structural_gap_run11/auto_aligned_rigid.xodr` (carla_-main) | `C765C4DAF84E051934E420D4AE71609EF7A0F3CC34EB02B2165EEB8A1A1EEA3A` | 13,845,703 | **TRACKED** | unchanged (`C765C4DA…`) ✅ |
| `artifacts/final_runs/scenario_b_audit/contract_run/08_final_structural_gap.xodr` (governed) | `2C120DC7CA739E40E7A5B409CC7324B9BED7C5392F550CFF98455F7560DF14B1` | 16,031,746 | untracked | unchanged (`2C120DC7…`) ✅ |
| `…/contract_run/08_final_structural_gap.xodr.bak_elevated` | `0F47A9F01E2C3BD9D8AE312DEB0EB05827CF3453B1131398FB1B31DD81DA3F33` | 16,031,746 | untracked | (new baseline) |
| `…/contract_run/08_final_structural_gap.xodr.bak_prewidthfix` | `DF09D57C72D84B011D665C4010BC9849D0CA7E10A530FF09ADB72B208BA6C2D1` | 16,031,381 | untracked | (new baseline) |
| `…/contract_run/08_final_structural_gap.xodr.bak_utm` | `90FD0FDEDA75A58A0D6106F47CE33F1A3E63D4192C4B0E1711E4E17EBB6B3033` | 13,846,068 | untracked | (new baseline) |
| `thesis_results/structural_gap_v1/run_11/` (governed; 4 files, NO XODR) | fig_intersection_density.png `5A0EA8FE…` · fig_road_type_distribution.png `D5C716A1…` · fig_semantic_depletion_bars.png `D275436F…` · road_length_measurement.json `6988A350…` | 57,824 / 65,522 / 47,924 / 436 | untracked | (new baseline) |
| `work/codex-full-pipeline-rerun-20260427/thesis_results/structural_gap_v1/run_11/auto_aligned_rigid.xodr` | `03AA1841831816C77B8061252FE6270F802E27D33F323BB1073CE6DC4BAEA2DE` | 13,625,961 | untracked | unchanged (`03AA1841…`) ✅ |

No protected-path changes detected; both cross-checkable hashes match the DSV02 record byte-for-byte.

## 4. Ledger ↔ reality cross-check — 5 STALE rows

`AGENT_TASK_LEDGER.md` was last updated before `c264e0c8` / `d6cd4e0b` / `64139d3b`:

| Ledger row | Ledger status | Commit/report reality | Verdict |
|---|---|---|---|
| VXR-COORD | RESOLVED | matches (R0–R9 reports + verdict) | ✅ consistent |
| DSV01 | READY | reports TRACKED (executed) | ⚠️ STALE → executed |
| DSV02 | READY | reports TRACKED (executed) | ⚠️ STALE → executed |
| C44V01 | BLOCKED (prereq DSV01∧DSV02) | C44V01 reports TRACKED (executed; prereq satisfied) | ⚠️ STALE → executed |
| C55V01 | BLOCKED | C55V01a donor-decision + CRS candidates committed (`c264e0c8`, `d6cd4e0b`) | ⚠️ STALE → C55V01a staged |
| P4 row | "B2 … OPEN" | B2 CLOSED @ `64139d3b` (LFS; DSV03 verified) | ⚠️ STALE → B2 closed |

## 5. Verdict summary

- Base clean: ✅ (HEAD==upstream, zero tracked modifications)
- Evidence tracked: ✅ (no orphaned reports; this DSV03-06 batch is committed in the accompanying batched commit)
- Invariants untouched: ✅ (fresh hashes match DSV02 records where available)
- Ledger: ⚠️ 5 rows stale (DSV01, DSV02, C44V01, C55V01, P4/B2) — coordinator to refresh; no blocking impact on base integrity.
