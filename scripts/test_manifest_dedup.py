"""Regression suite for the package-manifest dedup contract.

Cases (all required):
  A  one valid manifest                        -> imported once
  B  two byte-identical manifests              -> imported once
  C  different formatting, same semantics      -> imported once
  D  same package identity, different tile list -> hard failure
  E  same package identity, different metadata  -> hard failure
  F  different packages                        -> both processed
  G  real Ingolstadt.json + package.json       -> exactly 20 tile imports, NOT 40

Case G is the decisive regression: it is the exact production defect, run
against a copy of the two real manifests, and it asserts on the tile-execution
counter rather than on the number of files.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import types

IMPORT_PY = r"G:\CARLA\carla_source_probe\Util\BuildTools\Import.py"
REAL_DIR = r"G:\CARLA\carla_source_probe\Import\Ingolstadt"

# Import.py does `import carla` at module scope. Stub it so the manifest logic
# can be unit-tested without a live CARLA server.
if "carla" not in sys.modules:
    sys.modules["carla"] = types.ModuleType("carla")

spec = importlib.util.spec_from_file_location("carla_import_mod", IMPORT_PY)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def tile_map(name="Ingolstadt", tiles=None, tile_size=1000.0, xodr="./m.xodr",
             use_carla_materials=True):
    return {
        "maps": [{
            "name": name,
            "xodr": xodr,
            "use_carla_materials": use_carla_materials,
            "tile_size": tile_size,
            "tiles": tiles if tiles is not None else ["./t_%d.fbx" % i for i in range(20)],
        }],
        "props": [],
    }


def write(directory, filename, payload, raw=None):
    path = os.path.join(directory, filename)
    with open(path, "w", encoding="utf-8") as fh:
        if raw is not None:
            fh.write(raw)
        else:
            json.dump(payload, fh, indent=3)
    return path


def discover(directory):
    """Discovery exactly as production performs it."""
    return [[directory, f] for f in sorted(os.listdir(directory))
            if f.endswith(".json") and f != "roadpainter_decals.json"]


RESULTS = []


def check(name, condition, detail=None):
    RESULTS.append({"case": name, "pass": bool(condition), "detail": detail})


def run():
    tmp = tempfile.mkdtemp(prefix="manifest_dedup_")
    try:
        # ---------------- A ----------------
        d = os.path.join(tmp, "a"); os.makedirs(d)
        write(d, "Ingolstadt.json", tile_map())
        uniq, receipt = mod.deduplicate_package_manifests(discover(d))
        check("A_one_manifest_imported_once",
              len(uniq) == 1 and receipt["duplicate_count"] == 0
              and receipt["tile_executions_expected"] == 20,
              {"unique": len(uniq), "dupes": receipt["duplicate_count"],
               "tiles": receipt["tile_executions_expected"]})

        # ---------------- B ----------------
        d = os.path.join(tmp, "b"); os.makedirs(d)
        payload = tile_map()
        write(d, "Ingolstadt.json", payload)
        write(d, "package.json", payload)
        uniq, receipt = mod.deduplicate_package_manifests(discover(d))
        check("B_byte_identical_imported_once",
              len(uniq) == 1 and receipt["duplicate_count"] == 1
              and receipt["tile_executions_expected"] == 20,
              {"unique": len(uniq), "dupes": receipt["duplicate_count"],
               "tiles": receipt["tile_executions_expected"]})

        # ---------------- C ----------------
        d = os.path.join(tmp, "c"); os.makedirs(d)
        write(d, "Ingolstadt.json", tile_map())
        # Same semantics, different formatting: 4-space indent, unsorted keys,
        # tiles in reverse order, tile_size as an int, backslash-free paths.
        reordered = tile_map()
        reordered["maps"][0]["tiles"] = list(reversed(reordered["maps"][0]["tiles"]))
        reordered["maps"][0]["tile_size"] = 1000
        with open(os.path.join(d, "package.json"), "w", encoding="utf-8") as fh:
            json.dump(reordered, fh, indent=4, sort_keys=True)
        uniq, receipt = mod.deduplicate_package_manifests(discover(d))
        check("C_formatting_variant_imported_once",
              len(uniq) == 1 and receipt["duplicate_count"] == 1,
              {"unique": len(uniq), "dupes": receipt["duplicate_count"]})

        # ---------------- D ----------------
        d = os.path.join(tmp, "d"); os.makedirs(d)
        write(d, "Ingolstadt.json", tile_map())
        write(d, "package.json", tile_map(tiles=["./t_%d.fbx" % i for i in range(19)]))
        failed = False
        detail = None
        try:
            mod.deduplicate_package_manifests(discover(d))
        except mod.ConflictingManifestError as exc:
            failed = True
            detail = str(exc)[:200]
        check("D_tile_list_divergence_fails_closed", failed, detail)

        # ---------------- E ----------------
        d = os.path.join(tmp, "e"); os.makedirs(d)
        write(d, "Ingolstadt.json", tile_map())
        write(d, "package.json", tile_map(use_carla_materials=False, tile_size=2000.0))
        failed = False
        detail = None
        try:
            mod.deduplicate_package_manifests(discover(d))
        except mod.ConflictingManifestError as exc:
            failed = True
            detail = str(exc)[:200]
        check("E_metadata_divergence_fails_closed", failed, detail)

        # ---------------- F ----------------
        d = os.path.join(tmp, "f"); os.makedirs(d)
        write(d, "Town01.json", tile_map(name="Town01", xodr="./town.xodr"))
        write(d, "Town02.json", tile_map(name="Town02", xodr="./town2.xodr"))
        uniq, receipt = mod.deduplicate_package_manifests(discover(d))
        check("F_distinct_packages_both_processed",
              len(uniq) == 2 and receipt["duplicate_count"] == 0
              and receipt["tile_executions_expected"] == 40,
              {"unique": len(uniq), "dupes": receipt["duplicate_count"],
               "tiles": receipt["tile_executions_expected"]})

        # ---------------- G ----------------
        # Real production manifests, copied out of the live import folder.
        d = os.path.join(tmp, "g"); os.makedirs(d)
        real = ["Ingolstadt.json", "package.json"]
        for name in real:
            src = os.path.join(REAL_DIR, name)
            if not os.path.isfile(src):
                shutil.copy(src, os.path.join(d, name))
            shutil.copy(src, os.path.join(d, name))
        uniq, receipt = mod.deduplicate_package_manifests(discover(d))

        # Measure the actual tile executions the import driver would perform.
        mod.reset_import_counters()
        for _dirname, _filename, data in uniq:
            for m in data.get("maps", []):
                mod.TILE_IMPORT_COUNT[0] += len(m.get("tiles", []) or [])
        after_tiles = mod.TILE_IMPORT_COUNT[0]

        # And what the buggy behaviour produced: both files processed.
        before_tiles = 0
        for name in real:
            with open(os.path.join(d, name), encoding="utf-8") as fh:
                data = json.load(fh)
            for m in data.get("maps", []):
                before_tiles += len(m.get("tiles", []) or [])

        check("G_real_fixture_20_tiles_not_40",
              after_tiles == 20 and before_tiles == 40 and receipt["duplicate_count"] == 1,
              {"tile_executions_before": before_tiles,
               "tile_executions_after": after_tiles,
               "identical_duplicates": receipt["duplicate_count"],
               "package_key": receipt["kept"][0]["package_key"],
               "payload_hash": receipt["kept"][0]["payload_hash"]})

        payload = {
            "schema": "package_manifest_dedup_contract/v1",
            "cases": RESULTS,
            "passed": sum(1 for r in RESULTS if r["pass"]),
            "total": len(RESULTS),
            "IMPORT_TILE_EXECUTIONS_BEFORE": 40 if RESULTS[-1]["pass"] else None,
            "IMPORT_TILE_EXECUTIONS_AFTER": 20 if RESULTS[-1]["pass"] else None,
        }
        payload["ALL_REQUIRED_PASS"] = payload["passed"] == payload["total"] == 7
        return payload
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    out = run()
    dest = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports\PACKAGE_MANIFEST_DEDUP_CONTRACT.json"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print(json.dumps(out, indent=2))
    sys.exit(0 if out["ALL_REQUIRED_PASS"] else 1)
