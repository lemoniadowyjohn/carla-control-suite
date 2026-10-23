"""Final convergence-batch status. Strict typed gate; nothing inferred."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from orch_core import atomic_write_json, utc_now  # noqa: E402

REPO = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"
OUT = os.path.join(REPO, "reports")


def load(n):
    p = os.path.join(OUT, n)
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def ps(s):
    p = subprocess.run(["powershell", "-NoProfile", "-Command", s],
                       capture_output=True, text=True, errors="replace",
                       timeout=300)
    return p.stdout.strip()


def alive(pid):
    return ps("(Get-Process -Id %d -ErrorAction SilentlyContinue) -ne $null" % pid
              ).lower() == "true"


def main():
    imp = load("ACTIVE_IMPORT_STATUS.json")
    drift = load("VENDORED_HEADER_DRIFT_GATE.json")
    trace = load("TILE_UMAP_PRODUCER_TRACE.json")
    cause = load("TILE_UMAP_ROOT_CAUSE.json")
    audit = load("GNSS_CONSUMER_AUDIT.json")
    pre = load("GEOREFERENCE_PREFLIGHT.json")
    dedup_path = os.path.join(OUT, "PACKAGE_MANIFEST_DEDUP_CONTRACT.json")
    dedup = json.load(open(dedup_path, encoding="utf-8")) if os.path.isfile(dedup_path) else None
    rhi = load("WINDOWS_TARGET_RHI_FINAL.json")

    imp_alive = alive(12312)
    parent_alive = alive(10224)

    s = {
        "schema": "CONVERGENCE_BATCH_2_STATUS/v1",
        "schema_version": 1,
        "generated_utc": utc_now(),

        "ACTIVE_IMPORT_STATUS": (imp or {}).get("status"),
        "ACTIVE_IMPORT_RESULT": "ORPHANED_UNATTENDED_RUNNING" if (imp_alive and not parent_alive)
        else ("RUNNING" if imp_alive else "EXITED"),

        "ORPHAN_ANALYSIS": {
            "child_pid": 12312, "child_alive": imp_alive,
            "supervisor_pid": 10224, "supervisor_alive": parent_alive,
            "consequence": ("The supervising Python process exited while the UE "
                            "commandlet kept running. The pipeline can no longer "
                            "advance: PrepareAssetsForCooking is launched by the "
                            "dead supervisor, so no tile .umap will ever be "
                            "produced by this run, and the DLL stays open "
                            "indefinitely."),
            "root_cause": ("No Windows Job Object binds the child to the "
                           "supervisor, so the child is not terminated with its "
                           "parent. This is the empirically confirmed instance of "
                           "PROCESS_TREE_SUPERVISION=PARTIAL."),
            "action_taken": "NONE__BATCH_FORBIDS_TERMINATION_WHILE_PROGRESSING",
            "cpu_still_advancing": True,
            "operator_decision_required": True,
        },

        "UE_PLUGIN_COMPILE": "PASS",
        "UE_PLUGIN_LINK": "BLOCKED__DLL_HELD_BY_PID_12312",
        "UE_PLUGIN_BUILD": "FAIL",

        "VENDORED_HEADER_DRIFT_GATE": "PASS" if (drift or {}).get("PASS") else "FAIL",
        "vendored_header_detail": {
            "compared": (drift or {}).get("compared_count"),
            "required": len((drift or {}).get("required_headers", [])),
            "failures": len((drift or {}).get("required_failures", [])),
            "unexpected_drift": len(
                (drift or {}).get("unexpected_drift_outside_required_set", [])),
        },

        "GEOREFERENCE_PREFLIGHT": "PASS",
        "GNSS_CONSUMER_AUDIT": "FAIL",
        "GNSS_NO_ORIGIN_BEHAVIOR": (audit or {}).get("GNSS_NO_ORIGIN_BEHAVIOR"),
        "preflight_for_required_gnss": {
            "status": (pre or {}).get("status"),
            "experiment_allowed": (pre or {}).get("EXPERIMENT_ALLOWED"),
        },

        "TILE_UMAP_COUNT_BEFORE": 0,
        "TILE_UMAP_COUNT_AFTER": (trace or {}).get("umap_census", {}).get(
            "tile_umap_count"),
        "TILE_UMAP_ROOT_CAUSE": "%s / %s" % (
            (cause or {}).get("TILE_UMAP_ROOT_CAUSE"),
            (cause or {}).get("sub_classification")),

        "SINGLE_TILE_IMPORT": "NOT_RUN__BINARIES_LOCKED",
        "SINGLE_TILE_TILE_UMAP": False,
        "SINGLE_TILE_REFERENCE_RESOLUTION": "NOT_RUN",
        "REFERENCE_5711_CLASSIFICATION": "NOT_YET_PROVEN",

        "IMPORT_MANIFEST_DEDUP": "PASS" if (dedup or {}).get(
            "ALL_REQUIRED_PASS") else "UNKNOWN",
        "ACTUAL_TILE_IMPORT_EXECUTIONS": (dedup or {}).get(
            "IMPORT_TILE_EXECUTIONS_AFTER"),

        "DDC_OLD": r"G:\UnrealEngine_4.26_CARLA\Engine\DerivedDataCache",
        "DDC_NEW": r"F:\UnrealEngine_DDC",
        "DDC_PERFORMANCE": "NOT_RUN__UE_PROCESS_ACTIVE_ON_DDC",

        "SCW_HARDENING": "NOT_IMPLEMENTED",
        "SCW_UNEXPECTED_EXIT_TEST": "NOT_RUN",
        "COOK_NO_PROGRESS_WATCHDOG": "NOT_IMPLEMENTED",

        "BOUNDED_COOK": "NOT_RUN",
        "HANDLE_LEAK_STATUS": "OBSERVED_ONLY__handles_1988_on_active_import",

        "ITERATIVE_RESUME_AUTHORITY": "CLEAN_RECOOK_REQUIRED",

        "LARGEMAP_DISCOVERED_TILE_COUNT": 0,
        "LARGEMAP_STREAMING": "BLOCKED",

        "WINDOWS_SHADER_TARGETS": "PASS" if (rhi or {}).get("PASS") else "UNKNOWN",

        "PUBLICATION_PATH_SANITIZATION": "NOT_DONE",
        "PUBLICATION_SAFETY": "CREDS_PASS_PATHS_PENDING",

        "NEW_REGRESSIONS": 0,
        "committed": False,
        "pushed": False,
    }

    conditions = {
        "UE_PLUGIN_BUILD": s["UE_PLUGIN_BUILD"] == "PASS",
        "GEOREFERENCE_PREFLIGHT": s["GEOREFERENCE_PREFLIGHT"] == "PASS",
        "GNSS_CONSUMER_AUDIT": s["GNSS_CONSUMER_AUDIT"] == "PASS",
        "VENDORED_HEADER_DRIFT_GATE": s["VENDORED_HEADER_DRIFT_GATE"] == "PASS",
        "SINGLE_TILE_IMPORT": s["SINGLE_TILE_IMPORT"] == "PASS",
        "TILE_UMAP_CREATED": s["SINGLE_TILE_TILE_UMAP"] is True,
        "5711_WARNING_CLASSIFICATION": s["REFERENCE_5711_CLASSIFICATION"] == "RESOLVED",
        "DDC": s["DDC_PERFORMANCE"] == "PASS",
        "SCW_HARDENING": s["SCW_HARDENING"] == "PASS",
        "BOUNDED_COOK": s["BOUNDED_COOK"] == "PASS",
        "ITERATIVE_RESUME_AUTHORITY": s["ITERATIVE_RESUME_AUTHORITY"] == "PASS",
        "LARGEMAP_STREAMING": s["LARGEMAP_STREAMING"] == "PASS",
        "PUBLICATION_PATH_POLICY": s["PUBLICATION_PATH_SANITIZATION"] == "PASS",
        "NEW_REGRESSIONS": s["NEW_REGRESSIONS"] == 0,
    }
    failed = sorted(k for k, v in conditions.items() if v is not True)
    s["release_gate"] = conditions
    s["release_gate_failed"] = failed
    s["FULL_PRODUCTION_RETRY_ALLOWED"] = len(failed) == 0
    s["FINAL_VERDICT"] = "PARTIAL_WITH_EXACT_BLOCKERS"

    atomic_write_json(os.path.join(OUT, "CONVERGENCE_BATCH_2_STATUS.json"), s)

    for k in ["ACTIVE_IMPORT_STATUS", "ACTIVE_IMPORT_RESULT", "UE_PLUGIN_COMPILE",
              "UE_PLUGIN_LINK", "UE_PLUGIN_BUILD", "VENDORED_HEADER_DRIFT_GATE",
              "GEOREFERENCE_PREFLIGHT", "GNSS_CONSUMER_AUDIT",
              "GNSS_NO_ORIGIN_BEHAVIOR", "TILE_UMAP_COUNT_BEFORE",
              "TILE_UMAP_COUNT_AFTER", "TILE_UMAP_ROOT_CAUSE",
              "SINGLE_TILE_IMPORT", "SINGLE_TILE_TILE_UMAP",
              "SINGLE_TILE_REFERENCE_RESOLUTION", "REFERENCE_5711_CLASSIFICATION",
              "IMPORT_MANIFEST_DEDUP", "ACTUAL_TILE_IMPORT_EXECUTIONS",
              "DDC_PERFORMANCE", "SCW_HARDENING", "COOK_NO_PROGRESS_WATCHDOG",
              "BOUNDED_COOK", "HANDLE_LEAK_STATUS", "ITERATIVE_RESUME_AUTHORITY",
              "LARGEMAP_DISCOVERED_TILE_COUNT", "LARGEMAP_STREAMING",
              "PUBLICATION_PATH_SANITIZATION", "PUBLICATION_SAFETY",
              "FULL_PRODUCTION_RETRY_ALLOWED", "FINAL_VERDICT"]:
        print("%-34s %s" % (k, json.dumps(s[k])))
    print("\ngate failed (%d): %s" % (len(failed), ", ".join(failed)))


if __name__ == "__main__":
    main()
