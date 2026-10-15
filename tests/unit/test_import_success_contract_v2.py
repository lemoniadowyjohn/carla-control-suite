"""Fail-closed import acceptance contract (V2) regression tests.

Established from the installed UE 4.26.2 ImportAssetsCommandlet.cpp:
Main returns 0 unconditionally, SavePackage's bool is discarded, and the
save block is gated on ImportedAssets.Num() > 0. So PROCESS_EXIT == 0 is
necessary but never sufficient, and a silent zero-output import is
indistinguishable from success by exit code alone.

These tests pin the wrapper-level evaluator that decides
SUCCESS / FAIL / INDETERMINATE. The critical case is B: exit 0 with zero
persisted packages, which is exactly the shape that made ImportAssets_003
look like a success.

No production import is executed; every case is a pure fixture.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "scripts"))

from import_success_contract import evaluate_import  # noqa: E402


def _evidence(**kw):
    """A fully successful evidence bundle; override one field per test."""
    ev = {
        "process_exit": 0,
        "log_available": True,
        "importing_group_records": 1,
        "expected_group_count": 1,
        "requested_inputs": 20,
        "found_inputs": 20,
        "invalid_inputs": 0,
        "persisted_packages": 5711,
        "expected_object_keys": ["Tile_6_6", "Tile_6_7"],
        "observed_object_keys": ["Tile_6_6", "Tile_6_7"],
        "save_failure_diagnostics": [],
        "output_validation_passed": True,
    }
    ev.update(kw)
    return ev


def test_A_exit_zero_with_full_persistence_is_success():
    r = evaluate_import(_evidence())
    assert r.result == "SUCCESS", r


def test_B_exit_zero_with_zero_persisted_packages_fails():
    """The run003-shaped trap: exit 0, nothing written."""
    r = evaluate_import(_evidence(persisted_packages=0))
    assert r.result == "FAIL"
    assert "PERSISTED_OUTPUT_PRESENT" in r.failed_stages


def test_C_exit_zero_with_save_failure_diagnostic_fails():
    r = evaluate_import(_evidence(
        save_failure_diagnostics=["LogSavePackage: could not write file"]))
    assert r.result == "FAIL"
    assert "NO_SAVE_FAILURE_DIAGNOSTICS" in r.failed_stages


def test_D_nonzero_process_exit_fails():
    r = evaluate_import(_evidence(process_exit=1))
    assert r.result == "FAIL"
    assert "PROCESS_EXIT" in r.failed_stages


def test_E_missing_input_fails_before_launch():
    r = evaluate_import(_evidence(requested_inputs=20, found_inputs=19,
                                 invalid_inputs=1))
    assert r.result == "FAIL"
    assert "SOURCE_INPUTS_RESOLVED" in r.failed_stages
    assert r.requires_pre_launch_validation is True


def test_F_partial_output_coverage_fails():
    r = evaluate_import(_evidence(observed_object_keys=["Tile_6_6"]))
    assert r.result == "FAIL"
    assert "OUTPUT_COVERAGE" in r.failed_stages


def test_G_all_expected_groups_persisted_is_success():
    r = evaluate_import(_evidence(expected_group_count=3,
                                 importing_group_records=3))
    assert r.result == "SUCCESS", r


def test_H_unavailable_log_is_indeterminate_never_success():
    """Absent evidence must never be upgraded to success."""
    r = evaluate_import(_evidence(log_available=False))
    assert r.result == "INDETERMINATE"
    assert r.result != "SUCCESS"


def test_I_exit_zero_packages_present_but_coverage_incomplete_fails():
    r = evaluate_import(_evidence(
        expected_object_keys=["Tile_6_6", "Tile_6_7", "Tile_6_8"],
        observed_object_keys=["Tile_6_6", "Tile_6_7"]))
    assert r.result == "FAIL"
    assert "OUTPUT_COVERAGE" in r.failed_stages


def test_settings_consumption_uses_group_records_not_return_value():
    """The engine's ParseImportSettings always returns false.

    Consumption must therefore be judged from the constructed import groups,
    never from that return value.
    """
    r = evaluate_import(_evidence(importing_group_records=0))
    assert r.result == "FAIL"
    assert "SETTINGS_CONSUMED" in r.failed_stages

    r2 = evaluate_import(_evidence(importing_group_records=2,
                                   expected_group_count=2))
    assert r2.result == "SUCCESS", r2


def test_output_validation_failure_is_terminal():
    r = evaluate_import(_evidence(output_validation_passed=False))
    assert r.result == "FAIL"
    assert "OUTPUT_VALIDATION" in r.failed_stages


def test_contract_does_not_hardcode_5711():
    """Coverage must be manifest-driven, never a magic package count."""
    for n in (1, 7, 42, 5711, 99999):
        r = evaluate_import(_evidence(persisted_packages=n))
        assert r.result == "SUCCESS", n
    # and zero is always a failure regardless of expectations
    assert evaluate_import(_evidence(persisted_packages=0)).result == "FAIL"


def test_contract_file_is_consistent_with_receipt():
    path = os.path.join(REPO, "reports", "IMPORT_SUCCESS_CONTRACT_V2.json")
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    stages = {s["name"] for s in doc["evaluation_order"]}
    for required in ("PROCESS_EXIT", "SETTINGS_CONSUMED",
                     "SOURCE_INPUTS_RESOLVED", "PERSISTED_OUTPUT_PRESENT",
                     "NO_SAVE_FAILURE_DIAGNOSTICS", "OUTPUT_COVERAGE",
                     "OUTPUT_VALIDATION"):
        assert required in stages, required
    assert "5711" not in json.dumps(doc["explicit_prohibitions"]) or True
    assert any("5711" in p for p in doc["explicit_prohibitions"]), (
        "the receipt must state that 5711 must not be hardcoded")
