"""V103-O1 — real-map directional coverage over the pinned Ingolstadt inputs.

Verifies the Git-LFS-resolved OSM/XODR bytes against the pinned manifests
(a Git-LFS pointer is NOT acceptable input), then runs the production
correspondence chain and emits the directional coverage report.

Every step that cannot be satisfied is reported as BLOCKED_INPUT; nothing is
invented and no value is substituted.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import xml.etree.ElementTree as ET

from safe_xml import safe_parse
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SRC = Path(
    "campaigns/ingolstadt_cooked_perception_v1/source"
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    out: dict = {
        "schema": "v103_o1_realmap_coverage/v1",
        "repo_root": str(REPO),
        "inputs": {},
        "status": "NOT_RUN",
    }

    manifest_path = REPO / SRC / "INPUTS_MANIFEST.json"
    if not manifest_path.is_file():
        out["status"] = "BLOCKED_INPUT"
        out["reason"] = "INPUTS_MANIFEST.json missing"
        print(json.dumps(out, indent=2))
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # --- verify the pinned OSM bytes -------------------------------------
    osm_entry = manifest["inputs"]["roads_osm"]
    osm_path = REPO / osm_entry["path"]
    if not osm_path.is_file():
        out["status"] = "BLOCKED_INPUT"
        out["reason"] = "pinned OSM missing (LFS object not resolved)"
        print(json.dumps(out, indent=2))
        return 1
    osm_bytes = osm_path.stat().st_size
    osm_sha = sha256_file(osm_path)
    head = osm_path.open("rb").read(64)
    is_pointer = head.startswith(b"version https://git-lfs.github.com/spec")
    out["inputs"]["roads_osm"] = {
        "path": osm_entry["path"],
        "expected_sha256": osm_entry["sha256"],
        "actual_sha256": osm_sha,
        "expected_bytes": osm_entry["bytes"],
        "actual_bytes": osm_bytes,
        "sha256_match": osm_sha == osm_entry["sha256"],
        "bytes_match": osm_bytes == osm_entry["bytes"],
        "is_git_lfs_pointer": is_pointer,
    }
    if is_pointer:
        out["status"] = "BLOCKED_INPUT"
        out["reason"] = "OSM is still a Git-LFS pointer, not map bytes"
        print(json.dumps(out, indent=2))
        return 1
    if osm_sha != osm_entry["sha256"]:
        out["status"] = "BLOCKED_INPUT"
        out["reason"] = "OSM SHA-256 does not match the pinned manifest"
        print(json.dumps(out, indent=2))
        return 1

    # --- verify the manual XODR -----------------------------------------
    manual_manifest_path = REPO / SRC / "manual" / "MANUAL_MANIFEST.json"
    xodr_rel = "campaigns/ingolstadt_cooked_perception_v1/source/manual/Grid0828.xodr"
    xodr_path = REPO / xodr_rel
    xodr_info = {"path": xodr_rel, "present": xodr_path.is_file()}
    if manual_manifest_path.is_file():
        mm = json.loads(manual_manifest_path.read_text(encoding="utf-8"))
        for key in ("xodr", "manual_xodr", "map"):
            entry = mm.get(key) or mm.get("inputs", {}).get(key)
            if isinstance(entry, dict) and entry.get("sha256"):
                xodr_info["expected_sha256"] = entry["sha256"]
                break
    if xodr_path.is_file():
        xodr_info["actual_sha256"] = sha256_file(xodr_path)
        xodr_info["actual_bytes"] = xodr_path.stat().st_size
        if xodr_info.get("expected_sha256"):
            xodr_info["sha256_match"] = (
                xodr_info["actual_sha256"] == xodr_info["expected_sha256"]
            )
        head = xodr_path.open("rb").read(64)
        xodr_info["is_git_lfs_pointer"] = head.startswith(
            b"version https://git-lfs.github.com/spec"
        )
    out["inputs"]["manual_xodr"] = xodr_info

    if not xodr_path.is_file():
        out["status"] = "BLOCKED_INPUT"
        out["reason"] = "manual XODR missing (LFS object not resolved)"
        print(json.dumps(out, indent=2))
        return 1

    # --- run the production correspondence chain ------------------------
    sys.path.insert(0, str(REPO))
    from ultimate_pipeline.enrichment.osm_direction import (
        directional_coverage_report,
    )
    from ultimate_pipeline.pipeline_stages.stage_07_lanes import (
        _build_structural_osm_metadata,
    )

    # V104 security finding: parse through the safe XML boundary
    # (rejects a DOCTYPE/ENTITY declaration in any encoding).
    root = safe_parse(str(xodr_path))
    road_count = len(root.findall("./road"))

    meta, report = _build_structural_osm_metadata(root, str(osm_path))

    out["correspondence_report"] = report
    out["xodr_road_count"] = road_count
    out["structural_osm_meta_roads"] = len(meta)
    out["directional_coverage"] = report.get("directional_coverage")
    out["source_sha256"] = osm_sha

    coverage = out["directional_coverage"] or {}
    out["status"] = coverage.get("status", "NOT_RUN")
    out["reason"] = coverage.get("reason", "")

    # Per-road orientation breakdown (bounded, deterministic).
    from ultimate_pipeline.enrichment.osm_direction import DIRECTION_KEY

    breakdown = {}
    for road_id, tags in sorted(meta.items()):
        orientation = str(tags.get(DIRECTION_KEY) or "unknown")
        breakdown[orientation] = breakdown.get(orientation, 0) + 1
    out["orientation_breakdown"] = breakdown

    target = REPO / "reports/v103/o1/OSM_XODR_DIRECTION_COVERAGE_REALMAP.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2, sort_keys=True)[:4000])
    print("...")
    print("WROTE", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
