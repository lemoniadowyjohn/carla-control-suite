# C44 — Writer Lock Unification

Date: 2026-07-30
Branch: fix/claude-hooks-lock-governance-20260730

## Problem

Two incompatible lock specifications existed:
- `.agent_lock.json` — configured in `agent_sync.py` `LockPolicyContract.lock_file` default, referenced by 6 `agent_sync.yaml` copies
- `.agent_locks/writer.lock` — actual lock file on disk with schema `agent-writer-lock/v1`

No Python code ever enforced either lock. The `.agent_locks/writer.lock` was only manually managed JSON.

## Changes

### 1. Updated `agent_sync.py` LockPolicyContract

Changed `lock_file` default from `.agent_lock.json` → `.agent_locks/writer.lock`

### 2. Created `writer_lock.py`

New module at `ultimate_pipeline/contracts/writer_lock.py` with:
- `WriterLock` dataclass with full schema (schema, owner, branch, SHA, PID, host, lease, heartbeat, allowed/forbidden paths)
- `WriterLock.acquire()` — atomic file creation, stale lock reuse, malformed lock rejection
- `WriterLock.release()` — marks status "released"
- `WriterLock.heartbeat()` — updates heartbeat timestamp
- `WriterLock.is_live()` / `is_expired()` / `is_malformed()` / `owned_by()` / `overlaps_path()`
- Canonical path: `CANONICAL_LOCK_PATH = Path(".agent_locks") / "writer.lock"`

### 3. Backward Compatibility

Since `.agent_lock.json` never existed on disk, no migration was needed — only the default in `agent_sync.py` was updated. If a legacy `.agent_lock.json` appears in the future, the code will treat it as a conflict and warn.

## Tests

10 tests in `tests/unit/test_writer_lock.py` covering:
- Acquire and release
- Second writer blocked
- Expired lock reacquisition
- Malformed lock rejection
- Owner check
- Is live detection
- Heartbeat
- Save and load roundtrip
- Allowed/forbidden paths
- Canonical path
