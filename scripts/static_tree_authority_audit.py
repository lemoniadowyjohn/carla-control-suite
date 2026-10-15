"""Read-only provenance audit for the Ingolstadt canonical static tree.

Establishes, from evidence rather than assumption:
  * revalidated current FBX authority (SHA256 + MD5, deterministic manifest)
  * the exact package set run003 persisted, parsed from the authoritative log
  * the current canonical package set under Static/Terrain/Ingolstadt
  * name-level lineage between them
  * per-tile counts and exact object-set coverage

No Unreal package is opened for writing and nothing is resaved. Log parsing
and filesystem reads only.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from collections import Counter, defaultdict

REPO = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"
CONTENT = r"G:\CARLA\carla_source_probe\Unreal\CarlaUE4\Content"
FBX_DIR = r"G:\CARLA\carla_source_probe\Import\Ingolstadt"
RUN003_LOG = (r"G:\CARLA\carla_source_probe\Unreal\CarlaUE4\Saved\Logs"
              r"\CarlaUE4-backup-2026.10.06-01.19.32.log")
CANON_DIR = os.path.join(CONTENT, "Ingolstadt", "Static", "Terrain",
                         "Ingolstadt")
MAPS_DIR = os.path.join(CONTENT, "Ingolstadt", "Maps", "Ingolstadt")
OUT = os.path.join(REPO, "reports")

EXPECTED_MANIFEST_SHA = (
    "1a2e05833af639f599ed54e53cdd76f966bf0d14a81c57b4bfb100b1cca0689e")

SAVE_RE = re.compile(
    r"\[(?P<ts>[\d.\-:]+)\]\[\s*\d+\]LogSavePackage: Moving '.*' to "
    r"'(?P<dest>[^']+)'")
FBX_RE = re.compile(r"Loading FBX Scene from (?P<fbx>\S+)")
TILE_RE = re.compile(r"Ingolstadt_Tile_(?P<x>\d+)_(?P<y>\d+)")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- FBX
def revalidate_fbx():
    rows = []
    for name in sorted(os.listdir(FBX_DIR)):
        if not name.lower().endswith(".fbx"):
            continue
        path = os.path.join(FBX_DIR, name)
        st = os.stat(path)
        m = TILE_RE.search(os.path.splitext(name)[0])
        rows.append({
            "tile": "%s_%s" % (m.group("x"), m.group("y")) if m else None,
            "basename": os.path.splitext(name)[0],
            "relative_path": "Import/Ingolstadt/" + name,
            "size": st.st_size,
            "mtime_utc": __import__("datetime").datetime.fromtimestamp(
                st.st_mtime, __import__("datetime").timezone.utc).isoformat(),
            "sha256": sha256_file(path),
            "md5": md5_file(path),
        })
    rows.sort(key=lambda r: r["relative_path"])
    manifest = "\n".join("%s|%d|%s" % (r["relative_path"], r["size"],
                                       r["sha256"]) for r in rows)
    agg = hashlib.sha256(manifest.encode("utf-8")).hexdigest()
    return rows, agg


# ------------------------------------------------------- run003 log
def parse_run003():
    saves, fbxs = [], []
    with open(RUN003_LOG, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = SAVE_RE.search(line)
            if m:
                dest = m.group("dest").replace("/", os.sep)
                base = os.path.splitext(os.path.basename(dest))[0]
                tm = TILE_RE.search(base)
                saves.append({
                    "timestamp": m.group("ts"),
                    "original_physical_path": dest,
                    "original_virtual_package":
                        "/Game/Ingolstadt/Maps/Ingolstadt/" + base,
                    "object_name": base,
                    "tile": ("%s_%s" % (tm.group("x"), tm.group("y"))
                             if tm else None),
                })
                continue
            m2 = FBX_RE.search(line)
            if m2:
                fbxs.append(m2.group("fbx"))
    return saves, sorted(set(fbxs))


# ------------------------------------------------------- current
def current_canonical():
    rows = []
    for name in sorted(os.listdir(CANON_DIR)):
        if not name.lower().endswith(".uasset"):
            continue
        path = os.path.join(CANON_DIR, name)
        base = os.path.splitext(name)[0]
        tm = TILE_RE.search(base)
        rows.append({
            "current_virtual_package":
                "/Game/Ingolstadt/Static/Terrain/Ingolstadt/" + base,
            "basename": name,
            "object_name": base,
            "tile": ("%s_%s" % (tm.group("x"), tm.group("y"))
                     if tm else None),
            "size": os.stat(path).st_size,
        })
    return rows


def maps_inventory():
    items = []
    for name in sorted(os.listdir(MAPS_DIR)):
        path = os.path.join(MAPS_DIR, name)
        if os.path.isdir(path):
            # Subdirectories (OpenDrive, TM) are not packages and must not be
            # counted as Maps namespace files.
            continue
        ext = os.path.splitext(name)[1].lower()
        items.append({
            "name": name,
            "extension": ext,
            "package_type": "World" if ext == ".umap" else "Asset",
            "size": os.stat(path).st_size,
            "mtime_utc": __import__("datetime").datetime.fromtimestamp(
                os.stat(path).st_mtime, __import__("datetime").timezone.utc).isoformat(),
            "tile_keyed": bool(TILE_RE.fullmatch(
                os.path.splitext(name)[0])),
        })
    return items


def main():
    fbx_rows, agg = revalidate_fbx()
    saves, fbxs = parse_run003()
    canon = current_canonical()
    maps = maps_inventory()

    save_names = [s["object_name"] for s in saves]
    canon_names = [c["object_name"] for c in canon]
    save_set, canon_set = set(save_names), set(canon_names)

    dup_saves = [n for n, c in Counter(save_names).items() if c > 1]
    dup_canon = [n for n, c in Counter(canon_names).items() if c > 1]

    run003_per_tile = Counter(s["tile"] for s in saves)
    canon_per_tile = Counter(c["tile"] for c in canon)
    tiles = sorted(set(list(run003_per_tile) + list(canon_per_tile)),
                   key=lambda t: tuple(int(p) for p in t.split("_")))

    per_tile = []
    matches = mismatches = 0
    for t in tiles:
        a, b = run003_per_tile.get(t, 0), canon_per_tile.get(t, 0)
        if a == b:
            matches += 1
        else:
            mismatches += 1
        per_tile.append({"tile": t, "run003_saved": a,
                         "current_canonical": b, "match": a == b})

    # exact object-set coverage per tile
    run_by_tile, cur_by_tile = defaultdict(set), defaultdict(set)
    for s in saves:
        run_by_tile[s["tile"]].add(s["object_name"])
    for c in canon:
        cur_by_tile[c["tile"]].add(c["object_name"])
    missing = unexpected = 0
    for t in tiles:
        missing += len(run_by_tile[t] - cur_by_tile[t])
        unexpected += len(cur_by_tile[t] - run_by_tile[t])

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "RUN003_SAVED_PACKAGE_INVENTORY.csv"), "w",
              newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "timestamp", "original_physical_path",
            "original_virtual_package", "object_name", "tile",
            "save_result_evidence"], extrasaction="ignore")
        w.writeheader()
        for s in saves:
            s = dict(s)
            s["save_result_evidence"] = "LogSavePackage_Moving_tmp_to_final"
            w.writerow(s)

    with open(os.path.join(OUT, "CURRENT_CANONICAL_MESH_INVENTORY.csv"), "w",
              newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "current_virtual_package", "basename", "object_name", "tile",
            "size"])
        w.writeheader()
        w.writerows(canon)

    result = {
        "schema": "STATIC_TREE_EXACT_OBJECT_COVERAGE/v1",
        "CURRENT_FBX_COUNT": len(fbx_rows),
        "CURRENT_FBX_MANIFEST_SHA": agg,
        "CURRENT_FBX_MANIFEST_MATCH": agg == EXPECTED_MANIFEST_SHA,
        "RUN003_FBX_LOADED_COUNT": len(fbxs),
        "RUN003_SAVE_RECORDS": len(saves),
        "RUN003_DISTINCT_SAVED_TILE_ASSETS": len(save_set),
        "RUN003_DUPLICATE_SAVE_RECORDS": len(dup_saves),
        "CURRENT_CANONICAL_DISTINCT_MESHES": len(canon_set),
        "CURRENT_CANONICAL_DUPLICATES": len(dup_canon),
        "RUN003_ONLY": len(save_set - canon_set),
        "CURRENT_ONLY": len(canon_set - save_set),
        "INTERSECTION": len(save_set & canon_set),
        "RUN003_TO_CANONICAL_NAME_COVERAGE":
            "PASS" if (save_set == canon_set) else "FAIL",
        "STATIC_EXPECTED_OBJECT_COUNT": len(save_set),
        "STATIC_OBSERVED_OBJECT_COUNT": len(canon_set),
        "STATIC_MISSING_COUNT": missing,
        "STATIC_UNEXPECTED_COUNT": unexpected,
        "STATIC_DUPLICATE_COUNT": len(dup_canon),
        "PER_TILE_COUNT_MATCHES": matches,
        "PER_TILE_COUNT_MISMATCHES": mismatches,
        "STATIC_TREE_EXACT_OBJECT_COVERAGE":
            "PASS" if (matches == 20 and mismatches == 0 and missing == 0
                       and unexpected == 0 and save_set == canon_set)
            else "FAIL",
        "per_tile": per_tile,
        "maps_namespace": {
            "MAPS_CURRENT_FILE_COUNT": len(maps),
            "MATERIAL_COUNT": sum(1 for m in maps
                                  if m["name"].startswith("MAT_")),
            "TILE_UMAP_COUNT": sum(1 for m in maps
                                   if m["extension"] == ".umap"
                                   and m["tile_keyed"]),
            "OTHER_MAPS_PACKAGE_COUNT": sum(
                1 for m in maps if m["extension"] == ".umap"
                and not m["tile_keyed"]),
            "OTHER_MAPS_PACKAGES": [m["name"] for m in maps
                                    if m["extension"] == ".umap"
                                    and not m["tile_keyed"]],
        },
    }
    with open(os.path.join(OUT, "STATIC_TREE_EXACT_OBJECT_COVERAGE.json"),
              "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
    with open(os.path.join(OUT, "CURRENT_FBX_AUTHORITY_REVALIDATED.json"),
              "w", encoding="utf-8") as fh:
        json.dump({"schema": "CURRENT_FBX_AUTHORITY/v1",
                   "manifest_sha": agg,
                   "matches_prior_manifest": agg == EXPECTED_MANIFEST_SHA,
                   "count": len(fbx_rows), "fbx": fbx_rows}, fh, indent=2)
    with open(os.path.join(OUT, "MAPS_NAMESPACE_FINAL_INVENTORY.json"),
              "w", encoding="utf-8") as fh:
        json.dump({"schema": "MAPS_NAMESPACE_FINAL_INVENTORY/v1",
                   "count": len(maps), "items": maps}, fh, indent=2)
    print(json.dumps({k: v for k, v in result.items()
                      if k not in ("per_tile", "maps_namespace")}, indent=2))
    print("MAPS:", json.dumps(result["maps_namespace"]))


if __name__ == "__main__":
    main()
