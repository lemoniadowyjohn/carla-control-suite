"""Audit the source-building to OpenDRIVE ``cornerGlobal`` frame contract.

This is deliberately a read-only provenance tool.  A population centroid of
roads and buildings is not a frame-alignment metric: those two populations do
not occupy the same parts of a city.  Instead, the audit joins building
footprints by their stable OSM-derived object id, projects the source through
the production building loader, and compares each source centroid to the
corresponding local ``cornerGlobal`` centroid.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import math
import statistics
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ultimate_pipeline.enrichment.osm_polygon_loader import OSMPolygonLoader


DEFAULT_MAX_SYSTEMATIC_OFFSET_M = 1.0
DEFAULT_INDIVIDUAL_OUTLIER_M = 0.01


@dataclass(frozen=True)
class _Centroid:
    x: float
    y: float


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _percentile(values: Iterable[float], percentile: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    index = round((len(ordered) - 1) * percentile)
    return ordered[max(0, min(index, len(ordered) - 1))]


def _centroid(points: list[tuple[float, float]]) -> _Centroid | None:
    if not points:
        return None
    # Closed OpenDRIVE and GeoJSON rings repeat their initial point.  Exclude
    # that duplicate so a centroid is invariant to serialization convention.
    if len(points) > 1 and points[0] == points[-1]:
        points = points[:-1]
    if not points:
        return None
    return _Centroid(
        x=sum(point[0] for point in points) / len(points),
        y=sum(point[1] for point in points) / len(points),
    )


def _header_offset(root: ET.Element) -> tuple[float, float]:
    offset = root.find("header/offset")
    if offset is None:
        raise ValueError("OpenDRIVE header has no offset; cannot establish local building frame")
    try:
        x, y = float(offset.attrib["x"]), float(offset.attrib["y"])
    except (KeyError, ValueError) as exc:
        raise ValueError("OpenDRIVE header offset must contain finite x/y values") from exc
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError("OpenDRIVE header offset must contain finite x/y values")
    return x, y


def _xodr_building_centroids(root: ET.Element) -> tuple[dict[str, _Centroid], list[str]]:
    centroids: dict[str, _Centroid] = {}
    duplicate_ids: list[str] = []
    for obj in root.findall(".//object[@type='building']"):
        object_id = obj.get("id")
        if not object_id:
            continue
        points: list[tuple[float, float]] = []
        for corner in obj.findall("outline/cornerGlobal"):
            try:
                x, y = float(corner.attrib["x"]), float(corner.attrib["y"])
            except (KeyError, ValueError):
                continue
            if math.isfinite(x) and math.isfinite(y):
                points.append((x, y))
        centroid = _centroid(points)
        if centroid is None:
            continue
        if object_id in centroids:
            duplicate_ids.append(object_id)
            continue
        centroids[object_id] = centroid
    return centroids, sorted(duplicate_ids)


def _source_building_centroids(
    buildings_path: Path, offset_x: float, offset_y: float
) -> tuple[dict[str, _Centroid], list[str]]:
    # The loader historically reports a count on stdout.  The audit CLI must
    # remain machine-readable, so capture that legacy diagnostic here.
    with contextlib.redirect_stdout(io.StringIO()):
        buildings = OSMPolygonLoader.load_buildings_from_geojson(str(buildings_path))

    centroids: dict[str, _Centroid] = {}
    duplicate_ids: list[str] = []
    for building in buildings:
        if not building.id:
            continue
        centroid = _centroid(list(building.footprint))
        if centroid is None:
            continue
        local_centroid = _Centroid(centroid.x - offset_x, centroid.y - offset_y)
        if building.id in centroids:
            duplicate_ids.append(building.id)
            continue
        centroids[building.id] = local_centroid
    return centroids, sorted(duplicate_ids)


def audit_building_frame_alignment(
    xodr_path: str | Path,
    buildings_path: str | Path,
    *,
    max_systematic_offset_m: float = DEFAULT_MAX_SYSTEMATIC_OFFSET_M,
    individual_outlier_m: float = DEFAULT_INDIVIDUAL_OUTLIER_M,
) -> dict[str, Any]:
    """Return a deterministic source-to-XODR building-frame audit report.

    ``max_systematic_offset_m`` applies to robust population statistics, not
    the maximum individual error.  Individual OSM footprint changes should be
    reviewed as source-geometry drift; they must not trigger a destructive
    whole-map translation.
    """
    if not math.isfinite(max_systematic_offset_m) or max_systematic_offset_m <= 0:
        raise ValueError("max_systematic_offset_m must be finite and positive")
    if not math.isfinite(individual_outlier_m) or individual_outlier_m <= 0:
        raise ValueError("individual_outlier_m must be finite and positive")

    xodr = Path(xodr_path)
    buildings = Path(buildings_path)
    root = ET.parse(xodr).getroot()
    offset_x, offset_y = _header_offset(root)
    xodr_centroids, duplicate_xodr_ids = _xodr_building_centroids(root)
    source_centroids, duplicate_source_ids = _source_building_centroids(
        buildings, offset_x, offset_y
    )

    common_ids = sorted(set(source_centroids) & set(xodr_centroids))
    source_only_ids = sorted(set(source_centroids) - set(xodr_centroids))
    xodr_only_ids = sorted(set(xodr_centroids) - set(source_centroids))
    comparisons: list[dict[str, Any]] = []
    distances: list[float] = []
    dxs: list[float] = []
    dys: list[float] = []
    for object_id in common_ids:
        source = source_centroids[object_id]
        placed = xodr_centroids[object_id]
        dx, dy = placed.x - source.x, placed.y - source.y
        distance = math.hypot(dx, dy)
        dxs.append(dx)
        dys.append(dy)
        distances.append(distance)
        if distance > individual_outlier_m:
            comparisons.append(
                {
                    "object_id": object_id,
                    "dx_m": round(dx, 6),
                    "dy_m": round(dy, 6),
                    "distance_m": round(distance, 6),
                }
            )
    comparisons.sort(key=lambda entry: (-entry["distance_m"], entry["object_id"]))

    median_dx = statistics.median(dxs) if dxs else None
    median_dy = statistics.median(dys) if dys else None
    robust_offset = math.hypot(median_dx, median_dy) if median_dx is not None and median_dy is not None else None
    p95_distance = _percentile(distances, 0.95)
    status = "INCOMPLETE"
    frame_alignment = "INCOMPLETE"
    if common_ids and not duplicate_source_ids and not duplicate_xodr_ids:
        is_aligned = (
            robust_offset is not None
            and p95_distance is not None
            and robust_offset <= max_systematic_offset_m
            and p95_distance <= max_systematic_offset_m
        )
        status = "PASS" if is_aligned else "FAIL"
        frame_alignment = "PASS" if is_aligned else "FAIL"

    return {
        "schema_version": 1,
        "status": status,
        "frame_alignment": frame_alignment,
        "claim_boundary": (
            "Per-building correspondence establishes the shared coordinate frame. "
            "Road/building population-centroid distance is intentionally not used as a frame metric."
        ),
        "inputs": {
            "xodr_path": str(xodr),
            "xodr_sha256": _sha256_file(xodr),
            "buildings_path": str(buildings),
            "buildings_sha256": _sha256_file(buildings),
            "header_offset_m": {"x": offset_x, "y": offset_y},
        },
        "thresholds_m": {
            "max_systematic_offset_m": max_systematic_offset_m,
            "individual_outlier_m": individual_outlier_m,
        },
        "counts": {
            "source_buildings": len(source_centroids),
            "xodr_buildings": len(xodr_centroids),
            "common_building_ids": len(common_ids),
            "source_only_ids": len(source_only_ids),
            "xodr_only_ids": len(xodr_only_ids),
            "source_duplicate_ids": len(duplicate_source_ids),
            "xodr_duplicate_ids": len(duplicate_xodr_ids),
            "individual_geometry_drift_count": len(comparisons),
        },
        "systematic_offset_m": {
            "median_dx": round(median_dx, 9) if median_dx is not None else None,
            "median_dy": round(median_dy, 9) if median_dy is not None else None,
            "median_vector_magnitude": round(robust_offset, 9) if robust_offset is not None else None,
            "p95_per_building_distance": round(p95_distance, 9) if p95_distance is not None else None,
            "max_per_building_distance": round(max(distances), 9) if distances else None,
        },
        "individual_geometry_drift": comparisons,
        "source_only_ids": source_only_ids,
        "xodr_only_ids": xodr_only_ids,
        "duplicate_source_ids": duplicate_source_ids,
        "duplicate_xodr_ids": duplicate_xodr_ids,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only per-building source-to-XODR frame-alignment audit."
    )
    parser.add_argument("--xodr", required=True, type=Path, help="Input OpenDRIVE map")
    parser.add_argument("--buildings", required=True, type=Path, help="Pinned building Overpass JSON")
    parser.add_argument("--out", required=True, type=Path, help="Report JSON output")
    parser.add_argument(
        "--max-systematic-offset-m",
        type=float,
        default=DEFAULT_MAX_SYSTEMATIC_OFFSET_M,
        help="Fail when robust frame-offset metrics exceed this value (default: 1.0).",
    )
    parser.add_argument(
        "--individual-outlier-m",
        type=float,
        default=DEFAULT_INDIVIDUAL_OUTLIER_M,
        help="Report individual geometry drift above this value (default: 0.01).",
    )
    args = parser.parse_args(argv)
    report = audit_building_frame_alignment(
        args.xodr,
        args.buildings,
        max_systematic_offset_m=args.max_systematic_offset_m,
        individual_outlier_m=args.individual_outlier_m,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
