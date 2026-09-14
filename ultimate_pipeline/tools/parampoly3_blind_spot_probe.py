"""Read-only real-map characterization for the paramPoly3 blind-spot sweep."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import median
import xml.etree.ElementTree as ET

from ultimate_pipeline.geometry.opendrive_geometry_kernel import endpoint, sample


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _line_endpoint_delta(geometry: ET.Element) -> float | None:
    """Return the error of the former non-arc straight-line approximation."""
    try:
        x = float(geometry.get("x", "nan"))
        y = float(geometry.get("y", "nan"))
        heading = float(geometry.get("hdg", "nan"))
        length = float(geometry.get("length", "nan"))
        actual = endpoint(geometry)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    legacy_x = x + length * math.cos(heading)
    legacy_y = y + length * math.sin(heading)
    return math.hypot(actual.x - legacy_x, actual.y - legacy_y)


def characterize_xodr(path: Path) -> dict[str, object]:
    root = ET.parse(path).getroot()
    roads = root.findall("road")
    param_roads = 0
    param_geometries = 0
    deltas: list[float] = []
    nonzero_curvature_geometries = 0

    for road in roads:
        geometries = road.findall("./planView/geometry")
        param_geometries_for_road = [
            geometry for geometry in geometries if geometry.find("paramPoly3") is not None
        ]
        if not param_geometries_for_road:
            continue
        param_roads += 1
        for geometry in param_geometries_for_road:
            param_geometries += 1
            delta = _line_endpoint_delta(geometry)
            if delta is not None and math.isfinite(delta):
                deltas.append(delta)
            try:
                length = float(geometry.get("length", "0"))
                poses = sample(geometry, max(length / 3.0, 0.25))
                if any(
                    pose.curvature is not None
                    and math.isfinite(float(pose.curvature))
                    and abs(float(pose.curvature)) > 1e-12
                    for pose in poses
                ):
                    nonzero_curvature_geometries += 1
            except (TypeError, ValueError, ZeroDivisionError):
                continue

    return {
        "schema_version": 1,
        "xodr_path": str(path.resolve()),
        "xodr_sha256": _sha256(path),
        "road_count": len(roads),
        "parampoly3_road_count": param_roads,
        "parampoly3_geometry_count": param_geometries,
        "parampoly3_road_fraction": param_roads / len(roads) if roads else 0.0,
        "former_line_approximation": {
            "affected_geometry_count": sum(delta > 1e-9 for delta in deltas),
            "max_endpoint_error_m": max(deltas, default=0.0),
            "median_endpoint_error_m": median(deltas) if deltas else 0.0,
        },
        "canonical_sampling": {
            "parampoly3_geometries_with_nonzero_curvature": nonzero_curvature_geometries
        },
        "map_of_record_mutated": "NO",
        "live_carla": "NOT_RUN",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xodr", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = characterize_xodr(args.xodr)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
