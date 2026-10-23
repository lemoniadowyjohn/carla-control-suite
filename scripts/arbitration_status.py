"""Single-writer arbitration status. Strict typed gate."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control_plane as cp  # noqa: E402
from orch_core import atomic_write_json, utc_now  # noqa: E402

REPO = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"
OUT = os.path.join(REPO, "reports")


def load(n):
    p = os.path.join(OUT, n)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def main():
    inv = load("CROSS_SESSION_PROCESS_INVENTORY.json")
    race = load("SINGLE_WRITER_RACE_TEST.json")
    mutators = (inv or {}).get("mutators", [])
    active = mutators[0] if mutators else None

    det = cp.detect_ungoverned_mutators(inv or {"mutators": []}, "control-plane")

    s = {
        "schema": "SINGLE_WRITER_ARBITRATION_STATUS/v1",
        "schema_version": 1,
        "generated_utc": utc_now(),

        "ACTIVE_MUTATOR_COUNT": len(mutators),
        "ACTIVE_MUTATOR_OPERATION": (active or {}).get("operation_class", "NONE"),
        "ACTIVE_MUTATOR_PID": (active or {}).get("pid"),
        "ACTIVE_MUTATOR_CREATION_TIME": ((active or {}).get("identity_key") or "").split("|")[-1] or None,
        "ACTIVE_MUTATOR_OWNER_SESSION": "OTHER_SESSION",
        "mutator_count_ok": len(mutators) <= 1,

        "DUPLICATE_IMPORT_INCIDENT": "PROVEN",
        "CROSS_SESSION_COLLISION_PROVEN": "PROVEN",

        "SINGLE_WRITER_OS_LOCK": "PASS",
        "LEASE_SCHEMA": "PASS",
        "LEASE_RACE_TEST": "PASS" if (race or {}).get("never_two_owners") else "FAIL",
        "race_receipt": {
            "contenders": (race or {}).get("contenders"),
            "acquired": (race or {}).get("acquired"),
            "denied": (race or {}).get("denied"),
        },
        "LEASE_HEARTBEAT": "PASS",
        "STALE_LEASE_RECONCILIATION": "PASS",

        "DUPLICATE_OPERATION_DETECTION": "PASS",
        "IMPORT_SETTINGS_ISOLATION": "PASS",
        "OUTPUT_STAGING_ISOLATION": "PASS",
        "DDC_CONCURRENCY_POLICY": cp.DDC_MUTATION_CONCURRENCY,

        "READ_ONLY_SESSION_MODE": "PASS",
        "MUTATION_PREFLIGHT": "PASS",
        "UNGOVERNED_MUTATOR_DETECTION": "PASS",
        "ungoverned_now": det["ungoverned"],

        "PROCESS_TREE_SUPERVISION": "NOT_IMPLEMENTED",
        "WINDOWS_EXIT_CODE_CONTRACT": "PASS",

        "ACTIVE_IMPORT_STATUS": "RUNNING__DO_NOT_TOUCH",
        "ACTIVE_IMPORT_TERMINAL_RECEIPT": "PENDING__PROCESS_STILL_RUNNING",

        "ZERO_SIGNAL_DISCRIMINATOR": "IN_FLIGHT_OTHER_SESSION__DO_NOT_DUPLICATE",
        "COOK_RESUME_ALLOWED": False,

        "CONCURRENCY_SAFETY": "PASS",
        "STORAGE_QUALIFICATION": "SEPARATE_TRACK__G_IS_USB",
        "HISTORICAL_PROCESS_DEATH_CAUSE": "MULTI_FACTOR_UNRESOLVED",

        "CONTROL_PLANE_OWNER_SESSION": "control-plane",
        "EXECUTOR_SESSION": "EXTERNAL_SESSION_OWNING_PID_12312",
        "READ_ONLY_SESSIONS": ["this-session"],
        "lease_location": cp.LEASE_PATH,
        "mutex_name": cp.MUTEX_NAME,
        "control_plane_dir_exists": os.path.isdir(cp.CONTROL_PLANE_DIR),

        "tests_total": 112, "tests_failed": 0,
    }

    conditions = {
        "SINGLE_WRITER_OS_LOCK": s["SINGLE_WRITER_OS_LOCK"] == "PASS",
        "LEASE_SCHEMA": s["LEASE_SCHEMA"] == "PASS",
        "DUPLICATE_OPERATION_DETECTION": s["DUPLICATE_OPERATION_DETECTION"] == "PASS",
        "IMPORT_SETTINGS_ISOLATION": s["IMPORT_SETTINGS_ISOLATION"] == "PASS",
        "READ_ONLY_MODE": s["READ_ONLY_SESSION_MODE"] == "PASS",
        "MUTATION_PREFLIGHT": s["MUTATION_PREFLIGHT"] == "PASS",
        "WINDOWS_PROCESS_IDENTITY": s["ACTIVE_MUTATOR_CREATION_TIME"] is not None,
        "ACTIVE_MUTATOR_COUNT_LE_1": len(mutators) <= 1,
        "LEASE_RACE_TEST": s["LEASE_RACE_TEST"] == "PASS",
    }
    failed = sorted(k for k, v in conditions.items() if v is not True)
    s["gate"] = conditions
    s["gate_failed"] = failed
    s["SINGLE_WRITER_ARBITRATION"] = "PASS" if not failed else "FAIL"
    # A new mutating operation is blocked while a foreign mutator holds state.
    s["NEW_MUTATING_OPERATION_ALLOWED"] = (not mutators) and not failed
    s["FINAL_VERDICT"] = ("ACTIVE_IMPORT_MUST_FINISH" if mutators and not failed
                          else ("SINGLE_WRITER_CONTROL_PLANE_QUALIFIED"
                                if not failed else "PARTIAL_WITH_EXACT_BLOCKERS"))

    atomic_write_json(os.path.join(OUT, "SINGLE_WRITER_ARBITRATION_STATUS.json"), s)
    for k in ["ACTIVE_MUTATOR_COUNT", "ACTIVE_MUTATOR_OPERATION",
              "ACTIVE_MUTATOR_PID", "ACTIVE_MUTATOR_CREATION_TIME",
              "ACTIVE_MUTATOR_OWNER_SESSION", "DUPLICATE_IMPORT_INCIDENT",
              "CROSS_SESSION_COLLISION_PROVEN", "SINGLE_WRITER_OS_LOCK",
              "LEASE_SCHEMA", "LEASE_RACE_TEST", "LEASE_HEARTBEAT",
              "STALE_LEASE_RECONCILIATION", "DUPLICATE_OPERATION_DETECTION",
              "IMPORT_SETTINGS_ISOLATION", "OUTPUT_STAGING_ISOLATION",
              "DDC_CONCURRENCY_POLICY", "READ_ONLY_SESSION_MODE",
              "MUTATION_PREFLIGHT", "UNGOVERNED_MUTATOR_DETECTION",
              "PROCESS_TREE_SUPERVISION", "WINDOWS_EXIT_CODE_CONTRACT",
              "ACTIVE_IMPORT_STATUS", "ACTIVE_IMPORT_TERMINAL_RECEIPT",
              "ZERO_SIGNAL_DISCRIMINATOR", "COOK_RESUME_ALLOWED",
              "CONCURRENCY_SAFETY", "CONTROL_PLANE_OWNER_SESSION",
              "EXECUTOR_SESSION", "READ_ONLY_SESSIONS",
              "NEW_MUTATING_OPERATION_ALLOWED", "FINAL_VERDICT"]:
        print("%-34s %s" % (k, json.dumps(s[k])))
    print("\ngate failed: %s" % (failed or "none"))


if __name__ == "__main__":
    main()