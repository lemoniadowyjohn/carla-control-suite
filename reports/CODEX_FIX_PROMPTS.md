# CODEX_FIX_PROMPTS — Master Delegation Index

Authoritative index of the P0–P5 multi-model execution chain for the OSM→OpenDRIVE→CARLA base/governance
program. Self-contained prompts live in `reports/codex_prompts/`. Source spec:
`F:\pulpit\osm_carla_prompt_bundle\osm_carla_prompt_bundle\osm_carla_bundle_current_state_adjustments_v4.md`.

Branch: `integration/governed-map-quality-20260729`.

| Prompt | Model | Prompt file | Status | Verdict / gate |
|---|---|---|---|---|
| **P0** | Claude Opus 4.8 | (executed) | **DONE** | `INTEGRATION_BRANCH_PUSHED_GREEN` @ `42f7b77c`; evidence `reports/current_claude_completion/CC01–CC05` |
| **P1** | DeepSeek V4 Light | (executed) | **DONE** | `reports/delta_base_verification/DV01–DV04` present |
| **P2** | Claude (cheapest, fresh) | `reports/codex_prompts/P2_fresh_claude_hook_test.md` | **OPEN** | must return `FRESH_SESSION_HOOKS_PASS`; gates `GOV-HOOK-001=RESOLVED` |
| **P3** | Codex 4.4 Light | `reports/codex_prompts/P3_codex44_base_closure.md` | **DONE (this closure)** | canonical lock + `agent_sync.yaml` + ledger + tests; `reports/base_closure/BC01–BC06` |
| **P4** | Claude Opus 4.8 (fresh ≠ P0) | `reports/codex_prompts/P4_architecture_gate.md` | **OPEN** | prereq P2+P3; must return `ARCHITECTURE_APPROVED_FOR_CODEX_55`; outputs `reports/architecture_gate/AG01–AG07` |
| **P5** | Codex 5.5 | `reports/codex_prompts/P5_codex55_safety.md` | **BLOCKED** | prereq P4 approval (AG07); `REAL MAP MUTATION AUTHORIZED` = NO |
| P6 | highest + human/runtime | (not yet drafted) | **BLOCKED** | structural map repair; after independent artifact-safety review of P5 |

## Gating summary
```
P0 ✅ → P1 ✅ → P2 (fresh hook) → P3 ✅ base closure → P4 (fresh Opus arch gate) → P5 (Codex 5.5) → [independent review] → P6
```
Single-writer throughout (`.agent_locks/writer.lock`). P4 must run in a **fresh** Opus process (not the P0 session).
P5 stays BLOCKED until `reports/architecture_gate/AG07_verdict` = `ARCHITECTURE_APPROVED_FOR_CODEX_55`.

## Notes
- `GOV-HOOK-001` remains `FIXED_PENDING_FRESH_SESSION` until P2 passes — do not mark RESOLVED without P2 evidence.
- Base-closure decision: live `writer.lock` is **gitignored** (runtime); policy tracked at `.agent_locks/README.md`.
