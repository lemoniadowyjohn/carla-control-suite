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
| GOV-AUTH-001 | Clean pushed base with upstream | **RESOLVED** | `integration/governed-map-quality-20260729` @ base, local==origin, 0/0 |
| GOV-HOOK-001 | Portable Claude hooks (`run_python_hook.sh`) | **FIXED_PENDING_FRESH_SESSION** | Code landed @ `ee8871c8`; flips to RESOLVED only after P2 fresh-session hook test passes |
| GOV-LOCK-001 | Canonical writer-lock system | **RESOLVED** | `contracts/writer_lock.py` + `.agent_locks/writer.lock` (gitignored live) + README policy |
| GOV-SYNC-001 | `agent_sync.yaml` bound to canonical lock | **RESOLVED** | generated from schema; `lock_policy.lock_file=.agent_locks/writer.lock`; validates clean |
| P0 | Integration fast-forward + safety layer + map-identity | **RESOLVED** | `INTEGRATION_BRANCH_PUSHED_GREEN`; evidence `reports/current_claude_completion/` |
| P1 | Delta base verification | **RESOLVED** | `reports/delta_base_verification/DV01–DV04` |
| P2 | Fresh Claude hook smoke test | **OPEN** | prompt `reports/codex_prompts/P2_fresh_claude_hook_test.md`; gates GOV-HOOK-001 |
| P3 | Base + governance closure | **IN_PROGRESS → READY** | this ledger + agent_sync.yaml + CODEX_FIX_PROMPTS + tests |
| P4 | Architecture gate | **OPEN** | fresh Opus session (not P0); prereq P2+P3; prompt `reports/codex_prompts/P4_architecture_gate.md` |
| P5 | Governance & artifact-safety integration | **BLOCKED** | prereq P4 approval; prompt `reports/codex_prompts/P5_codex55_safety.md` |
| S01 | Artifact transactions | **READY** | 8/9 modules present in `ultimate_pipeline/artifacts/`; add `hashing.py`+`locking.py` (P5) |
| MAP-REPAIR | Structural map repair | **BLOCKED** | not authorized; later P6 after independent artifact-safety review |
