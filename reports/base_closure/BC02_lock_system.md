# BC02 — Canonical Writer-Lock System

- **Canonical system:** `ultimate_pipeline/contracts/writer_lock.py` (schema `agent-writer-lock/v1`,
  `CANONICAL_LOCK_PATH = .agent_locks/writer.lock`). Already tracked; not reinvented.
- **Decision (tracked vs ignored):** chose **A** — live `writer.lock` is **gitignored** (`.agent_locks/*.lock`),
  since it carries `pid`/`lease_minutes`/`expires_at`/`status` (runtime/ephemeral). Policy tracked at
  `.agent_locks/README.md`; `.gitignore` updated. `git check-ignore .agent_locks/writer.lock` → ignored (confirmed).
- **Contract binding:** `agent_sync.yaml → lock_policy.lock_file = .agent_locks/writer.lock`. Legacy `.agent_lock.json`
  is alias-only.
- **Prior Codex lock observed:** a previous `Codex 5.5` lock existed in `status: released` (task `P5-CODEX55-SAFETY`,
  purpose "P5 blocked-status artifacts only") — Codex correctly acquired, detected the unmet P5 gate, and released.
- **P3 lock:** acquired live for this closure (owner "Claude Opus 4.8 (P3 base closure)", task `P3-BASE-CLOSURE`);
  released at end of BC06.
- **Lock tests:** `tests/unit/test_writer_lock.py` (10) + new `test_agent_sync_contract.py` lock cases
  (acquire-blocks-second-live, canonical-path, malformed-replaced) — all pass.
