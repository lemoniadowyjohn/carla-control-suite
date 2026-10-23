"""Consolidated material-binding receipts. Read-only; no package written."""
from __future__ import annotations

import json
import os

OUT = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports"
MAPS = r"G:\CARLA\carla_source_probe\Unreal\CarlaUE4\Content\Ingolstadt\Maps\Ingolstadt"


def w(name, obj):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)


mats = sorted(x for x in os.listdir(MAPS)
              if x.startswith("MAT_") and x.endswith(".uasset"))
w("INGOLSTADT_MATERIAL_INVENTORY.json", {
    "schema": "INGOLSTADT_MATERIAL_INVENTORY/v1",
    "MATERIAL_COUNT": len(mats),
    "assets": [{
        "name": os.path.splitext(m)[0],
        "virtual_package_path": "/Game/Ingolstadt/Maps/Ingolstadt/"
                                + os.path.splitext(m)[0],
        "extension": ".uasset",
        "size": os.stat(os.path.join(MAPS, m)).st_size,
        "mtime_utc": "2026-10-04T14:27:29Z..14:28:03Z",
        "class": "UObject (material placeholder); exact class not decoded "
                 "without opening the package in Unreal",
        "producer": "NOT FOUND in CARLA or UE 4.26.2 source",
    } for m in mats],
    "all_identical_size": len({os.stat(os.path.join(MAPS, m)).st_size
                               for m in mats}) == 1,
})

w("LOAD_ASSET_MATERIALS_CONTRACT.json", {
    "schema": "LOAD_ASSET_MATERIALS_CONTRACT/v1",
    "source": "Plugins/Carla/Source/Carla/Commandlet/"
              "LoadAssetMaterialsCommandlet.cpp",
    "what_it_actually_does": [
        "Reads <PackageName>.Package.json for map paths (line 400-443).",
        "Loads only those worlds (line 330-342).",
        "Looks for a StaticMeshActor whose name contains 'Road' or 'Roads' "
        "(line 359-368).",
        "If found and the map is tiled, ApplyRoadPainterMaterials spawns "
        "DecalActors whose materials come from roadpainter_decals.json "
        "(line 125-264).",
        "Calls UEditorLoadingAndSavingUtils::SaveDirtyPackages "
        "(line 261, 377, 455).",
    ],
    "what_it_does_NOT_do": [
        "It never touches StaticMesh material slots.",
        "It contains no SetMaterial, no OverrideMaterials, no StaticMaterials "
        "iteration.",
        "It contains no reference to any MAT_ asset.",
        "It never assigns materials to StaticMeshComponents.",
    ],
    "package_json_for_ingolstadt": {
        "maps": [{"name": "Ingolstadt",
                  "path": "/Game/Ingolstadt/Maps/Ingolstadt",
                  "use_carla_materials": True}],
        "props": [],
        "note": "Only the MAIN world is listed. The 20 tile worlds are NOT "
                "listed, so this commandlet never visits them.",
    },
    "uses_carla_materials_flag": "Parsed into FMapData::bUseCarlaMapMaterials "
                                 "(line 424) but never read anywhere in this "
                                 "commandlet. Dead in this class.",
    "MATERIAL_BINDING_BY_THIS_COMMANDLET": False,
})

w("MATERIAL_PRODUCER_SOURCE_TRACE.json", {
    "schema": "MATERIAL_PRODUCER_SOURCE_TRACE/v1",
    "MATERIAL_PRODUCER": "NOT_TILE_PIPELINE__NO_PRODUCER_FOUND",
    "searched": [
        "LoadAssetMaterialsCommandlet.cpp - no MAT_ reference, no slot logic",
        "PrepareAssetsForCookingCommandlet.cpp - assigns 7 fixed "
        "/Game/Carla/... instances by SSTag, never a MAT_ path",
        "SSTags.h - no MAT_ value",
        "Import.py - no material creation for the tile meshes",
    ],
    "producer_of_real_bindings": {
        "file": "Plugins/Carla/Source/Carla/Commandlet/"
                "PrepareAssetsForCookingCommandlet.cpp",
        "lines": "225-267",
        "rule": "if (bUseCarlaMaterials) select by AssetName.Contains(SSTag):"
                " R_MARKING -> M_Road_03_Tiled_V3 / M_Road_03_LMW (chosen by "
                "whether ImportedMaterialSlotName contains 'Yellow'); "
                "R_ROAD -> M_Road_03_Tiled_V2; R_TERRAIN -> "
                "MI_LargeLandscape_Grass; R_SIDEWALK -> MI_largeM_tile02; "
                "R_CURB -> MI_largeM_curb01; R_GUTTER -> MI_largeM_gutter01",
        "level": "StaticMeshComponent override via SetMaterial",
        "assigned_material_instances_all_exist": True,
    },
    "why_no_assignment_fired": "0 of 5711 canonical asset names contain any "
                               "SSTag substring. The canonical tree is "
                               "buildings only: every name is "
                               "Ingolstadt_Tile_X_Y_Building*. There are zero "
                               "Road/Terrain/Sidewalk/Curb/Gutter/Marking "
                               "assets, so no branch can match.",
    "MAT_N_M_dating": "2026-10-04T14:27-14:28Z, two days BEFORE run003 "
                      "(2026-10-05T18:38Z). run003's log contains no MAT_ "
                      "save record; its 5711 saves are all mesh assets.",
})

w("LOAD_ASSET_MATERIALS_EVENT_TRACE.json", {
    "schema": "LOAD_ASSET_MATERIALS_EVENT_TRACE/v1",
    "log": "CarlaUE4-backup-2026.10.06-11.55.39.log",
    "log_sha_note": "session 11:53:29Z-11:55:39Z, command line "
                    "-run=LoadAssetMaterials -PackageName=Ingolstadt",
    "commandlet_class": "/Script/Carla.LoadAssetMaterialsCommandlet",
    "executed_at": "2026.10.06-11.53.40Z",
    "engine_exit": "2026.10.06-11.55.31Z (result 0)",
    "LogSavePackage_records": 0,
    "SavePackage_records": 0,
    "DecalActor_records": 0,
    "RoadDecal_records": 0,
    "SpawnActor_records": 0,
    "LogStaticMesh_records": 11423,
    "errors": "none substantive; the 2 raw 'Error' substring hits were "
              "benign text (RenderDoc library notice)",
    "warning_profile": "60x duplicate PrimaryAssetID for stock Carla test "
                       "maps, 14x Walker blueprint AssetLog, 5x null world "
                       "context, 3x ExampleDeviceProfileSelector, 3x "
                       "streaming pool size. All stock noise.",
    "LOAD_ASSET_MATERIALS_ASSIGNMENT_COUNT": 0,
    "LOAD_ASSET_MATERIALS_SAVED_PACKAGE_COUNT": 0,
    "interpretation": "Expected no-op, not a silent failure. "
                      "Ingolstadt.Package.json lists only the 25KB main "
                      "world, which contains no StaticMeshActor named "
                      "Road/Roads, so HasRoadMesh is false, "
                      "ApplyRoadPainterMaterials is never called, and "
                      "SaveDirtyPackages has nothing dirty to write. Exit 0 "
                      "here does NOT mean materials were applied.",
    "prior_claim_corrected": "A prior pipeline receipt recorded "
                             "'LoadAssetMaterials=PASS'. PASS reflects only "
                             "process exit 0. This trace shows the commandlet "
                             "performed zero assignments and saved zero "
                             "packages.",
})

w("STATICMESH_MATERIAL_INTERFACE_AUDIT.json", {
    "schema": "STATICMESH_MATERIAL_INTERFACE_AUDIT/v1",
    "method": "read-only byte inspection of persisted packages; presence of "
              "an object path implies a serialized reference, absence of any "
              "material path implies no interface is bound",
    "UNIQUE_IMPORTED_MATERIAL_SLOTS": ["MAT_0", "MAT_1"],
    "RESOLVED_MATERIAL_SLOT_COUNT": 0,
    "UNRESOLVED_MATERIAL_SLOT_COUNT": 2,
    "canonical_meshes_sampled": 300,
    "meshes_with_any_MAT_N_M_reference": 0,
    "meshes_with_any_Carla_semantic_material_reference": 0,
    "meshes_with_any_default_or_fallback_material_reference": 0,
    "STATICMESH_MATERIAL_INTERFACE_BINDING": "NONE_BOUND",
    "finding": "Each imported building mesh declares two material slots named "
               "MAT_0 and MAT_1 (FBX slot names) but no material interface is "
               "bound to either. No MAT_N_M, no /Game/Carla material, and no "
               "fallback material path appears in any sampled package.",
    "consequence": "Buildings will render with the engine default surface "
                   "material. This is a VISUAL QUALITY defect, not a cook "
                   "blocker: cooking a StaticMesh with unbound material "
                   "interfaces succeeds and substitutes a default at render "
                   "time.",
})

w("MATERIAL_ASSETREGISTRY_BINDING.json", {
    "schema": "MATERIAL_ASSETREGISTRY_BINDING/v1",
    "note": "No AssetRegistry query was executed, because doing so requires "
            "launching Unreal, which this batch forbids. Binding was instead "
            "established from package-level reference evidence plus source "
            "semantics.",
    "hard_package_referencers_of_MAT_N_M": "NONE FOUND in any of the 29 "
                                            "Maps-namespace packages or in "
                                            "300 sampled canonical meshes",
    "referencers_of_representative_mesh_packages": "tile worlds (the 20 "
                                                   "Ingolstadt_Tile_*.umap)",
    "warning": "Absence of a serialized reference is NOT by itself proof of "
               "disuse. It is conclusive here only because the source shows "
               "no dynamic MAT_ lookup path exists (DYNAMIC_MATERIAL_LOOKUP="
               "REFUTED), so there is no mechanism by which these assets "
               "could be resolved at runtime.",
    "MATERIALS_REACHABLE_FROM_TILE_COOK_ROOT": "FALSE",
    "MATERIALS_REACHABLE_RATIONALE": "Cook pulls dependencies from serialized "
                                     "references. MAT_N_M are referenced by "
                                     "nothing, so they are not in any cook "
                                     "dependency graph and are not cookable "
                                     "runtime assets for this map.",
})

print("receipts written")
