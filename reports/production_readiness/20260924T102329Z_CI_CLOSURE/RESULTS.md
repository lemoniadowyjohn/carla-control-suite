# CI closure — Blender fake-runner portability (GAP-028) + WriterLock partial-publication race (GAP-029): local green, GitHub Actions green

Branch `fix/ci-closure-blender-writerlock-20260924`, worktree
`C:\Users\admin\AppData\Local\Temp\opencode\ci-closure-20260924`, baseline SHA
`66a28b82814f466246f1755f04c1ac95645a1707`. Single implementer (writer) for this
L3 task; all edits made in this worktree, never in the main checkout. No force-push,
reset, branch delete, CARLA start, or map-pin change was performed. Machine-readable
record: `VERIFICATION.json` (this directory). First-of-kind
race analysis: `WRITER_LOCK_RACE_ANALYSIS.md` (this directory).

**GAP id renumber (post-merge):** upstream `origin/integration/production-large-map-20260918`
claimed `GAP-027` for the MainPipeline dedent crash while this branch was in flight.
On merge (`526de371`), our Blender entry was renumbered **GAP-027 → GAP-028** and our
WriterLock entry **GAP-028 → GAP-029** (provenance preserved in `fixing_commit`).
Upstream GAP-027 is untouched. Register counts after merge: **29 tracked, 22 fixed**.

## 1. Baseline

`python -c "import ultimate_pipeline.contracts.writer_lock as m; print(m.__file__)"`
printed a path inside this worktree before any test ran (confirmed). Working tree
was clean at baseline `66a28b82`. Baseline family-A behavior on this Windows
machine: `python -m pytest tests/unit/test_blender_conversion_integrity.py -q`
→ `20 passed in 20.20s` — i.e. the 12 fake-injection tests PASS locally because
this machine has Blender at `E:\Program Files\Blender Foundation\Blender 4.3\blender.exe`,
which is exactly why the defect is CI-only (GitHub Ubuntu has no Blender).

## 2. Family A — FakeBlenderRunner machine-Blender dependence: root cause + fix

**Root cause (test file only; zero production changes).** `FakeBlenderRunner.run()`
(baseline line 71) mirrors production and calls `self._check_blender()` (baseline
line 83) but did not override it, so it inherited `BlenderRunner._check_blender`
(`ultimate_pipeline/enrichment/blender_runner.py:276-298`). On GitHub Ubuntu no
Blender exists → returns `(False, ...)` → `run()` takes the blocked branch
(baseline test lines 86-89) → all 12 fake-injection tests
(`test_a_success_path_all_checks_pass` … `test_m_input_hash_readable_fails_on_empty`)
report `status=blocked` before ever reaching their intended conditions and fail.

**Fix (commit `8cb1cd95`).** In `tests/unit/test_blender_conversion_integrity.py`
only:

- `_check_blender` overridden **inside `FakeBlenderRunner` only**
  (now line 71: `return True, "Blender 4.3.0 (fake-injected)"`) — a class-local
  override, NOT a global monkeypatch of `BlenderRunner._check_blender`.
  `test_n`/`test_o`/`test_p`/`test_t` depend on the real probe and are untouched
  (`test_t` already used this exact instance-monkeypatch pattern at its line 617).
- ONE new characterization test
  `test_u_real_runner_default_discovery_missing_blender_blocked` (now line 537):
  constructs a real `BlenderRunner` with a valid OBJ, monkeypatches
  `_BLENDER_CANDIDATE_PATHS` / `_discover_blender_exe` / `DEFAULT_BLENDER_EXE` to a
  definitely-nonexistent path, calls `run()`, and asserts
  `result.status == "blocked"`, `"Blender not available" in result.reason`, and
  `status != "skipped"` — independent of whether this machine has Blender.

**Not done, deliberately:** no modification of
`ultimate_pipeline/enrichment/blender_runner.py` (verified: `git diff 66a28b82...HEAD --
ultimate_pipeline/enrichment/blender_runner.py` is empty), no
`submission/infrastructure/...` changes (also verified empty diff), no skip/xfail
markers, no CI Blender install.

## 3. Family B — WriterLock partial-publication race (GAP-029): root cause + fix

**Root cause.** In `ultimate_pipeline/contracts/writer_lock.py`, `acquire()`'s
`os.open(lock_path, O_CREAT|O_EXCL|O_WRONLY|O_BINARY)` (baseline line 129) makes
the pathname visible at size 0 BEFORE the `fdopen/write/flush/fsync` (baseline
lines 149-152) complete. A losing process gets `FileExistsError` (baseline 130),
immediately calls `cls.load()` (baseline 132); `load()`'s
`json.loads(path.read_text())` (baseline 203) raises `JSONDecodeError` on the
empty/torn file. Only `FileNotFoundError` was caught (baseline 133-136);
`JSONDecodeError` (a `ValueError`) propagated out of `acquire()` → the mp worker
(`tests/unit/_writer_lock_mp_worker.py`, generic `except Exception` → `"error"`)
→ `tests/unit/test_writer_lock_concurrency.py` `assert not errors` failed on Linux
CI with `JSONDecodeError('Expecting value: line 1 column 1 (char 0)')`. This is a
NEW residual gap INTRODUCED by the GAP-024 O_EXCL fix (visible-before-written
window for readers) — distinct from GAP-024, whose entry is untouched.

**Fix (commit `1bc93eef`) — the required three-way split in `acquire()`'s
`FileExistsError` branch:**

1. `load()` raises `FileNotFoundError` → existing `continue` (retry outer
   O_EXCL loop), unchanged.
2. `load()` raises `(ValueError, TypeError)` (empty file, torn JSON, JSON list,
   extra-key `TypeError` from `from_dict`) → UNREADABLE content → bounded
   fresh-publication re-read sub-loop: up to `_FRESH_PUBLISH_MAX_REREADS = 100`
   × `_FRESH_PUBLISH_REREAD_DELAY_S = 0.005` (~500 ms ceiling; both constants
   documented at module level next to `_ACQUIRE_MAX_ATTEMPTS`, lines 27-39).
   - re-read succeeds → fall through to the normal path below with that object;
   - `FileNotFoundError` during re-reads → `continue` outer loop;
   - still unreadable after the full budget → raise the DISTINCT
     `RuntimeError("writer.lock at {lock_path} exists but is not readable JSON;
     refusing to acquire or delete it")` (lines 200-203): a `RuntimeError` (mp
     worker maps it to `"blocked"`), containing **not** the phrase
     `"Writer lock held by"`, with **no unlink** in this state.
3. `load()` succeeds → existing logic byte-compatible: `is_live()` →
   `RuntimeError("Writer lock held by ...")` (prefix unchanged, lines 207-211);
   not live → unlink (`FileNotFoundError` ignored) + `continue` (lines 212-216).

The unlink (lines 212-215) is reachable only after a successful `load()`.
The inaccurate baseline comment block (old lines 117-126, which implied the
O_EXCL-created path could not be observed incomplete) was rewritten (now lines
131-154) to state the real semantics: O_EXCL remains the sole exclusivity
authority; losers treat unreadable fresh content as bounded-retry-then-fail-closed,
never reclaimable.

**Untouched, verified:** `load()` (line 268), `from_dict()` (277), `save()` (233),
`release()` (306), `heartbeat()` (324), `_assert_still_current()` (331),
`is_live`/`is_malformed`/`_parse_iso`, the `acquire()` signature, `SCHEMA_VERSION`,
the `O_CREAT|O_EXCL|O_WRONLY` flags (line 129), `_ACQUIRE_MAX_ATTEMPTS = 64`.

**RED→GREEN proof for the new widened-timing test** (optional stash check,
executed): `git stash push -- ultimate_pipeline/contracts/writer_lock.py` →
`test_widened_fresh_publication_contender_never_sees_partial_json` FAILED on
iteration 0 with all 8 contenders reporting
`error=JSONDecodeError('Expecting value: line 1 column 1 (char 0)')` (the exact
CI signature) → `git stash pop` → same test PASSES (`4 passed` for the new
module). Final tree contains the fix (`git diff` on `writer_lock.py` shows the
`_FRESH_PUBLISH_*` constants and the three-way branch).

## 4. Gap register updates

Edited BOTH live copies (the 20260919 superseded snapshot was not touched):

- `reports/production_readiness/20260918T000000Z_PRODUCTION_CLOSURE/MASTER_GAP_REGISTER.json`
- `reports/production_readiness/20260918T000000Z_PRODUCTION_CLOSURE/MASTER_GAP_REGISTER.md`

Added exactly two new 13-field issues (schema mirrored from existing entries):
**GAP-028** (P2, `fixed`, Blender) and **GAP-029** (P1, `fixed`, WriterLock), with
`fixing_commit` = `8cb1cd95` / `1bc93eef` respectively, each carrying renumber
provenance (originally drafted as GAP-027/GAP-028 pre-merge; renumbered after the
upstream GAP-027 collision during merge `526de371`). Upstream's own `GAP-027`
(MainPipeline dedent) is present and untouched. `counts` after merge:
`total` 29, `fixed` 22 (other keys preserved); `last_updated_utc` and the .md
`Last updated:` / `Totals:` lines updated to match (29 tracked, 22 fixed, 3 closed,
1 deferred, 1 open, 1 blocked_external, 1 in_progress). Two table rows sit after
upstream GAP-027, mirroring the GAP-025/026 row style. **The existing GAP-024
entry was not modified**.

## 5. Focused test results (exact commands + pass/fail lines)

Command (workdir = worktree, `python -m pytest` so cwd-first on sys.path):

```
python -m pytest tests/unit/test_blender_conversion_integrity.py tests/unit/test_writer_lock.py tests/unit/test_writer_lock_concurrency.py tests/unit/test_writer_lock_atomic_publication.py tests/unit/test_agent_sync_contract.py -q --tb=short
```

Result line (exact):

```
======================= 53 passed in 192.68s (0:03:12) ========================
```

Zero failed, zero skipped, zero errors. This includes: the 12 formerly-CI-red
fake-injection tests + new `test_u` (21 total in the Blender file); the bumped
8×50 exactly-one-winner race test + the four strengthened persistent-corruption
fail-closed tests; the 4 new GAP-029 tests; and `test_agent_sync_contract.py`
(including `test_lock_replaces_malformed_lock`).

RED (unfixed production file stashed) / GREEN (fix restored) for the new
widened-timing test, exact summary lines:

```
FAILED tests/unit/test_writer_lock_atomic_publication.py::test_widened_fresh_publication_contender_never_sees_partial_json
=========================== short test summary info ===========================
FAILED ...::test_widened_fresh_publication_contender_never_sees_partial_json
============================== 1 failed in 4.28s ==============================
```

```
tests\unit\test_writer_lock_atomic_publication.py ....                   [100%]
============================= 4 passed in 26.00s ==============================
```

(The RED failure message named all 8 contenders with
`JSONDecodeError('Expecting value: line 1 column 1 (char 0)')` — see §3.)

## 6. Full-suite result (exact command + summary line; GAP-007 plugin policy)

Attempt 1 — bare, exactly as CI runs it (`python -m pytest -q`), default pytest
plugin autoload **enabled** (no `PYTEST_DISABLE_PLUGIN_AUTOLOAD`):

```
python -m pytest -q
```

Result line (exact):

```
========= 6264 passed, 6 skipped, 178 warnings in 1529.18s (0:25:29) ==========
```

Exit code 0. The run **completed** — it did not hang after visible 100%, so the
GAP-007 plugin-autoload fallback (`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`) was **not
needed** and was not used; there is no second attempt to report. Policy note per
GAP-007: the bare default-autoload invocation is the CI-equivalent command and
produced a complete, non-partial result (full summary line above, not a
truncated progress view). Skip count is **6**, unchanged from the pre-task
expectation ceiling; zero failed. `git diff 66a28b82...HEAD | grep -iE "skip|xfail"`
shows **no new skip/xfail markers** — the only matches are prose in the GAP-028
register text ("zero skip/xfail markers") and the assertion
`assert result.status != "skipped"` added by `test_u` (a status assertion, not a
marker).

## 7. GitHub Actions run URL — green (pre-merge tree)

Pre-merge run on head `52bf6c27` (branch tip before merging upstream):

- **Run #137** (id `35987817151`): https://github.com/lemoniadowyjohn/carla-control-suite/actions/runs/35987817151
- `conclusion=success`; all six jobs success:
  `offline tests`, `package / wheel smoke`, `governance integrity`,
  `thesis RQ contract`, `research provenance`, `repository health`.
- Job log text is admin-only (anonymous download returns 403); job
  `conclusion=success` is the authoritative green signal. Exact CI pytest counts
  are therefore not quoted (honestly recorded as unavailable, not guessed).

This run covers the fix tree at `52bf6c27`. The merged integration tip (post
`526de371` merge + docs commit) is verified by a subsequent run on the pushed
integration branch; final production SHA and its run URL are recorded in the
coordinator handback and in `VERIFICATION.json` → `github_actions.post_merge_run`
when observed.
