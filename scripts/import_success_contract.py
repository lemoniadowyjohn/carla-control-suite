"""Fail-closed import acceptance evaluator (contract V2).

Exit code 0 from UE 4.26.2's ImportAssetsCommandlet is NOT evidence of
persisted output. In the installed source, Main initialises Result to 0 and
its only assignment is also 0, so the commandlet returns 0 even when
ImportAndSave fails; SavePackage's bool return is discarded; and the entire
save block is skipped when ImportedAssets.Num() == 0. A run can therefore
import for hours, write nothing, and still exit 0.

This module evaluates an evidence bundle and returns SUCCESS, FAIL, or
INDETERMINATE. Exit code is a necessary but never sufficient condition.
Coverage is always derived from the supplied manifest, never from a
hardcoded package count.

Placement: run this immediately after the commandlet returns and BEFORE any
MoveAssets step, while the destination still holds what the import wrote.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence

SCHEMA_VERSION = 2

SUCCESS = "SUCCESS"
FAIL = "FAIL"
INDETERMINATE = "INDETERMINATE"


@dataclass
class ImportResult:
    result: str
    failed_stages: List[str] = field(default_factory=list)
    indeterminate_stages: List[str] = field(default_factory=list)
    requires_pre_launch_validation: bool = False
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({
            "schema": "IMPORT_STAGE_RESULT/v%d" % SCHEMA_VERSION,
            "IMPORT_STAGE_RESULT": self.result,
            "failed_stages": self.failed_stages,
            "indeterminate_stages": self.indeterminate_stages,
            "requires_pre_launch_validation": self.requires_pre_launch_validation,
            "detail": self.detail,
        }, indent=2)


def evaluate_import(evidence: Dict[str, Any]) -> ImportResult:
    """Decide SUCCESS / FAIL / INDETERMINATE for one governed import.

    A stage that cannot be evaluated yields INDETERMINATE unless a later
    stage has already failed outright, in which case the overall result is
    FAIL. INDETERMINATE is never promoted to SUCCESS.
    """
    failed: List[str] = []
    indeterminate: List[str] = []

    # Stage 2/3 style evidence gaps are indeterminate rather than failures,
    # but a hard failure anywhere dominates the verdict.
    if not evidence.get("log_available", False):
        indeterminate.append("SETTINGS_CONSUMED")

    # --- stage 1: process exit (necessary, never sufficient) ---------------
    if evidence.get("process_exit") != 0:
        failed.append("PROCESS_EXIT")

    # --- stage 2: settings actually consumed ------------------------------
    if evidence.get("log_available", False):
        groups = int(evidence.get("importing_group_records") or 0)
        expected_groups = int(evidence.get("expected_group_count") or 0)
        if groups <= 0 or groups != expected_groups:
            failed.append("SETTINGS_CONSUMED")

    # --- stage 3: every requested source accounted for --------------------
    requested = int(evidence.get("requested_inputs") or 0)
    found = int(evidence.get("found_inputs") or 0)
    invalid = int(evidence.get("invalid_inputs") or 0)
    pre_launch_required = False
    if requested <= 0:
        failed.append("SOURCE_INPUTS_RESOLVED")
        pre_launch_required = True
    elif found + invalid != requested or invalid > 0:
        failed.append("SOURCE_INPUTS_RESOLVED")
        # A missing or invalid source must be caught before the commandlet is
        # launched at all; reaching UE with an unresolvable input is itself the
        # defect, so record that pre-launch validation is mandatory.
        pre_launch_required = True

    # --- stage 4: something was actually persisted ------------------------
    if int(evidence.get("persisted_packages") or 0) <= 0:
        failed.append("PERSISTED_OUTPUT_PRESENT")

    # --- stage 5: no save-failure diagnostics -----------------------------
    if list(evidence.get("save_failure_diagnostics") or []):
        failed.append("NO_SAVE_FAILURE_DIAGNOSTICS")

    # --- stage 6: manifest-driven coverage --------------------------------
    expected_keys = set(evidence.get("expected_object_keys") or [])
    observed_keys = set(evidence.get("observed_object_keys") or [])
    if not expected_keys:
        failed.append("OUTPUT_COVERAGE")
    elif not expected_keys.issubset(observed_keys):
        failed.append("OUTPUT_COVERAGE")

    # --- stage 7: independent output validation ---------------------------
    if evidence.get("output_validation_passed") is not True:
        failed.append("OUTPUT_VALIDATION")

    if failed:
        return ImportResult(result=FAIL, failed_stages=failed,
                            indeterminate_stages=indeterminate,
                            requires_pre_launch_validation=pre_launch_required,
                            detail={"persisted_packages":
                                    evidence.get("persisted_packages"),
                                    "process_exit": evidence.get("process_exit")})
    if indeterminate:
        return ImportResult(result=INDETERMINATE,
                            indeterminate_stages=indeterminate,
                            failed_stages=[],
                            detail={"note": "evidence unavailable; "
                                            "must not be treated as success"})
    return ImportResult(result=SUCCESS, detail={
        "persisted_packages": evidence.get("persisted_packages"),
        "observed_object_keys": len(observed_keys),
        "expected_object_keys": len(expected_keys),
    })
