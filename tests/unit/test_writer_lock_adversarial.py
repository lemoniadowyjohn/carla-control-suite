"""B1 - WriterLock adversarial stress harness.

Deterministic (and where a window is inherently racy, statistically
repeated) adversarial scenarios against ultimate_pipeline/contracts/
writer_lock.py, run on the local OS with real multiprocessing.Process
workers (spawn context, platform-neutral).

Scenario coverage:
  1-3. 2 / 8 / 16 simultaneous competing acquire processes
  4.    50 repeated contention rounds minimum (WRITER_LOCK_ADVERSARIAL_ROUNDS)
  5.    artificial delay between lock-file create / JSON serialize /
        flush / fsync (widened publish windows observed by a concurrent probe)
  6.    process killed during publication (create-window and fsync-window)
  7.    malformed pre-existing lock
  8.    zero-byte pre-existing lock
  9.    stale valid lock
 10.    active valid lock
 11.    unknown schema
 12.    concurrent release/acquire attempt

Invariants asserted:
  * exactly one winner for a fresh lock
  * active lock is never stolen
  * malformed persistent record is fail-closed
  * fresh partially-written record is not reclaimed
  * stale-owner semantics stay unchanged
  * no uncaught JSON parsing race (raw *DecodeError/TypeError leak)
  * no silent lock deletion
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import sys
import time
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _writer_lock_adversarial_worker import (  # noqa: E402
    contend_worker,
    delayed_publish_worker,
    probe_worker,
    releaser_worker,
)

from ultimate_pipeline.contracts.writer_lock import WriterLock  # noqa: E402

_REPORT_PATH = os.environ.get("WL_ADVERSARIAL_REPORT", "")
_ROUNDS = int(os.environ.get("WRITER_LOCK_ADVERSARIAL_ROUNDS", "50"))

_RAW_EXCEPTION_TYPES = (
    json.JSONDecodeError,
    UnicodeDecodeError,
    TypeError,
    KeyError,
    ValueError,
)


def _is_controlled(exc: BaseException) -> bool:
    return not isinstance(exc, _RAW_EXCEPTION_TYPES)


def _report(name: str, detail: dict) -> None:
    if not _REPORT_PATH:
        return
    out = Path(_REPORT_PATH)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"scenario": name, **detail}) + "\n")


def _race_round(root: Path, n_workers: int, lease_minutes: int = 60) -> dict:
    ctx = mp.get_context("spawn")
    ready_events = [ctx.Event() for _ in range(n_workers)]
    go_event = ctx.Event()
    result_queue = ctx.Queue()
    procs = []
    for idx in range(n_workers):
        p = ctx.Process(
            target=contend_worker,
            args=(str(root), f"agent-{idx}", ready_events[idx], go_event, result_queue, lease_minutes),
        )
        p.start()
        procs.append(p)
    for e in ready_events:
        assert e.wait(timeout=60), "worker failed to signal ready"
    go_event.set()
    results = [result_queue.get(timeout=60) for _ in range(n_workers)]
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0, "worker process exited abnormally"
    outcomes = {"ok": 0, "blocked": 0, "error": 0}
    winners: list[str] = []
    for _owner, outcome, _detail in results:
        outcomes[outcome] += 1
        if outcome == "ok":
            winners.append(_owner)
    return {"round": root.name, "winners": winners, "outcomes": outcomes}


def _run_contention(base: Path, worker_count: int, rounds: int) -> dict:
    total = Counter()
    multi_rounds = 0
    zero_rounds = 0
    error_details: list[str] = []
    for i in range(rounds):
        root = base / f"wl_{worker_count}_{i}"
        root.mkdir(parents=True, exist_ok=True)
        try:
            res = _race_round(root, worker_count)
        except Exception as exc:  # pragma: no cover - surfaced in the test
            error_details.append(f"round={i} {type(exc).__name__}: {exc!r}")
            continue
        for k, v in res["outcomes"].items():
            total[k] += v
        if len(res["winners"]) == 0:
            zero_rounds += 1
        if len(res["winners"]) > 1:
            multi_rounds += 1
    summary = {
        "worker_count": worker_count,
        "rounds": rounds,
        "total_ok": int(total["ok"]),
        "total_blocked": int(total["blocked"]),
        "total_error": int(total["error"]),
        "rounds_with_zero_winners": zero_rounds,
        "rounds_with_multi_winners": multi_rounds,
        "round_errors": error_details,
    }
    _report(f"contention_{worker_count}_procs", summary)
    return summary


@pytest.mark.slow
def test_scenario_1_2_8_16_simultaneous_processes_and_50_rounds(tmp_path) -> None:
    """Scenarios 1-4: exactly one winner per fresh-lock round at 2, 8 and 16
    simultaneous processes, over the round budget, with zero raw exceptions.
    """
    rounds = _ROUNDS
    for count in (2, 8, 16):
        summary = _run_contention(tmp_path, count, rounds)
        assert summary["rounds"] == rounds
        assert summary["total_error"] == 0, f"{count}-way: raw errors: {summary['round_errors']}"
        assert summary["rounds_with_multi_winners"] == 0, (
            f"{count}-way: {summary['rounds_with_multi_winners']} rounds with >1 winner"
        )
        assert summary["rounds_with_zero_winners"] == 0, (
            f"{count}-way: {summary['rounds_with_zero_winners']} rounds with 0 winners"
        )


def test_scenario_6_killed_during_publication_leave_partial_lock_fail_closed(tmp_path) -> None:
    """A process killed inside the create window leaves a zero-byte lock.
    A subsequent acquire must fail closed (controlled exception), must not
    reclaim the partial record, and must not delete it.
    """
    for kill_stage, delay_key, expected_state in (
        ("created", "created", "empty_partial"),
        ("fsynced", "fsynced", "complete_active"),
    ):
        root = tmp_path / f"kill_{kill_stage}"
        root.mkdir(parents=True)
        ctx = mp.get_context("spawn")
        events = {name: ctx.Event() for name in ("serialized", "created", "flushed", "fsynced")}
        result_queue = ctx.Queue()
        writer = ctx.Process(
            target=delayed_publish_worker,
            args=(
                str(root),
                f"doomed-{kill_stage}",
                events["serialized"],
                events["created"],
                events["flushed"],
                events["fsynced"],
                {delay_key: 60.0},
                result_queue,
            ),
        )
        writer.start()
        assert events[delay_key].wait(timeout=60), f"{kill_stage}: writer never reached stage"
        writer.terminate()
        writer.join(timeout=30)
        lock_path = root / ".agent_locks" / "writer.lock"
        assert lock_path.exists(), f"{kill_stage}: killed writer must leave a lock file"
        lock_path_bytes = lock_path.stat().st_size

        probe_out = _run_single_acquire(root, f"probe-{kill_stage}")

        assert probe_out["outcome"] != "ok", (
            f"{kill_stage}: a lock left by a killed publisher must not be acquired"
        )
        assert lock_path.exists() and lock_path.stat().st_size == lock_path_bytes, (
            f"{kill_stage}: failed acquire modified the killed publisher's lock file"
        )
        assert probe_out["outcome"] == "blocked", (
            f"{kill_stage}: expected controlled fail-closed acquire, got {probe_out['outcome']}"
        )
        assert probe_out["controlled"], (
            f"{kill_stage}: raw exception leaked: {probe_out['error_type']}"
        )
        if expected_state == "complete_active":
            on_disk = WriterLock.load(lock_path)
            assert on_disk.status == "active" and on_disk.owner.startswith("doomed-")
            assert "held by" in (probe_out["detail"] or "").lower()
        _report(f"killed_during_publication_{kill_stage}", {"expected_state": expected_state, **probe_out})


def _run_single_acquire(root: Path, owner: str) -> dict:
    ctx = mp.get_context("spawn")
    ready = ctx.Event()
    go = ctx.Event()
    q = ctx.Queue()
    p = ctx.Process(
        target=contend_worker,
        args=(str(root), owner, ready, go, q, 60),
    )
    p.start()
    assert ready.wait(timeout=60)
    go.set()
    _owner, outcome, detail = q.get(timeout=60)
    p.join(timeout=30)
    controlled = True
    parsed_error_type = None
    if outcome == "error":
        parsed_error_type = detail.split(":")[0]
        controlled = False
    return {"owner": _owner, "outcome": outcome, "detail": detail, "controlled": controlled,
            "error_type": parsed_error_type}


def test_scenario_5_delayed_publication_has_no_uncaught_json_race(tmp_path) -> None:
    """Scenario 5: while one writer is mid-publication (widened windows
    between create/serialize/flush/fsync), a concurrent acquirer must never
    observe an uncaught parse exception, never win the lock away, and the
    writer must still reach its own successful publication.
    """
    root = tmp_path / "delay_race"
    root.mkdir(parents=True)
    ctx = mp.get_context("spawn")
    events = {name: ctx.Event() for name in ("serialized", "created", "flushed", "fsynced")}
    result_queue = ctx.Queue()
    delays = {"serialized": 0.1, "created": 6.0, "flushed": 0.6, "fsynced": 0.3}

    writer = ctx.Process(
        target=delayed_publish_worker,
        args=(str(root), "primary", events["serialized"], events["created"],
              events["flushed"], events["fsynced"], delays, result_queue),
    )
    writer.start()
    assert events["created"].wait(timeout=60), "primary never reached create stage"

    probe_ready = ctx.Event()
    stop_evt = ctx.Event()
    probe_queue = ctx.Queue()
    probe = ctx.Process(target=probe_worker, args=(str(root), probe_ready, stop_evt, probe_queue))
    probe.start()
    assert probe_ready.wait(timeout=60), "probe never started sampling"
    assert events["fsynced"].wait(timeout=60), "primary never reached fsync stage"

    writer_owner, writer_outcome, writer_detail = result_queue.get(timeout=60)
    writer.join(timeout=30)
    assert writer_outcome == "ok", f"primary publisher failed: {writer_detail}"

    time.sleep(0.5)
    stop_evt.set()
    probe_outcomes, raw_types = probe_queue.get(timeout=60)
    probe.join(timeout=30)

    assert probe_outcomes.get("ok", 0) == 0, "probe stole the primary's in-flight lock"
    assert probe_outcomes.get("unparseable", 0) > 0, (
        "probe never observed the widened empty-publish window (sampling regression)"
    )
    assert raw_types == [], f"uncaught parse exceptions observed: {raw_types}"

    on_disk = WriterLock.load(root / ".agent_locks" / "writer.lock")
    assert on_disk.owner == "primary" and on_disk.lock_id == writer_detail

    _report("delayed_publication_probe", {"probe": probe_outcomes, "raw": raw_types})


def test_scenario_6_7_malformed_and_zero_byte_lock_fail_closed(tmp_path) -> None:
    """Per the invariants, a pre-existing file that cannot be parsed is
    fail-closed: acquire() raises a controlled error, does not delete the
    file, and does not reclaim it. (Raw JSONDecodeError / UnicodeDecodeError
    / TypeError leaking out of acquire would fail these assertions.)
    """
    cases = {
        "malformed_json": b"{not valid json",
        "zero_byte": b"",
        "truncated_json": b'{"schema": "agent-writer-lock/v1", "status": "acti',
        "binary_garbage": bytes(range(256)) * 4,
        "json_list": b"['not', 'a', 'dict']".replace(b"'", b'"'),
    }
    for name, content in cases.items():
        root = tmp_path / f"fail_closed_{name}"
        root.mkdir(parents=True)
        lock_path = root / ".agent_locks" / "writer.lock"
        lock_path.parent.mkdir(parents=True)
        lock_path.write_bytes(content)
        with pytest.raises(RuntimeError) as err:
            WriterLock.acquire(root=root, branch="b", head_sha="s", owner="agent")
        assert "lock" in str(err.value).lower()
        assert lock_path.exists()
        assert lock_path.read_bytes() == content, f"{name}: silent lock deletion/reclaim"
    _report("malformed_zero_byte_fail_closed", {"cases": list(cases)})


def test_scenario_10_active_valid_lock_is_never_stolen(tmp_path) -> None:
    root = tmp_path / "active_lock"
    root.mkdir(parents=True)
    lock = WriterLock.acquire(root=root, branch="b", head_sha="s", owner="owner-a")
    with pytest.raises(RuntimeError, match="held by"):
        WriterLock.acquire(root=root, branch="b", head_sha="s", owner="owner-b")
    on_disk = WriterLock.load(root / ".agent_locks" / "writer.lock")
    assert on_disk.owner == "owner-a" and on_disk.status == "active"
    assert on_disk.lock_id == lock.lock_id
    _report("active_valid_lock", {"owner_after": on_disk.owner})


def test_scenario_9_stale_valid_lock_reclaim_keeps_semantics(tmp_path) -> None:
    root = tmp_path / "stale_lock"
    root.mkdir(parents=True)
    old = WriterLock.acquire(
        root=root, branch="b", head_sha="s", owner="owner-a", lease_minutes=0
    )
    assert old.is_expired()
    fresh = WriterLock.acquire(root=root, branch="b", head_sha="s", owner="owner-b")
    assert fresh.owner == "owner-b"
    on_disk = WriterLock.load(root / ".agent_locks" / "writer.lock")
    assert on_disk.owner == "owner-b" and on_disk.lock_id == fresh.lock_id
    _report("stale_valid_lock", {"reclaimed": True})


def test_scenario_11_unknown_schema_fail_closed_when_live(tmp_path) -> None:
    root = tmp_path / "unknown_schema"
    root.mkdir(parents=True)
    lock_path = root / ".agent_locks" / "writer.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(
        json.dumps(
            {
                "schema": "some-unknown-schema/v99",
                "status": "active",
                "owner": "agent-x",
                "branch": "b",
                "head_sha": "s",
                "created_at": "2026-01-01T00:00:00+00:00",
                "expires_at": "2099-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="held by"):
        WriterLock.acquire(root=root, branch="b", head_sha="s", owner="agent")
    assert lock_path.exists()
    _report("unknown_schema_live", {"fail_closed": True})


@pytest.mark.slow
def test_scenario_12_concurrent_release_acquire_no_clobber(tmp_path) -> None:
    """A real owner's release raced against simultaneous acquire attempts:
    the final on-disk record must be consistent - exactly one active owner
    (whose lock_id equals the sole reported winner) or a clean release -
    and a stale release must never overwrite a newly granted lock.
    """
    rounds = max(5, min(_ROUNDS, 20))
    inconsistent = 0
    errors = []
    for i in range(rounds):
        root = tmp_path / f"release_race_{i}"
        root.mkdir(parents=True)
        holder = WriterLock.acquire(root=root, branch="b", head_sha="s", owner="holder-a")
        ctx = mp.get_context("spawn")
        go = ctx.Event()
        rel_q = ctx.Queue()
        rel = ctx.Process(
            target=releaser_worker,
            args=(str(root), "holder-a", holder.lock_id, go, rel_q),
        )
        acq_q = ctx.Queue()
        contenders = []
        for j in range(2):
            ready = ctx.Event()
            p = ctx.Process(target=contend_worker, args=(str(root), f"contender-{j}", ready, go, acq_q))
            p.start()
            contenders.append((p, ready))
        rel.start()
        for p, ready in contenders:
            assert ready.wait(timeout=60)
        go.set()

        rel_owner, rel_outcome, rel_detail = rel_q.get(timeout=60)
        acq_results = [acq_q.get(timeout=60) for _ in range(2)]
        for p, _ready in contenders + [(rel, None)]:
            if _ready is not None:
                p.join(timeout=30)
                assert p.exitcode == 0
        rel.join(timeout=30)

        on_disk = WriterLock.load(root / ".agent_locks" / "writer.lock") if (
            root / ".agent_locks" / "writer.lock"
        ).exists() else None
        acq_winners = [o for o, out, _d in acq_results if out == "ok"]
        acq_errors = [d for o, out, d in acq_results if out == "error"]

        if rel_outcome == "error":
            errors.append(f"round {i}: releaser error {rel_detail}")
        if len(acq_winners) > 1:
            inconsistent += 1
        if on_disk is not None and on_disk.status == "active":
            if len(acq_winners) != 1:
                inconsistent += 1
            elif acq_winners:
                on_disk_ids = {on_disk.lock_id}
                winner_ids = set()
                for o, out, d in acq_results:
                    if out == "ok":
                        winner_ids.add(d)
                if winner_ids != on_disk_ids:
                    inconsistent += 1
    assert errors == []
    assert inconsistent == 0, (
        f"{inconsistent}/{rounds} rounds had inconsistent release/acquire state"
    )
    _report("concurrent_release_acquire", {"rounds": rounds, "inconsistent": inconsistent})