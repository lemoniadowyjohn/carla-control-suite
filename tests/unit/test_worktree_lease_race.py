"""Process-level regression for monotonic worktree lease fencing generations."""
from __future__ import annotations

import multiprocessing
import json
import os
from queue import Empty
import subprocess
import time
import traceback
import uuid
from pathlib import Path


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.email=test@example.invalid", "-c", "user.name=Lease Test",
         "-c", "init.defaultBranch=main", *args],
        cwd=str(cwd), check=True, capture_output=True, text=True,
    )


def _lease_worker(root: str, ready_queue, start_event, queue, iterations: int) -> None:
    worktree = Path(root)
    try:
        from ultimate_pipeline.governance.single_writer import worktree_lock as wl

        # Keep the race focused on lease serialization, not platform process
        # startup identity discovery or repeated git subprocess startup. Keep
        # the OS-backed peer liveness probe real: os.kill(pid, 0) is unsafe as
        # a Windows test seam because it can send CTRL+C to the shared console.
        worker_pid = os.getpid()
        worker_start = wl.process_identity.process_start_identity(worker_pid)
        wl.process_identity.current_process_identity = lambda: (worker_pid, worker_start)
        canonical_root = worktree.resolve()
        wl.lock_paths.resolve_git_common_dir = lambda _root: canonical_root / ".git"
        wl.os.fsync = lambda fd: None
        ready_queue.put(("ready", os.getpid()))
        if not start_event.wait(timeout=20):
            queue.put(("error", os.getpid(), "start barrier timed out"))
            return
        for _ in range(iterations):
            while True:
                try:
                    lease = wl.acquire_worktree_lease(worktree, purpose="generation-race")
                    break
                except RuntimeError as exc:
                    if "leased by another process" not in str(exc):
                        queue.put(("error", os.getpid(), traceback.format_exc()))
                        return
                    time.sleep(0)
            started = time.monotonic_ns()
            if not wl.validate_lease(lease):
                queue.put(("invalid", os.getpid(), lease.generation))
                return
            # Keep the ownership window observable while still keeping this stress test short.
            time.sleep(0.0005)
            ended = time.monotonic_ns()
            try:
                wl.release_worktree_lease(worktree, lease.owner_token, lease.lease_id)
            except Exception as exc:
                queue.put(("error", os.getpid(), traceback.format_exc()))
                return
            queue.put(("grant", lease.generation, started, ended))
    except BaseException as exc:
        queue.put(("error", os.getpid(), traceback.format_exc()))


def test_multiprocess_lease_race_has_unique_increasing_generations_and_no_temps(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    root = tmp_path / f"race-worktree-{uuid.uuid4().hex}"
    root.mkdir()
    _git("init", cwd=root)
    _git("commit", "--allow-empty", "-m", "init", cwd=root)
    # Windows spawn imports the package in every child. Four independent
    # processes still exercise real cross-process O_EXCL arbitration while
    # keeping this bounded regression practical on slower CI hosts.
    workers, iterations = 4, 5
    timeout_s = 45.0
    start_event = ctx.Event()
    ready_queue = ctx.Queue()
    queue = ctx.Queue()
    procs = [ctx.Process(target=_lease_worker,
                         args=(str(root), ready_queue, start_event, queue, iterations))
             for _ in range(workers)]
    deadline = time.monotonic() + timeout_s
    records = []
    try:
        for proc in procs:
            proc.start()
        ready = []
        for _ in range(workers):
            remaining = deadline - time.monotonic()
            assert remaining > 0, "workers did not reach the start barrier within 45 seconds"
            try:
                ready.append(ready_queue.get(timeout=remaining))
            except Empty as exc:
                raise AssertionError(
                    f"timed out waiting for worker readiness; ready={ready}; "
                    f"exitcodes={[p.exitcode for p in procs]}"
                ) from exc
        assert all(item[0] == "ready" for item in ready), ready
        start_event.set()
        expected = workers * iterations
        while len(records) < expected:
            remaining = deadline - time.monotonic()
            assert remaining > 0, (
                f"lease race exceeded {timeout_s:.0f}s; received {len(records)} "
                f"of {expected} records; exitcodes={[p.exitcode for p in procs]}"
            )
            try:
                row = queue.get(timeout=remaining)
            except Empty as exc:
                raise AssertionError(
                    f"timed out waiting for lease result; received {len(records)} "
                    f"of {expected}; exitcodes={[p.exitcode for p in procs]}"
                ) from exc
            if row[0] != "grant":
                raise AssertionError(f"worker reported {row!r}")
            records.append(row)
        for proc in procs:
            proc.join(timeout=max(0.0, deadline - time.monotonic()))
        alive = [proc.pid for proc in procs if proc.is_alive()]
        assert not alive, f"lease workers did not exit within {timeout_s:.0f}s: {alive}"
        assert [proc.exitcode for proc in procs] == [0] * workers
    finally:
        # Always open the barrier and reap children, including on assertion or
        # timeout, so a failed regression cannot leak processes into pytest.
        start_event.set()
        for proc in procs:
            if proc.is_alive():
                proc.terminate()
        for proc in procs:
            if proc.pid is not None:
                proc.join(timeout=2.0)
                if proc.is_alive() and hasattr(proc, "kill"):
                    proc.kill()
                    proc.join(timeout=2.0)
        ready_queue.close()
        queue.close()

    grants = sorted(records, key=lambda row: row[2])
    generations = [row[1] for row in grants]
    assert len(generations) == workers * iterations
    assert len(set(generations)) == len(generations)
    assert generations == sorted(generations)
    for previous, current in zip(grants, grants[1:]):
        assert previous[3] <= current[2], (previous, current)

    lease_path = Path(__import__(
        "ultimate_pipeline.governance.single_writer.worktree_lock", fromlist=["_worktree_lease_path"]
    )._worktree_lease_path(root))
    leftovers = [p.name for p in lease_path.parent.iterdir()
                 if p.name.startswith(lease_path.name) and p.name != lease_path.name
                 and ("tmp" in p.name or "pub" in p.name or "tombstone" in p.name)]
    assert leftovers == []


def test_corrupt_generation_ledger_refuses_acquire(tmp_path):
    from ultimate_pipeline.governance.single_writer import worktree_lock as wl

    root = tmp_path / "corrupt-ledger-worktree"
    root.mkdir()
    _git("init", cwd=root)
    _git("commit", "--allow-empty", "-m", "init", cwd=root)
    ledger = wl._ledger_path(root)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("1\nnot-an-integer\n", encoding="utf-8")
    try:
        wl.acquire_worktree_lease(root, purpose="must-refuse-corrupt-ledger")
    except RuntimeError:
        pass
    else:
        raise AssertionError("a corrupt generation ledger must fail closed")
    assert not wl._worktree_lease_path(root).exists()


def test_generation_ledger_is_fsynced_before_lease_is_granted(tmp_path, monkeypatch):
    from ultimate_pipeline.governance.single_writer import worktree_lock as wl

    root = tmp_path / "fsync-ledger-worktree"
    root.mkdir()
    _git("init", cwd=root)
    _git("commit", "--allow-empty", "-m", "init", cwd=root)
    calls = []
    original = wl.os.fsync

    def record_fsync(fd):
        calls.append(os.fstat(fd).st_size)
        return original(fd)

    monkeypatch.setattr(wl.os, "fsync", record_fsync)
    lease = wl.acquire_worktree_lease(root, purpose="fsync-contract")
    try:
        assert calls, "acquire must fsync generation/lease publication before returning"
    finally:
        wl.release_worktree_lease(root, lease.owner_token, lease.lease_id)


def test_generation_claim_retries_when_removed_between_stat_and_read(tmp_path, monkeypatch):
    from ultimate_pipeline.governance.single_writer import worktree_lock as wl

    root = tmp_path / "claim-remove-race-worktree"
    root.mkdir()
    _git("init", cwd=root)
    _git("commit", "--allow-empty", "-m", "init", cwd=root)
    claim_path = wl._generation_claim_path(root)
    claim_path.parent.mkdir(parents=True, exist_ok=True)
    pid, start_identity = wl.process_identity.current_process_identity()
    claim_path.write_text(
        json.dumps(
            {"pid": pid, "start_identity": start_identity or "", "token": "stale-test-claim"}
        ),
        encoding="utf-8",
    )
    old_time = time.time() - 2.0
    os.utime(claim_path, (old_time, old_time))

    original_stat = Path.stat
    state = {"removed": False}

    def stat_then_remove(path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        if path == claim_path and not state["removed"]:
            path.unlink()
            state["removed"] = True
        return result

    monkeypatch.setattr(Path, "stat", stat_then_remove)
    with wl._generation_claim(root):
        assert state["removed"]
