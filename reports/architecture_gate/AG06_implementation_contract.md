# AG06 — Binding Implementation Contract for Codex 5.5 (P5 scope)

> **ACTIVATION STATUS: CONDITIONAL / NOT YET AUTHORIZED.**
> This contract becomes binding **only** when AG07 flips to `ARCHITECTURE_APPROVED_FOR_CODEX_55` **and** base blockers B1–B4 close.
> Current AG07 verdict is `REQUIRES_BASE_CORRECTION`, so P5 **remains BLOCKED** (consistent with `C55_08` = `BLOCKED_INVALID_BASE`).

## 1. Scope P5 MAY do (once authorized)

P5 is **governance & artifact-safety integration** — code + tests only. Difficulty class C (Codex 5.5). Deliverables:

| ID | Deliverable | Location | Definition of done |
|---|---|---|---|
| P5-1 | Complete artifact-transaction layer | `ultimate_pipeline/artifacts/hashing.py`, `locking.py` | 9/9 modules; unit tests; integrates with existing `store/transaction/promotion/recovery` |
| P5-2 | Map registry + SHA registration | new module + registry file | Register Grid0821 & Grid0828 by content SHA; resolve the **mislabeled** `manual_ingolstadt_grid0828.xodr` (holds Grid0821 content) deterministically |
| P5-3 | Governance enforcer | new module | Fail-closed on registry mismatch / unregistered map / identity drift |
| P5-4 | Calibration contract | codify `agent_sync.yaml` sensor rig | **2026-08-15 D2 update:** resolved and codified in `ultimate_pipeline/sensors/calibration_contract.py`; review legacy `attach_sensors_safe.py` before using it for evidence |
| P5-5 | Elevation guard wiring | wire `elevation/`+`dem/` into a guard | Vertical-datum guard with tests |
| P5-6 | Promotion / rollback / validator-immutability | extend `promotion.py`/`recovery.py` | Atomic promotion + tested rollback + validator-immutability proof |
| P5-7 | Failure-injection + full test suite | `tests/` | Offline + geometry + cross-comparison green; failure injection proves guards fire |

## 2. Hard boundaries P5 MUST NOT cross

- **No real map mutation.** Structural map repair is **P6**, gated behind an independent artifact-safety review of P5. (`REAL MAP MUTATION AUTHORIZED = NO`.)
- **No Unreal/CARLA cook execution.** That is the separate cook campaign (AG05), gated on B2–B4.
- **No thesis/`run_11` evidence changes.** `submission/results/structural_gap_run11/` and historical thesis outputs are immutable unless an explicit governed promotion occurs.
- **Single-writer discipline.** Acquire `.agent_locks/writer.lock` (`agent-writer-lock/v1`) before mutating tracked files; fail closed on a live lease.
- **Bounded atomic commits.** Never stage `nul`, `vehicle.`, `.idea/`, `__pycache__/`, `.pytest_cache/`, large XODR/datasets, secrets.
- **Canonical entrypoint** `python -m ultimate_pipeline.cli`; forbidden import `config.settings`.

## 3. Preconditions P5 must re-verify at start (fail-closed)

1. `git rev-parse HEAD == origin/integration/governed-map-quality-20260729`.
2. A **committed** `reports/architecture_gate/AG07_verdict.*` reads `ARCHITECTURE_APPROVED_FOR_CODEX_55` (**not present** — currently `REQUIRES_BASE_CORRECTION`).
3. B1 (P2 hook governance) RESOLVED; `GOV-HOOK-001 = RESOLVED` with `reports/fresh_claude_hook_test/` evidence present.
4. B2 authoritative XODR pinned; B3 FBX/visible-road decision recorded; B4 toolchain available — *for the cook campaign only; P5 code/tests can proceed once B1 + AG07 approval hold.* **[07-31 #2: B2/B3 satisfied; B4 still open]**

If precondition 2 or 3 fails → P5 returns `BLOCKED_INVALID_BASE` and mutates nothing (exactly as `C55_08` already did).

## 4. Note on the existing untracked `codex55_safety/` outputs

`reports/codex55_safety/C55_00..C55_08` exist **untracked** and correctly report `BLOCKED_INVALID_BASE` at the *pre-P3* SHA `0e6e652e`. They are evidence that governance held (no mutation, no commit). They are **stale** relative to current HEAD and must be regenerated when P5 is actually authorized; do not treat them as a completed P5.
