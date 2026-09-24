# WriterLock fresh-lock atomic-publication partial-read race (GAP-029) — analysis

First-of-kind analysis of the reader-side race opened by the GAP-024 O_EXCL
fix in `ultimate_pipeline/contracts/writer_lock.py`. GAP-029 is a **distinct
residual gap introduced by GAP-024**, not a re-opening of GAP-024.

## 1. Race narrative (exact file:line refs)

Write side (baseline numbers from the pre-fix file at `66a28b82`; post-fix
numbers in parentheses where the lines moved):

1. Winner: `acquire()` computes `open_flags = O_CREAT | O_EXCL | O_WRONLY | O_BINARY`
   (baseline 115 → now **129**) and calls `os.open(str(lock_path), open_flags)`
   (baseline 129 → now **157**). `O_CREAT|O_EXCL` is one atomic syscall: it
   creates the inode/directory entry and fails with `FileExistsError` if the
   path already exists. **The pathname is now visible to every other process,
   with file size 0 — the payload has not been written yet.**
2. Winner: only after `os.open` returns does it `os.fdopen(fd, "wb")`,
   `write(payload)`, `flush()`, `os.fsync()` (baseline 149-152 → now
   **219-222**). Between step 1 and the end of step 2 is the
   **fresh-publication window** (naturally ~microseconds to low milliseconds).

Read side (the loser):

3. Loser: `os.open` raises `FileExistsError` (baseline 130 → now **158**) and
   the branch immediately called `cls.load(lock_path)` (baseline 132 → now
   **162**).
4. `load()` (baseline 197-204 → now **268-274**) does
   `data = json.loads(path.read_text())` (baseline 203 → now **273**). On an
   empty file this raises
   `JSONDecodeError('Expecting value: line 1 column 1 (char 0)')`; on a
   torn/partially-written file, any of several `JSONDecodeError`s.
5. Baseline `acquire()` caught **only** `FileNotFoundError` around that
   `load()` (baseline 133-136) — a ValueError subclass like `JSONDecodeError`
   (and the `TypeError` that `from_dict` raises for a JSON list or an
   unrecognized extra key) **propagated out of `acquire()`**.
6. The multiprocessing worker's generic handler
   (`tests/unit/_writer_lock_mp_worker.py`, `except Exception` →
   `result_queue.put((owner, "error", repr(exc)))`, now lines **44-45**)
   classified this as `"error"`.
7. `tests/unit/test_writer_lock_concurrency.py`'s exactly-one-winner test
   (`assert not errors`) therefore failed on Linux CI:
   observed `JSONDecodeError('Expecting value: line 1 column 1 (char 0)')`.

Critically, **exclusivity was never broken**: the loser never won the lock;
it crashed out of `acquire()` with the wrong exception type. The damage is
an indeterminate worker outcome (`"error"` instead of a clean `"blocked"`),
flaky CI, and — before this fix — no principled handling of "file exists but
content is unreadable".

## 2. Why GAP-024's fix created this residual window

GAP-024 replaced the old `exists()`-check-then-`write()` TOCTOU with
`O_CREAT|O_EXCL`. Its comment block (baseline lines 117-126) claimed, in
effect, that this closed the race completely:

> "Atomic create-exclusive acquire: os.open(..., O_CREAT|O_EXCL) is a single
> OS syscall that fails atomically if the path already exists, so it is the
> sole arbiter of "who wins" -- unlike the previous exists()-check-then-write()
> sequence, no two processes can both observe "nobody holds this" and then
> both write."

That claim is correct **for the write side** — no two processes can both win.
But the comment treated the created-then-written path as if it were never
observable in its incomplete state. For **readers** (the losers, whose entire
job after `FileExistsError` is to `load()` the winner's file so they can
decide held-vs-reclaimable) the pathname **is** observable at size 0 between
`os.open` returning and `fsync` completing. The old `exists()`-check-then-write`
sequence did not open this particular window for losers in the same way,
because a loser that observed an existing path was observing a path a previous
winner had already fully written (or the exists() check raced differently);
the GAP-024 loser path newly *assumed* the existing path was fully published.
That assumption is the gap. The baseline comment block has been rewritten
(now lines 131-154) to state the real semantics: O_EXCL remains the sole
exclusivity authority; losers treat unreadable fresh content as
bounded-retry-then-fail-closed, never reclaimable.

## 3. Widened-timing test design (deterministic reproduction)

The real window is microseconds — too small to hit reliably in CI. The test
widens it **without touching production code**:

- `tests/unit/_writer_lock_mp_worker.py::delayed_publish_worker` (top-level,
  spawn-importable) does exactly what a winner does up to the claim: raw
  `os.open(lock_path, O_CREAT|O_EXCL|O_WRONLY|O_BINARY)`, reports `"claimed"`,
  then **sleeps `hold_seconds = 0.25s` with the file still empty**, then
  writes a pre-built valid live lock JSON (built in the parent: owner
  `sim-winner`, `status="active"`, future `expires_at`, unique `lock_id`),
  `fsync`, `close`, reports `"ok"`.
  - 0.25s is far **above** the real ~µs window (so contenders deterministically
    land inside it) and far **below** the 500ms re-read budget (so the fixed
    code recovers by re-reading rather than failing closed).
- `test_widened_fresh_publication_contender_never_sees_partial_json`
  (5 iterations): starts the publisher, starts 8 real `acquire_worker`
  processes (Windows spawn-safe, gated on a second event so they are warm
  before the window opens), releases the publisher, waits for the `"claimed"`
  queue message and asserts the path exists at size 0, **then** releases the
  contenders into the open window; collects 8 contender results + the
  publisher's final message; asserts **zero `"error"` outcomes**, publisher
  `"ok"`, and that the on-disk lock is valid JSON with `owner == "sim-winner"`
  (contenders did not clobber/unlink it).
- **RED proof:** with `writer_lock.py` temporarily stashed, iteration 0 fails
  with all 8 contenders `error=JSONDecodeError('Expecting value: line 1 column
  1 (char 0)')` — the exact CI signature. **GREEN:** with the fix restored,
  the module passes 4/4.

Supporting tests in the same module: persistent 0-byte lock → distinct
RuntimeError, bounded (<5s, actual ~0.5s), file still size 0; malformed old
lock → fail-closed, content byte-identical; expired (lease 0) valid lock →
second acquire still succeeds (guards against over-fail-closed).

## 4. Bounded-retry design

In `acquire()`'s `FileExistsError` branch, a `(ValueError, TypeError)` from
`load()` (JSONDecodeError is a ValueError; `from_dict` raises TypeError for a
JSON list or an unexpected extra key) enters a re-read sub-loop of
`_FRESH_PUBLISH_MAX_REREADS = 100` attempts, `time.sleep(
_FRESH_PUBLISH_REREAD_DELAY_S = 0.005)` between attempts → **~500ms total
ceiling** (constants at lines 38-39, documented at 27-39 next to
`_ACQUIRE_MAX_ATTEMPTS`). Outcomes:

- load succeeds mid-window → break; treat as a normal parsed object
  (live → held error; not-live → unlink+retry).
- `FileNotFoundError` mid-window (file vanished) → `continue` outer O_EXCL loop.
- still unreadable after the full budget → raise the DISTINCT
  `RuntimeError("writer.lock at {lock_path} exists but is not readable JSON;
  refusing to acquire or delete it")` (lines 200-203): RuntimeError maps to
  `"blocked"` in the mp worker, deliberately does **not** contain
  `"Writer lock held by"`, and **no unlink** occurs.

Persistent-corruption tests each now take ~500ms (bounded) instead of
raising instantly — acceptable and asserted (`elapsed < 5.0`).

## 5. Requirements → mechanism map (all 9)

| # | Master-task requirement | Mechanism (code) | Enforcing test(s) |
|---|---|---|---|
| 1 | Exactly-one winner under contention | `O_CREAT\|O_EXCL` sole arbiter (writer_lock.py:129,157), unchanged by this fix | `test_concurrent_acquire_exactly_one_winner_real_processes` (8 workers × **50** iterations, `assert len(oks)==1`) |
| 2 | Partial-fresh lock never reclaimable by a loser | Unreadable branch never reaches the unlink; bounded re-read then distinct fail-closed (lines 167-205) | `test_widened_fresh_publication_contender_never_sees_partial_json` (publisher payload survives, `owner=="sim-winner"`); `test_contender_fails_closed_on_persistent_empty_fresh_lock_without_deleting` |
| 3 | Empty/malformed persistent lock fails closed | `(ValueError, TypeError)` → re-read budget → distinct RuntimeError (lines 192-203) | strengthened `test_acquire_fails_closed_on_empty_file` / `_invalid_json` / `_json_list` / `_unrecognized_extra_key` (all now also assert file exists + content unchanged + message lacks "Writer lock held by"); `test_malformed_old_lock_fails_closed_and_is_not_deleted` |
| 4 | Retry is bounded (no infinite spin) | `_FRESH_PUBLISH_MAX_REREADS × _FRESH_PUBLISH_REREAD_DELAY_S ≈ 500ms`; outer loop still capped by `_ACQUIRE_MAX_ATTEMPTS = 64` | persistent-empty test asserts `elapsed < 5.0`; the four corruption tests complete in ~0.5s each |
| 5 | Heartbeat / release semantics intact | `heartbeat()`, `release()`, `_assert_still_current()` untouched (lines 306, 324, 331) | `test_stale_owner_heartbeat_does_not_clobber_reclaimed_lock`, `test_stale_owner_release_does_not_clobber_reclaimed_lock`, `test_heartbeat`, `test_acquire_and_release` |
| 6 | Works on Windows and Linux | Pure-Python re-read loop; no OS-specific primitives beyond the existing O_EXCL (with `O_BINARY`); mp workers top-level for Windows spawn | Focused suite + full suite run on Windows here (6264 passed); CI (Linux) is the PENDING external confirmation |
| 7 | JSONDecodeError never reported as indefinite "held by" | Distinct message at lines 200-203, asserted to **not** contain "Writer lock held by"; the held-by message (209) is only produced after a **successful** parse | strengthened corruption tests (`assert "Writer lock held by" not in ...`); `test_acquire_fails_closed_on_unknown_schema_with_valid_required_fields` still matches held-by (parseable+live) |
| 8 | No silent delete of unreadable/malformed locks | Unlink (lines 212-215) reachable only on the successful-load-not-live path | no-delete assertions in all four strengthened corruption tests + both new fail-closed tests |
| 9 | O_EXCL remains the exclusivity authority | Flags line 129 unchanged; re-read loop only classifies what the loser observed, never claims exclusivity | exactly-one-winner test (req 1) + comment block lines 131-154 documenting the authority split |

## 6. Three-way `load()` classification in `acquire()`'s FileExistsError branch

| Class | `load()` outcome | Behavior | Pinned by |
|---|---|---|---|
| **Unreadable** | raises `ValueError`/`TypeError` (empty file, torn JSON, JSON list, extra-key TypeError from `from_dict`) | bounded fresh-publication re-read (~500ms) → recover to one of the other classes, or vanish→retry, or distinct RuntimeError fail-closed (**never** unlink, **never** "Writer lock held by") | strengthened `test_acquire_fails_closed_on_empty_file` / `_invalid_json` / `_json_list` / `_unrecognized_extra_key`; `test_contender_fails_closed_on_persistent_empty_fresh_lock_without_deleting`; `test_malformed_old_lock_fails_closed_and_is_not_deleted`; recovery case by `test_widened_fresh_publication_contender_never_sees_partial_json` |
| **Parseable, not live (reclaimable)** | succeeds; `is_live()` False (expired lease, released, or parseable-but-malformed e.g. missing required fields) | unlink (FileNotFoundError ignored) + `continue` outer O_EXCL loop — reclaim path unchanged | `test_lock_replaces_malformed_lock` (test_agent_sync_contract.py:58); `test_expired_lock_can_be_reacquired`; `test_stale_expired_lock_is_reclaimable` |
| **Parseable, live (held)** | succeeds; `is_live()` True | `RuntimeError("Writer lock held by {owner} (PID {pid}, expires {expires})")` — message prefix byte-compatible | `test_acquire_fails_closed_on_unknown_schema_with_valid_required_fields` (match="Writer lock held by"); `test_second_acquire_blocked`; `test_lock_acquire_blocks_second_live_acquire` |
| (File vanished) | raises `FileNotFoundError` | `continue` outer O_EXCL loop — pre-existing behavior, unchanged | covered implicitly by reclaim/race tests; no test change needed |

`load()` itself (line 268) remains **strict** — it still raises on bad content;
the classification happens only at the `acquire()` call site. Direct-load
behavior is pinned by `test_malformed_lock_rejected`
(`test_writer_lock.py:72`): a parseable partial dict still loads and reports
`is_malformed()`, because the dataclass has defaults.

## 7. GAP-024 vs GAP-029 — explicit distinction

| | GAP-024 | GAP-029 |
|---|---|---|
| What it was | TOCTOU: `exists()`-check-then-write allowed **multiple simultaneous winners**; plus stale-handle heartbeat/release clobber | Reader-side: loser's immediate `load()` could observe the winner's **not-yet-written** file → `JSONDecodeError` escapes `acquire()` as an indeterminate `"error"` |
| Side affected | **Write** side (exclusivity) | **Read** side (loser classification) |
| Introduced by | (original defect) | **The GAP-024 O_EXCL fix itself** — visible-before-written window for readers |
| Status | Still fixed — O_EXCL unchanged, exactly-one-winner still green at 8×50 | Fixed here — bounded re-read + distinct fail-closed |
| Register entry | GAP-024, **untouched** by this task | GAP-029, added by this task |

The two must not be conflated: reverting GAP-029's handling would not
reintroduce multi-winner, and GAP-024's entry/claims remain true.

## 8. Residual risks (honest)

1. **Legacy `.agent_lock.json` path still raises raw `JSONDecodeError`** —
   `acquire()`'s legacy check (lines 90-98) calls `cls.load(legacy_lock_path)`
   with no ValueError handling. Pre-existing, out of scope for GAP-029, and
   fails loud (an exception), not silent. Not tracked as a new gap here
   because no CI test exercises a corrupt legacy file.
2. **Windows unlink sharing hazard (pre-existing)** — reclaiming a
   parseable lock still `unlink()`s a path another process may hold open;
   on Windows this can raise a sharing error. Unchanged by this fix (the
   fix only makes unlink *less* reachable, never more). The task explicitly
   scoped Windows unlink-OSError hardening out; noted here as residual.
3. **500ms budget assumes a healthy winner completes publication within
   it** — if a winner stalls (heavy load, swap) longer than ~500ms before
   `fsync`, the contender fails closed with the distinct RuntimeError. That
   is **safe-but-conservative**: no silent delete, no false "held by" claim,
   no lost exclusivity — a human/operator can inspect and retry. It trades a
   rare spurious `blocked` for never misclassifying unreadable content.
4. **Linux CI confirmation still PENDING** — all local runs here were on
   Windows. The race mechanics and fix are OS-neutral pure Python, but the
   GitHub Actions run URL has not been observed (see `RESULTS.md` §7);
   no CI-green claim is made.
