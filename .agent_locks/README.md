# `.agent_locks/` — Canonical Single-Writer Lock

This directory holds the **live writer lock** that enforces single-writer discipline across the
multi-agent (Claude / Codex / Gemini) workflow on this repository.

## Canonical system (this is the authority)
- Implementation: `ultimate_pipeline/contracts/writer_lock.py`
- Schema: `agent-writer-lock/v1`
- Canonical path: **`.agent_locks/writer.lock`** (constant `CANONICAL_LOCK_PATH`)
- Contract binding: `agent_sync.yaml` → `lock_policy.lock_file: .agent_locks/writer.lock`
- Legacy alias (do NOT use as the live lock): `.agent_lock.json`

## Tracked vs. ignored (deliberate)
- The live lock **`writer.lock` is NOT tracked** — it is a runtime artifact carrying `pid`, `lease_minutes`,
  `expires_at`, and `status`. Committing an `active` lock would encode a perpetually-held lock and cause
  merge conflicts. It is excluded via `.gitignore` (`.agent_locks/*.lock`).
- This `README.md` (the policy) **is** tracked, so the canonical location and rules are versioned.

## Acquire / release (via the code, never by hand)
```python
from pathlib import Path
from ultimate_pipeline.contracts.writer_lock import WriterLock

lock = WriterLock.acquire(
    Path("."), branch, head_sha,
    owner="<agent>", purpose="<task>", model="<model>", task_id="<id>",
    allowed_paths=[...], forbidden_paths=[...],
)
# ... do bounded work ...
lock.release()   # sets status=released; or let the lease expire
```

## Strict behavior (from `agent_sync.yaml` lock_policy)
- `active_lease` → **block** (a live lock is exclusive)
- `stale_lease` → warn + allow override (`acquire()` replaces an expired lock)
- `malformed_lock` → **block** (missing required fields → replaced only when not live)

Required fields: `owner, branch, head_sha, hostname/host, pid, created_at, lease_minutes, expires_at`.
