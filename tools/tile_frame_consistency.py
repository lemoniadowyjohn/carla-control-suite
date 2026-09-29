"""Generate an evidence-only tile frame consistency report for O3."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map

ROOT = Path(__file__).resolve().parents[1]
TILE_RE = "__Tile_{tx}_{ty}"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _bounds_from_roundtrip(path: Path) -> dict[str, list[float]] | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    points = []
    for obj in doc.get("objects", []):
        for p in obj.get("bounds", []):
            if isinstance(p, list) and len(p) >= 3:
                try:
                    points.append([float(p[0]), float(p[1]), float(p[2])])
                except (TypeError, ValueError):
                    pass
    if not points:
        return None
    return {
        "min": [min(p[i] for p in points) for i in range(3)],
        "max": [max(p[i] for p in points) for i in range(3)],
    }


def _manifest_for_tile(root: Path, tx: int, ty: int) -> tuple[Path | None, Path | None, Path | None]:
    directory = root / f"tile_{tx}_{ty}"
    tile = directory / f"Ingolstadt_Tile_{tx}_{ty}.fbx"
    manifest = directory / f"Ingolstadt_Tile_{tx}_{ty}.tile_fbx.json"
    roundtrip = directory / "fbx_roundtrip_manifest.json"
    return (tile if tile.is_file() else None, manifest if manifest.is_file() else None, roundtrip if roundtrip.is_file() else None)


def generate_report(cook_results: Path, tile_size_m: float, frame_offset: list[float]) -> dict[str, Any]:
    try:
        cook = json.loads(cook_results.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"schema": "tile_frame_consistency/v1", "status": "INCOMPLETE", "failures": [f"cannot read COOK_RESULTS.json: {exc}"], "tiles": [], "adjacent_pairs": []}
    source_sha = ((cook.get("source_provenance") or {}).get("map_of_record_sha256") or "").lower()
    tile_root = cook_results.parent / "artifacts"
    tiles: list[dict[str, Any]] = []
    failures: list[str] = []
    expected_offsets = {tuple(float(v) for v in frame_offset)}
    frame_ids: set[str] = set()
    for result in cook.get("results", []):
        try:
            tx, ty = (int(result["tile_index"][0]), int(result["tile_index"][1]))
        except (KeyError, IndexError, TypeError, ValueError):
            failures.append(f"invalid tile_index: {result!r}")
            continue
        fbx, manifest_path, roundtrip_path = _manifest_for_tile(tile_root, tx, ty)
        item: dict[str, Any] = {
            "tile_index": [tx, ty],
            "tile_name": result.get("fbx_name"),
            "source_bbox_m": {
                "x_min": tx * tile_size_m,
                "x_max": (tx + 1) * tile_size_m,
                "y_min": ty * tile_size_m,
                "y_max": (ty + 1) * tile_size_m,
            },
            "expected_world_origin_m": [tx * tile_size_m, ty * tile_size_m],
            "expected_frame_offset_xy_m": list(frame_offset),
            "actual_frame_offset_xy_m": None,
            "exported_object_bounds": None,
            "fbx_path": str(fbx) if fbx else None,
            "manifest_path": str(manifest_path) if manifest_path else None,
            "roundtrip_manifest_path": str(roundtrip_path) if roundtrip_path else None,
            "source_map_sha256": None,
            "status": "INCOMPLETE",
            "failures": [],
        }
        if manifest_path is None:
            item["failures"].append("missing tile manifest")
        else:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                provenance = manifest.get("source_provenance") or {}
                actual_offset = provenance.get("header_offset_xy")
                item["actual_frame_offset_xy_m"] = actual_offset
                item["source_map_sha256"] = provenance.get("map_of_record_sha256")
                if isinstance(actual_offset, list) and len(actual_offset) == 2:
                    actual = tuple(float(v) for v in actual_offset)
                    frame_ids.add(json.dumps(actual, sort_keys=True, separators=(",", ":")))
                    if actual not in expected_offsets:
                        item["failures"].append(f"frame offset differs from authoritative {frame_offset}: {actual_offset}")
                else:
                    item["failures"].append("manifest missing frame offset")
                if not source_sha or str(provenance.get("map_of_record_sha256", "")).lower() != source_sha:
                    item["failures"].append("tile source SHA differs from COOK_RESULTS source SHA")
            except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                item["failures"].append(f"manifest unreadable: {exc}")
        if roundtrip_path is None:
            item["failures"].append("missing roundtrip manifest with exported object bounds")
        else:
            bounds = _bounds_from_roundtrip(roundtrip_path)
            if bounds is None:
                item["failures"].append("roundtrip manifest contains no object bounds")
            else:
                item["exported_object_bounds"] = bounds
        item["status"] = "PASS" if not item["failures"] else "INCOMPLETE"
        if item["failures"]:
            failures.extend(f"tile {tx},{ty}: {failure}" for failure in item["failures"])
        tiles.append(item)
    by_index = {(item["tile_index"][0], item["tile_index"][1]): item for item in tiles}
    pairs = []
    for (tx, ty), left in sorted(by_index.items()):
        for right_index in ((tx + 1, ty), (tx, ty + 1)):
            right = by_index.get(right_index)
            if right is None:
                continue
            axis = "x" if right_index[0] > tx else "y"
            expected_shared = (tx + 1) * tile_size_m if axis == "x" else (ty + 1) * tile_size_m
            pair = {
                "left_tile": [tx, ty],
                "right_tile": list(right_index),
                "axis": axis,
                "expected_shared_border_m": expected_shared,
                "actual_exported_boundary_delta_m": None,
                "boundary_observed": False,
                "status": "INCOMPLETE",
            }
            if left["exported_object_bounds"] and right["exported_object_bounds"]:
                lb = left["exported_object_bounds"]
                rb = right["exported_object_bounds"]
                if axis == "x":
                    left_edge = lb["max"][0]
                    right_edge = rb["min"][0]
                else:
                    left_edge = lb["max"][1]
                    right_edge = rb["min"][1]
                pair["actual_exported_boundary_delta_m"] = abs(right_edge - left_edge)
                pair["boundary_observed"] = True
                pair["expected_boundary_relation"] = "opaque building partition; no required geometric continuity at empty cell boundary"
            pairs.append(pair)
    frame_identity_hash = hashlib.sha256(json.dumps(sorted(frame_ids), separators=(",", ":")).encode()).hexdigest()
    deltas = [p["actual_exported_boundary_delta_m"] for p in pairs if p["actual_exported_boundary_delta_m"] is not None]
    return {
        "schema": "tile_frame_consistency/v1",
        "status": "PASS" if not failures else "INCOMPLETE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "cook_results_path": str(cook_results),
        "cook_results_sha256": sha256(cook_results),
        "source_map_sha256": source_sha,
        "tile_size_m": tile_size_m,
        "authoritative_frame_offset_xy_m": list(frame_offset),
        "frame_identity_hash": frame_identity_hash,
        "frame_identity_count": len(frame_ids),
        "max_seam_delta_m": max(deltas) if deltas else None,
        "mean_seam_delta_m": sum(deltas) / len(deltas) if deltas else None,
        "seam_delta_definition": "distance between exported aggregate object-boundary extrema at a shared cell boundary; descriptive only because the visual layer is a centroid-partitioned building set, not a continuous surface",
        "tiles": tiles,
        "adjacent_pairs": pairs,
        "failures": failures,
        "limitations": [
            "No Unreal import or runtime streaming was run.",
            "No tile-local origin reset is accepted; exported object bounds are read from Blender roundtrip manifests.",
            "A shared cell boundary may have no geometry on either side, so boundary delta is not a seam defect by itself.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cook-results", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tile-size", type=float, default=1000.0)
    parser.add_argument("--frame-offset", nargs=2, type=float, default=[832671.676, 5458671.104])
    args = parser.parse_args()
    report = generate_report(args.cook_results, args.tile_size, args.frame_offset)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "frame_identity_hash", "frame_identity_count", "max_seam_delta_m", "mean_seam_delta_m")}, indent=2))
    return 0 if report["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
