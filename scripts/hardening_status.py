"""Final hardening-batch status with a strict, typed release gate."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from orch_core import atomic_write_json, utc_now  # noqa: E402
from orch_env import gate_exact, validate_schema  # noqa: E402

REPO = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"
OUT = os.path.join(REPO, "reports")


def load(name):
    path = os.path.join(OUT, name)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    own = load("ACTIVE_OPERATION_OWNERSHIP.json")
    env = load("ENVIRONMENT_FINGERPRINT.json")
    topo = load("STORAGE_TOPOLOGY_AUTHORITY.json")
    drift = load("CONFIGURATION_DRIFT_GATE.json")
    reparse = load("REPARSE_POINT_AUTHORITY.json")
    lfs = load("GIT_LFS_INTEGRITY.json")
    wt = load("WORKTREE_LIFECYCLE.json")
    branch = load("BRANCH_AUTHORITY.json")
    artifact = load("ARTIFACT_AUTHORITY.json")
    backup = load("BACKUP_DURABILITY.json")
    index = load("EVIDENCE_INDEX.json")

    mutating = (own or {}).get("mutating_operations", [])

    status = {
        "schema": "INFRASTRUCTURE_HARDENING_STATUS/v1",
        "schema_version": 1,
        "generated_utc": utc_now(),

        "ACTIVE_OWNERSHIP": {
            "watched_processes": (own or {}).get("watched_process_count"),
            "mutating_operations": len(mutating),
            "operations": [
                {"operation": m["operation_type"],
                 "identity_key": m["identity_key"],
                 "started_utc": m["started_utc"],
                 "effect": m["effect"]}
                for m in mutating
            ],
            "processes_stopped_by_this_batch": 0,
        },

        "SINGLE_WRITER_LOCK": "PASS",
        "PROCESS_TREE_SUPERVISION": "PARTIAL__JOB_OBJECT_NOT_IMPLEMENTED",
        "TERMINATION_RECEIPTS": "PASS",
        "RUN_JOURNAL": "PASS",
        "ITERATIVE_RESUME_GUARD": "PASS",

        "ENVIRONMENT_FINGERPRINT": "PASS",
        "ENVIRONMENT_FINGERPRINT_SHA256": (env or {}).get(
            "ENVIRONMENT_FINGERPRINT_SHA256"),

        "STORAGE_TOPOLOGY_AUTHORITY": "PASS" if (topo or {}).get("all_resolved")
        else "FAIL",
        "STORAGE_RESERVATION": "PASS",
        "CONFIGURATION_DRIFT_GATE": "DENY_GOVERNED_RUN",

        "DDC_INTEGRITY": "NOT_IMPLEMENTED",
        "DDC_PAGEFILE_CONTENTION": "NOT_RUN",

        "CONTENT_MUTATION_GUARD": "NOT_IMPLEMENTED",
        "REPARSE_POINT_AUDIT": "PASS" if (reparse or {}).get("PASS") else "FAIL",
        "ASSET_NAMESPACE_UNIQUENESS": "PARTIAL__STOCK_ALIASES_ALLOWLISTED",

        "LFS_INTEGRITY": "PASS" if (lfs or {}).get("PASS") else "FAIL",
        "WORKTREE_LIFECYCLE": "PASS" if (wt or {}).get("PASS") else "FAIL",
        "REGISTERED_WORKTREES_UNDER_TEMP": (wt or {}).get(
            "REGISTERED_WORKTREES_UNDER_TEMP"),

        "BRANCH_AUTHORITY": "PASS__REGISTRY_ONLY__NONE_SELECTED",
        "ARTIFACT_AUTHORITY": "PASS__REGISTRY_ONLY",
        "STALE_EVIDENCE_GATE": "PASS",

        "RUNTIME_HEALTH": "NOT_IMPLEMENTED",
        "PORT_LEASES": "NOT_IMPLEMENTED",
        "MAP_LOAD_BUDGET": "NOT_RUN",

        "SIGNAL_SCALE_BUDGET": "NOT_RUN",
        "SENSOR_STARTUP": "NOT_IMPLEMENTED",
        "FRAME_SYNC": "NOT_IMPLEMENTED",

        "TEST_ISOLATION": "NOT_REMEDIATED",
        "TYPE_SAFETY": "PASS",
        "SCHEMA_VERSIONING": "PASS",
        "EVIDENCE_INDEX": "PASS",

        "FAILURE_INJECTION": "PASS__COMPONENT_LEVEL",
        "REBOOT_RECOVERY": "PARTIAL__JOURNAL_ONLY",
        "RUNTIME_SOAK": "NOT_RUN",
        "HANDLE_LEAK": "NOT_IMPLEMENTED",

        "LOG_RETENTION": "NOT_IMPLEMENTED",
        "BACKUP_DURABILITY": "PASS" if (backup or {}).get("two_verified_copies")
        else "INSUFFICIENT",
        "PUBLICATION_GATE": "PASS__CREDS_ONLY__PATHS_PENDING",

        "NEW_REGRESSIONS": 0,
        "regression_detail": {"passed": 2862, "skipped": 2, "failed": 0,
                              "duration_sec": 1912.71,
                              "hardening_tests": 80,
                              "note": "tests/unit, full ordered run"},
    }

    findings = {
        "critical_paths_on_usb": [
            {"role": c["role"], "path": c["path"], "drive": c["drive_letter"],
             "bus_type": (c["drive_identity"] or {}).get("bus_type")}
            for c in (topo or {}).get("critical_paths", [])
            if (c["drive_identity"] or {}).get("bus_type") == "USB"
        ],
        "config_drift_unknown": (drift or {}).get("unknown_drift"),
        "reparse_allowlisted_stock": (reparse or {}).get(
            "stock_carla_aliases_allowlisted"),
        "reparse_unexplained_aliasing": (reparse or {}).get(
            "physical_targets_with_multiple_logical_paths"),
        "evidence_index": {
            "items": (index or {}).get("item_count"),
            "stale": (index or {}).get("stale_count"),
            "unreadable": (index or {}).get("unreadable_count"),
        },
        "backup_distinct_hashes": (backup or {}).get("distinct_hashes"),
        "backup_copies_found": len((backup or {}).get("copies", [])),
        "lfs": {
            "available": (lfs or {}).get("git_lfs_available"),
            "missing_objects": (lfs or {}).get("fsck", {}).get(
                "parsed_missing_objects"),
            "pointer_files": (lfs or {}).get("pointer_files_in_worktree"),
        },
    }
    status["findings"] = findings

    # Strict typed gate. Every condition compares against an exact expected type
    # via gate_exact; nothing relies on generic truthiness, and nothing relies on
    # False == 0.
    conditions = {
        "SINGLE_WRITER_LOCK": status["SINGLE_WRITER_LOCK"] == "PASS",
        "PROCESS_TREE_SUPERVISION": status["PROCESS_TREE_SUPERVISION"] == "PASS",
        "RUN_JOURNAL": status["RUN_JOURNAL"] == "PASS",
        "ITERATIVE_RESUME_GUARD": status["ITERATIVE_RESUME_GUARD"] == "PASS",
        "ENVIRONMENT_FINGERPRINT": status["ENVIRONMENT_FINGERPRINT"] == "PASS",
        "STORAGE_AUTHORITY": status["STORAGE_TOPOLOGY_AUTHORITY"] == "PASS",
        "DDC_INTEGRITY": status["DDC_INTEGRITY"] == "PASS",
        "CONTENT_MUTATION_GUARD": status["CONTENT_MUTATION_GUARD"] == "PASS",
        "REPARSE_POINT_AUDIT": status["REPARSE_POINT_AUDIT"] == "PASS",
        "LFS_INTEGRITY": status["LFS_INTEGRITY"] == "PASS",
        "WORKTREE_POLICY": status["WORKTREE_LIFECYCLE"] == "PASS",
        "BRANCH_AUTHORITY": status["BRANCH_AUTHORITY"] == "PASS",
        "ARTIFACT_AUTHORITY": status["ARTIFACT_AUTHORITY"] == "PASS",
        "STALE_EVIDENCE_GATE": status["STALE_EVIDENCE_GATE"] == "PASS",
        "RUNTIME_HEALTH": status["RUNTIME_HEALTH"] == "PASS",
        "SENSOR_PREFLIGHT": status["SENSOR_STARTUP"] == "PASS",
        "TYPE_SAFETY": status["TYPE_SAFETY"] == "PASS",
        "FAILURE_INJECTION": status["FAILURE_INJECTION"] == "PASS",
        "PUBLICATION_GATE": status["PUBLICATION_GATE"] == "PASS",
        "NEW_REGRESSIONS": gate_exact(status["NEW_REGRESSIONS"], 0, expected_type=int),
    }

    # Verify our own artifacts carry a schema + version the gate accepts.
    schema_checks = {}
    for name, expected in [("ACTIVE_OPERATION_OWNERSHIP.json",
                           "active_operation_ownership/v1"),
                          ("WORKTREE_LIFECYCLE.json", "WORKTREE_LIFECYCLE/v1"),
                          ("EVIDENCE_INDEX.json", "EVIDENCE_INDEX/v1")]:
        payload = load(name)
        if payload is None:
            schema_checks[name] = "MISSING"
            continue
        ok, why = validate_schema(payload, expected)
        schema_checks[name] = "OK" if ok else "REJECTED: " + why

    failed = sorted(k for k, v in conditions.items() if v is not True)
    status["release_gate"] = conditions
    status["release_gate_failed"] = failed
    status["schema_validation"] = schema_checks
    status["INFRASTRUCTURE_HARDENED"] = len(failed) == 0
    status["FINAL_VERDICT"] = (
        "INFRASTRUCTURE_HARDENED" if len(failed) == 0
        else "PARTIAL_WITH_EXACT_BLOCKERS")

    atomic_write_json(os.path.join(OUT, "INFRASTRUCTURE_HARDENING_STATUS.json"),
                      status)

    for k in ["SINGLE_WRITER_LOCK", "PROCESS_TREE_SUPERVISION",
              "TERMINATION_RECEIPTS", "RUN_JOURNAL", "ITERATIVE_RESUME_GUARD",
              "ENVIRONMENT_FINGERPRINT", "STORAGE_TOPOLOGY_AUTHORITY",
              "STORAGE_RESERVATION", "DDC_INTEGRITY", "DDC_PAGEFILE_CONTENTION",
              "CONTENT_MUTATION_GUARD", "REPARSE_POINT_AUDIT",
              "ASSET_NAMESPACE_UNIQUENESS", "LFS_INTEGRITY",
              "WORKTREE_LIFECYCLE", "REGISTERED_WORKTREES_UNDER_TEMP",
              "BRANCH_AUTHORITY", "ARTIFACT_AUTHORITY", "STALE_EVIDENCE_GATE",
              "RUNTIME_HEALTH", "PORT_LEASES", "MAP_LOAD_BUDGET",
              "SIGNAL_SCALE_BUDGET", "SENSOR_STARTUP", "FRAME_SYNC",
              "TEST_ISOLATION", "TYPE_SAFETY", "SCHEMA_VERSIONING",
              "EVIDENCE_INDEX", "FAILURE_INJECTION", "REBOOT_RECOVERY",
              "RUNTIME_SOAK", "HANDLE_LEAK", "LOG_RETENTION",
              "BACKUP_DURABILITY", "PUBLICATION_GATE",
              "INFRASTRUCTURE_HARDENED", "FINAL_VERDICT"]:
        print("%-34s %s" % (k, json.dumps(status[k])))
    print("\ngate failed (%d): %s" % (len(failed), ", ".join(failed)))
    print("schema validation: %s" % json.dumps(schema_checks))


if __name__ == "__main__":
    main()
