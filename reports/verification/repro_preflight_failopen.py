"""
Reproduction: tools/preflight_import_package.py aggregation silently ignores
a FAIL from audit_large_map_package_contract() (O2), because the aggregator
only checks for status == "BLOCKED" / "INCOMPLETE", while the contract audit
returns "PASS" / "FAIL". A structural violation the O2 audit was built to
catch (per-tile XODR leak / duplicated road authority) is displayed in the
JSON but does NOT change the overall verdict or exit code.

Run:  python reports/verification/repro_preflight_failopen.py
Expected (bug present): prints "BUG CONFIRMED: overall=READY exit_code=0"
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

import preflight_import_package as pf  # noqa: E402

WORKDIR = Path(__file__).resolve().parent / "_repro_pkg"


def build_package(workdir: Path) -> str:
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)

    xodr = workdir / "Ingolstadt.xodr"
    xodr.write_text(
        "<OpenDRIVE><header revMajor='1' revMinor='4'>"
        "<offset x='832671.676' y='5458671.104' z='0' hdg='0'/>"
        "</header></OpenDRIVE>"
    )
    xodr_sha = hashlib.sha256(xodr.read_bytes()).hexdigest()

    # Contract violation: a second, per-tile XODR sitting in the package dir.
    # This is exactly invariant #1/#7 that O2's audit_large_map_package_contract()
    # exists to catch ("exactly one authoritative .xodr, no per-tile XODR leak").
    (workdir / "Ingolstadt_Tile_0_0.xodr").write_text("<OpenDRIVE></OpenDRIVE>")

    tile_name = "Ingolstadt_Tile_0_0.fbx"
    (workdir / tile_name).write_bytes(b"FAKE FBX DATA")

    doc = {
        "maps": [{
            "name": "Ingolstadt",
            "xodr": "./Ingolstadt.xodr",
            "use_carla_materials": True,
            "tile_size": 1000.0,
            "tiles": [f"./{tile_name}"],
        }],
        "props": [],
    }
    (workdir / "package.json").write_text(json.dumps(doc))
    (workdir / "Ingolstadt.large_map_package.json").write_text(json.dumps({
        "xodr": {"filename": "Ingolstadt.xodr", "sha256": xodr_sha},
        "tiles_provenance": {tile_name: xodr_sha},
    }))
    return xodr_sha


def main() -> int:
    xodr_sha = build_package(WORKDIR)
    result = pf.preflight_package(
        str(WORKDIR), expected_tile_size_m=1000.0, min_free_gib=0.001,
        expected_xodr_sha=xodr_sha,
    )
    audit_check = next(c for c in result["checks"] if c["check"] == "audit_contract")
    print("audit_contract check:", audit_check["status"], audit_check["failures"])
    print("overall status:", result["status"], "claim:", result["claim"])
    if audit_check["status"] == "FAIL" and result["status"] == "READY":
        print(f"BUG CONFIRMED: overall=READY exit_code=0 despite audit_contract=FAIL "
              f"({audit_check['failures']})")
        return 0
    print("bug not reproduced in this run (aggregation may have been fixed)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
