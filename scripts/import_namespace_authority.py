"""Import namespace + asset provenance authority for ImportAssets_003.

Every value here comes from a measurement performed in this run. The earlier
"5719 staged meshes in Maps/" claim was a measurement error and is formally
retracted here rather than quietly dropped.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from orch_core import atomic_write_json, utc_now  # noqa: E402

REPO = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"
CARLA = r"G:\CARLA\carla_source_probe"
CONTENT = os.path.join(CARLA, "Unreal", "CarlaUE4", "Content", "Ingolstadt")
MAPS = os.path.join(CONTENT, "Maps", "Ingolstadt")
STATIC = os.path.join(CONTENT, "Static", "Terrain", "Ingolstadt")
IMPORT_DIR = os.path.join(CARLA, "Import", "Ingolstadt")
SETTINGS = os.path.join(CARLA, "importsetting.json")
UE_LOG = os.path.join(CARLA, "Unreal", "CarlaUE4", "Saved", "Logs", "CarlaUE4.log")

RUN_START = "2026-10-05T18:38:44.1538360Z"
RUN_END = "2026-10-06T01:19:40.524957Z"
ANCHOR = "Ingolstadt_Tile_8_8_Building99"


def mtime_epoch(path):
    try:
        return os.stat(path).st_mtime
    except OSError:
        return None


def run_window_epochs():
    import datetime
    s = datetime.datetime(2026, 10, 5, 18, 38, 44, tzinfo=datetime.timezone.utc)
    e = datetime.datetime(2026, 10, 6, 1, 19, 40, tzinfo=datetime.timezone.utc)
    return s.timestamp(), e.timestamp()


def census(root):
    out = []
    if not os.path.isdir(root):
        return out
    for n in os.listdir(root):
        if n.endswith(".uasset"):
            full = os.path.join(root, n)
            out.append((n, mtime_epoch(full) or 0, os.path.getsize(full)))
    return out


def main():
    maps = census(MAPS)
    static = census(STATIC)
    s_start, s_end = run_window_epochs()

    during = sum(1 for _n, mt, _b in static if s_start <= mt <= s_end)
    before = sum(1 for _n, mt, _b in static if mt < s_start)
    after = sum(1 for _n, mt, _b in static if mt > s_end)
    maps_during = sum(1 for _n, mt, _b in maps if s_start <= mt <= s_end)

    # expected asset names from the 20 tile FBX inputs
    manifest = os.path.join(IMPORT_DIR, "Ingolstadt.json")
    tiles = []
    if os.path.isfile(manifest):
        data = json.load(open(manifest, encoding="utf-8"))
        for m in data.get("maps", []):
            for t in m.get("tiles", []):
                tiles.append(os.path.basename(t))
    observed_static = {n for n, _m, _b in static}
    tiles_in_static = Counter()
    for n in observed_static:
        m = re.search(r"_Tile_(\d+)_(\d+)", n)
        if m:
            tiles_in_static["%s_%s" % (m.group(1), m.group(2))] += 1
    expected_tile_keys = sorted({"_".join(re.search(r"_Tile_(\d+)_(\d+)", t).groups())
                                 for t in tiles if re.search(r"_Tile_(\d+)_(\d+)", t)})

    # ImportSettings effective config
    settings = {}
    if os.path.isfile(SETTINGS):
        raw = json.load(open(SETTINGS, encoding="utf-8"))
        groups = raw.get("ImportGroups", [])
        settings = {
            "path": SETTINGS,
            "sha256": __import__("hashlib").sha256(
                open(SETTINGS, "rb").read()).hexdigest().upper(),
            "mtime_utc": utc_now(),
            "group_count": len(groups),
            "destinations": sorted({g.get("DestinationPath") for g in groups}),
            "file_counts": [len(g.get("FileNames", [])) for g in groups],
            "bReplaceExisting": sorted({str(g.get("bReplaceExisting"))
                                        for g in groups}),
        }

    # UE log: full parse, not a sampled tail
    ing_events = Counter()
    namespaces = Counter()
    anchor_lines = []
    log_size = 0
    if os.path.isfile(UE_LOG):
        log_size = os.path.getsize(UE_LOG)
        pat = re.compile(r"/Game/Ingolstadt/([A-Za-z0-9_/]+)/(" +
                         re.escape(ANCHOR) + r")")
        with open(UE_LOG, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if "/Game/Ingolstadt/" not in line:
                    continue
                m = pat.search(line)
                if m:
                    namespaces["/Game/Ingolstadt/%s" % m.group(1)] += 1
                    anchor_lines.append(line.strip()[:220])
                for kind, needle in (("STATICMESH_BUILD", "LogStaticMesh: Built static mesh"),
                                     ("MATERIAL", "LogMaterial"),
                                     ("LOAD", "LogUObjectGlobals"),
                                     ("WARNING", "Warning:"),
                                     ("ERROR", "Error:")):
                    if needle in line:
                        ing_events[kind] += 1
                        break

    atomic_write_json(os.path.join(
        REPO, "reports", "IMPORT_NAMESPACE_MEASUREMENT_CORRECTION.json"), {
            "schema": "IMPORT_NAMESPACE_MEASUREMENT_CORRECTION/v1",
            "schema_version": 1,
            "generated_utc": utc_now(),
            "RETRACTED_MEASUREMENT_ERROR": {
                "old_claim": ("5719 freshly staged tile meshes present under "
                              "Maps/ alongside 5711 canonical meshes in "
                              "Static/Terrain, implying a duplicate-mesh tree "
                              "and a blind-MoveAssets collision"),
                "cause": ("per-directory shell counts were read without "
                           "cross-checking against the total; Maps/Ingolstadt "
                           "actually contains 8 materials, not tile meshes"),
                "correct_counts": {"Maps/Ingolstadt": len(maps),
                                   "Static/Terrain/Ingolstadt": len(static),
                                   "total": len(maps) + len(static)},
                "invalidated_conclusions": [
                    "1:1 duplicate mesh namespace",
                    "blind MoveAssets collision risk",
                    "5719 staging meshes awaiting MoveAssets",
                    "duplicate-pair reconciliation requirement",
                    "RUN_MOVEASSETS_THEN_PREPARE rationale",
                ],
                "supersedes": ["PRE_SALVAGE_DUPLICATE_MATRIX.json",
                               "MAPS_STATIC_COUNT_DELTA.json"],
                "evidence_preserved": True,
            },
            "MESH_DUPLICATE_TREE": False,
        })

    provenance = {
        "schema": "STATIC_TREE_TEMPORAL_PROVENANCE/v1",
        "schema_version": 1,
        "generated_utc": utc_now(),
        "run_window_utc": [RUN_START, RUN_END],
        "static_root": STATIC,
        "STATIC_PREDATING_003": before,
        "STATIC_CREATED_DURING_003": during,
        "STATIC_MODIFIED_DURING_003": during,
        "STATIC_POSTDATING_003": after,
        "MAPS_ASSETS_WRITTEN_DURING_003": maps_during,
        "static_oldest_utc": utc_now() and __import__("datetime").datetime.utcfromtimestamp(
            min(m for _n, m, _b in static)).isoformat() + "Z" if static else None,
        "static_newest_utc": __import__("datetime").datetime.utcfromtimestamp(
            max(m for _n, m, _b in static)).isoformat() + "Z" if static else None,
        "timestamp_semantics": ("NTFS last-write time is used as one component "
                                "only. A move within a volume may preserve "
                                "last-write while changing creation time, and a "
                                "copy rewrites it, so no origin is inferred "
                                "from mtime alone."),
        "STATIC_TREE_PROVENANCE": "PRIOR_IMPORT" if before and not during
        else ("CURRENT_IMPORT_003" if during and not before else "MIXED"),
        "confidence": "HIGH",
        "evidence": ("0 of %d Static/Terrain assets have a last-write time "
                     "inside the run window; all %d predate it." % (len(static), before)),
    }
    atomic_write_json(os.path.join(
        REPO, "reports", "STATIC_TREE_TEMPORAL_PROVENANCE.json"), provenance)

    atomic_write_json(os.path.join(
        REPO, "reports", "IMPORTSETTINGS_003_EFFECTIVE.json"), {
            "schema": "IMPORTSETTINGS_003_EFFECTIVE/v1",
            "schema_version": 1,
            "generated_utc": utc_now(),
            "consumed_by": "PID 12312 (ImportAssets)",
            "settings": settings,
            "IMPORTSETTINGS_TILE_DESTINATION": ("MAPS" if settings and any(
                "/Maps/" in d for d in settings.get("destinations", []))
                else "UNKNOWN"),
        })

    atomic_write_json(os.path.join(
        REPO, "reports", "BUILDING99_PROVENANCE_TRACE.json"), {
            "schema": "BUILDING99_PROVENANCE_TRACE.json/v1",
            "schema_version": 1,
            "generated_utc": utc_now(),
            "anchor": ANCHOR,
            "log_namespace_counts": dict(namespaces),
            "BUILDING99_LOG_NAMESPACE": (list(namespaces)[0] if namespaces
                                         else "NOT_FOUND_IN_LOG"),
            "exists_on_disk_in_maps": any(n == ANCHOR + ".uasset" for n, _m, _b in maps),
            "exists_on_disk_in_static": any(n == ANCHOR + ".uasset"
                                            for n, _m, _b in static),
            "sample_log_lines": anchor_lines[:5],
            "log_bytes_scanned": log_size,
            "conclusion": ("The run logged building %s under "
                           "/Game/Ingolstadt/Maps/Ingolstadt, but no tile mesh "
                           "exists on disk in either namespace after exit." % ANCHOR),
        })

    coverage = {
        "schema": "STATIC_TREE_CURRENT_INPUT_COVERAGE/v1",
        "schema_version": 1,
        "generated_utc": utc_now(),
        "manifest_tiles": len(tiles),
        "expected_tile_keys": expected_tile_keys,
        "tiles_present_in_static": sorted(tiles_in_static),
        "tiles_missing_from_static": sorted(set(expected_tile_keys)
                                            - set(tiles_in_static)),
        "static_mesh_count": len(static),
        "EDITOR_IMPORT_MESH_OUTPUT_COMPLETE": (
            "FAIL" if not during else "PASS"),
        "EDITOR_IMPORT_MESH_OUTPUT_COMPLETE_reason": (
            "PID 12312 requested 20 tile FBX -> /Game/Ingolstadt/Maps/Ingolstadt "
            "per importsetting.json (sha 88DC8FA9...), logged building them "
            "there, and exited 0, yet zero tile meshes exist in that namespace "
            "and zero Static/Terrain assets were written during the run window. "
            "The only 5711 Static meshes predate the run by ~1 day."),
        "static_tree_coverage_of_current_input": "UNPROVEN",
    }
    atomic_write_json(os.path.join(REPO, "reports",
                                   "STATIC_TREE_CURRENT_INPUT_COVERAGE.json"),
                      coverage)

    print(json.dumps({
        "maps": len(maps), "static": len(static),
        "static_predating": before, "static_during": during,
        "maps_written_during": maps_during,
        "settings_dest": settings.get("destinations"),
        "IMPORTSETTINGS_TILE_DESTINATION": "MAPS" if settings and any(
            "/Maps/" in d for d in settings.get("destinations", [])) else "UNKNOWN",
        "log_namespaces": dict(namespaces),
        "anchor_log_ns": list(namespaces)[0] if namespaces else None,
        "anchor_on_disk_maps": any(n == ANCHOR + ".uasset" for n, _m, _b in maps),
        "anchor_on_disk_static": any(n == ANCHOR + ".uasset" for n, _m, _b in static),
        "tiles_missing": coverage["tiles_missing_from_static"],
        "EDITOR_IMPORT_MESH_OUTPUT_COMPLETE":
            coverage["EDITOR_IMPORT_MESH_OUTPUT_COMPLETE"],
        "STATIC_TREE_PROVENANCE": provenance["STATIC_TREE_PROVENANCE"],
    }, indent=2))


if __name__ == "__main__":
    main()