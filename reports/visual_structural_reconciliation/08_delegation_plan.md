# 08 — Delegation Plan

**Coordinator:** Claude Opus 4.8 · **Principle:** Claude does not spend expensive context on mechanical searches that a cheap model can do.

## Task graph
```
        ┌─ DSV01 (visual donors)  ┐  read-only, DeepSeek V4 Light   ┐
R00 ──► ┤                         ├─ run IN PARALLEL               ├─► C44V01 (Codex 4.4) ─► Claude synthesis ─► C55V01 (Codex 5.5, BLOCKED)
        └─ DSV02 (xodr donors)    ┘                                ┘
```

| Task | Model | Difficulty | Mode | Gate to start | Prompt file |
|---|---|---|---|---|---|
| **DSV01** | DeepSeek V4 Light | 2 | read-only | R00 ✅ | `reports/delegation_prompts/visual_xodr_campaign/DSV01_visual_donor_discovery.md` |
| **DSV02** | DeepSeek V4 Light | 3 | read-only | R00 ✅ | `…/DSV02_xodr_donor_discovery.md` |
| **C44V01** | Codex 4.4 Light | 4 | read-only data (may add verifier code+tests) | DSV01 ∧ DSV02 done | `…/C44V01_coordinate_contract_verifier.md` |
| **C55V01** | Codex 5.5 | 9 | writer | **BLOCKED** until Claude approves donor matrix + CRS contract + OSM + FBX decision (and B2/B3/B4) | `…/C55V01_new_campaign_integration.md` |

## Governance
- One writer after discovery; DSV01/DSV02 are read-only and may run concurrently.
- Canonical writer lock only (`.agent_locks/writer.lock` via `ultimate_pipeline/contracts/writer_lock.py`). No second lock system.
- Every status change cites a fresh command/SHA/hash. No filename authority — hashes only.

## After discovery, Claude produces (currently PENDING placeholders 01–06)
`CLAUDE_donor_decision.{md,json}` (per-subsystem USE_BASE / CHERRY_PICK_EXACT_COMMIT / RECREATE_MINIMAL_PATCH / USE_AS_REFERENCE_ONLY / REGENERATE_ARTIFACT / REJECT / BLOCKED), FBX-reuse decision (§11.2), OSM-source decision (§11.3), campaign architecture (§11.4 — see 07).

## Next action
Run **DSV01** and **DSV02** on DeepSeek V4 Light (read-only, parallel). Then C44V01. Then return to Claude for synthesis.
