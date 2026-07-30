from __future__ import annotations

from pathlib import Path

import pytest

from ultimate_pipeline.contracts.agent_sync import (
    AgentSyncContract,
    load_agent_sync,
    validate_agent_sync,
)
from ultimate_pipeline.contracts.writer_lock import CANONICAL_LOCK_PATH, WriterLock

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_repo_agent_sync_yaml_exists_loads_and_is_canonical() -> None:
    path = REPO_ROOT / "agent_sync.yaml"
    assert path.exists(), "agent_sync.yaml must exist at repo root (P3 base closure)"
    contract = load_agent_sync(path)
    assert contract.lock_policy.lock_file == ".agent_locks/writer.lock"
    report = validate_agent_sync(path)
    assert report["valid"], report["errors"]


def test_generated_contract_round_trips(tmp_path) -> None:
    path = tmp_path / "agent_sync.yaml"
    AgentSyncContract().save(path)
    contract = load_agent_sync(path)
    assert contract.version >= 1
    assert contract.lock_policy.lock_file == ".agent_locks/writer.lock"
    # Canonical sensor-rig directions must survive the round trip.
    assert contract.sensor_rig.ctv_inverted is False
    assert contract.sensor_rig.vtl_inverted is True
    assert contract.sensor_rig.use_K_undistortion is True


def test_validate_rejects_inverted_ctv(tmp_path) -> None:
    path = tmp_path / "agent_sync.yaml"
    contract = AgentSyncContract()
    contract.sensor_rig.ctv_inverted = True  # forbidden by the contract
    contract.save(path)
    report = validate_agent_sync(path)
    assert not report["valid"]
    assert any("cTv" in err for err in report["errors"])


def test_lock_file_is_canonical_path() -> None:
    assert str(CANONICAL_LOCK_PATH).replace("\\", "/") == ".agent_locks/writer.lock"


def test_lock_acquire_blocks_second_live_acquire(tmp_path) -> None:
    WriterLock.acquire(tmp_path, "branch", "sha", owner="A")
    with pytest.raises(RuntimeError):
        WriterLock.acquire(tmp_path, "branch", "sha", owner="B")


def test_lock_replaces_malformed_lock(tmp_path) -> None:
    lock_path = tmp_path / ".agent_locks" / "writer.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text('{"schema": "agent-writer-lock/v1"}', encoding="utf-8")
    # Missing required fields => malformed and not live => acquire replaces it.
    lock = WriterLock.acquire(tmp_path, "branch", "sha", owner="A")
    assert lock.status == "active"
    assert lock.owner == "A"
