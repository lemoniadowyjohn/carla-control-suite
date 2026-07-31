# AGENT TASK LEDGER — Ultimate Pipeline (governed)

Shared operational task board for the multi-agent (Claude / Codex / Gemini) workflow.
Authoritative on branch `integration/governed-map-quality-20260729`.

## Operating rules
1. **Single writer.** Acquire the canonical lock (`.agent_locks/writer.lock`, schema `agent-writer-lock/v1`,
   via `ultimate_pipeline/contracts/writer_lock.py`) before mutating tracked files. Fail closed on a live lock.
2. **Immutable parent → isolated candidate → read-only validation → atomic promotion.** No in-place map mutation.
3. **Evidence before claims.** Every status change cites a fresh command/SHA/test result. No unsupported passes.
4. **Bounded, atomic commits.** Stage only required files; never stage `nul`, `vehicle.`, `.idea/`,
   `__pycache__/`, `.pytest_cache/`, large XODR/datasets, secrets.
5. **Canonical entrypoint** `python -m ultimate_pipeline.cli`; forbidden import `config.settings`.

## Status vocabulary
`OPEN` · `IN_PROGRESS` · `READY` · `BLOCKED` · `FIXED_PENDING_FRESH_SESSION` · `RESOLVED` ·
`REGRESSED` · `DEFERRED` · `OPEN_UNTIL_REVERIFIED_ON_PUBLISHED_ACTIVE_BRANCH`

## Model-routing table (difficulty → tier)
| Difficulty | Class | Model | Use |
|---|---|---|---|
| 1–2 | A | DeepSeek V4 Light / Claude Haiku | read-only discovery, smoke tests |
| 3–4 | B | Codex 4.4 Light | narrow git/config/lock wiring, bounded patches |
| 5–7 | C | Codex 5.5 normal/high | integration, typed architecture, artifact transactions |
| 8 | C+ | Codex 5.5 xhigh / Claude Opus 4.8 | architecture gate, governance/safety integration |
| 9–10 | D | highest + human/runtime | map repair, Unreal cook, CARLA runtime, perception |

## Active writer lock
See `.agent_locks/writer.lock` (runtime; not tracked). Policy: `.agent_locks/README.md`.

## Current tasks
| ID | Task | Status | Notes |
|---|---|---|---|
| GOV-AUTH-001 | Clean pushed base with upstream | **RESOLVED** | `integration/governed-map-quality-20260729` on upstream-tracked base; local/remote verified clean before P3 evidence refresh |
| GOV-HOOK-001 | Portable Claude hooks (`run_python_hook.sh`) | **RESOLVED** | P2 fresh-session hook test passed (`FCH01`); no `python3` hook failures observed |
| GOV-LOCK-001 | Canonical writer-lock system | **RESOLVED** | `contracts/writer_lock.py` + `.agent_locks/writer.lock` (gitignored live) + README policy |
| GOV-SYNC-001 | `agent_sync.yaml` bound to canonical lock | **RESOLVED** | generated from schema; `lock_policy.lock_file=.agent_locks/writer.lock`; validates clean |
| P0 | Integration fast-forward + safety layer + map-identity | **RESOLVED** | `INTEGRATION_BRANCH_PUSHED_GREEN`; evidence `reports/current_claude_completion/` |
| P1 | Delta base verification | **RESOLVED** | `reports/delta_base_verification/DV01–DV04` |
| P2 | Fresh Claude hook smoke test | **RESOLVED** | prompt `reports/codex_prompts/P2_fresh_claude_hook_test.md`; `FCH01` PASS |
| P3 | Base + governance closure | **RESOLVED** | canonical lock/test refresh + ledger + CODEX_FIX_PROMPTS + reports |
| P4 | Architecture gate | **BLOCKED** | REQUIRES_BASE_CORRECTION; B1/B2/B3 CLOSED (B2 via LFS @64139d3b, B3 CARLA_GENERATED_ROAD); ONLY B4 (cook toolchain) OPEN; re-gate after B4 |
| P5 | Governance & artifact-safety integration | **BLOCKED** | prereq P4 approval; prompt `reports/codex_prompts/P5_codex55_safety.md` |
| S01 | Artifact transactions | **READY** | 8/9 modules present in `ultimate_pipeline/artifacts/`; add `hashing.py`+`locking.py` (P5) |
| MAP-REPAIR | Structural map repair | **BLOCKED** | not authorized; later P6 after independent artifact-safety review |
| VXR-COORD | Visual/XODR campaign coordination (`ingolstadt_cooked_perception_v1`) | **RESOLVED** | R0 done @ `02bdc100`; base clean, prior writer closed; verdict `READY_TO_RUN_LOW_COST_DISCOVERY`; evidence `reports/visual_structural_reconciliation/R00,00,07,08,09` |
| DSV01 | Visual (OSM2World/Blender/FBX) donor discovery | **RESOLVED** | VISUAL_DONORS_MAPPED; best visual pipeline carla_main_governed@deb261bf; report DSV01_visual_donor_matrix |
| DSV02 | OSM→XODR + structural-validation donor discovery | **RESOLVED** | XODR_DONORS_MAPPED; best OSM->XODR donor codex-full-pipeline-rerun@6b250621; report DSV02_xodr_donor_matrix |
| C44V01 | Read-only coordinate-contract + FBX/XODR alignment verifier | **RESOLVED** | CRS_CONTRACT_READY after C55V01a recert; CRS=EPSG:32632; report C44V01_coordinate_contract |
| C55V01a | New governed structural + matched visual candidate — CRS stage | **RESOLVED** | CRS_CONTRACT_READY_CANDIDATES_STAGED @ d6cd4e0b; OSM b9e07465, XODR ff2a05e7 (EPSG:32632), VISUAL=CARLA_GENERATED_ROAD, vertical=LOCAL_FLAT_ZERO; B2 LFS-closed @64139d3b |
| C55V01b | New governed structural + matched visual candidate — structural freeze | **BLOCKED** | AUTHORIZED by Claude 2026-07-31 (base corrected, CRS ready, determinism proven); prereq = Codex 5.5 quota only; candidate-only, STOP before cook (B4). |
