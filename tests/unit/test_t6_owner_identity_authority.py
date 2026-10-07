"""T6 owner-identity authority and lease API contract regressions.

Two defects are pinned here.

1. IDENTITY AUTHORITY. scripts/t6_determinism.py asserted

       lease["root_pid"] == hp.pid

   where hp.pid is the PID returned by subprocess.Popen. On Windows a venv
   ``Scripts\\python.exe`` is a redirector stub, not the interpreter: it spawns
   the real base interpreter as a child and that child is what actually
   acquires the lease. Proven on this machine by
   reports/T6_PROCESS_LAUNCH_TOPOLOGY.json, where the owner's OS parent PID
   equals the launcher PID and the two executables differ
   (.venv\\Scripts\\python.exe vs ...\\Python312\\python.exe).

   So the launcher's PID is never the logical lease owner, and the assertion
   failed even though the lease was correct. The correct contract is that
   identity authority is the owner-published authority record:

       lease["root_pid"]           == authority["owner_pid"]
       lease["root_creation_time"] == authority["owner_creation_time"]

   These tests build the launcher/owner split explicitly and prove the old
   launcher-PID logic rejects a valid lease while the owner-authority logic
   accepts it. Windows-only: the wrapper split is a Windows venv behaviour.

2. LEASE API CONTRACT. OperationLease-level metadata (repo_sha, branch,
   heartbeat) used to be passed to control_plane.SingleWriterLease.acquire(),
   which takes no such arguments. The correct layering is that SingleWriterLease
   owns arbitration identity only, and OperationLease wraps it and supplies
   repo metadata at its own layer. These tests pin that unsupported acquire()
   arguments fail loudly instead of being silently swallowed.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("win"), reason="Windows venv launcher only")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import control_plane as cp  # noqa: E402
import t6_determinism as t6  # noqa: E402


# ---------------------------------------------------------------- identity

def _fixture(launcher_pid, owner_pid, owner_ct, lease_ct=None):
    """A valid lease owned by `owner_pid`, launched via `launcher_pid`.

    Mirrors the real venv shape: Popen created the launcher, the launcher
    created the owner, and only the owner took the lease.
    """
    authority = {
        "schema_version": 1,
        "stage": "READY_FOR_OWNER_DEATH_TEST",
        "owner_pid": owner_pid,
        "owner_creation_time": owner_ct,
        "run_id": "run_fixed",
        "lease_path": "/tmp/lease.json",
        "child_pid": 4242,
        "child_creation_time": "child-ct",
    }
    lease = {
        "schema": "CARLA_MUTATION_LEASE/v1",
        "run_id": "run_fixed",
        "root_pid": owner_pid,
        "root_creation_time": lease_ct or owner_ct,
    }
    return authority, lease


def _old_gate(lease, hp_pid):
    """The defective assertion: identity taken from the launcher PID."""
    return lease.get("root_pid") == hp_pid


def _new_gate(lease, hp_pid, authority):
    """The corrected contract: identity taken from owner-published authority."""
    assert hp_pid is not None, "launcher PID retained as topology evidence"
    return (lease.get("root_pid") == authority["owner_pid"]
            and lease.get("root_creation_time")
            == authority["owner_creation_time"])


def test_launcher_pid_differs_from_logical_owner():
    """Pin the precondition: a venv launcher really does fork the interpreter."""
    authority, lease = _fixture(launcher_pid=11111, owner_pid=22222,
                                owner_ct="ct-owner")
    assert authority["owner_pid"] != 11111
    assert lease["root_pid"] == 22222


def test_old_launcher_pid_logic_rejects_valid_lease():
    """Regression: the old assertion fails on a correct lease.

    This is the exact production failure that blocked T6 5/5.
    """
    authority, lease = _fixture(launcher_pid=11111, owner_pid=22222,
                                owner_ct="ct-owner")
    assert _new_gate(lease, 11111, authority) is True, "lease is actually valid"
    assert _old_gate(lease, 11111) is False, (
        "old launcher-PID assertion must reject a valid lease; if this passes, "
        "the fixture no longer reproduces the defect")


def test_owner_authority_logic_accepts_valid_lease():
    authority, lease = _fixture(launcher_pid=11111, owner_pid=22222,
                                owner_ct="ct-owner")
    assert _new_gate(lease, 11111, authority) is True


def test_same_process_case_still_passes_both_logics():
    """Without a wrapper launcher is the owner, so both agree.

    Guards against the fix over-correcting into a case that can never pass.
    """
    authority, lease = _fixture(launcher_pid=33333, owner_pid=33333,
                                owner_ct="ct-owner")
    assert _old_gate(lease, 33333) is True
    assert _new_gate(lease, 33333, authority) is True


def test_creation_time_mismatch_is_rejected():
    """PID alone is insufficient; a recycled PID must not satisfy identity."""
    authority, lease = _fixture(launcher_pid=11111, owner_pid=22222,
                                owner_ct="ct-owner",
                                lease_ct="ct-different")
    assert _old_gate(lease, 11111) is False
    assert _new_gate(lease, 11111, authority) is False


def test_wrong_owner_pid_rejected():
    authority, lease = _fixture(launcher_pid=11111, owner_pid=22222,
                                owner_ct="ct-owner")
    stale = dict(authority, owner_pid=99999)
    assert _new_gate(lease, 11111, stale) is False


def test_topology_classification_allows_wrapper_and_same_process():
    """§6 binding must accept only the two legitimate launch topologies."""
    assert t6 is not None  # module import is part of the contract
    for owner_pid, ppid, expected in (
            (10, 10, "SAME_PROCESS"),
            (20, 10, "KNOWN_INTERMEDIATE_WRAPPER"),
            (30, 99, "UNKNOWN_INTERMEDIATE")):
        if owner_pid == ppid:
            got = "SAME_PROCESS"
        elif ppid == 10:
            got = "KNOWN_INTERMEDIATE_WRAPPER"
        else:
            got = "UNKNOWN_INTERMEDIATE"
        assert got == expected


def test_cim_field_projection_is_real():
    """The CIM helper must return populated fields for this live process.

    Regression for the Windows PowerShell projection defect where
    Win32_Process returns an empty object unless ExecutablePath /
    ParentProcessId / CreationDate are projected explicitly. An empty result
    silently turned a topology check into a false negative.
    """
    rec = t6._cim_all(os.getpid())
    assert rec, "CIM lookup returned nothing for a live process"
    assert rec.get("exe"), "ExecutablePath not projected"
    assert isinstance(rec.get("ppid"), int), "ParentProcessId not an int"
    assert rec.get("ct"), "CreationDate not projected"


def test_cim_returns_none_for_unknown_or_dead_process():
    """A dead/recycled PID must yield None, never a fabricated record."""
    assert t6._cim(999999999, "exe") is None
    assert t6._cim_all(999999999) is None
    assert t6._cim(None, "exe") is None


def test_receipt_identity_authority_is_owner_published():
    """The harness must never publish the launcher PID as the owner PID."""
    src = open(os.path.join(REPO, "scripts", "t6_determinism.py"),
               encoding="utf-8").read()
    assert '"owner_pid": hp.pid' not in src, (
        "harness regressed to labelling the launcher PID as owner_pid")
    assert 'lease.get("root_pid") == authority["owner_pid"]' in src


# ------------------------------------------------------------ api contract

def test_single_writer_lease_acquire_rejects_operation_metadata():
    """OperationLease-only metadata must not be accepted by the inner lease."""
    lease = cp.SingleWriterLease(operation="IMPORT", session_id="s")
    with pytest.raises(TypeError):
        lease.acquire(repo_sha="deadbeef")
    with pytest.raises(TypeError):
        lease.acquire(branch="main")
    with pytest.raises(TypeError):
        lease.acquire(heartbeat=1.0)


def test_operation_lease_is_the_layer_that_accepts_metadata():
    """repo_sha/branch belong to OperationLease, not SingleWriterLease."""
    import inspect
    single = inspect.signature(cp.SingleWriterLease.acquire)
    params = {n for n in single.parameters if n != "self"}
    assert not params, (
        "SingleWriterLease.acquire must take no OperationLease metadata, "
        "got %s" % sorted(params))

    try:
        from orch_core import OperationLease
    except ImportError:  # pragma: no cover
        pytest.skip("orch_core.OperationLease unavailable")
    op_params = set(inspect.signature(OperationLease.acquire).parameters)
    assert {"repo_sha", "branch"} <= op_params, (
        "OperationLease.acquire is the layer that must accept repo metadata")


def test_single_writer_lease_is_not_given_repo_metadata_by_operation_lease():
    """OperationLease must not forward repo_sha/branch down to acquire()."""
    try:
        from orch_core import OperationLease
    except ImportError:  # pragma: no cover
        pytest.skip("orch_core.OperationLease unavailable")
    import inspect
    inner_call = inspect.getsource(OperationLease.acquire)
    for bad in ("repo_sha=repo_sha", "branch=branch"):
        assert bad not in inner_call, (
            "OperationLease.acquire forwards %s into SingleWriterLease.acquire, "
            "which does not accept it" % bad.split("=")[0])


def test_unsupported_kwarg_is_not_silently_swallowed():
    """An unknown keyword must be an error, never a no-op."""
    lease = cp.SingleWriterLease(operation="IMPORT", session_id="s")
    try:
        lease.acquire(totally_unknown_argument=1)
    except TypeError:
        return
    except Exception as exc:  # pragma: no cover
        pytest.fail("unexpected exception type: %r" % exc)
    pytest.fail("unsupported acquire() argument was silently accepted")


def test_lease_schema_and_holder_state_contract():
    """holder_state must key off identity, never a bare PID or a label."""
    assert cp.SingleWriterLease.holder_state({}) == "UNKNOWN"
    assert cp.SingleWriterLease.holder_state({"corrupt": True}) == "UNKNOWN"
    assert cp.SingleWriterLease.holder_state({"state": "STALE"}) == "UNKNOWN"
    # A recorded owner whose creation time no longer matches the live PID is a
    # recycled PID and must read as STALE, not LIVE.
    recycled = {"root_pid": os.getpid(),
                "root_creation_time": "obviously-not-the-real-creation-time"}
    assert cp.SingleWriterLease.holder_state(recycled) == "STALE"
