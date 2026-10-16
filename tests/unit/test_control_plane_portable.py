"""Platform-neutral coverage for scripts/control_plane.py helpers.

The Win32 named-mutex arbitration suite is skipped on non-Windows because the
control plane it validates acquires a Global\\ named mutex. Several helpers in
that same module, however, are pure logic with no OS dependency -- path
scoping, read-only preflight, configuration comparison, ungoverned-mutator
detection and operation fingerprinting.

Those behaviours used to execute on Linux only incidentally, as a side effect
of the arbitration module not being guarded. This module keeps them under
explicit cross-platform test so the platform guard does not quietly drop real
coverage.
"""
from __future__ import annotations

import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "scripts"))

import control_plane as cp  # noqa: E402
from control_plane import (  # noqa: E402
    compare_configuration,
    detect_ungoverned_mutators,
    mutation_preflight,
    run_scoped_settings_path,
    run_scoped_staging,
    SingleWriterLease,
)


# --- run-scoped staging / settings paths ------------------------------------
def test_run_scoped_settings_paths_are_isolated(tmp_path):
    a = run_scoped_settings_path(str(tmp_path / "staging"), "runA")
    b = run_scoped_settings_path(str(tmp_path / "staging"), "runB")
    assert a != b
    assert "runA" in a and "runB" in b


def test_run_scoped_settings_content_is_isolated(tmp_path):
    root = str(tmp_path / "staging")
    a = run_scoped_settings_path(root, "runA")
    b = run_scoped_settings_path(root, "runB")
    with open(a, "w", encoding="utf-8") as fh:
        fh.write('{"tiles": ["a"]}')
    with open(b, "w", encoding="utf-8") as fh:
        fh.write('{"tiles": ["b"]}')
    with open(b, "w", encoding="utf-8") as fh:
        fh.write('{"tiles": ["MUTATED"]}')
    with open(a, encoding="utf-8") as fh:
        assert fh.read() == '{"tiles": ["a"]}'


def test_run_scoped_staging_isolated(tmp_path):
    a = run_scoped_staging(str(tmp_path), "runA")
    b = run_scoped_staging(str(tmp_path), "runB")
    assert a != b and os.path.isdir(a) and os.path.isdir(b)


# --- read-only session preflight -------------------------------------------
def test_read_only_session_denied_mutation():
    lease = SingleWriterLease(operation="IMPORT", session_id="s1", read_only=True)
    with pytest.raises(cp.ArbitrationError) as exc:
        lease.acquire()
    assert exc.value.reason == "READ_ONLY_SESSION_MODE_FORBIDS_MUTATION"


def test_read_only_preflight_denies_governed_command():
    res = mutation_preflight(
        "UE4Editor-Cmd.exe proj -run=ImportAssets", "ro-session", read_only=True)
    assert res["verdict"] == "DENY"
    assert res["reason"] == "READ_ONLY_SESSION_MODE"


def test_read_only_allows_audit_command():
    assert mutation_preflight("git status", "ro-session", read_only=True)["verdict"] == "ALLOW"


def test_preflight_denies_without_lease():
    res = mutation_preflight("UE4Editor-Cmd.exe p -run=cook", "s9")
    assert res["verdict"] == "DENY"


# --- ungoverned mutator detection ------------------------------------------
def test_ungoverned_mutator_detection():
    inventory = {"mutators": [
        {"pid": 111, "identity_key": "111|t", "name": "UE4Editor-Cmd.exe",
         "operation_class": "IMPORT", "command_line": "x"},
        {"pid": 222, "identity_key": "222|t", "name": "UE4Editor.exe",
         "operation_class": "COOK", "command_line": "y"},
    ]}
    res = detect_ungoverned_mutators(inventory, "s1")
    assert res["UNGOVERNED_MUTATOR_DETECTED"] is True
    assert len(res["ungoverned"]) == 2
    assert res["action"] == "ALERT_AND_BLOCK_NEW_MUTATIONS__DO_NOT_KILL"


# --- fingerprints ------------------------------------------------------------
def test_different_operations_have_different_fingerprints(tmp_path):
    a = SingleWriterLease(operation="IMPORT", session_id="a",
                           engine_root=str(tmp_path / "ue"))
    b = SingleWriterLease(operation="COOK", session_id="b",
                           engine_root=str(tmp_path / "ue"))
    assert a.fingerprint["fingerprint"] != b.fingerprint["fingerprint"]


# --- configuration comparison ----------------------------------------------
def test_configuration_mutation_detected():
    before = {"files": {"Import.py": "aaa", "DefaultEngine.ini": "bbb"}}
    same = compare_configuration(before, {
        "files": {"Import.py": "aaa", "DefaultEngine.ini": "bbb"}})
    assert same["CONFIGURATION_MUTATED_DURING_RUN"] is False
    assert same["run_authoritative"] is True

    changed = compare_configuration(before, {
        "files": {"Import.py": "ZZZ", "DefaultEngine.ini": "bbb"}})
    assert changed["CONFIGURATION_MUTATED_DURING_RUN"] is True
    assert changed["run_authoritative"] is False

