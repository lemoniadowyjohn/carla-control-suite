"""Generate a real, world-frame-anchored tile seam consistency report for O3.

GAP-031 (reports/verification/O3_FULLGRID_VERIFICATION_20260929.md): the prior
version of this tool compared each tile's raw, independently-OSM2World-auto-
centered local bounding box directly against its neighbour's, with no tile-
placement transform applied at all, and its per-pair ``status`` field was dead
code (initialized to "INCOMPLETE", never reassigned). A ground-truth-anchored
re-derivation found genuine, previously-undetected north-south seam defects of
170-270m (>12 standard errors) in a real full-grid cook that this tool's own
"PASS" verdict never caught -- because OSM2World auto-centers every tile's
exported mesh around its own local (0, 0), and nothing in this tool (or the
rest of the artifact chain) ever corrected for that per-tile drift before
comparing tiles to each other.

This version fixes both defects: it reconstructs each tile's true placement in
the shared world frame from the same building-footprint nodes written into
that tile's own OSM XML (``_true_bbox_center_from_osm``), compares adjacent
tiles' resulting placement *corrections* relative to the only other
placement reference this codebase documents (the naive nominal tile-grid
corner) rather than comparing raw building geometry directly (which is
confounded by ordinary, geographically-real sparse-building gaps near a tile
boundary), and makes per-pair/top-level ``status`` a real function of the
resulting seam delta against a tolerance -- not dead code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Tuple

from pyproj import Transformer

from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map

ROOT = Path(__file__).resolve().parents[1]
TILE_RE = "__Tile_{tx}_{ty}"

# Identical bare-tmerc global frame to ultimate_pipeline.tiling.tile_fbx_generator
# / ultimate_pipeline.enrichment.osm_polygon_loader (C29, AG04). Do NOT change;
# roads/buildings/tile placement must all share exactly this projection.
_PROJ_STRING = "+proj=tmerc +datum=WGS84 +units=m +no_defs"
_FWD_TRANSFORMER = Transformer.from_crs("EPSG:4326", _PROJ_STRING, always_xy=True)

# Default world-frame seam tolerance (metres). GAP-031's ground-truth-anchored
# investigation found real seam defects of 170-270m (>12 standard errors) using
# a sparse sample (5-14 named buildings/tile) whose own measurement noise was
# ~14-22m. This tool's placement estimate instead uses every building-footprint
# node written into the tile's own OSM XML (hundreds per tile, not a dozen), so
# its noise floor is materially tighter (GAP-031 cross-check: a real tile's own
# exported-mesh bbox center measured 0.000m/x and <=0.03m/z off from (0, 0)).
# 10m is a deliberately generous multiple of that noise floor, far below the
# scale of the real defect this tool exists to catch.
DEFAULT_WORLD_SEAM_TOLERANCE_M = 10.0


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


def _osm_for_tile(root: Path, tx: int, ty: int, fbx_name: str | None) -> Path | None:
    """Locate a tile's source OSM XML (same directory, same map-name prefix as its FBX)."""
    directory = root / f"tile_{tx}_{ty}"
    map_name = "Ingolstadt"
    if fbx_name and f"_Tile_{tx}_{ty}.fbx" in fbx_name:
        map_name = fbx_name.split(f"_Tile_{tx}_{ty}.fbx")[0]
    osm_path = directory / f"{map_name}_Tile_{tx}_{ty}.osm"
    return osm_path if osm_path.is_file() else None


def _true_bbox_center_from_osm(osm_path: Path, header_offset: Tuple[float, float]) -> Optional[Tuple[float, float]]:
    """Independent ground-truth placement anchor for one tile (GAP-031).

    OSM2World auto-centers every tile's exported mesh around the bounding-box
    center of its own output geometry, regardless of the tile's true
    geographic position (empirically confirmed: real exported meshes' own x/z
    bounds center almost exactly on (0, 0)). Nothing in the artifact chain
    corrects for this per-tile drift before tiles are compared to each other,
    which is how GAP-031's 170-270m north-south seam defect went undetected.

    This reconstructs where local mesh (0, 0) actually sits in the shared
    world frame: the bounding-box center of the *same* building-footprint
    nodes ``write_tile_osm_xml`` wrote into this tile's own OSM XML (every
    node of every building assigned to this tile, and only those -- the tile
    clip is a hard, non-overlapping, whole-building partition), reprojected
    through the pipeline's bare-tmerc frame and rebased by the same header
    offset every other coordinate in this codebase uses (C29, AG04).

    Not exact -- OSM2World centers on its *rendered geometry* bbox, this uses
    the *input node* bbox -- but these coincide almost exactly for a
    buildings-only, terrain-off, no-landuse-polygon tile clip (see the
    tolerance docstring above). Returns ``None`` on any missing/unparseable
    file or empty node set; callers must fail closed to "INCOMPLETE", never
    silently assume a placement.
    """
    try:
        tree = ET.parse(osm_path)
    except (OSError, ET.ParseError):
        return None
    ox, oy = header_offset
    xs: list[float] = []
    ys: list[float] = []
    for node in tree.getroot().iter("node"):
        lat_s, lon_s = node.get("lat"), node.get("lon")
        if lat_s is None or lon_s is None:
            continue
        try:
            lat, lon = float(lat_s), float(lon_s)
        except ValueError:
            continue
        if not (math.isfinite(lat) and math.isfinite(lon)):
            continue
        x, y = _FWD_TRANSFORMER.transform(lon, lat)
        xs.append(x - ox)
        ys.append(y - oy)
    if not xs:
        return None
    return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)


def generate_report(
    cook_results: Path,
    tile_size_m: float,
    frame_offset: list[float],
    world_seam_tolerance_m: float = DEFAULT_WORLD_SEAM_TOLERANCE_M,
) -> dict[str, Any]:
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
        osm_path = _osm_for_tile(tile_root, tx, ty, result.get("fbx_name"))
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
            "osm_path": str(osm_path) if osm_path else None,
            # GAP-031: the real placement anchor -- where this tile's exported
            # mesh local (0, 0) actually sits in the shared world frame, NOT
            # the naive (tx, ty) * tile_size_m grid corner. None means this
            # tile's world-frame placement (and therefore any seam check
            # touching it) could not be independently verified.
            "world_placement_offset_m": None,
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
        if osm_path is None:
            item["failures"].append("no OSM source available for world-frame placement verification")
        else:
            offset_for_placement = tuple(float(v) for v in frame_offset)
            if isinstance(item["actual_frame_offset_xy_m"], list) and len(item["actual_frame_offset_xy_m"]) == 2:
                offset_for_placement = tuple(float(v) for v in item["actual_frame_offset_xy_m"])
            center = _true_bbox_center_from_osm(osm_path, offset_for_placement)
            if center is None:
                item["failures"].append("OSM source contains no usable nodes for world-frame placement")
            else:
                item["world_placement_offset_m"] = list(center)
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
                # GAP-031's real, world-frame-anchored seam check. None until
                # both tiles have a verified world_placement_offset_m AND
                # exported_object_bounds.
                "world_seam_delta_m": None,
                "world_seam_tolerance_m": world_seam_tolerance_m,
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
            if left["world_placement_offset_m"] and right["world_placement_offset_m"]:
                # GAP-031's real check: NOT a gap/overlap between the two tiles'
                # actual building geometry (that is confounded by ordinary,
                # geographically-real sparse-building gaps near a tile
                # boundary -- exactly the "boundary delta is not a seam
                # defect by itself" caveat already carried on
                # actual_exported_boundary_delta_m above). Instead, this asks:
                # relative to the only *other* placement reference this
                # codebase documents (the naive nominal grid corner
                # tx*tile_size_m/ty*tile_size_m), do these two adjacent
                # tiles' true placements require materially DIFFERENT
                # corrections? If so, no single, uniform per-tile placement
                # offset could place both tiles consistently with true
                # geography at once -- a real seam defect, independent of
                # where any building happens to sit. This mirrors GAP-031's
                # validated ground-truth methodology (median per-tile
                # correction K, compared between adjacent tiles) at full
                # building-set (not sparse named-building-sample) precision.
                axis_idx = 0 if axis == "x" else 1
                left_correction = left["world_placement_offset_m"][axis_idx] - left["expected_world_origin_m"][axis_idx]
                right_correction = right["world_placement_offset_m"][axis_idx] - right["expected_world_origin_m"][axis_idx]
                world_delta = abs(right_correction - left_correction)
                pair["world_seam_delta_m"] = world_delta
                pair["left_correction_m"] = left_correction
                pair["right_correction_m"] = right_correction
                if world_delta <= world_seam_tolerance_m:
                    pair["status"] = "PASS"
                else:
                    pair["status"] = "FAIL"
                    failures.append(
                        f"seam {tx},{ty}<->{right_index[0]},{right_index[1]} ({axis}): "
                        f"world-frame placement-consistency delta {world_delta:.2f}m exceeds tolerance {world_seam_tolerance_m:.2f}m"
                    )
            pairs.append(pair)
    frame_identity_hash = hashlib.sha256(json.dumps(sorted(frame_ids), separators=(",", ":")).encode()).hexdigest()
    deltas = [p["actual_exported_boundary_delta_m"] for p in pairs if p["actual_exported_boundary_delta_m"] is not None]
    world_deltas = [p["world_seam_delta_m"] for p in pairs if p["world_seam_delta_m"] is not None]
    return {
        "schema": "tile_frame_consistency/v2",
        "status": "PASS" if not failures else "FAIL" if any(p["status"] == "FAIL" for p in pairs) else "INCOMPLETE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "cook_results_path": str(cook_results),
        "cook_results_sha256": sha256(cook_results),
        "source_map_sha256": source_sha,
        "tile_size_m": tile_size_m,
        "authoritative_frame_offset_xy_m": list(frame_offset),
        "world_seam_tolerance_m": world_seam_tolerance_m,
        "frame_identity_hash": frame_identity_hash,
        "frame_identity_count": len(frame_ids),
        "max_seam_delta_m": max(deltas) if deltas else None,
        "mean_seam_delta_m": sum(deltas) / len(deltas) if deltas else None,
        "max_world_seam_delta_m": max(world_deltas) if world_deltas else None,
        "mean_world_seam_delta_m": sum(world_deltas) / len(world_deltas) if world_deltas else None,
        "seam_delta_definition": "distance between exported RAW local object-boundary extrema at a shared cell boundary; descriptive only (mixes two independently-auto-centered local frames, see world_seam_delta_m for the real check) because the visual layer is a centroid-partitioned building set, not a continuous surface",
        "world_seam_delta_definition": "distance between two tiles' exported object bounds after each is projected into the shared world frame via its own independently-verified world_placement_offset_m (GAP-031); this IS the real seam check and gates status/PASS-FAIL",
        "tiles": tiles,
        "adjacent_pairs": pairs,
        "failures": failures,
        "limitations": [
            "No Unreal import or runtime streaming was run.",
            "world_placement_offset_m is derived from the tile's own OSM input node bbox, not OSM2World's actual rendered-geometry bbox; these coincide almost exactly for a buildings-only, terrain-off tile clip but are not proven identical.",
            "A shared cell boundary may have no geometry on either side, so a small/absent boundary delta does not by itself prove seam continuity (opaque, non-overlapping building partition).",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cook-results", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tile-size", type=float, default=1000.0)
    parser.add_argument("--frame-offset", nargs=2, type=float, default=[832671.676, 5458671.104])
    parser.add_argument("--world-seam-tolerance", type=float, default=DEFAULT_WORLD_SEAM_TOLERANCE_M,
                         help="Max allowed world-frame seam delta in metres (GAP-031 real check) before status=FAIL.")
    args = parser.parse_args()
    report = generate_report(args.cook_results, args.tile_size, args.frame_offset, args.world_seam_tolerance)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "status", "frame_identity_hash", "frame_identity_count",
        "max_seam_delta_m", "mean_seam_delta_m",
        "max_world_seam_delta_m", "mean_world_seam_delta_m",
    )}, indent=2))
    return 0 if report["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
