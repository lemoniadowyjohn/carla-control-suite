"""Read-only AssetImportData audit over the canonical Ingolstadt static tree.

For each canonical StaticMesh .uasset, extracts the AssetImportData payload
from the package bytes and compares the stored source FileMD5 against the
MD5 of the current authoritative FBX on disk.

This is a pure byte-read of already-persisted packages. No package is opened
for writing, nothing is resaved, and no Unreal commandlet is launched.

The stored payload is a JSON array of FFileImportData records:
  [{ "RelativeFilename": "...", "Timestamp": "...", "FileMD5": "...",
     "DisplayLabelName": "" }]
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from collections import Counter, defaultdict

CONTENT = r"G:\CARLA\carla_source_probe\Unreal\CarlaUE4\Content"
FBX_DIR = r"G:\CARLA\carla_source_probe\Import\Ingolstadt"
CANON_DIR = os.path.join(CONTENT, "Ingolstadt", "Static", "Terrain",
                         "Ingolstadt")
OUT = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports"

PAYLOAD_RE = re.compile(
    rb'\[\{\s*"RelativeFilename"\s*:\s*"(?P<rel>[^"]*)"\s*,\s*'
    rb'"Timestamp"\s*:\s*"(?P<ts>[^"]*)"\s*,\s*'
    rb'"FileMD5"\s*:\s*"(?P<md5>[^"]*)"')
ASCII_RE = re.compile(rb"[\x20-\x7E]{8,}")
TILE_RE = re.compile(r"Ingolstadt_Tile_(?P<x>\d+)_(?P<y>\d+)")
FBX_NAME_RE = re.compile(r"(Ingolstadt_Tile_\d+_\d+)\.fbx$", re.IGNORECASE)

HAS, ABSENT, INVALID, MULTI = "HAS_IMPORTDATA", "NO_IMPORTDATA", \
    "INVALID_IMPORTDATA", "MULTIPLE_SOURCE_FILES"


def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    fbx_md5 = {}
    for name in os.listdir(FBX_DIR):
        m = FBX_NAME_RE.search(name)
        if m:
            fbx_md5[m.group(1)] = md5_file(os.path.join(FBX_DIR, name))

    rows = []
    stats = Counter()
    hash_avail = hash_match = hash_mismatch = 0
    unknown_source_tile = 0
    tile_bindings = defaultdict(set)
    binding_dupes = 0

    for name in sorted(os.listdir(CANON_DIR)):
        if not name.lower().endswith(".uasset"):
            continue
        path = os.path.join(CANON_DIR, name)
        with open(path, "rb") as fh:
            blob = fh.read()

        obj = os.path.splitext(name)[0]
        tm = TILE_RE.search(obj)
        tile = ("%s_%s" % (tm.group("x"), tm.group("y")) if tm else None)

        matches = PAYLOAD_RE.findall(blob)
        if not matches:
            # fall back to a looser scan so absence is evidence, not a regex miss
            has_marker = b"AssetImportData" in blob
            cls = (INVALID if has_marker else ABSENT)
            stats[cls] += 1
            rows.append({"canonical_asset": obj, "tile": tile,
                         "classification": cls,
                         "source_relative_filename": "",
                         "source_basename": "", "stored_md5": "",
                         "current_fbx_md5": "", "md5_match": "",
                         "stored_timestamp": "", "source_file_count": 0})
            continue

        recs = []
        for rel, ts, md5 in matches:
            rel_s = rel.decode("utf-8", "replace")
            mb = FBX_NAME_RE.search(rel_s.replace("\\", "/"))
            recs.append({"rel": rel_s, "basename": mb.group(1) if mb else None,
                         "ts": ts.decode(), "md5": md5.decode().lower()})
        # de-duplicate identical repeated records
        uniq = {(r["basename"], r["md5"]) for r in recs}
        if len(uniq) > 1:
            stats[MULTI] += 1
        else:
            stats[HAS] += 1

        rec = recs[0]
        cur = fbx_md5.get(rec["basename"] or "")
        if rec["md5"] and cur:
            hash_avail += 1
            if rec["md5"] == cur:
                hash_match += 1
            else:
                hash_mismatch += 1
        if rec["basename"] is None or rec["basename"] not in fbx_md5:
            unknown_source_tile += 1
        else:
            tile_bindings[rec["basename"]].add(obj)
        rows.append({
            "canonical_asset": obj, "tile": tile,
            "classification": HAS if len(uniq) == 1 else MULTI,
            "source_relative_filename": rec["rel"],
            "source_basename": rec["basename"] or "",
            "stored_md5": rec["md5"], "current_fbx_md5": cur or "",
            "md5_match": ("" if not cur else str(rec["md5"] == cur)),
            "stored_timestamp": rec["ts"],
            "source_file_count": len(uniq),
        })

    for fbx, assets in tile_bindings.items():
        if len(assets) != len(set(assets)):
            binding_dupes += 1

    total = len(rows)
    with open(os.path.join(OUT, "STATICMESH_ASSETIMPORTDATA_RAW.csv"), "w",
              newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    coverage = ("FULL" if stats[HAS] + stats[MULTI] == total and total
                else "PARTIAL" if stats[HAS] + stats[MULTI] else "NONE")
    if hash_avail == 0:
        match_class = "HASH_NOT_AVAILABLE"
    elif hash_mismatch == 0:
        match_class = "EXACT"
    elif hash_match > 0:
        match_class = "PARTIAL_EXACT"
    else:
        match_class = "MISMATCH"

    result = {
        "schema": "STATICMESH_ASSETIMPORTDATA_AUDIT/v1",
        "method": "read-only byte scan of persisted .uasset packages; "
                  "no package opened for writing, nothing resaved",
        "ASSET_IMPORTDATA_TOTAL": total,
        "ASSET_IMPORTDATA_PRESENT": stats[HAS] + stats[MULTI],
        "ASSET_IMPORTDATA_ABSENT": stats[ABSENT],
        "ASSET_IMPORTDATA_INVALID": stats[INVALID],
        "ASSET_IMPORTDATA_MULTIPLE_SOURCE_FILES": stats[MULTI],
        "ASSET_IMPORTDATA_COVERAGE": coverage,
        "ASSET_IMPORTDATA_HASH_AVAILABLE_COUNT": hash_avail,
        "ASSET_IMPORTDATA_HASH_MATCH_COUNT": hash_match,
        "ASSET_IMPORTDATA_HASH_MISMATCH_COUNT": hash_mismatch,
        "ASSET_IMPORTDATA_SOURCE_HASH_MATCH": match_class,
        "UNKNOWN_SOURCE_TILE_ASSETS": unknown_source_tile,
        "DUPLICATE_SOURCE_BINDINGS": binding_dupes,
        "distinct_source_fbx_referenced": len(tile_bindings),
        "per_source_fbx_asset_counts": {k: len(v) for k, v
                                        in sorted(tile_bindings.items())},
    }
    with open(os.path.join(OUT, "STATICMESH_ASSETIMPORTDATA_AUDIT.json"),
              "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
