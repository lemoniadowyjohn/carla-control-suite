"""Contract V2 governance regressions for the supervised UE harness.

Each test targets a defect proven on the historical COOK_620e51db run.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ultimate_pipeline" / "governance" / "single_writer"))

import lease_store as _ls  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    """Every test gets its own lease directory; never touch the real one."""
    _ls.set_dir_override(str(tmp_path / "leases"))
    yield
    _ls.set_dir_override(None)


# --- G2: heartbeat must fail closed on a dead owner ----------------------

def test_heartbeat_promotes_acquired_to_running_when_owner_alive():
    lease = _ls.new_lease("T", ["D"], _ls.fingerprint_operation({"a": 1}),
                          "Global")
    _ls._write_current(lease)
    _ls.heartbeat(lease)
    assert lease.state == "RUNNING"


def test_heartbeat_does_not_refresh_dead_owner():
    """Historical defect: a dead owner kept receiving fresh heartbeats."""
    lease = _ls.new_lease("T", ["D"], _ls.fingerprint_operation({"a": 1}),
                          "Global")
    lease.root_pid = 999999           # implausible / nonexistent pid
    lease.root_creation_time = "2000-01-01T00:00:00.000000Z"
    _ls._write_current(lease)
    before = lease.heartbeat_utc
    _ls.heartbeat(lease)
    assert lease.state == "STALE"
    assert lease.heartbeat_utc == before, "dead owner must not be refreshed"
    assert lease.terminal_state == "OWNER_IDENTITY_LOST"


def test_heartbeat_detects_pid_reuse():
    """Same pid, different creation time => the pid is NOT our process."""
    lease = _ls.new_lease("T", ["D"], _ls.fingerprint_operation({"a": 1}),
                          "Global")
    lease.root_pid = os.getpid()                       # genuinely alive
    lease.root_creation_time = "2000-01-01T00:00:00.000000Z"  # wrong identity
    _ls._write_current(lease)
    _ls.heartbeat(lease)
    assert lease.state == "STALE", "pid reuse must not pass as valid"


def test_heartbeat_ignores_a_different_run():
    lease = _ls.new_lease("A", ["D"], _ls.fingerprint_operation({"a": 1}),
                          "Global")
    other = _ls.new_lease("B", ["D"], _ls.fingerprint_operation({"a": 2}),
                          "Global")
    _ls._write_current(other)
    before = lease.heartbeat_utc
    _ls.heartbeat(lease)
    assert lease.heartbeat_utc == before


# --- G3: terminal transition ---------------------------------------------

def test_release_moves_lease_out_of_running_and_persists_terminal():
    lease = _ls.new_lease("T", ["D"], _ls.fingerprint_operation({"a": 1}),
                          "Global")
    _ls._write_current(lease)
    _ls.heartbeat(lease)
    assert lease.state == "RUNNING"
    _ls.release(lease, "CLEAN_SUCCESS")
    assert lease.state == "RELEASED"
    assert lease.end_utc
    assert lease.terminal_state == "CLEAN_SUCCESS"
    assert _ls.read_current() is None, "current lease must be cleared"


def test_release_is_reachable_by_the_harness():
    """The function already existed; the harness never called it."""
    import inspect
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sup", ROOT / "tools" / "supervised_ue_run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    src = inspect.getsource(mod)
    assert "release(lease" in src, "harness must release the lease"
    assert "_ls.release" in src


# --- G1 / G4: acquisition and mutation-root binding ----------------------

def test_harness_acquires_its_own_lease():
    import inspect
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sup", ROOT / "tools" / "supervised_ue_run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    src = inspect.getsource(mod)
    assert "new_lease(" in src, "harness must acquire a lease"
    assert "rebind_mutation_root" in src, "lease must bind to the mutation root"


def test_new_lease_records_creation_time():
    lease = _ls.new_lease("T", ["D"], _ls.fingerprint_operation({"a": 1}),
                          "Global")
    assert lease.root_pid == os.getpid()
    assert lease.root_creation_time, "authoritative pid needs a creation time"


def test_rebind_mutation_root_sets_pid_and_creation_time():
    lease = _ls.new_lease("T", ["D"], _ls.fingerprint_operation({"a": 1}),
                          "Global")
    _ls.rebind_mutation_root(lease, os.getpid())
    assert lease.root_pid == os.getpid()
    assert lease.root_creation_time


def test_rebind_refuses_when_creation_time_unavailable():
    lease = _ls.new_lease("T", ["D"], _ls.fingerprint_operation({"a": 1}),
                          "Global")
    with pytest.raises(RuntimeError):
        _ls.rebind_mutation_root(lease, 999999)


# --- Contract V2: no naked authoritative PIDs in the receipt -------------

def test_receipt_schema_has_no_naked_top_level_pids():
    """v1 persisted launcher_pid/executor_pid bare; v2 must not."""
    import inspect
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sup", ROOT / "tools" / "supervised_ue_run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    src = inspect.getsource(mod)
    assert '"executor_pid"]' not in src, "naked executor pid is forbidden"
    assert 'supervised_ue_run/v2' in src


def test_stale_lease_is_never_treated_as_valid_coverage():
    """A lease that failed closed must not look like a live lease.

    is_stale() is intentionally TTL-gated (no silent auto-reclaim), so it is
    NOT the mechanism that marks the lease dead -- heartbeat() is. The
    invariant that matters is that the lease leaves the RUNNING set and
    records why, so no later reader can treat it as coverage.
    """
    lease = _ls.new_lease("T", ["D"], _ls.fingerprint_operation({"a": 1}),
                          "Global")
    _ls._write_current(lease)
    lease.root_pid = 999999
    lease.root_creation_time = "2000-01-01T00:00:00.000000Z"
    _ls.heartbeat(lease)

    persisted = _ls.read_current()
    assert persisted is not None
    assert persisted.state == "STALE", "must not still read RUNNING"
    assert persisted.state != "RUNNING"
    assert persisted.terminal_state == "OWNER_IDENTITY_LOST"
    # TTL-based staleness is a separate, explicit reconciliation concern.
    assert _ls.is_stale(lease) is False, "recent heartbeat age is not TTL stale"


def test_reconcile_stale_refuses_to_steal_a_live_lease():
    lease = _ls.new_lease("T", ["D"], _ls.fingerprint_operation({"a": 1}),
                          "Global")
    _ls._write_current(lease)
    out = _ls.reconcile_stale()
    assert out["action"] == "refused"
    assert _ls.read_current().run_id == lease.run_id


def test_contract_document_exists():
    doc = ROOT / "reports" / "PROCESS_IDENTITY_CONTRACT_V2.json"
    assert doc.exists(), "Contract V2 must be present"
    data = json.loads(doc.read_text(encoding="utf-8"))
    assert data["schema"] == "PROCESS_IDENTITY_CONTRACT_V2/v1"
    assert data["roles"]["executor"]["authoritative"] is False
    assert "creation_time" in data["forbidden"][0]


def test_heartbeat_reaches_released_state_safely():
    lease = _ls.new_lease("T", ["D"], _ls.fingerprint_operation({"a": 1}),
                          "Global")
    _ls._write_current(lease)
    _ls.heartbeat(lease)
    _ls.release(lease, "CLEAN_SUCCESS")
    before = lease.heartbeat_utc
    _ls.heartbeat(lease)
    assert lease.state == "RELEASED"
    assert lease.heartbeat_utc == before
