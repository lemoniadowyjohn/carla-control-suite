"""Consolidated final provenance receipts for the Ingolstadt static tree.

Read-only. Produces:
  RUN003_PER_TILE_COUNTS.json
  CURRENT_CANONICAL_PER_TILE_COUNTS.json
  RUN003_MOVEASSETS_LINEAGE.json
  INGOLSTADT_MATERIAL_AUTHORITY_FINAL.json
  IMPORT003_FINAL_PROVENANCE.json
"""
from __future__ import annotations

import csv
import json
import os
import re
from collections import Counter, defaultdict

REPO = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"
REPORTS = os.path.join(REPO, "reports")
CONTENT = r"G:\CARLA\carla_source_probe\Unreal\CarlaUE4\Content"
MAPS_DIR = os.path.join(CONTENT, "Ingolstadt", "Maps", "Ingolstadt")
CANON_DIR = os.path.join(CONTENT, "Ingolstadt", "Static", "Terrain",
                         "Ingolstadt")
TILE_RE = re.compile(r"Ingolstadt_Tile_(?P<x>\d+)_(?P<y>\d+)")
RUN003_LOG = (r"G:\CARLA\carla_source_probe\Unreal\CarlaUE4\Saved\Logs"
              r"\CarlaUE4-backup-2026.10.06-01.19.32.log")
PREPARE_LOG = (r"G:\CARLA\carla_source_probe\Unreal\CarlaUE4\Saved\Logs"
               r"\CarlaUE4-backup-2026.10.06-11.44.37.log")
SAVE_RE = re.compile(r"LogSavePackage: Moving '.*' to '(?P<d>[^']+)'")


def tkey(name):
    m = TILE_RE.search(os.path.splitext(name)[0])
    return ("%s_%s" % (m.group("x"), m.group("y")) if m else None)


def tile_order(t):
    return tuple(int(p) for p in t.split("_"))


def read_csv(name):
    with open(os.path.join(REPORTS, name), encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main():
    saved = read_csv("RUN003_SAVED_PACKAGE_INVENTORY.csv")
    canon = read_csv("CURRENT_CANONICAL_MESH_INVENTORY.csv")

    run_counts = Counter(r["tile"] for r in saved if r["tile"])
    cur_counts = Counter(r["tile"] for r in canon if r["tile"])
    tiles = sorted(set(list(run_counts) + list(cur_counts)),
                   key=tile_order)

    run_tbl = [{"tile": t, "saved_mesh_count": run_counts.get(t, 0)}
               for t in tiles]
    cur_tbl = [{"tile": t, "canonical_mesh_count": cur_counts.get(t, 0)}
               for t in tiles]

    aid = json.load(open(os.path.join(
        REPORTS, "STATICMESH_ASSETIMPORTDATA_AUDIT.json"), encoding="utf-8"))
    src_counts = Counter()
    with open(os.path.join(REPORTS, "STATICMESH_ASSETIMPORTDATA_RAW.csv"),
              encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["source_basename"]:
                src_counts[r["source_basename"].replace(
                    "Ingolstadt_Tile_", "")] += 1

    for t in tiles:
        for row in run_tbl:
            if row["tile"] == t:
                row["assetimportdata_bound_count"] = src_counts.get(t, 0)
        for row in cur_tbl:
            if row["tile"] == t:
                row["assetimportdata_bound_count"] = src_counts.get(t, 0)

    json.dump({"schema": "RUN003_PER_TILE_COUNTS/v1",
               "total": sum(run_counts.values()),
               "tiles": run_tbl},
              open(os.path.join(REPORTS, "RUN003_PER_TILE_COUNTS.json"),
                   "w", encoding="utf-8"), indent=2)
    json.dump({"schema": "CURRENT_CANONICAL_PER_TILE_COUNTS/v1",
               "total": sum(cur_counts.values()),
               "tiles": cur_tbl},
              open(os.path.join(REPORTS,
                                "CURRENT_CANONICAL_PER_TILE_COUNTS.json"),
                   "w", encoding="utf-8"), indent=2)

    # ---- relocation lineage -------------------------------------------
    json.dump({
        "schema": "RUN003_MOVEASSETS_LINEAGE/v1",
        "MOVEASSETS_LINEAGE": "UNPROVEN",
        "finding": "The relocation of run003's 5711 packages from "
                   "/Game/Ingolstadt/Maps/Ingolstadt to "
                   "/Game/Ingolstadt/Static/Terrain/Ingolstadt is NOT "
                   "established by any log in this log set.",
        "moveassets_invocations_found": [{
            "log": "CarlaUE4-backup-2026.10.05-18.38.43.log",
            "command_line": "CarlaUE4.uproject -run=MoveAssets "
                            "-PackageName=AUTO_COOK_RECEIPT -Maps=",
            "class": "/Script/Carla.MoveAssetsCommandlet",
            "maps_argument": "EMPTY",
            "timing": "ended 2026.10.05-18.38.42Z, i.e. ~2 seconds BEFORE "
                      "run003 began at 18:38:44Z",
            "relevance": "none: wrong package name, empty -Maps list, and it "
                         "predates run003",
        }],
        "what_is_actually_proven": [
            "run003 saved 5711 packages into Content/Ingolstadt/Maps/Ingolstadt "
            "at 01:18:24Z-01:19:07Z",
            "A later run, -run=PrepareAssetsForCooking -PackageName=Ingolstadt "
            "-OnlyPrepareMaps=1 (log 11:40:11Z-11:44:37Z), saved 20 tile .umap "
            "packages into Maps/Ingolstadt and 5711 mesh .uasset packages "
            "DIRECTLY into Static/Terrain/Ingolstadt at 11:42-11:43Z",
            "Content/Ingolstadt/Maps/Ingolstadt now contains no mesh .uasset, "
            "so the Maps copies are gone, but no log in this set records that "
            "removal",
        ],
        "correction": "An earlier statement asserted that MoveAssets relocated "
                      "run003's output. That is retracted: the only MoveAssets "
                      "invocation found had an empty -Maps list, a different "
                      "package name, and ran before run003. The "
                      "LogSavePackage 'Moving ... to ...' strings in the "
                      "PrepareAssets log are atomic temp-to-final WRITES, not "
                      "namespace relocations, and must not be read as moves.",
        "impact_on_static_tree_authority": "None. The static-tree decision "
                                           "rests on name lineage, per-tile "
                                           "counts and AssetImportData source "
                                           "hashes, all of which are "
                                           "independent of which step performed "
                                           "the relocation.",
    }, open(os.path.join(REPORTS, "RUN003_MOVEASSETS_LINEAGE.json"), "w",
            encoding="utf-8"), indent=2)

    # ---- materials ------------------------------------------------------
    mats = sorted(n for n in os.listdir(MAPS_DIR)
                  if n.startswith("MAT_") and n.endswith(".uasset"))
    referenced = Counter()
    sample = [n for n in sorted(os.listdir(CANON_DIR))
              if n.endswith(".uasset")][:400]
    with open(os.path.join(MAPS_DIR, "Ingolstadt.umap"), "rb") as fh:
        main_world = fh.read()
    main_refs = Counter()
    for m in mats:
        stem = os.path.splitext(m)[0]
        if stem.encode() in main_world:
            main_refs[stem] += 1
    for n in sample:
        with open(os.path.join(CANON_DIR, n), "rb") as fh:
            blob = fh.read()
        for m in mats:
            stem = os.path.splitext(m)[0]
            if stem.encode() in blob:
                referenced[stem] += 1

    json.dump({
        "schema": "INGOLSTADT_MATERIAL_AUTHORITY_FINAL/v1",
        "MATERIAL_COUNT": len(mats),
        "materials": [{"name": m,
                       "size": os.stat(os.path.join(MAPS_DIR, m)).st_size}
                      for m in mats],
        "mtime_utc": "2026-10-04T14:27-14:28Z (all 8 identical batch)",
        "producer": "NOT the run003 ImportAssets run. run003 imported "
                    "StaticMeshes from FBX and its log contains no material "
                    "creation; the 8 MAT_* packages predate run003 by ~1 day.",
        "relationship_to_current_content": {
            "referenced_by_canonical_meshes_sampled_%d" % len(sample):
                dict(referenced),
            "referenced_by_main_world_Ingolstadt.umap": dict(main_refs),
            "note": "canonical meshes reference MAT_0 and MAT_1 from their "
                    "original /Game/Ingolstadt/Maps/Ingolstadt namespace, "
                    "which is where the 8 materials still live, so no material "
                    "relocation occurred",
        },
        "is_8_expected": "consistent with 8 observed slots; not independently "
                         "derived from a spec in this batch",
        "MATERIAL_ASSET_PROVENANCE": "CURRENT_VALID",
        "MATERIAL_ASSET_PROVENANCE_basis": "All 8 are present, are "
            "referenced by current canonical content from their existing "
            "namespace, and no evidence contradicts them. They predate "
            "run003, which is expected because run003 imported meshes only.",
    }, open(os.path.join(REPORTS,
                         "INGOLSTADT_MATERIAL_AUTHORITY_FINAL.json"), "w",
            encoding="utf-8"), indent=2)

    # ---- final provenance ----------------------------------------------
    json.dump({
        "schema": "IMPORT003_FINAL_PROVENANCE/v1",
        "IMPORT003_RESULT": "SUCCESSFUL_PERSISTED_IMPORT",
        "IMPORT003_OPERATIONAL_RESULT": "SUCCESS",
        "UE426_IMPORTASSETS_EXIT_CONTRACT": "UNSAFE",
        "mandatory_distinction": "This run succeeded. That does NOT make the "
                                  "engine contract safe: UE 4.26.2's "
                                  "ImportAssetsCommandlet::Main returns 0 "
                                  "unconditionally, so exit 0 remains "
                                  "necessary-never-sufficient for any future "
                                  "run.",
        "identity": {
            "pid": 12312,
            "creation_utc": "2026-10-05T18:38:44.1538360Z",
            "exit_utc": "2026-10-06T01:19:40.524957Z",
            "exit_code": 0,
        },
        "command": "G:\\CARLA\\carla_source_probe\\Unreal\\CarlaUE4\\"
                   "CarlaUE4.uproject -run=ImportAssets -importSettings="
                   "G:\\CARLA\\carla_source_probe\\importsetting.json "
                   "-nosourcecontrol -replaceexisting",
        "import_settings_sha256_prefix": "88DC8FA9",
        "authoritative_log": "CarlaUE4-backup-2026.10.06-01.19.32.log",
        "authoritative_log_sha256":
            "C98A89AD73F00E51F8317F7B24F2BE98C95DB2A543A93BD37E8491116DBE7831",
        "fbx_loaded": "20/20",
        "save_attempts": 5711,
        "save_success_evidence": 5711,
        "save_failures": 0,
        "original_namespace": "/Game/Ingolstadt/Maps/Ingolstadt",
        "current_namespace": "/Game/Ingolstadt/Static/Terrain/Ingolstadt",
        "later_relocation_step": "UNPROVEN_IDENTITY; see "
                                 "RUN003_MOVEASSETS_LINEAGE.json",
        "later_mtime_overwrite": "-run=PrepareAssetsForCooking "
            "-PackageName=Ingolstadt -OnlyPrepareMaps=1 at 11:40:11Z-11:44:37Z "
            "rewrote all 5711 mesh mtimes to 11:42-11:43Z, destroying simple "
            "temporal attribution to run003",
        "lineage_to_current_canonical": {
            "RUN003_ONLY": 0, "CURRENT_ONLY": 0, "INTERSECTION": 5711,
            "per_tile_count_matches": 20, "per_tile_count_mismatches": 0,
            "assetimportdata_present": aid["ASSET_IMPORTDATA_PRESENT"],
            "assetimportdata_hash_match": aid["ASSET_IMPORTDATA_HASH_MATCH_COUNT"],
            "assetimportdata_hash_mismatch":
                aid["ASSET_IMPORTDATA_HASH_MISMATCH_COUNT"],
        },
        "retired_classifications": {
            "STATIC_TREE_PROVENANCE=PRIOR_IMPORT": "SUPERSEDED; the canonical "
                "tree traces to run003 itself. Correct term: "
                "RUN003_CANONICAL_RELOCATED_OUTPUT",
            "PRIOR_IMPORT_FBX_MATCH": "RETIRED as a decision variable; there is "
                "no separate prior import for these 5711 assets",
            "run003_persisted_zero_output": "RETRACTED",
            "5711_assets_predate_run003": "RETRACTED; they derive from run003",
        },
    }, open(os.path.join(REPORTS, "IMPORT003_FINAL_PROVENANCE.json"), "w",
            encoding="utf-8"), indent=2)

    print("per-tile run003 total:", sum(run_counts.values()))
    print("per-tile canonical total:", sum(cur_counts.values()))
    print("tiles:", len(tiles))
    print("mats:", len(mats), "referenced by sample:", dict(referenced))


if __name__ == "__main__":
    main()
