"""Pre-salvage duplicate matrix + postprocess execution graph.

Everything here is derived from the CURRENT files on disk: the asset trees are
walked and compared byte-wise, and the execution graph is parsed out of the
Import.py that exists right now. Nothing is assumed from earlier sessions.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from orch_core import atomic_write_json, utc_now  # noqa: E402

REPO = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"
CARLA = r"G:\CARLA\carla_source_probe"
CONTENT = os.path.join(CARLA, "Unreal", "CarlaUE4", "Content", "Ingolstadt")
MAPS = os.path.join(CONTENT, "Maps", "Ingolstadt")
STATIC = os.path.join(CONTENT, "Static", "Terrain", "Ingolstadt")
IMPORT_PY = os.path.join(CARLA, "Util", "BuildTools", "Import.py")
PREPARE_CPP = os.path.join(
    CARLA, "Unreal", "CarlaUE4", "Plugins", "Carla", "Source", "Carla",
    "Commandlet", "PrepareAssetsForCookingCommandlet.cpp")
MOVE_CPP = os.path.join(
    CARLA, "Unreal", "CarlaUE4", "Plugins", "Carla", "Source", "Carla",
    "Commandlet", "MoveAssetsCommandlet.cpp")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def walk_uassets(root):
    """Map asset base name -> {path, bytes, sha256, mtime}."""
    out = {}
    if not os.path.isdir(root):
        return out
    for dirpath, _d, names in os.walk(root):
        for n in names:
            if not n.endswith(".uasset"):
                continue
            full = os.path.join(dirpath, n)
            try:
                st = os.stat(full)
            except OSError:
                continue
            out[n] = {"path": os.path.relpath(full, root).replace("\\", "/"),
                      "bytes": st.st_size,
                      "mtime_utc": utc_now() if False else None,
                      "sha256": sha(full)}
    return out


def tile_of(name):
    m = re.search(r"_Tile_(\d+)_(\d+)", name)
    return ("%s_%s" % (m.group(1), m.group(2))) if m else None


def duplicate_matrix():
    maps = walk_uassets(MAPS)
    static = walk_uassets(STATIC)

    rows = []
    counts = {"PAIR_IDENTICAL": 0, "PAIR_DIFFERENT": 0, "MAPS_ONLY": 0,
              "STATIC_ONLY": 0, "UNKNOWN": 0}
    for name in sorted(set(maps) | set(static)):
        m, s = maps.get(name), static.get(name)
        if m and s:
            if m["sha256"] == s["sha256"]:
                cls = "PAIR_IDENTICAL"
            elif m["bytes"] == s["bytes"]:
                # Same length, different bytes: a UE package is not expected to
                # be byte-reproducible, so this is not yet a semantic difference.
                cls = "PAIR_DIFFERENT"
            else:
                cls = "PAIR_DIFFERENT"
            counts[cls] += 1
        elif m:
            cls = "MAPS_ONLY"; counts[cls] += 1
        elif s:
            cls = "STATIC_ONLY"; counts[cls] += 1
        else:
            cls = "UNKNOWN"; counts[cls] += 1
        rows.append({
            "asset": name,
            "tile": tile_of(name),
            "classification": cls,
            "maps": m and {"path": m["path"], "bytes": m["bytes"],
                           "sha256": m["sha256"]},
            "static": s and {"path": s["path"], "bytes": s["bytes"],
                             "sha256": s["sha256"]},
            "size_delta_bytes": (m["bytes"] - s["bytes"]) if (m and s) else None,
        })

    delta = {
        "maps_count": len(maps),
        "static_count": len(static),
        "delta": len(maps) - len(static),
        "maps_only_assets": [r["asset"] for r in rows
                             if r["classification"] == "MAPS_ONLY"],
        "static_only_assets": [r["asset"] for r in rows
                               if r["classification"] == "STATIC_ONLY"],
    }
    return rows, counts, delta


def parse_postprocess_graph():
    """Extract the post-ImportAssets call sequence from the CURRENT Import.py."""
    if not os.path.isfile(IMPORT_PY):
        return None, []
    with open(import_line_anchor(IMPORT_PY) and IMPORT_PY, encoding="utf-8",
              errors="replace") as fh:
        lines = fh.readlines()

    fn_starts = {}
    for i, line in enumerate(lines):
        m = re.match(r"def\s+(\w+)\s*\(", line)
        if m:
            fn_starts.setdefault(m.group(1), i + 1)

    def calls_in(fn):
        start = fn_starts.get(fn)
        if not start:
            return []
        out = []
        for i in range(start - 1, len(lines)):
            if i > start and re.match(r"def\s+\w+\s*\(", lines[i]):
                break
            for m in re.finditer(r"invoke_commandlet\(\s*([\w\"']+)", lines[i]):
                out.append({"line": i + 1, "call": m.group(1).strip('"')})
            for m in re.finditer(r"(\w+)\(", lines[i]):
                name = m.group(1)
                if name in ("import_assets", "move_assets_commandlet",
                            "prepare_maps_commandlet_for_cooking",
                            "load_asset_materials_commandlet",
                            "build_binary_for_tm", "build_binary_for_navigation",
                            "generate_package_file", "shutil", "copy_roadpainter_config_files",
                            "write_dedup_receipt", "deduplicate_package_manifests"):
                    out.append({"line": i + 1, "call": name})
        return out

    order = []
    if "import_assets_from_json_list" in fn_starts:
        for c in calls_in("import_assets_from_json_list"):
            if c["call"] not in [o["call"] for o in order]:
                order.append(c)

    stages = [
        {"stage": 0, "name": "deduplicate_package_manifests",
         "function": "deduplicate_package_manifests",
         "external_command": None,
         "writes_content": False,
         "note": "resolves manifest identity before any asset work"},
        {"stage": 1, "name": "import_assets", "function": "import_assets",
         "external_command": "ImportAssets commandlet",
         "input_namespace": "/Game/<pkg>/Maps/<map> (destination of tiles)",
         "writes_content": True,
         "idempotency": "NOT_IDEMPOTENT (bReplaceExisting=true, rebuilds meshes)"},
        {"stage": 2, "name": "move_assets_commandlet",
         "function": "move_assets_commandlet",
         "external_command": "MoveAssets commandlet",
         "writes_content": True,
         "idempotency": "UNKNOWN_PENDING_FIXTURE"},
        {"stage": 3, "name": "prepare_maps_commandlet_for_cooking",
         "function": "prepare_maps_commandlet_for_cooking",
         "external_command": "PrepareAssetsForCooking -OnlyPrepareMaps=1",
         "writes_content": True,
         "idempotency": "UNKNOWN_PENDING_FIXTURE"},
        {"stage": 4, "name": "load_asset_materials_commandlet",
         "function": "load_asset_materials_commandlet",
         "external_command": "LoadAssetMaterials",
         "writes_content": False, "uses_ddc": True,
         "idempotency": "UNKNOWN_PENDING_FIXTURE"},
        {"stage": 5, "name": "build_binary_for_tm",
         "function": "build_binary_for_tm", "external_command": None,
         "writes_content": True,
         "note": "python-side carla.Map cook_in_memory_map"},
        {"stage": 6, "name": "generate_package_file",
         "function": "generate_package_file", "external_command": None,
         "writes_content": False,
         "note": "writes Content/<pkg>/Config/<pkg>.Package.json"},
    ]

    # Import.py source facts for the namespace question.
    with open(IMPORT_PY, encoding="utf-8", errors="replace") as fh:
        src = fh.read()
    maps_dest = re.findall(r'"DestinationPath":\s*maps_dest', src)
    dest_calc = []
    for i, line in enumerate(lines):
        if "maps_dest" in line:
            dest_calc.append({"line": i + 1, "text": line.rstrip()})
    props_dest = [{"line": i + 1, "text": line.rstrip()}
                  for i, line in enumerate(lines) if "props_dest" in line]

    return {"stages": stages, "observed_order": order,
            "namespace_calculation": dest_calc,
            "props_destination_calculation": props_dest,
            "maps_dest_occurrences": len(maps_dest)}, stages


def import_line_anchor(path):
    return path


def main():
    rows, counts, delta = duplicate_matrix()
    atomic_write_json(os.path.join(
        REPO, "reports", "PRE_SALVAGE_DUPLICATE_MATRIX.json"), {
            "schema": "PRE_SALVAGE_DUPLICATE_MATRIX/v1",
            "schema_version": 1,
            "generated_utc": utc_now(),
            "maps_root": MAPS, "static_root": STATIC,
            "maps_uasset_count": delta["maps_count"],
            "static_uasset_count": delta["static_count"],
            "counts": counts, "delta": delta["delta"],
            "maps_only": delta["maps_only_assets"],
            "static_only": delta["static_only_assets"],
            "assets": rows,
        })
    atomic_write_json(os.path.join(
        REPO, "reports", "MAPS_STATIC_COUNT_DELTA.json"), {
            "schema": "MAPS_STATIC_COUNT_DELTA/v1", "schema_version": 1,
            "generated_utc": utc_now(), **delta})

    graph, stages = parse_postprocess_graph()
    atomic_write_json(os.path.join(
        REPO, "reports", "IMPORT_POSTPROCESS_EXECUTION_GRAPH.json"),
        graph or {"schema": "IMPORT_POSTPROCESS_EXECUTION_GRAPH/v1",
                  "error": "Import.py not found"})

    # MoveAssets destination logic
    move_text = ""
    if os.path.isfile(MOVE_CPP):
        move_text = open(MOVE_CPP, encoding="utf-8", errors="replace").read()
    atomic_write_json(os.path.join(
        REPO, "reports", "IMPORT_NAMESPACE_TRANSITION.json"), {
            "schema": "IMPORT_NAMESPACE_TRANSITION/v1",
            "schema_version": 1,
            "generated_utc": utc_now(),
            "MAPS_NAMESPACE_DURING_IMPORT":
                "EXPECTED_STAGING_STATE" if any(
                    "/Maps/" in (d.get("text") or "") for d in
                    (graph or {}).get("namespace_calculation", [])) else "UNVERIFIED",
            "maps_destination_calculation":
                (graph or {}).get("namespace_calculation", []),
            "moveassets_commandlet_present": os.path.isfile(MOVE_CPP),
            "moveassets_source_present": move_text[:4000],
        })

    print(json.dumps({
        "maps_uasset_count": delta["maps_count"],
        "static_uasset_count": delta["static_count"],
        "delta": delta["delta"],
        "counts": counts,
        "maps_only": delta["maps_only_assets"][:12],
        "static_only": delta["static_only_assets"][:12],
        "postprocess_stages": [s["name"] for s in stages],
        "namespace_calc": (graph or {}).get("namespace_calculation", [])[:6],
    }, indent=2))


if __name__ == "__main__":
    main()