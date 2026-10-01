#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DEPRECATED / STALE — DO NOT USE ON C29+ MAPS.

This script was C29 remediation option (b) for pre-C29 pinned XODR whose building
`cornerGlobal` points were written in the pre-fix projection origin. The CURRENT
pinned map (auto_map_of_record, sha256=370abbbb...) is ALREADY C29-corrected:
building `cornerGlobal` is in the rebased local frame. Running this script on the
current pin would CORRUPT it by applying a double-correction.

Retained only for historical superseded map reference. Any invocation on a C29+
map is an error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import warnings
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ultimate_pipeline.domain_gap.local_registration import (
    building_frame_shift_to_auto_local,
    read_georef_proj4,
)

# Emit deprecation warning on import
warnings.warn(
    "patch_pinned_building_frame.py is DEPRECATED and STALE for C29+ maps. "
    "The current pinned map is already C29-corrected; this script would double-shift.",
    DeprecationWarning,
    stacklevel=2
)


def patch_building_corner_global(root: ET.Element, dx: float, dy: float) -> int:
    """Shift every building object's `cornerGlobal` x/y by (dx, dy) in place. Returns the
    number of corner points patched. z is untouched; non-building objects are untouched."""
    count = 0
    for obj in root.findall(".//object[@type='building']"):
        for corner in obj.findall("outline/cornerGlobal"):
            x = float(corner.get("x", "0"))
            y = float(corner.get("y", "0"))
            corner.set("x", f"{x + dx:.6f}")
            corner.set("y", f"{y + dy:.6f}")
            count += 1
    return count


def compute_shift_for_pinned_map(
    root: ET.Element, *, osm_lat_min: float, osm_lon_min: float
) -> Tuple[float, float]:
    """(dx, dy) correction for THIS file's own header offset + geoReference."""
    header = root.find(".//header")
    if header is None:
        raise RuntimeError("patch: no <header> in XODR")
    offset = header.find("offset")
    if offset is None:
        raise RuntimeError("patch: no <header><offset> in XODR")
    ox = float(offset.get("x", "0"))
    oy = float(offset.get("y", "0"))
    auto_proj4 = read_georef_proj4(root)
    return building_frame_shift_to_auto_local(
        osm_lat_min=osm_lat_min,
        osm_lon_min=osm_lon_min,
        auto_proj4=auto_proj4,
        auto_offset=(ox, oy),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 16):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_xodr", type=Path)
    parser.add_argument("output_xodr", type=Path)
    args = parser.parse_args()

    from ultimate_pipeline.config.settings import SETTINGS

    gps = SETTINGS.load_gps_bounds()

    print(f"[PATCH] parsing {args.input_xodr} ...")
    tree = ET.parse(args.input_xodr)
    root = tree.getroot()

    dx, dy = compute_shift_for_pinned_map(
        root, osm_lat_min=gps["lat_min"], osm_lon_min=gps["lon_min"]
    )
    print(f"[PATCH] computed shift: dx={dx:.3f} dy={dy:.3f}")

    n = patch_building_corner_global(root, dx, dy)
    print(f"[PATCH] patched {n} cornerGlobal points")
    if n == 0:
        raise RuntimeError("patch: 0 building cornerGlobal points patched — refusing to write an unchanged file")

    args.output_xodr.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(args.output_xodr), encoding="utf-8", xml_declaration=True)

    report: Dict[str, Any] = {
        "input_xodr": str(args.input_xodr),
        "output_xodr": str(args.output_xodr),
        "input_sha256": _sha256_file(args.input_xodr),
        "output_sha256": _sha256_file(args.output_xodr),
        "shift_dx": dx,
        "shift_dy": dy,
        "corners_patched": n,
        "gps_lat_min_used": gps["lat_min"],
        "gps_lon_min_used": gps["lon_min"],
        "note": (
            "Surgical patch (C29 remediation option b). Only .//object[@type='building']"
            "/outline/cornerGlobal x/y changed; z, roads, lanes, signals, elevation "
            "untouched. NOT an automatic re-pin -- promoting this output to the map-of-"
            "record pointer is a separate, explicit decision."
        ),
    }
    report_path = args.output_xodr.with_suffix(".patch_report.json")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[PATCH] wrote {args.output_xodr}")
    print(f"[PATCH] wrote {report_path}")
    print(f"[PATCH] input_sha256={report['input_sha256']}")
    print(f"[PATCH] output_sha256={report['output_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
