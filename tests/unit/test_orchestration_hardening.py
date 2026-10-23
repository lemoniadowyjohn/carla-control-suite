"""Failure-injection and hardening test suite.

Every test drives the real orchestration components (orch_core, orch_env) under
a deliberately induced condition, because these are exactly the paths where a
silent PASS is possible. Nothing here is mocked at the logic layer: leases hit
the filesystem, journals use atomic replaces, and the typed gates are exercised
with the JSON values that broke the original release gate.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts"))

from orch_core import (  # noqa: E402
    JournalTransitionError, LeaseConflict, OperationLease, RunJournal,
    TERMINATION_ACCESS_VIOLATION, TERMINATION_C_CONTROL,
    TERMINATION_NONZERO, TERMINATION_NORMAL, TERMINATION_RESOURCE,
    TERMINATION_TIMEOUT, TERMINATION_UNKNOWN, TERMINATION_WORKER_LOST,
    classify_termination, process_creation_time, process_identity,
    termination_receipt,
)
from orch_env import (  # noqa: E402
    GateTypeError, gate_bool, gate_exact, gate_not_none,
    resume_integrity, storage_reservation, validate_schema,
)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def tmpdir():
    d = tempfile.mkdtemp(prefix="orch_hardening_")
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# termination classification (phase 3)
# ---------------------------------------------------------------------------
def test_zero_exit_is_normal():
    assert classify_termination(0) == TERMINATION_NORMAL


@pytest.mark.parametrize("code,expected", [
    (1, TERMINATION_NONZERO),
    (2, TERMINATION_NONZERO),
    (-1073741510, TERMINATION_C_CONTROL),
    (3221225786, TERMINATION_C_CONTROL),
    (0xC0000005, TERMINATION_ACCESS_VIOLATION),
    (0xC0000409, TERMINATION_ACCESS_VIOLATION),
    (0xC0000017, TERMINATION_RESOURCE),
    (0xC0000020, TERMINATION_RESOURCE),
])
def test_exit_codes_are_not_collapsed(code, expected):
    """Distinct causes must not all become FAILED."""
    assert classify_termination(code) == expected


def test_unsigned_ntstatus_above_32bit_is_recognised():
    assert classify_termination(-1, exit_code_raw=0xC0000005) == TERMINATION_ACCESS_VIOLATION


def test_timeout_and_worker_loss_are_distinct():
    assert classify_termination(0, timed_out=True) == TERMINATION_TIMEOUT
    assert classify_termination(None, worker_disappeared=True) == TERMINATION_WORKER_LOST


def test_missing_exit_code_is_unknown_not_success():
    assert classify_termination(None) == TERMINATION_UNKNOWN


def test_two_nonzero_causes_do_not_collapse():
    """The point of the schema: 1 and an access violation are different facts."""
    assert (classify_termination(1)
            != classify_termination(0xC0000005) != classify_termination(-1073741510))


def test_termination_receipt_has_identity_and_hashes(tmpdir):
    out = os.path.join(tmpdir, "o.log")
    err = os.path.join(tmpdir, "e.log")
    with open(out, "wb") as fh:
        fh.write(b"hello")
    with open(err, "wb") as fh:
        fh.write(b"bad")
    r = termination_receipt(os.getpid(), ["cmd", "x"], 3, stdout_path=out,
                            stderr_path=err, started_utc="t0")
    assert r["schema"] == "PROCESS_TERMINATION_RECEIPT/v1"
    assert r["exit_code_hex"] == "0x00000003"
    assert r["termination_class"] == TERMINATION_NONZERO
    assert r["stdout_sha256"] and r["stderr_sha256"]
    assert r["stdout_sha256"] != r["stderr_sha256"]
    assert "identity_key" in r and "creation_time_utc" in r


# ---------------------------------------------------------------------------
# single-writer lease (phase 1)
# ---------------------------------------------------------------------------
def test_live_lease_denies_second_writer(tmpdir):
    path = os.path.join(tmpdir, "lease.json")
    first = OperationLease(path, "import", owner_pid=os.getpid())
    first.acquire(repo_sha="abc", branch="main")

    second = OperationLease(path, "cook", owner_pid=os.getpid())
    with pytest.raises(LeaseConflict) as exc:
        second.acquire()
    assert "live" in str(exc.value).lower()


def test_lease_records_required_fields(tmpdir):
    path = os.path.join(tmpdir, "lease.json")
    lease = OperationLease(path, "import", owner_pid=os.getpid(),
                           repo=REPO, project_path="x")
    rec = lease.acquire(repo_sha="deadbeef", branch="b1")
    for field in ("run_id", "operation", "owner_identity", "user", "repo_sha",
                  "branch", "project_path", "start_utc", "heartbeat_utc"):
        assert field in rec, field
    assert rec["owner_identity"]["creation_time_utc"], "PID alone is not identity"
    assert rec["owner_identity"]["identity_key"]


def test_stale_lease_must_be_reconciled_not_stolen(tmpdir):
    path = os.path.join(tmpdir, "lease.json")
    lease = OperationLease(path, "import", owner_pid=999999999)
    record = lease.acquire()
    assert OperationLease.holder_state(record) == "STALE"

    # A new writer must NOT silently take over.
    other = OperationLease(path, "cook", owner_pid=os.getpid())
    with pytest.raises(LeaseConflict) as exc:
        other.acquire()
    assert "reconcil" in str(exc.value).lower()

    outcome = OperationLease.reconcile(path, acknowledged_by_run_id="test")
    assert outcome["action"] == "RECONCILED"
    assert os.path.isfile(path + ".reconciled.json")
    other.acquire()  # now permitted


def test_corrupt_lease_blocks_rather_than_allows(tmpdir):
    path = os.path.join(tmpdir, "lease.json")
    with open(path, "w") as fh:
        fh.write("{not json")
    with pytest.raises(LeaseConflict):
        OperationLease(path, "cook", owner_pid=os.getpid()).acquire()


def test_release_then_reacquire(tmpdir):
    path = os.path.join(tmpdir, "lease.json")
    a = OperationLease(path, "import", owner_pid=os.getpid())
    a.acquire()
    a.release("COMPLETE")
    assert not os.path.exists(path)
    b = OperationLease(path, "cook", owner_pid=os.getpid())
    assert b.acquire()["operation"] == "cook"


def test_reconcile_refuses_live_lease(tmpdir):
    path = os.path.join(tmpdir, "lease.json")
    OperationLease(path, "import", owner_pid=os.getpid()).acquire()
    with pytest.raises(LeaseConflict):
        OperationLease.reconcile(path, "test")


def test_recycled_pid_is_detected_as_stale(tmpdir):
    """A lease whose recorded creation time no longer matches is stale."""
    path = os.path.join(tmpdir, "lease.json")
    lease = OperationLease(path, "import", owner_pid=os.getpid())
    rec = lease.acquire()
    rec["owner_identity"]["creation_time_utc"] = "1999-01-01T00:00:00.0000000Z"
    with open(path, "w") as fh:
        json.dump(rec, fh)
    assert OperationLease.holder_state(rec) == "STALE"


# ---------------------------------------------------------------------------
# transactional run journal (phase 4)
# ---------------------------------------------------------------------------
def test_journal_illegal_transition_is_rejected(tmpdir):
    j = RunJournal(os.path.join(tmpdir, "j.json"), operation="cook")
    with pytest.raises(JournalTransitionError):
        j.transition("COMPLETE")  # PLANNED -> COMPLETE is not allowed
    assert j.record["state"] == "PLANNED"


def test_journal_happy_path(tmpdir):
    j = RunJournal(os.path.join(tmpdir, "j.json"), operation="import")
    j.transition("PREFLIGHT_PASS")
    j.transition("RUNNING")
    j.transition("PROGRESS", note_progress="1/20")
    j.transition("COMPLETING")
    j.transition("COMPLETE")
    states = [h["state"] for h in j.record["history"]]
    assert states == ["PLANNED", "PREFLIGHT_PASS", "RUNNING", "PROGRESS",
                      "COMPLETING", "COMPLETE"]


def test_journal_is_never_partially_written(tmpdir):
    """Atomic replace: a reader sees either the old or the whole new record."""
    path = os.path.join(tmpdir, "j.json")
    j = RunJournal(path, operation="cook")
    j.transition("PREFLIGHT_PASS")
    first = open(path, encoding="utf-8").read()
    json.loads(first)  # parses => valid snapshot
    j.transition("RUNNING")
    second = open(path, encoding="utf-8").read()
    json.loads(second)
    assert len(second) > 0


def test_no_temp_files_left_behind(tmpdir):
    j = RunJournal(os.path.join(tmpdir, "j.json"), operation="cook")
    j.transition("PREFLIGHT_PASS")
    leftovers = [f for f in os.listdir(tmpdir) if f.startswith(".tmp-")]
    assert leftovers == []


def test_killed_run_classified_as_recovery_required(tmpdir):
    """Simulates abrupt death: journal left mid-flight, no terminal state."""
    path = os.path.join(tmpdir, "j.json")
    j = RunJournal(path, operation="cook")
    j.transition("PREFLIGHT_PASS")
    j.transition("RUNNING")
    # process dies here; nothing else written
    reloaded = RunJournal.load(path)
    verdict = RunJournal.classify_on_restart(reloaded.record)
    assert verdict["action"] == "RECONCILE_THEN_DECIDE"
    assert verdict["resumable"] is False
    assert verdict["classification"] == "UNKNOWN_RECOVERY_REQUIRED"


def test_terminal_journal_needs_no_recovery(tmpdir):
    path = os.path.join(tmpdir, "j.json")
    j = RunJournal(path, operation="cook")
    j.transition("PREFLIGHT_PASS")
    j.transition("RUNNING")
    j.transition("FAILED")
    verdict = RunJournal.classify_on_restart(RunJournal.load(path).record)
    assert verdict["action"] == "NONE_TERMINAL"


# ---------------------------------------------------------------------------
# resume integrity (phase 5)
# ---------------------------------------------------------------------------
def _inputs(**over):
    base = {
        "ENGINE_SHA": "e1", "CARLA_SHA": "c1", "PROJECT_SHA": "p1",
        "IMPORT_PY_SHA": "i1", "DEFAULT_ENGINE_INI_SHA": "d1",
        "XODR_SHA": "x1", "FBX_OBJECT_HASHES": "f1",
        "IMPORT_SETTINGS_SHA": "s1", "DDC_CONFIG_SHA": "d2",
        "TARGETED_RHIS_SHA": "r1", "MAP_REGISTRY_IDENTITY": "m1",
        "COOK_COMMAND_SHA": "cmd1", "PLUGIN_BINARY_SHA": "b1",
    }
    base.update(over)
    return base


def test_resume_allowed_when_identical():
    r = resume_integrity(_inputs(), _inputs())
    assert r["ITERATIVE_RESUME_ALLOWED"] is True


def test_resume_denied_when_xodr_changes():
    r = resume_integrity(_inputs(), _inputs(XODR_SHA="x2"))
    assert r["ITERATIVE_RESUME_ALLOWED"] is False
    assert any(d["input"] == "XODR_SHA" for d in r["denied_differences"])


def test_resume_denied_on_engine_change():
    r = resume_integrity(_inputs(), _inputs(ENGINE_SHA="e2"))
    assert r["ITERATIVE_RESUME_ALLOWED"] is False


def test_missing_input_is_not_treated_as_match():
    """Absence of evidence must not read as equality."""
    incomplete = _inputs()
    del incomplete["PLUGIN_BINARY_SHA"]
    r = resume_integrity(_inputs(), incomplete)
    assert r["ITERATIVE_RESUME_ALLOWED"] is False
    assert "PLUGIN_BINARY_SHA" in r["missing_inputs"]


def test_documented_rule_can_tolerate_a_difference():
    r = resume_integrity(_inputs(), _inputs(COOK_COMMAND_SHA="cmd2"))
    assert r["ITERATIVE_RESUME_ALLOWED"] is True
    assert r["tolerated_differences"][0]["input"] == "COOK_COMMAND_SHA"


def test_empty_rule_set_means_no_tolerance():
    r = resume_integrity(_inputs(), _inputs(COOK_COMMAND_SHA="cmd2"),
                         documented_rules={})
    assert r["ITERATIVE_RESUME_ALLOWED"] is False


# ---------------------------------------------------------------------------
# storage reservation (phase 9)
# ---------------------------------------------------------------------------
def test_reservation_deny_when_would_eat_another_runs_budget():
    r = storage_reservation(reserve_bytes=10, expected_growth_bytes=95,
                            reservations=[{"run_id": "a", "reserved_bytes": 90}],
                            free_bytes=100, hard_floor_bytes=5)
    assert r["allowed"] is False
    assert r["RESERVED_BY_ACTIVE_RUNS"] == 90
    assert r["violations"]


def test_reservation_allows_when_reserve_intact():
    r = storage_reservation(reserve_bytes=10, expected_growth_bytes=5,
                            reservations=[{"run_id": "a", "reserved_bytes": 10}],
                            free_bytes=100, hard_floor_bytes=5)
    assert r["allowed"] is True


def test_reservation_respects_hard_floor():
    # free 100, no other reservations, growth 96 => post-run reserve 4,
    # which is below the required reserve (10) and below the hard floor (5).
    r = storage_reservation(reserve_bytes=10, expected_growth_bytes=96,
                            reservations=[{"run_id": "a", "reserved_bytes": 0}],
                            free_bytes=100, hard_floor_bytes=5)
    assert r["allowed"] is False
    assert "post_run_reserve < hard_floor" in r["violations"]
    assert r["POST_RUN_RESERVE"] == 4


# ---------------------------------------------------------------------------
# typed gates (phase 28) -- the False == 0 regression
# ---------------------------------------------------------------------------
def test_false_does_not_satisfy_boolean_gate():
    assert gate_bool(False, expected=True) is False
    assert gate_bool(True, expected=True) is True
    assert gate_bool(False, expected=False) is True


@pytest.mark.parametrize("value", [0, 1, "false", "true", [], {}, None, 0.0])
def test_non_bool_rejected_by_boolean_gate(value):
    with pytest.raises(GateTypeError):
        gate_bool(value, expected=True)


def test_int_zero_does_not_satisfy_bool_gate_expecting_false():
    """The exact original defect: False == 0."""
    assert 0 == False, "python really does equate these"
    with pytest.raises(GateTypeError):
        gate_bool(0, expected=False)


@pytest.mark.parametrize("value", ["0", False, None, [], {}, 0.0, "false"])
def test_int_gate_rejects_non_int(value):
    with pytest.raises(GateTypeError):
        gate_exact(value, 0, expected_type=int)


def test_int_gate_accepts_real_zero():
    assert gate_exact(0, 0, expected_type=int) is True
    assert gate_exact(1, 0, expected_type=int) is False


def test_bool_gate_expects_bool():
    assert gate_exact(False, False, expected_type=bool) is True
    with pytest.raises(GateTypeError):
        gate_exact(0, False, expected_type=bool)


def test_str_gate_is_type_strict():
    assert gate_exact("PASS", "PASS", expected_type=str) is True
    with pytest.raises(GateTypeError):
        gate_exact(0, "PASS", expected_type=str)


def test_gate_not_none():
    assert gate_not_none(0) is True
    assert gate_not_none(False) is True
    assert gate_not_none(None) is False


def test_schema_version_gate_rejects_unknown_version():
    ok, why = validate_schema({"schema": "X/v1", "schema_version": 1}, "X/v1")
    assert ok is True
    ok, why = validate_schema({"schema": "X/v1", "schema_version": 99}, "X/v1")
    assert ok is False and "schema_version" in why


def test_schema_gate_rejects_wrong_schema_name():
    ok, _ = validate_schema({"schema": "Y/v1", "schema_version": 1}, "X/v1")
    assert ok is False


def test_old_report_format_is_not_silently_accepted():
    """Stale evidence must not be reinterpreted as a current contract."""
    legacy = {"schema": "X/v1"}  # no schema_version
    ok, _ = validate_schema(legacy, "X/v1")
    assert ok is False


# ---------------------------------------------------------------------------
# process identity (phase 1)
# ---------------------------------------------------------------------------
def test_process_identity_keys_on_creation_time():
    ident = process_identity(os.getpid(), run_id="r1")
    assert ident["alive"] is True
    assert ident["creation_time_utc"]
    assert ident["identity_key"] == "%d|%s" % (os.getpid(), ident["creation_time_utc"])


def test_dead_pid_identity_is_marked_dead():
    ident = process_identity(999999999)
    assert ident["alive"] is False
    assert ident["identity_key"] is None
    assert process_creation_time(999999999) is None
