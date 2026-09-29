# B1 — WriterLock Adversarial Stress Harness

- Date: 2026-09-24
- Platform exercised: win32 (Python 3.12.2), real `multiprocessing.Process` spawn workers
- CI note: same harness runs on Linux (`pytest -m slow tests/unit/test_writer_lock_adversarial.py`); no OS-specific API used
- Results file: `reports/production_readiness/20260924T124500Z_WRITERLOCK_ADVERSARIAL/results.jsonl`

## Deliverables

| Item | Location |
| --- | --- |
| Harness (test-first) | `tests/unit/test_writer_lock_adversarial.py` |
| Spawn-safe workers | `tests/unit/_writer_lock_adversarial_worker.py` |
| Production repair (smallest) | `ultimate_pipeline/contracts/writer_lock.py::WriterLock.load` |

## Production defect found and repaired

### Reproduction (minimal, deterministic)

A process that is killed between the `O_CREAT|O_EXCL` lock-file creation and
the completion of write/flush/fsync leaves a zero-byte (or truncated) lock
file. The next `WriterLock.acquire()` enters its `FileExistsError` reclaim
branch, calls `WriterLock.load()` on the unparseable file, and the raw parser
exception escaped **uncaught** out of `acquire()`:

- zero-byte / truncated JSON → `json.decoder.JSONDecodeError`
- binary garbage → `UnicodeDecodeError`
- valid JSON that is a list (not an object) → `TypeError`

`RuntimeError` is the documented rejection channel of `acquire()` (callers
catch `RuntimeError`; the GAP-024 worker does `except RuntimeError`), so raw
`ValueError`/`TypeError` subclasses bypass every caller's error handling and
crashed the whole contention run with an unexpected exception type and no
context about which lock file was at fault.

The adversarial harness reproduced this three ways before the repair:

1. static: pre-existing empty/truncated/binary/list lock file → `acquire()`
   raised `JSONDecodeError`/`TypeError`/`UnicodeDecodeError`
2. kill-during-publication: worker killed inside the publish window, then a
   fresh probe `acquire()` reported outcome `error` (raw parse exception)
   instead of controlled `blocked`
3. delayed-publication race: a concurrent probe `acquire()`-ing in a tight
   loop while a publisher was mid-publication observed raw `JSONDecodeError`s

### Repair (smallest change)

`WriterLock.load()` now converts any unparseable/corrupt record into a
controlled `RuntimeError` that names the offending path, states the record
will be left untouched (fail-closed), and does not reclaim or delete it.
`load()` is the single choke point used by the `acquire()` reclaim loop, the
legacy `.agent_lock.json` check, and `release()`/`heartbeat()`
(`_assert_still_current`), so the raw-parse leak is closed everywhere without
touching the O_EXCL arbitration logic. No lock semantics were loosened; the
O_EXCL create remains the sole arbiter of "who wins".

## Per-scenario results and failure frequency

All scenarios exercised against the repaired production code; then full
50-round contention campaign re-run (2/8/16 processes).

| # | Scenario | Result | Failure frequency |
| --- | --- | --- | --- |
| 1 | 2 simultaneous processes | PASS — exactly 1 winner / round | 0/50 rounds with 0 or >1 winner; 0 errors |
| 2 | 8 simultaneous processes | PASS — exactly 1 winner / round | 0/50; 0 errors |
| 3 | 16 simultaneous processes | PASS — exactly 1 winner / round | 0/50; 0 errors |
| 4 | 50+ repeated contention rounds | PASS (2/8/16-way × 50) | 0 multi/zero-winner rounds |
| 5 | delay between create/serialize/flush/fsync | PASS — probe observed 792 `unparseable` (empty-window) + 200 `held_by` acquire attempts during the widened window; 0 raw parse exceptions; primary still won | 0 raw exceptions observed |
| 6 | killed during publication (created window) | PASS — zero-byte lock left; probe failed closed (`RuntimeError`); file untouched | controlled 100% |
| 6 | killed during publication (fsync window) | PASS — complete active record left; probe blocked with "held by"; file untouched | controlled 100% |
| 7 | malformed pre-existing lock | PASS — fail-closed; file byte-identical after failed acquire | n/a |
| 8 | zero-byte pre-existing lock | PASS — fail-closed; file preserved | n/a |
| 9 | stale valid lock | PASS — reclaimed by new owner; on-disk lock_id updated | n/a |
| 10 | active valid lock | PASS — second acquire blocked; owner/lock_id unchanged | n/a |
| 11 | unknown schema | PASS (live) — fail-closed "held by"; file preserved | n/a |
| 12 | concurrent release/acquire | PASS — 20 rounds, 0 inconsistent final states | 0/20 |

Summary of contention outcomes (50 rounds per process count):

- 2-way: 50 ok / 50 blocked / 0 error
- 8-way: 50 ok / 350 blocked / 0 error
- 16-way: 50 ok / 750 blocked / 0 error

## Invariants

| Invariant | Verdict |
| --- | --- |
| exactly one winner for a fresh lock | PASS (O_EXCL sole arbiter; 150 rounds) |
| active lock is never stolen | PASS |
| malformed persistent record is fail-closed | PASS (now a controlled `RuntimeError`) |
| fresh partially-written record is not reclaimed | PASS — killed publisher's partial record left untouched |
| stale-owner semantics stay unchanged | PASS — stale handle `heartbeat`/`release` still rejected |
| no uncaught JSON parsing race | PASS after repair — raw parse exceptions sealed at `load()` |
| no silent lock deletion | PASS — failed acquire never deletes/modifies the record |

## Regression coverage

Existing lock suites re-run green after the repair:

- `tests/unit/test_writer_lock.py` (14)
- `tests/unit/test_agent_sync_contract.py` (6)
- `tests/unit/test_writer_lock_concurrency.py` (8)

## Note on worktree volatility

During the verification campaign an external process restored several tracked
files to HEAD (including the `writer_lock.py` repair and a pre-existing
`tile_fbx_generator.py` edit), which produced one transient harness failure.
The repair was re-applied and the affected scenarios re-verified; no test or
report above depends on that transient state.