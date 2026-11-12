"""Adversarial V98 common-Git fencing and authority regressions."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from ultimate_pipeline.governance.single_writer import common_git_lock as cgl


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.email=test@example.invalid", "-c", "user.name=V98 Test",
         "-c", "init.defaultBranch=main", *args],
        cwd=str(cwd), capture_output=True, text=True, check=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git("init", cwd=root)
    _git("commit", "--allow-empty", "-m", "init", cwd=root)
    return root


def test_generation_allocation_crash_gap_is_not_reused(repo: Path) -> None:
    first = cgl._issue_generation(repo)
    # Simulates a process crash after durable allocation and before publication.
    second = cgl._issue_generation(repo)
    assert second > first
    assert cgl._ledger_path(repo).read_text(encoding="ascii").splitlines() == [
        str(first), str(second)
    ]


def test_process_crash_after_allocation_leaves_nonreusable_generation(
    repo: Path, tmp_path: Path,
) -> None:
    code_root = Path(__file__).resolve().parents[2]
    output = tmp_path / "allocated.txt"
    script = tmp_path / "allocate_then_crash.py"
    script.write_text(
        "import os, sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from pathlib import Path\n"
        "from ultimate_pipeline.governance.single_writer import common_git_lock as cgl\n"
        "value=cgl._issue_generation(Path(sys.argv[2]))\n"
        "Path(sys.argv[3]).write_text(str(value))\n"
        "os._exit(0)\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(script), str(code_root), str(repo), str(output)],
        cwd=str(code_root), capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    crashed_generation = int(output.read_text(encoding="ascii"))
    assert cgl._issue_generation(repo) > crashed_generation


def test_generation_namespace_is_shared_by_linked_worktrees(repo: Path, tmp_path: Path) -> None:
    linked = tmp_path / "linked"
    _git("worktree", "add", "--detach", str(linked), cwd=repo)
    first = cgl._issue_generation(repo)
    second = cgl._issue_generation(linked)
    assert second > first
    assert cgl._ledger_path(repo).resolve() == cgl._ledger_path(linked).resolve()


def test_generation_ledger_corruption_fails_closed(repo: Path) -> None:
    ledger = cgl._ledger_path(repo)
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_bytes(b"1\n3\n2\n")
    with pytest.raises(cgl.GenerationLedgerError, match="corrupt or nonmonotonic"):
        cgl._issue_generation(repo)
    assert ledger.read_bytes() == b"1\n3\n2\n"


def test_deleted_generation_ledger_cannot_reuse_high_water(repo: Path) -> None:
    first = cgl._issue_generation(repo)
    ledger = cgl._ledger_path(repo)
    ledger.unlink()
    with pytest.raises(cgl.GenerationLedgerError, match="missing while high-water"):
        cgl._issue_generation(repo)
    assert not ledger.exists()
    assert first == 1


def test_co_deleted_ledger_and_high_water_still_fail_closed(repo: Path) -> None:
    cgl._issue_generation(repo)
    ledger = cgl._ledger_path(repo)
    cgl._generation_authority_path(repo).unlink()
    ledger.unlink()
    with pytest.raises(cgl.GenerationLedgerError, match="initialized generation ledger is missing"):
        cgl._issue_generation(repo)
    assert not ledger.exists()


def test_cross_process_allocator_is_unique_in_25_by_8_five_runs(tmp_path: Path) -> None:
    """Eight OS processes contend at a deterministic per-round barrier."""
    code_root = Path(__file__).resolve().parents[2]
    child = tmp_path / "generation_contender.py"
    child.write_text(
        "import os, sys, time\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from ultimate_pipeline.governance.single_writer import common_git_lock as cgl\n"
        "repo, barrier, worker = map(str, sys.argv[2:5]); repo=Path(repo); barrier=Path(barrier)\n"
        "for round_id in range(25):\n"
        "    ready=barrier / f'{round_id}-{worker}.ready'; ready.write_text('ready')\n"
        "    deadline=time.monotonic()+30\n"
        "    while len(list(barrier.glob(f'{round_id}-*.ready'))) < 8:\n"
        "        if time.monotonic() > deadline: raise TimeoutError('ready barrier')\n"
        "        time.sleep(.002)\n"
        "    value=cgl._issue_generation(repo)\n"
        "    (barrier / f'{round_id}-{worker}.result').write_text(str(value))\n"
        "    while len(list(barrier.glob(f'{round_id}-*.result'))) < 8:\n"
        "        if time.monotonic() > deadline: raise TimeoutError('result barrier')\n"
        "        time.sleep(.002)\n",
        encoding="utf-8",
    )

    for run_id in range(5):
        run_root = tmp_path / f"stress-{run_id}"
        run_root.mkdir()
        _git("init", cwd=run_root)
        _git("commit", "--allow-empty", "-m", "init", cwd=run_root)
        barrier = run_root / "barrier"
        barrier.mkdir()
        workers = [
            subprocess.Popen(
                [sys.executable, str(child), str(code_root), str(run_root),
                 str(barrier), str(worker)],
                cwd=str(code_root), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True,
            )
            for worker in range(8)
        ]
        outputs = [process.communicate(timeout=180) for process in workers]
        return_codes = [process.returncode for process in workers]
        assert return_codes == [0] * 8, outputs
        generations = [
            int(result.read_text(encoding="ascii"))
            for result in barrier.glob("*.result")
        ]
        assert len(generations) == 25 * 8
        assert len(set(generations)) == 25 * 8
        assert sorted(generations) == list(range(1, 25 * 8 + 1))


def test_renewal_and_successor_transition_are_serialized(repo: Path, monkeypatch) -> None:
    owner = cgl.acquire_common_git_lock(repo, "renew-race")
    entered = threading.Event()
    resume = threading.Event()
    original_write = cgl._write_lock_unlocked
    renew_result: list[object] = []

    def paused_write(lock):
        entered.set()
        assert resume.wait(5)
        original_write(lock)

    monkeypatch.setattr(cgl, "_write_lock_unlocked", paused_write)

    def renew():
        try:
            renew_result.append(cgl.renew_common_git_lock(
                repo, owner.owner_token, owner.lock_id, ttl_seconds=90
            ))
        except Exception as exc:  # captured for assertion in the main thread
            renew_result.append(exc)

    worker = threading.Thread(target=renew)
    worker.start()
    assert entered.wait(5)
    successor_result: list[object] = []

    def successor():
        try:
            cgl.release_common_git_lock(repo, owner.owner_token, owner.lock_id)
            successor_result.append(cgl.acquire_common_git_lock(repo, "successor"))
        except Exception as exc:
            successor_result.append(exc)

    successor_thread = threading.Thread(target=successor)
    successor_thread.start()
    resume.set()
    worker.join(10)
    successor_thread.join(10)
    assert not worker.is_alive() and not successor_thread.is_alive()
    assert len(renew_result) == 1 and isinstance(renew_result[0], cgl.CommonGitLock)
    assert len(successor_result) == 1 and isinstance(successor_result[0], cgl.CommonGitLock)
    current = cgl._read_lock(repo)
    assert current is not None
    assert current.lock_id == successor_result[0].lock_id
    assert current.owner_token == successor_result[0].owner_token
    cgl.release_common_git_lock(repo, current.owner_token, current.lock_id)


def test_context_manager_does_not_claim_success_after_release_failure(repo: Path, monkeypatch) -> None:
    def fail_release(*_args, **_kwargs):
        raise RuntimeError("injected release failure")

    monkeypatch.setattr(cgl, "release_common_git_lock", fail_release)
    with pytest.raises(cgl.CommonGitLockReleaseError, match="success must not be claimed"):
        with cgl.common_git_lock(repo, "release-failure"):
            pass


def test_context_manager_preserves_body_exception_and_attaches_release_failure(
    repo: Path, monkeypatch,
) -> None:
    def fail_release(*_args, **_kwargs):
        raise RuntimeError("injected release failure")

    monkeypatch.setattr(cgl, "release_common_git_lock", fail_release)
    with pytest.raises(ValueError, match="body failure") as captured:
        with cgl.common_git_lock(repo, "body-and-release-failure"):
            raise ValueError("body failure")
    assert isinstance(captured.value.lock_release_error, RuntimeError)
    assert "injected release failure" in str(captured.value.lock_release_error)


def test_malformed_recovery_claims_only_audited_bytes(repo: Path, monkeypatch) -> None:
    path = cgl._get_common_git_lock_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    audited = b"{ definitely malformed\n"
    changed = b"{ changed after audit\n"
    path.write_bytes(audited)
    original_claim = cgl._claim_by_rename_unlocked

    def replace_then_claim(root, tag, expect):
        path.write_bytes(changed)
        return original_claim(root, tag, expect)

    monkeypatch.setattr(cgl, "_claim_by_rename_unlocked", replace_then_claim)
    result = cgl.recover_malformed_lock(repo, "operator", "test exact bytes")
    assert result["recovered"] is False
    assert path.read_bytes() == changed
    assert Path(result["evidence_path"]).read_bytes() == audited
