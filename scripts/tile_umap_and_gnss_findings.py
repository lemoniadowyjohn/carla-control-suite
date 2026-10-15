"""Emit the convergence-batch evidence artifacts from measured findings."""

from __future__ import annotations

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from convergence_gates import gnss_consumer_audit, georeference_preflight  # noqa: E402
from orch_core import atomic_write_json, utc_now  # noqa: E402

REPO = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"
OUT = os.path.join(REPO, "reports")
CARLA = r"G:\CARLA\carla_source_probe"
MESH_DIR = os.path.join(CARLA, "Unreal", "CarlaUE4", "Content", "Ingolstadt",
                        "Static", "Terrain", "Ingolstadt")
MAPS = os.path.join(CARLA, "Unreal", "CarlaUE4", "Content", "Ingolstadt", "Maps",
                    "Ingolstadt")


def tile_inventory():
    import re
    grid = {}
    non_tile = 0
    total = 0
    for name in os.listdir(MESH_DIR):
        if not name.endswith(".uasset"):
            continue
        total += 1
        m = re.search(r"_Tile_(\d+)_(\d+)", os.path.splitext(name)[0])
        if m:
            grid[(int(m.group(1)), int(m.group(2)))] = \
                grid.get((int(m.group(1)), int(m.group(2))), 0) + 1
        else:
            non_tile += 1
    xs = sorted({x for x, _ in grid})
    ys = sorted({y for _, y in grid})
    return {
        "total_uassets": total,
        "non_tile_uassets": non_tile,
        "tile_indices_present": ["%d_%d" % k for k in sorted(grid)],
        "tile_count": len(grid),
        "assets_per_tile": {"%d_%d" % k: v for k, v in sorted(grid.items())},
        "x_range": [min(xs), max(xs)] if xs else None,
        "y_range": [min(ys), max(ys)] if ys else None,
        "origin_tile_0_0_present": (0, 0) in grid,
    }


def umap_census():
    out = {"umaps": [], "tile_umaps": []}
    for path in glob.glob(os.path.join(MAPS, "**", "*.umap"), recursive=True):
        rel = os.path.relpath(path, MAPS).replace("\\", "/")
        out["umaps"].append(rel)
        if "_Tile_" in os.path.basename(path):
            out["tile_umaps"].append(rel)
    out["umap_count"] = len(out["umaps"])
    out["tile_umap_count"] = len(out["tile_umaps"])
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    tiles = tile_inventory()
    umaps = umap_census()

    # ---- TILE_UMAP_PRODUCER_TRACE ----
    trace = {
        "schema": "TILE_UMAP_PRODUCER_TRACE/v1",
        "schema_version": 1,
        "generated_utc": utc_now(),
        "question": "Which code creates, names and saves per-tile .umap files?",
        "answer": ("PrepareAssetsForCooking, NOT ImportAssets. ImportAssets only "
                   "creates StaticMesh assets; tile worlds are created and saved by "
                   "a later commandlet in the Import.py pipeline."),
        "pipeline_order": [
            "Import.py:import_assets()  -> invoke_commandlet('ImportAssets')",
            "Import.py:move_assets_commandlet()",
            "Import.py:prepare_maps_commandlet_for_cooking() -> "
            "invoke_commandlet('PrepareAssetsForCooking', -OnlyPrepareMaps=1)",
            "Import.py:load_asset_materials_commandlet()",
            "Import.py:build_binary_for_tm()",
        ],
        "producer_locations": {
            "tile_name_format":
                "Unreal/CarlaUE4/Plugins/Carla/Source/Carla/Commandlet/"
                "PrepareAssetsForCookingCommandlet.cpp:643",
            "tile_save_call":
                "PrepareAssetsForCookingCommandlet.cpp:646 "
                "SaveWorld(AssetData, PackageName, Map.Path, TileName)",
            "tile_discovery_loop":
                "PrepareAssetsForCookingCommandlet.cpp:631-658",
            "tile_mesh_match":
                "PrepareAssetsForCookingCommandlet.cpp:192 + :207 "
                "(TileName=_Tile_<i>_<j>; asset must EndWith(TileName) or "
                "Contain(TileName + '_'))",
            "package_path":
                "Map.Path + '/' + TileName  (registered as MapPathsIds at :647-649)",
            "large_map_consumer":
                "Unreal/CarlaUE4/Plugins/Carla/Source/Carla/MapGen/LargeMapManager.cpp:453-462",
            "tile_material_consumer":
                "LoadAssetMaterialsCommandlet.cpp:136,169-206,372",
        },
        "expected_canonical_package_shape":
            "/Game/<Package>/Maps/<MapName>/<MapName>_Tile_<X>_<Y>",
        "save_phase_per_tile_fields": {
            "WORLD_CREATED_IN_MEMORY": "same UWorld is reused; actors are "
                                       "spawned then destroyed (:651)",
            "PACKAGE_CREATED": "SaveWorld(...)",
            "SAVE_REQUESTED": "SaveWorld(...)",
            "SAVE_SUCCEEDED": "not logged at :645 (UE_LOG is COMMENTED OUT)",
            "PACKAGE_NAME": "<Map.Name>_Tile_<i>_<j>",
            "PACKAGE_PATH": "Map.Path + '/' + TileName",
        },
        "observability_gap": ("The 'Saving as %s to %s' log line at :645 is "
                              "commented out, so a tile save failure would be "
                              "invisible. Tile saves are also only observable in "
                              "the PrepareAssetsForCooking phase, never in "
                              "ImportAssets."),
        "tile_inventory": tiles,
        "umap_census": umaps,
    }
    atomic_write_json(os.path.join(OUT, "TILE_UMAP_PRODUCER_TRACE.json"), trace)

    # ---- TILE_UMAP_ROOT_CAUSE ----
    has_origin_tile = tiles["origin_tile_0_0_present"]
    cause = {
        "schema": "TILE_UMAP_ROOT_CAUSE/v1",
        "schema_version": 1,
        "generated_utc": utc_now(),
        "TILE_UMAP_ROOT_CAUSE": "OTHER",
        "sub_classification": "TILE_GRID_ORIGIN_MISMATCH",
        "proximate_mechanism": "SAVE_PHASE_NEVER_REACHED",
        "confidence": "HIGH",
        "proof_type": "STATIC_CODE_PROOF_PLUS_DISK_CENSUS",
        "explanation": (
            "PrepareAssetsForCookingCommandlet.cpp:631-658 enumerates tiles with "
            "do { i=0; do { spawn(i,j); if (ok) {save; ++i;} } while (ok); ++j } "
            "while (i>0). The inner loop advances only while the previous tile was "
            "found and stops at the FIRST miss, so enumeration assumes a tile grid "
            "that is contiguous and anchored at (0,0). "
            "SpawnMeshesToWorld (:192,:207) selects meshes whose name ends with "
            "'_Tile_<i>_<j>'. "
            "The imported Ingolstadt grid is X in {6..10}, Y in {6..9}: 20 tiles, "
            "5711 assets, and NO tile at (0,0). At (0,0) zero meshes match, ok is "
            "false, i is still 0, and the outer loop exits immediately having saved "
            "zero tile worlds."),
        "evidence": {
            "tile_0_0_present": has_origin_tile,
            "x_range": tiles["x_range"],
            "y_range": tiles["y_range"],
            "tile_count": tiles["tile_count"],
            "mesh_assets": tiles["total_uassets"],
            "non_tile_meshes": tiles["non_tile_uassets"],
            "naming_pattern_matches_producer":
                "assets are named Ingolstadt_Tile_<X>_<Y>_<suffix>, which does "
                "satisfy the Contains(TileName + '_') test; naming is NOT the defect",
            "tile_umap_count": umaps["tile_umap_count"],
        },
        "consequences": [
            "PrepareAssetsForCooking saves zero tile .umap files for this grid",
            "LargeMapManager therefore discovers zero tiles",
            "LARGEMAP_STREAMING can never pass for this tile numbering",
            "TILE_UMAP_COUNT=0 is expected and is NOT an interrupted-import symptom",
        ],
        "candidate_fixes": [
            {"option": "REINDEX_TILES_TO_ORIGIN",
             "detail": "rename/re-import tiles to start at (0,0)",
             "cost": "full re-import of 5711 assets; changes asset names",
             "risk": "high"},
            {"option": "PATCH_PRODUCER_ENUMERATION",
             "detail": "derive tile bounds from the actual asset set or from the "
                       "manifest instead of scanning from (0,0) and stopping at "
                       "the first miss",
             "cost": "small C++ change in PrepareAssetsForCookingCommandlet.cpp",
             "risk": "low; does not disturb existing correct maps because a "
                     "0,0-anchored grid enumerates identically"},
            {"option": "ADD_SYNTHETIC_TILE_0_0",
             "detail": "rejected",
             "risk": "would fabricate a tile that has no source geometry"},
        ],
        "not_yet_observed": (
            "The static proof is deterministic given the tile set, but "
            "PrepareAssetsForCooking has not yet been observed to run on this "
            "import. Confirmation requires the single-tile reproduction, which "
            "requires the UE binaries to be free."),
        "does_not_explain": (
            "It does not explain the 5711 reference warnings, which concern mesh "
            "references rather than tile world enumeration. Those remain "
            "NOT_YET_PROVEN."),
    }
    atomic_write_json(os.path.join(OUT, "TILE_UMAP_ROOT_CAUSE.json"), cause)

    # ---- GNSS consumer audit ----
    consumers = [
        {"consumer": "phase_q.protocols / resource_profiles sensor-rate spec",
         "role": "declares gnss rate 10 Hz",
         "waits_for_first_frame": False, "timeout_sec": None,
         "aborts_on_timeout": False, "treats_missing_as_optional": False},
        {"consumer": "phase_l_validation.step_l9_sensor_validation",
         "role": "L9 sensor validation reported in evidence manifests",
         "waits_for_first_frame": False, "timeout_sec": None,
         "aborts_on_timeout": False, "treats_missing_as_optional": False},
        {"consumer": "phase_l_validation.step_l10_performance",
         "role": "L10 performance reported in evidence manifests",
         "waits_for_first_frame": False, "timeout_sec": None,
         "aborts_on_timeout": False, "treats_missing_as_optional": False},
        {"consumer": "phase_l_validation.step_l11_old_vs_new",
         "role": "L11 comparison reported in evidence manifests",
         "waits_for_first_frame": False, "timeout_sec": None,
         "aborts_on_timeout": False, "treats_missing_as_optional": False},
    ]
    audit = gnss_consumer_audit(consumers)

    # The three phase_l steps do not merely tolerate silence, they fabricate a
    # PASS. That is more severe than SILENT_DATA_LOSS and must be recorded as
    # its own class rather than folded into the taxonomy.
    audit["fabricated_pass_findings"] = [
        {
            "location": "phase_l_validation.py:346-357 "
                        "step_l9_sensor_validation",
            "defect": "FABRICATED_SENSOR_VALIDATION",
            "detail": ("Accepts a live client, calls get_world(), then hardcodes "
                       "status CAPTURED for rgb/depth/semantic/lidar/gnss/imu, "
                       "synchronization_status PASS, and gnss_agreement PASS. It "
                       "subscribes to no sensor and receives no frame."),
            "impact": ("On a map with no absolute origin GNSS emits nothing, yet "
                       "this still records gnss status CAPTURED and agreement "
                       "PASS, so any gate reading L9 sees a false success."),
            "severity": "CRITICAL",
        },
        {
            "location": "phase_l_validation.py:361-382 step_l10_performance",
            "defect": "FABRICATED_PERFORMANCE_MEASUREMENT",
            "detail": ("fps=0, p95_frame_time_ms=0, ram_usage_mb=0, "
                       "vram_usage_mb=0, rpc_timeouts=0 are all hardcoded while "
                       "performance_status is reported as PASS."),
            "severity": "HIGH",
        },
        {
            "location": "phase_l_validation.py:385-391 step_l11_old_vs_new",
            "defect": "UNCOMPUTED_COMPARISON_REPORTED_AS_PASS",
            "detail": "comparison_status PASS with no comparison performed.",
            "severity": "HIGH",
        },
    ]
    audit["persisted_fabricated_evidence"] = {
        "pattern": "reports/post_audit_hardening/*/L9_sensor_validation.json",
        "occurrences": len(glob.glob(os.path.join(
            REPO, "reports", "post_audit_hardening", "*",
            "L9_sensor_validation.json"))),
        "referenced_by": [
            "reports/post_audit_hardening/*/PHASE_L_RUNTIME_VALIDATION.json",
            "reports/post_audit_hardening/20260805T141616Z_GITHUB_SHIP/"
            "A00_LOCAL_REMOTE_RECONCILIATION.md",
            "reports/post_audit_hardening/20260805T141616Z_N_CERTIFICATION/"
            "EVIDENCE_MANIFEST.json",
        ],
        "severity": "CRITICAL",
        "note": ("Fabricated PASS evidence is referenced from a certification "
                 "manifest inside a directory named GITHUB_SHIP. Any prior "
                 "runtime PASS derived from these files is void."),
    }
    audit["PASS"] = False
    audit["GNSS_NO_ORIGIN_BEHAVIOR"] = "SILENT_NO_DATA_PLUS_FABRICATED_PASS"
    atomic_write_json(os.path.join(OUT, "GNSS_CONSUMER_AUDIT.json"), audit)

    # ---- georeference preflight, both branches ----
    pre_ok = georeference_preflight(True, has_absolute_origin=False,
                                    map_name="Ingolstadt")
    atomic_write_json(os.path.join(OUT, "GEOREFERENCE_PREFLIGHT.json"), pre_ok)

    print(json.dumps({
        "tile_grid": {"x": tiles["x_range"], "y": tiles["y_range"],
                      "count": tiles["tile_count"], "origin_0_0": has_origin_tile},
        "tile_umap_count": umaps["tile_umap_count"],
        "umap_count": umaps["umap_count"],
        "TILE_UMAP_ROOT_CAUSE": cause["TILE_UMAP_ROOT_CAUSE"],
        "sub_classification": cause["sub_classification"],
        "gnss_audit_PASS": audit["PASS"],
        "fabricated_pass_findings": len(audit["fabricated_pass_findings"]),
        "persisted_fabricated_occurrences":
            audit["persisted_fabricated_evidence"]["occurrences"],
        "preflight_gnss_required": {
            "status": pre_ok["status"], "allowed": pre_ok["EXPERIMENT_ALLOWED"]},
    }, indent=2))


if __name__ == "__main__":
    main()
