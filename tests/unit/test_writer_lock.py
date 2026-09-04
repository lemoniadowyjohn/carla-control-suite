import json
import time
from pathlib import Path

import pytest

from ultimate_pipeline.contracts.writer_lock import (
    WriterLock,
    CANONICAL_LOCK_PATH,
)


def test_acquire_and_release(tmp_path: Path) -> None:
    lock = WriterLock.acquire(
        root=tmp_path,
        branch="test-branch",
        head_sha="abcdef1234567890",
        owner="test-agent",
    )
    assert lock.status == "active"
    assert lock.owner == "test-agent"
    assert lock.branch == "test-branch"
    assert lock.head_sha == "abcdef1234567890"
    assert lock.pid > 0
    assert lock.lock_id

    lock_path = tmp_path / ".agent_locks" / "writer.lock"
    assert lock_path.exists()

    lock.release(owner="test-agent", lock_id=lock.lock_id)
    assert lock.status == "released"


def test_second_acquire_blocked(tmp_path: Path) -> None:
    WriterLock.acquire(
        root=tmp_path,
        branch="branch-a",
        head_sha="aaa",
        owner="agent-1",
        lease_minutes=60,
    )
    with pytest.raises(RuntimeError, match="Writer lock held by"):
        WriterLock.acquire(
            root=tmp_path,
            branch="branch-b",
            head_sha="bbb",
            owner="agent-2",
            lease_minutes=60,
        )


def test_expired_lock_can_be_reacquired(tmp_path: Path) -> None:
    lock = WriterLock.acquire(
        root=tmp_path,
        branch="branch-old",
        head_sha="old",
        owner="agent-1",
        lease_minutes=0,
    )
    assert lock.is_expired()

    lock2 = WriterLock.acquire(
        root=tmp_path,
        branch="branch-new",
        head_sha="new",
        owner="agent-2",
        lease_minutes=60,
    )
    assert lock2.owner == "agent-2"


def test_malformed_lock_rejected(tmp_path: Path) -> None:
    lock_path = tmp_path / ".agent_locks" / "writer.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text('{"status": "active"}')
    loaded = WriterLock.load(lock_path)
    assert loaded.is_malformed()


def test_legacy_lock_conflict_rejected(tmp_path: Path) -> None:
    legacy_path = tmp_path / ".agent_lock.json"
    legacy_path.write_text(
        json.dumps(
            {
                "schema": "agent-writer-lock/v1",
                "status": "active",
                "owner": "legacy-agent",
                "branch": "legacy-branch",
                "head_sha": "legacy-sha",
                "created_at": "2026-07-30T00:00:00+00:00",
                "expires_at": "2099-01-01T00:00:00+00:00",
                "pid": 1,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="Legacy writer lock held"):
        WriterLock.acquire(
            root=tmp_path,
            branch="branch",
            head_sha="sha",
            owner="agent",
        )


def test_owner_check(tmp_path: Path) -> None:
    lock = WriterLock.acquire(
        root=tmp_path,
        branch="test",
        head_sha="abc",
        owner="my-agent",
        lease_minutes=60,
    )
    assert lock.owned_by("my-agent")
    assert not lock.owned_by("other-agent")


def test_wrong_owner_release_rejected(tmp_path: Path) -> None:
    lock = WriterLock.acquire(
        root=tmp_path,
        branch="test",
        head_sha="abc",
        owner="my-agent",
    )
    with pytest.raises(RuntimeError, match="release rejected for owner"):
        lock.release(owner="other-agent")
    lock.release(owner="my-agent", lock_id=lock.lock_id)


def test_is_live(tmp_path: Path) -> None:
    lock = WriterLock.acquire(
        root=tmp_path,
        branch="test",
        head_sha="abc",
        owner="agent",
        lease_minutes=1,
    )
    assert lock.is_live()
    assert not lock.is_expired()


def test_read_only_coexistence(tmp_path: Path) -> None:
    read_only_lock = WriterLock.acquire(
        root=tmp_path,
        branch="test",
        head_sha="abc",
        owner="reader",
        read_only=True,
    )
    assert read_only_lock.status == "read_only"
    assert not read_only_lock.is_live()

    writer_lock = WriterLock.acquire(
        root=tmp_path,
        branch="test",
        head_sha="def",
        owner="writer",
    )
    assert writer_lock.status == "active"


def test_path_overlap_detection(tmp_path: Path) -> None:
    lock = WriterLock.acquire(
        root=tmp_path,
        branch="test",
        head_sha="abc",
        owner="agent",
        allowed_paths=["reports/**", "*.md"],
        forbidden_paths=["cities/**"],
    )
    assert not lock.overlaps_path(tmp_path / "reports" / "base_closure" / "BC01.md")
    assert lock.overlaps_path(tmp_path / "cities" / "blocked.txt")
    assert lock.overlaps_path(tmp_path / "nested" / "notes.txt")


def test_heartbeat(tmp_path: Path) -> None:
    lock = WriterLock.acquire(
        root=tmp_path,
        branch="test",
        head_sha="abc",
        owner="agent",
        lease_minutes=60,
    )
    old_heartbeat = lock.heartbeat_at
    time.sleep(0.01)
    lock.heartbeat()
    assert lock.heartbeat_at != old_heartbeat


def test_save_and_load(tmp_path: Path) -> None:
    lock = WriterLock.acquire(
        root=tmp_path,
        branch="test-branch",
        head_sha="abcdef",
        owner="test-agent",
    )
    lock_path = tmp_path / ".agent_locks" / "writer.lock"
    loaded = WriterLock.load(lock_path)
    assert loaded.owner == lock.owner
    assert loaded.branch == lock.branch
    assert loaded.head_sha == lock.head_sha


def test_allowed_paths(tmp_path: Path) -> None:
    lock = WriterLock.acquire(
        root=tmp_path,
        branch="test",
        head_sha="abc",
        owner="agent",
        allowed_paths=["reports/*", "*.md"],
        forbidden_paths=["cities/*"],
    )
    assert len(lock.allowed_paths) == 2
    assert len(lock.forbidden_paths) == 1


def test_canonical_path() -> None:
    # Path str() renders with the OS-native separator (backslash on Windows,
    # forward slash on Linux/Mac); compare via Path equality, which
    # normalizes both operands the same way, rather than a hardcoded
    # separator literal.
    assert CANONICAL_LOCK_PATH == Path(".agent_locks") / "writer.lock"
