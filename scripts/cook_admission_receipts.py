"""Phase A/B gate receipts for bounded cook admission.

Emits the decisive receipts plus explicit NOT_RUN markers for every Phase B
stage that was not reached because a hard gate failed first. Nothing here
fabricates a result: any stage not executed is recorded as NOT_RUN with the
gate that stopped it.
"""
from __future__ import annotations

import json
import os
import subprocess

OUT = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports"


def w(name, obj):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)


# ---- carry forward the Phase A determinations already proven -------------
w("MATERIAL_AUTHORITY_FINAL.json", {
    "schema": "MATERIAL_AUTHORITY_FINAL/v1",
    "OBSERVED_MATERIAL_COUNT": 8,
    "EXPECTED_MATERIAL_COUNT": 0,
    "EXPECTED_MATERIAL_COUNT_basis":
        "The only material-binding mechanism in the tile pipeline is "
        "PrepareAssetsForCookingCommandlet.cpp:225-267, which assigns 7 fixed "
        "/Game/Carla/... instances selected by RoadRunner SSTag substrings in "
        "the ASSET NAME. 0 of 5711 canonical names contain any SSTag because "
        "the tree is buildings-only, so zero MAT_N_M assets are expected. "
        "'8 exists' is not accepted as justification for 8.",
    "MISSING_MATERIALS": 0,
    "UNEXPECTED_MATERIALS": 8,
    "UNEXPECTED_MATERIALS_detail":
        "All 8 MAT_N_M are unreferenced import-era artifacts dated "
        "2026-10-04T14:27-14:28Z, two days before run003. run003's log "
        "contains no MAT_ save record. No producer was found in CARLA or "
        "UE 4.26.2 source.",
    "MATERIAL_PRODUCER": "NOT_TILE_PIPELINE__NO_PRODUCER_FOUND",
    "MATERIAL_RUNTIME_ROLE": "VALID_BUT_UNUSED",
    "MATERIALS_REACHABLE_FROM_TILE_COOK_ROOT": "FALSE",
    "MATERIAL_ASSET_PROVENANCE": "STALE",
    "STATICMESH_MATERIAL_INTERFACE_BINDING": "NONE_BOUND",
    "UNIQUE_IMPORTED_MATERIAL_SLOTS": ["MAT_0", "MAT_1"],
    "UNIQUE_RESOLVED_MATERIAL_INTERFACES": [],
    "DYNAMIC_MATERIAL_LOOKUP": "REFUTED",
    "DEFAULT_MATERIAL_BINDINGS": 0,
    "NULL_MATERIAL_BINDINGS": "5711 meshes x 2 slots unbound",
    "UNEXPECTED_FALLBACK_BINDINGS": 0,
    "MISSING_MATERIAL_TEXTURE_DEPENDENCIES": 0,
    "MATERIAL_BINDING_BLOCKS_COOK": False,
    "MATERIAL_BINDING_BLOCKS_COOK_reasoning":
        "Cook does not require material interfaces to be bound; an unbound "
        "slot substitutes a default at render time and cooks successfully. "
        "MAT_N_M are referenced by nothing and are therefore in no cook "
        "dependency graph, so they cannot be missing dependencies. "
        "No fallback material asset is referenced, so UNEXPECTED_FALLBACK_"
        "BINDINGS is 0.",
    "SEPARATE_BLOCKER_NOT_A_COOK_GATE":
        "Every building mesh has two FBX material slots (MAT_0, MAT_1) with "
        "no interface bound. For CARLA semantic segmentation this is very "
        "likely a real runtime defect, because semantic tags are carried by "
        "materials. It is recorded here and must be resolved before any "
        "perception work, but it does not block the cook process itself.",
    "6116_reference_receipt": "NOT_REVERIFIED_THIS_BATCH",
    "xodr_authority": "370ABBBB... byte exact, reverified this batch",
})

w("COOK_PROCESS_CONTROL_ADMISSION.json", {
    "schema": "COOK_PROCESS_CONTROL_ADMISSION/v1",
    "PROCESS_TREE_SUPERVISION": "PASS",
    "evidence": "reports/PROCESS_TREE_SUPERVISION_FINAL.json; clean-checkout "
                "reproduction at published SHA 32fbde8e: matrix 25/25, stress "
                "270/270, T6 5/5, coupling 11/11, identity 15/15, native "
                "crashes 0, GetProcessHandleCount 176->181 growth 5.",
    "LEASE_JOB_COUPLING": "PASS",
    "SINGLE_WRITER_CONTROL_PLANE": "PASS",
    "NATIVE_CRASHES": 0,
    "ACTIVE_CONTENT_MUTATORS": 1,
    "ACTIVE_CONTENT_MUTATORS_detail": [{
        "pid": 396,
        "creation_utc": "2026-10-06T12:30:44.7613250Z",
        "executable": "G:\\UnrealEngine_4.26_CARLA\\Engine\\Binaries\\Win64\\"
                      "UE4Editor.exe",
        "command_line": "\"G:\\UnrealEngine_4.26_CARLA\\Engine\\Binaries\\Win64"
                        "\\UE4Editor.exe\" G:\\CARLA\\carla_source_probe\\Unreal"
                        "\\CarlaUE4\\CarlaUE4.uproject -nullrhi -unattended "
                        "-executecmds=quit",
        "parent_pid": 31268,
        "parent_alive": False,
        "working_set_mb": 1220,
        "private_mb": 9732,
        "threads": 114,
        "classification": "UNKNOWN_PRESERVE",
        "why_unknown":
            "-nullrhi -unattended -executecmds=quit should terminate almost "
            "immediately, yet the process is still resident ~25 minutes after "
            "creation. Its parent (31268) is gone, so it is ORPHANED and "
            "outside any single-writer lease or Job Object supervision. It "
            "cannot be shown to be governed, and it cannot be shown to be "
            "harmless: an unsupervised Unreal process can hold package file "
            "locks on the exact Content tree a cook would read.",
    }],
    "COOK_ADMISSION": "DENIED",
    "COOK_ADMISSION_reason":
        "B2 requires ACTIVE_CONTENT_MUTATORS=0. An orphaned, unsupervised "
        "UE4Editor is present on the target project. Per the prompt's own "
        "rule, an unknown mutator yields UNKNOWN_PRESERVE and denies cook "
        "admission.",
    "action_not_taken":
        "This process was NOT killed. It was not started by this session, "
        "killing by image name is forbidden, and terminating a process the "
        "operator may be using is an operator decision.",
})

w("COOK_STORAGE_AUTHORITY.json", {
    "schema": "COOK_STORAGE_AUTHORITY/v1",
    "topology_verified_fresh": True,
    "volumes": [
        {"drive": "C:", "disk": 1, "media": "INTEL SSDPEKKF512G8L",
         "bus": "NVMe", "size_gb": 475.9, "free_gb": 9.8, "free_pct": 2.1},
        {"drive": "E:", "disk": 0, "media": "INTENSO SSD", "bus": "SATA",
         "size_gb": 280.7, "free_gb": 11.6, "free_pct": 4.1},
        {"drive": "F:", "disk": 0, "media": "INTENSO SSD", "bus": "SATA",
         "size_gb": 673.1, "free_gb": 41.5, "free_pct": 6.2},
        {"drive": "G:", "disk": 3, "media": "Intenso SCSI", "bus": "USB",
         "size_gb": 931.5, "free_gb": 32.7, "free_pct": 3.5},
        {"drive": "H:", "disk": 4, "media": "Intenso SCSI", "bus": "USB",
         "size_gb": 931.5, "free_gb": 16.6, "free_pct": 1.8},
    ],
    "topology_matches_stated_authority": True,
    "topology_note": "G is USB external and F is internal SATA as stated, "
                      "but H is a SECOND USB disk that the stated authority "
                      "did not mention. F and E share physical disk 0.",
    "current_ddc_state": {
        "project_ddc": "G:\\CARLA\\carla_source_probe\\Unreal\\CarlaUE4\\"
                       "DerivedDataCache = 1 file, ~0.0 GB (effectively empty)",
        "F_ddc_candidate": "F:\\UnrealEngine_DDC exists but is EMPTY (0 files)",
        "engine_ddc": "%ENGINEDIR%DerivedDataCache (G:\\UnrealEngine_4.26_CARLA"
                      "\\Engine\\DerivedDataCache) not measured in this batch",
        "implication": "The historical G: DDC slowdown does not apply to the "
                       "current project DDC because it is empty. Any cook "
                       "would build DDC essentially cold.",
    },
    "capacity_admission": {
        "DDC_TARGET_CAPACITY": "FAIL",
        "reasoning":
            "Every volume is at or below 6.2% free. F: is the largest "
            "candidate at 41.5 GB free, but it must simultaneously hold a "
            "cold DDC for this content (typically tens of GB for 5711 meshes "
            "plus engine shader compilation) AND bounded cook output, with a "
            "safety reserve. C: at 9.8 GB free (2.1%) is the TEMP/pagefile "
            "volume and is itself a cook-time risk. No configuration of "
            "existing free space is capacity-safe.",
        "no_migration_attempted": True,
        "no_deletion_attempted": True,
        "note": "Deleting old DDC or user data requires explicit "
                "authorization and was not attempted.",
    },
})

w("PRECOOK_GATE_STATUS.json", {
    "schema": "PRECOOK_GATE_STATUS/v1",
    "PHASE_A_GATE": "PASS",
    "PHASE_A_conditions": {
        "STATIC_TREE_CURRENT_INPUT_AUTHORITY": "PROVEN_EXACT_CURRENT_INPUT",
        "MATERIAL_BINDING_BLOCKS_COOK": False,
        "UNEXPECTED_FALLBACK_BINDINGS": 0,
        "MISSING_MATERIAL_TEXTURE_DEPENDENCIES": 0,
        "tile_worlds_present": "20/20",
        "canonical_meshes_present": 5711,
        "xodr_authority": "370ABBBB byte exact",
        "PROCESS_TREE_SUPERVISION": "PASS",
        "6116_reference_receipt": "NOT_REVERIFIED_THIS_BATCH (prior receipt; "
                                  "reverification requires launching Unreal)",
    },
    "PHASE_B_GATE": "FAIL",
    "PHASE_B_blockers": [
        {"gate": "B2 mutator census",
         "blocker": "orphaned unsupervised UE4Editor.exe PID 396 "
                    "(creation 2026-10-06T12:30:44.7613250Z) on the target "
                    "project",
         "class": "UNKNOWN_PRESERVE"},
        {"gate": "B3/D4 storage capacity",
         "blocker": "all volumes <=6.2% free; C: 9.8 GB (2.1%), F: 41.5 GB "
                    "(6.2%); cold DDC plus bounded cook output plus reserve "
                    "does not fit",
         "class": "DDC_TARGET_CAPACITY=FAIL"},
    ],
    "stages_not_reached": {
        "B4_COOK_INPUT_FINGERPRINT_V3": "NOT_RUN (blocked by B2/B3)",
        "B5_TILE_WORLD_EDITOR_LOAD": "NOT_RUN (requires launching Unreal "
                                     "while an unsupervised Unreal process "
                                     "already holds the project)",
        "B6_MAIN_LARGEMAP_WORLD_VALIDATION": "NOT_RUN",
        "B7_PRECOOK_LARGEMAP_DISCOVERY": "PARTIAL_PRIOR_RECEIPT_ONLY",
        "B8_SERVE_FIRST_TILE_PROOF": "NOT_RUN",
        "C_RHI_CONFIG_PROMOTION": "NOT_RUN (config mutation not authorized "
                                  "before admission)",
        "D_DDC_MIGRATION": "NOT_RUN (capacity FAIL; do not migrate)",
        "E_SCW_QUALIFICATION": "NOT_RUN",
        "F_BOUNDED_COOK_SELECTION": "NOT_RUN",
        "G_RESOURCE_BASELINE": "NOT_RUN",
        "H_BOUNDED_COOK_EXECUTE": "NOT_RUN",
        "I_COOK_OUTPUT_ACCEPTANCE": "NOT_RUN",
        "J_SCW_FAILURE_INJECTION": "NOT_RUN",
        "K_FULL_PRODUCTION_COOK_ADMISSION": "NOT_AUTHORIZED",
    },
    "cook_executed": False,
    "content_mutated": False,
    "policy_note": "The prompt instructs stopping immediately on an unknown "
                   "active mutator and on unsafe DDC capacity, and forbids "
                   "continuing to gather results after a hard gate fails. "
                   "Both conditions are present, so Phase B was not entered.",
})

print("phase A gate receipts written")
print(subprocess.run(["cmd", "/c", "echo", "done"], capture_output=True,
                     text=True).stdout)
