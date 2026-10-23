"""Phase 0 executor-admission receipt.

Records the hard stop. Nothing beyond Phase 0 was executed: no fingerprint,
no tile load, no RHI patch, no DDC migration, no cook. Content untouched.
"""
from __future__ import annotations

import json
import os

OUT = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports"


def w(name, obj):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)


w("COOK_EXECUTOR_ADMISSION.json", {
    "schema": "COOK_EXECUTOR_ADMISSION/v1",
    "PHASE_0_RESULT": "FAIL",
    "PROCESS_TREE_SUPERVISION": "PASS",
    "LEASE_JOB_COUPLING": "PASS",
    "SINGLE_WRITER_CONTROL_PLANE": "PASS",
    "process_control_basis":
        "reports/PROCESS_TREE_SUPERVISION_FINAL.json and clean-checkout "
        "reproduction at published SHA 32fbde8e (matrix 25/25, stress 270/270, "
        "T6 5/5, coupling 11/11, identity 15/15, native crashes 0).",
    "ACTIVE_CONFLICTING_MUTATORS": 1,
    "mutators": [{
        "pid": 396,
        "creation_time_utc": "2026-10-06T12:30:44.7613250Z",
        "parent_pid": 31268,
        "parent_alive": False,
        "image": "UE4Editor.exe",
        "executable": "G:\\UnrealEngine_4.26_CARLA\\Engine\\Binaries\\Win64\\"
                      "UE4Editor.exe",
        "command_line": "UE4Editor.exe G:\\CARLA\\carla_source_probe\\Unreal\\"
                        "CarlaUE4\\CarlaUE4.uproject -nullrhi -unattended "
                        "-executecmds=quit",
        "classification": "UNKNOWN_PRESERVE",
        "state_observed": {
            "private_mb": 9861,
            "working_set_mb": 1240,
            "threads": 115,
            "accumulated_cpu_s": 4997,
            "cpu_delta_over_12s_wall": 7.44,
            "cpu_utilisation_pct_of_one_core": 62,
            "private_mb_delta_over_12s": 0.0,
        },
        "why_this_is_a_hard_stop": [
            "ORPHANED: parent PID 31268 no longer exists, so this process is "
            "outside any single-writer lease and outside any Job Object. It "
            "cannot be supervised or reaped by the control plane.",
            "HUNG: -executecmds=quit should terminate almost immediately, yet "
            "it has run for over 35 minutes and accumulated ~5000 s of CPU.",
            "ACTIVELY SPINNING: 7.44 s CPU per 12 s of wall clock, sustained "
            "at 62% of one core, with no memory release.",
            "ACTIVELY CONSUMING SCARCE STORAGE: G: free space fell from "
            "32.7 GB to 28.7 GB (about 4 GB) during roughly 20 minutes of "
            "observation, while G: is already at 3.1% free. The writes are "
            "not attributed, which is itself disqualifying.",
            "It holds an Unreal process on the exact project and Content tree "
            "a bounded cook would read and write.",
        ],
    }],
    "other_mutators": {
        "ShaderCompileWorker": "none running",
        "UE4Editor-Cmd": "none running",
        "CarlaUE4_server": "none running",
        "Import.py": "none running",
        "cook processes": "none running",
    },
    "ACTION_NOT_TAKEN": {
        "process_not_killed": True,
        "reason":
            "This process was not started by this session, killing by image "
            "name is forbidden, and terminating a possibly operator-owned "
            "process is an operator decision. It is reported with exact "
            "PID + creation_time so it can be terminated deterministically.",
        "exact_binding_for_operator_action": {
            "pid": 396,
            "creation_time_utc": "2026-10-06T12:30:44.7613250Z",
            "note": "bind termination to this PID AND creation time, never to "
                    "the image name UE4Editor.exe, because other legitimate "
                    "editor sessions may exist.",
        },
        "no_content_mutated": True,
        "no_cook_started": True,
    },
    "downstream_not_reached": {
        "PHASE_1_PRECOOK_CONTENT_AUTHORITY": "NOT_RUN",
        "PHASE_2_COOK_INPUT_FINGERPRINT_V3": "NOT_RUN",
        "PHASE_3_TILE_WORLD_EDITOR_LOAD": "NOT_RUN",
        "PHASE_4_MAIN_LARGEMAP_WORLD_VALIDATION": "NOT_RUN",
        "PHASE_5_PRECOOK_LARGEMAP_DISCOVERY": "NOT_RUN",
        "PHASE_6_WINDOWS_RHI_CONFIG_PROMOTION": "NOT_RUN",
        "PHASE_7_DDC_CURRENT_AUTHORITY": "PARTIAL_PRIOR_BATCH_READING_ONLY",
        "PHASE_8_STORAGE_BENCHMARK": "PARTIAL_TOPOLOGY_ONLY",
        "PHASE_9_F_DDC_CAPACITY": "FAIL_PRECONDITION",
        "PHASE_10_QUALIFY_INTERNAL_DDC": "NOT_RUN",
        "PHASE_11_SCW_QUALIFICATION": "PARTIAL_STATIC_IDENTITY_ONLY",
        "PHASE_12_REPRESENTATIVE_TILE_SELECTION": "NOT_RUN",
        "PHASE_20_EXECUTE_BOUNDED_COOK": "NOT_RUN",
        "PHASE_32_FULL_PRODUCTION_COOK_ADMISSION": "NOT_AUTHORIZED",
    },
    "why_not_proceed_on_a_best_effort_basis":
        "Phase 3 would have to launch Unreal against the same project an "
        "unsupervised Unreal process currently holds, which risks lock "
        "contention and would make any load result untrustworthy. Phase 9 "
        "capacity additionally fails independently. The prompt requires an "
        "immediate stop on an unknown plausible mutator.",
})

w("BUILDING_MATERIAL_VISUAL_DEFECT.json", {
    "schema": "BUILDING_MATERIAL_VISUAL_DEFECT/v1",
    "status": "OPEN",
    "BUILDING_UNBOUND_MESH_COUNT": 5711,
    "BUILDING_UNBOUND_SLOT_NAMES": ["MAT_0", "MAT_1"],
    "RESOLVED_MATERIAL_SLOT_COUNT": 0,
    "UNRESOLVED_MATERIAL_SLOT_COUNT": 2,
    "current_behaviour":
        "Every canonical building StaticMesh declares two FBX material slots "
        "with no bound material interface. No MAT_N_M, no /Game/Carla material "
        "and no fallback material asset is referenced by any sampled mesh or "
        "by any of the 20 tile worlds. Buildings therefore render with "
        "engine/default surface material behaviour.",
    "BUILDING_VISUAL_DEFECT_BLOCKS_COOK": False,
    "why_not_blocking_cook":
        "Cooking a StaticMesh with unbound material interfaces succeeds; the "
        "engine substitutes a default at render time. This is a visual and "
        "semantic fidelity issue, not a cook-process failure mode.",
    "must_be_resolved_or_explicitly_accepted_before": [
        "perception-quality acceptance",
        "visual-fidelity claims",
        "RQ3 perception comparison",
    ],
    "likely_semantic_impact":
        "CARLA semantic segmentation is carried by materials. With no material "
        "bound, buildings are very likely to be untagged or default-tagged in "
        "the semantic camera. This was NOT verified by launching the runtime "
        "in this batch and must not be assumed either way.",
    "remediation_not_attempted_here": True,
    "correct_terminology_note":
        "Current material state must NOT be described as visually correct.",
})

w("COOK_BATCH_BLOCKERS.json", {
    "schema": "COOK_BATCH_BLOCKERS/v1",
    "blockers": [
        {"id": "B1", "severity": "HARD",
         "title": "Orphaned unsupervised UE4Editor.exe actively spinning",
         "evidence": "PID 396, creation 2026-10-06T12:30:44.7613250Z, parent "
                     "31268 dead, 9861 MB private, 115 threads, ~5000 s CPU, "
                     "62% of one core sustained, G: free fell 32.7->28.7 GB "
                     "during observation",
         "gate": "PHASE_0 / ACTIVE_CONFLICTING_MUTATORS=0",
         "resolution": "Operator terminates PID 396 bound to its creation "
                       "time, then re-runs Phase 0. Preferably relaunch any "
                       "editor probe under a lease and Job Object so it can "
                       "never orphan again."},
        {"id": "B2", "severity": "HARD",
         "title": "No capacity-safe storage for DDC plus bounded cook",
         "evidence": "C: 9.8 GB free (2.1%), E: 11.6 (4.1%), F: 41.5 (6.2%), "
                     "G: 28.7 (3.1%), H: 16.6 (1.8%). Project DDC on G: is "
                     "effectively empty so any cook builds DDC cold.",
         "gate": "PHASE_9 / DDC_TARGET_CAPACITY=PASS",
         "resolution": "Free capacity, most urgently on C: which backs TEMP "
                       "and pagefile. Do not delete old DDC or user data "
                       "without explicit authorization."},
        {"id": "B3", "severity": "MEDIUM",
         "title": "Phase 1 receipts consumed without fresh revalidation",
         "evidence": "The 6116/6116 mesh-reference receipt and the per-tile "
                     "hash bindings were carried from prior batches; this "
                     "batch did not launch Unreal to revalidate them.",
         "gate": "PHASE_1",
         "resolution": "Execute Phase 1 fresh revalidation once Phase 0 is "
                       "clear, since Phase 3 launches Unreal anyway."},
    ],
    "cook_executed": False,
    "content_mutated": False,
    "config_mutated": False,
    "FULL_PRODUCTION_COOK_ALLOWED": False,
})

print("Phase 0 receipts written; no cook executed, no content mutated.")
