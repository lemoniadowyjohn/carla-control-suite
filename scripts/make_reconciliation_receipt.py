"""Phase 1: POST_HOC reconciliation receipt for COOK_620e51db (tile 6_8).

This is NOT producer-emitted. The producer receipt is preserved byte-for-byte
and its SHA recorded; nothing in it is rewritten.
"""
from __future__ import annotations

import hashlib
import json
import os

OUT = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports"
CW = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla-control-plane"
PRODUCER = os.path.join(CW, "reports", "control_plane",
                        "BOUNDED_COOK_6_8_RECEIPT.json")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


prod = json.load(open(PRODUCER, encoding="utf-8"))

receipt = {
    "schema": "COOK_620e51db_RECONCILIATION_RECEIPT/v1",
    "schema_version": 1,
    "receipt_type": "POST_HOC_RECONCILIATION",
    "producer_emitted": False,
    "producer_emitted_claim":
        "This file was authored during post-hoc reconciliation, NOT by "
        "supervised_ue_run.py. It must never be presented as a producer "
        "artifact. The producer receipt is preserved unmodified at the path "
        "recorded below.",

    "producer_receipt": {
        "path": PRODUCER,
        "sha256_at_reconciliation": sha256(PRODUCER),
        "bytes": os.path.getsize(PRODUCER),
        "preserved_unmodified": True,
        "sha256_before_terminal_transition":
            "8628326E77C1AA4BB437116452ECED7348A59586065601FFB85EE7AF7814DCB2",
        "sha256_after_terminal_transition":
            "594B368095347215082D96B7460EC9AA2CC32D25E6619776B4CC2A31C5DF569E",
    },

    "cook_identity": {
        "run_id": "COOK_620e51db",
        "label": "BoundedCook_6_8",
        "root_pid": 29972,
        "root_creation_time_utc": "2026-10-06T16:59:33.3967880Z",
        "root_identity_verified": True,
        "root_pid_reuse_observed": False,
        "supervisor_pid_observed": 11096,
        "lease_store_used": r"C:\ProgramData\carla-ops\leases",
        "lease_store_note":
            "this cook uses the carla-ops lease_store, NOT the published "
            "%ProgramData%\\CARLA\\control_plane SingleWriterLease store",
    },

    "terminal_state": {
        "terminal_utc": prod["end_utc"],
        "exit_code_dec": prod["exit_code_dec"],
        "exit_code_hex": prod["exit_code_hex"],
        "termination_class": "CLEAN_SUCCESS",
        "timed_out": prod["timed_out"],
        "drained": prod["drain"]["drained"],
        "drain_wait_s": prod["drain"]["wait_s"],
        "job_members_final": prod["job_members_final"],
        "descendants_alive": 0,
        "commandlet_seconds": 10827.48,
        "log_sha256": prod["log_sha256"],
    },

    "technical_result": {
        "TECHNICAL_COOK_RESULT": "PASS",
        "cooked": 1666,
        "expected": 1666,
        "remaining": 0,
        "shaders_remaining": 0,
        "shader_failures": 0,
        "Error:": 0,
        "Fatal error": 0,
        "Assertion failed": 0,
        "ensure condition failed": 0,
        "Warning:": 331,
        "error_summary_note":
            "the single 'Error Summary' match is the header "
            "'Warning/Error Summary (Unique only)'; all listed entries are "
            "Warnings and all are stock-CARLA noise (streaming pool priority, "
            "missing ExampleDeviceProfileSelector module, null world context, "
            "duplicate PrimaryAssetID for Town11/EmptyMap/LargeMap test maps). "
            "None reference Ingolstadt.",
        "zero_byte_files": 1,
        "zero_byte_detail":
            "cook_6_8_20261006T165932Z.log.err, the empty stderr capture "
            "created at launch; not a cook output artifact",
        "iterative_baseline_source": "EMPTY_BASELINE",
        "RETIRED_COOK_METADATA_CONSUMED": False,
        "retired_reference_audit": {
            "cook_out": 0, "Saved/Cooked": 0, "2975": 0, "3558": 1,
            "3558_context":
                "'shaders left to compile 3558' - a coincidental integer, "
                "not a reference to the retired 2975/3558 cook state",
        },
        "iterative_metadata": {
            "Metadata_directory_present": True,
            "OpenOrder_present": False,
            "uptnl_present": False,
        },
        "handle_classification": "STEP_INCREASE_NONLEAK",
        "handle_detail":
            "3784 -> 4293 once (+509), then delta 0 across a 150 s window, a "
            "240 s window, a 4-minute watch loop and the final pre-terminal "
            "sample. No renewed monotonic growth, so not a leak.",
        "stdout_classification": "SAFE_FOR_THIS_COOK_COMMANDLET",
        "stdout_scope":
            "applies only to UE4Editor -run=cook; the separate source-tree "
            "GAME-launch -stdout warning is unaffected",
    },

    "timeout": {
        "configured_seconds": 14400,
        "fired": False,
        "elapsed_seconds": 10827.48,
        "margin_seconds": 3572.52,
        "TIMEOUT_INCREASE_REQUIRED": False,
        "note":
            "the cook finished about 57 minutes inside budget. Earlier "
            "completion projections derived from short shader-rate windows "
            "(12-13/min, then 32.5/min) were disproven: the drain proved "
            "burst-dominated at roughly 336/min. No timeout increase is "
            "justified by this run.",
    },

    "governance_defects": [
        {"id": "G1", "severity": "HIGH",
         "title": "harness never acquires a lease",
         "evidence":
             "supervised_ue_run.py performs only read_current() then "
             "heartbeat(); there is no acquire() call in the file",
         "impact":
             "an unrelated pre-existing lease can become the de facto "
             "authority for a run it does not govern"},
        {"id": "G2", "severity": "HIGH",
         "title": "heartbeat is timestamp-only",
         "evidence":
             "lease_store.heartbeat() (lines 250-257) refreshes "
             "heartbeat_utc, promotes ACQUIRED->RUNNING and writes back when "
             "run_id matches. It never calls owner_alive() or "
             "lease_owner_alive().",
         "impact":
             "a lease whose owner is dead keeps receiving fresh heartbeats "
             "and remains RUNNING indefinitely; "
             "lease_owner_alive() already existed and would have caught it"},
        {"id": "G3", "severity": "HIGH",
         "title": "no terminal lease transition",
         "evidence":
             "after the cook reached terminal state the lease still read "
             "state=RUNNING, terminal_state='', end_utc=''; heartbeat "
             "stopped only because the supervisor process exited",
         "impact":
             "the control plane cannot distinguish a finished run from an "
             "abandoned one"},
        {"id": "G4", "severity": "HIGH",
         "title": "lease identity stale relative to the mutation root",
         "evidence":
             "lease root_pid=28436 created 2026-10-06T12:20:34.602992Z (dead) "
             "versus actual cook root_pid=29972 created "
             "2026-10-06T16:59:33.3967880Z, a 4.65 hour divergence",
         "impact":
             "the lease never represented the process it was claimed to "
             "cover",
         "LEASE_PROCESS_BINDING_VALID": False,
         "LEASE_ACQUIRING_CALLER": "UNRESOLVED",
         "acquiring_caller_note":
             "because the harness never calls acquire(), the caller that "
             "originally wrote this lease is unidentified. No explanation is "
             "fabricated."},
        {"id": "G5", "severity": "MEDIUM",
         "title": "receipt persists a naked, unresolvable executor PID",
         "evidence":
             "executor_pid=34196 is dead; the receipt carries no "
             "executor_creation_time, no owner identity and no durable role "
             "semantics. Source: resolve_executor_pid(job, proc.pid, "
             "timeout_s=120) at line 96, written at line 98.",
         "impact":
             "the field cannot be validated after the fact and must not be "
             "treated as authority",
         "RECEIPT_EXECUTOR_PID_ROOT_CAUSE": "STALE_PROCESS_ID"},
        {"id": "G6", "severity": "MEDIUM",
         "title": "receipt records launcher PID without creation time",
         "evidence":
             "launcher_pid is persisted but no launcher_creation_time field "
             "exists, so root identity is PID-only and unverifiable under PID "
             "reuse",
         "impact": "weaker than PID+creation_time identity"},
    ],

    "job_object": {
        "COOK_JOB_SUPERVISION_AUTHORITY": "ASSIGNMENT_CODEPATH_PROVEN",
        "codepath": [
            "create_job()",
            "Popen with CREATE_SUSPENDED | CREATE_BREAKAWAY_FROM_JOB",
            "AssignProcessToJobObject with explicit raise on failure",
            "resume_primary_thread only after successful assignment",
            "wait_for_drain(job, timeout_s=300)",
            "job_members_final recorded in receipt (empty at terminal)",
        ],
        "runtime_membership": "NOT_INDEPENDENTLY_OBSERVED",
        "runtime_membership_note":
            "Sysinternals handle.exe is not installed on this host. "
            "Codepath evidence is deliberately NOT upgraded to runtime "
            "membership evidence, and the historical run's classification "
            "must not be upgraded retroactively.",
        "supporting_operational_evidence":
            "all 4 ShaderCompileWorkers were gone by the first post-terminal "
            "sample and job_members_final is empty, which is consistent with "
            "correct containment but does not by itself prove membership",
    },

    "final_authority": {
        "COOK_OUTPUT_AUTHORITY": "TECHNICALLY_VALID_NONAUTHORITATIVE",
        "AUTHORITATIVE": False,
        "reasoning":
            "technical output is clean and complete, but exclusive ownership "
            "coverage for this exact run is not evidenced: the lease was never "
            "bound to the mutation root, never failed closed on a dead owner, "
            "and never transitioned to terminal. No independent equivalent "
            "durable evidence of exclusive ownership exists.",
        "retroactive_promotion_forbidden": True,
        "retroactive_promotion_note":
            "repairing the harness afterwards MUST NOT upgrade this run. An "
            "authoritative rerun under the repaired harness is required.",
    },

    "output_summary": {
        "files": 3629,
        "bytes": 1559078572,
        "gb": 1.45,
        "note": "tile 6_8 only; a second cook for tile 10_9 later added to "
                "the same run-scoped output root",
    },

    "successor_run_observed": {
        "label": "BoundedCook_10_9",
        "root_pid": 16164,
        "root_creation_time_utc": "2026-10-06T20:23:42.475297Z",
        "terminal_utc": "2026-10-06T20:47:53.014445Z",
        "exit_code_dec": 0,
        "termination_class": "SUCCESS",
        "timed_out": False,
        "drained": True,
        "job_members_final": [],
        "cooked": 1970,
        "expected": 1970,
        "remaining": 0,
        "shaders_remaining": 0,
        "executor_pid": 29788,
        "executor_defect_repeats": True,
        "authority": "NOT_RECONCILED_IN_THIS_BATCH",
        "authority_note":
            "reconciliation of the second cook is out of scope here; it was "
            "examined only to establish machine quiescence. It exhibits the "
            "same naked executor_pid defect.",
    },

    "lease_store_state_after_both_cooks": {
        "path": r"C:\ProgramData\carla-ops\leases\current_lease.json",
        "observed": "ABSENT",
        "note":
            "after the tile 6_8 cook the file still read state=RUNNING with "
            "empty terminal_state and end_utc (defect G3). Following the "
            "tile 10_9 run the file no longer exists. Whether it was removed "
            "by that run or by other means was not determined, and no cause "
            "is asserted. The file's absence does not retroactively validate "
            "the governance of either run.",
    },
}

path = os.path.join(OUT, "COOK_620e51db_RECONCILIATION_RECEIPT.json")
with open(path, "w", encoding="utf-8") as fh:
    json.dump(receipt, fh, indent=2)
print("wrote", path)
print("TECHNICAL_COOK_RESULT =", receipt["technical_result"]["TECHNICAL_COOK_RESULT"])
print("COOK_OUTPUT_AUTHORITY =", receipt["final_authority"]["COOK_OUTPUT_AUTHORITY"])
print("defects recorded =", len(receipt["governance_defects"]))
