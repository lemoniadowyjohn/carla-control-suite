"""RQ1 OSM pointer repair: Phases 3-6.

Read-only verification plus a process-scoped environment override. No repo
file is modified: settings.py, INPUTS_MANIFEST.json and every pinned config
are left byte-identical. ENABLE_OSM_DOWNLOAD is deliberately NOT disabled.
"""
from __future__ import annotations

import hashlib
import json
import os

REPO = r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"
GOVERNED_REL = ("campaigns/ingolstadt_cooked_perception_v1/source/"
                "ingolstadt_authoritative.osm")
GOVERNED = os.path.join(REPO, *GOVERNED_REL.split("/"))
MANIFEST = os.path.join(REPO, "campaigns", "ingolstadt_cooked_perception_v1",
                        "source", "INPUTS_MANIFEST.json")
EXPECT_SHA = "b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f"
EXPECT_BYTES = 11154738


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    # ---- Phase 3: revalidate governed OSM -----------------------------
    exists = os.path.isfile(GOVERNED)
    size = os.path.getsize(GOVERNED) if exists else 0
    got = sha256(GOVERNED) if exists else ""
    hash_match = (got.lower() == EXPECT_SHA and size == EXPECT_BYTES)

    with open(MANIFEST, encoding="utf-8") as fh:
        man = json.load(fh)
    entry = man["inputs"]["roads_osm"]
    man_match = (entry["sha256"].lower() == got.lower()
                 and entry["bytes"] == size and entry["status"] == "pinned")

    if not hash_match:
        print("GOVERNED_OSM_HASH_MATCH=false -- STOP")
        return 1

    # ---- Phase 4: reversible env pin ----------------------------------
    before = os.environ.get("UP_OSM_FILE")
    os.environ["UP_OSM_FILE"] = GOVERNED
    after = os.environ.get("UP_OSM_FILE")

    # ---- Phase 5: prove effective settings WITHOUT running RQ1 -------
    import sys
    sys.path.insert(0, REPO)
    for mod in [m for m in list(sys.modules)
                if m.startswith("ultimate_pipeline")]:
        del sys.modules[mod]
    from ultimate_pipeline.config import settings as cfg
    S = cfg.SETTINGS
    eff = str(S.OSM_FILE)
    eff_match = os.path.normcase(os.path.abspath(eff)) == \
        os.path.normcase(os.path.abspath(GOVERNED))
    eff_exists = os.path.exists(eff)

    out = {
        "schema": "RQ1_OSM_POINTER_REPAIR/v1",
        "OSM_FILE_CONFIG_SOURCE": "ultimate_pipeline/config/settings.py",
        "OSM_FILE_CONFIGURED_PATH_WITHOUT_PIN":
            os.path.join(REPO, "cities", "ingolstadt", "osm",
                         "ingolstadt.osm"),
        "CONFIGURED_PATH_EXISTS_WITHOUT_PIN": os.path.exists(
            os.path.join(REPO, "cities", "ingolstadt", "osm",
                         "ingolstadt.osm")),
        "GOVERNED_OSM_PATH": GOVERNED,
        "GOVERNED_OSM_RELATIVE": GOVERNED_REL,
        "GOVERNED_OSM_SIZE": size,
        "GOVERNED_OSM_SHA256": got,
        "GOVERNED_OSM_HASH_MATCH": hash_match,
        "INPUTS_MANIFEST_STILL_PINS_SAME": man_match,
        "manifest_entry": entry,
        "UP_OSM_FILE_BEFORE": before,
        "UP_OSM_FILE_AFTER": after,
        "OSM_CONFIG_REPAIR_METHOD": "ENV_OVERRIDE",
        "OSM_CONFIG_REPAIR_SCOPE":
            "process-local environment of this diagnostic session only; it is "
            "not exported to the OS, not persisted, and does not affect any "
            "other process or session",
        "CONFIG_CHANGED": False,
        "files_modified": [],
        "settings_py_modified": False,
        "inputs_manifest_modified": False,
        "EFFECTIVE_OSM_FILE": eff,
        "EFFECTIVE_OSM_FILE_MATCH": eff_match,
        "EFFECTIVE_OSM_FILE_EXISTS": eff_exists,
        "ENABLE_OSM_DOWNLOAD": getattr(S, "ENABLE_OSM_DOWNLOAD", None),
        "AUTO_DOWNLOAD_OSM": getattr(S, "AUTO_DOWNLOAD_OSM", None),
        "gate_weakening":
            "NONE. ENABLE_OSM_DOWNLOAD remains True. The repair removes the "
            "need for the remote fallback by making the governed local path "
            "resolve, rather than suppressing the fallback.",
        "EXTERNAL_ACQUISITION_REQUIRED": False,
    }
    path = os.path.join(REPO, "reports", "RQ1_OSM_POINTER_REPAIR.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)

    print("GOVERNED_OSM_HASH_MATCH =", hash_match)
    print("manifest still pins same =", man_match)
    print("UP_OSM_FILE_BEFORE =", before)
    print("UP_OSM_FILE_AFTER  =", after)
    print("EFFECTIVE_OSM_FILE =", eff)
    print("EFFECTIVE_OSM_FILE_MATCH =", eff_match)
    print("EFFECTIVE exists =", eff_exists)
    print("ENABLE_OSM_DOWNLOAD =", getattr(S, "ENABLE_OSM_DOWNLOAD", None))
    print("CONFIG_CHANGED = False (no file edited)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
