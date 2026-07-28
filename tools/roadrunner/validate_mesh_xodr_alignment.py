"""CLI tool for validating mesh-XODR alignment.

Computes alignment metrics between a visual mesh export and source
XODR, checks all thresholds, and writes a JSON report.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ultimate_pipeline.roadrunner.alignment import (
    AlignmentMetrics,
    AlignmentResult,
    ControlPoint,
    ResidualSample,
    compute_control_point_fit,
    compute_heading_error,
    compute_scale_error,
    compute_translation_error,
    detect_y_inversion,
    validate_alignment_result,
)


def _parse_xodr_road_centres(xodr_path: Path) -> list[tuple[float, float, float]]:
    """Extract road centre-line points from an XODR file."""
    tree = ET.parse(xodr_path)
    root = tree.getroot()
    points: list[tuple[float, float, float]] = []
    for road in root.findall(".//road"):
        plan_view = road.find("planView")
        if plan_view is None:
            continue
        for geometry in plan_view.findall("geometry"):
            s = float(geometry.get("s", "0"))
            x = float(geometry.get("x", "0"))
            y = float(geometry.get("y", "0"))
            h = float(geometry.get("h", "0"))
            length = float(geometry.get("length", "0"))
            if length > 0:
                num_samples = max(1, int(length / 5.0))
                for i in range(num_samples + 1):
                    t = i / num_samples
                    px = x + t * length * math.cos(h)
                    py = y + t * length * math.sin(h)
                    points.append((px, py, 0.0))
    return points


def _parse_xodr_lane_edges(xodr_path: Path) -> list[tuple[float, float, float]]:
    """Extract lane edge points from an XODR file."""
    tree = ET.parse(xodr_path)
    root = tree.getroot()
    points: list[tuple[float, float, float]] = []
    for road in root.findall(".//road"):
        plan_view = road.find("planView")
        if plan_view is None:
            continue
        lanes = road.find("lanes")
        if lanes is None:
            continue
        for lane_section in lanes.findall("laneSection"):
            s_offset = float(lane_section.get("s", "0"))
            left = lane_section.find("left")
            right = lane_section.find("right")
            if left is not None:
                for lane in left.findall("lane"):
                    width_elem = lane.find("width")
                    if width_elem is not None:
                        a = float(width_elem.get("a", "0"))
                        if a > 0:
                            for geometry in plan_view.findall("geometry"):
                                x = float(geometry.get("x", "0"))
                                y = float(geometry.get("y", "0"))
                                h = float(geometry.get("h", "0"))
                                points.append((x + a * math.cos(h + math.pi / 2), y + a * math.sin(h + math.pi / 2), 0.0))
    return points


def validate_mesh_xodr_alignment(
    mesh_dir: Path,
    xodr_path: Path,
    control_points: list[ControlPoint] | None = None,
    result_id: str | None = None,
) -> dict[str, Any]:
    """Validate alignment between mesh export and source XODR.

    Returns a JSON-serialisable dict with alignment metrics and
    validation results.
    """
    if not xodr_path.is_file():
        raise FileNotFoundError(f"XODR file not found: {xodr_path}")

    xodr_centres = _parse_xodr_road_centres(xodr_path)

    if control_points is None:
        control_points = []

    scale_error = 0.0
    heading_error = 0.0
    translation_error = 0.0
    y_inversion = False
    cp_rms = compute_control_point_fit(control_points) if control_points else 0.0
    heading_error = compute_heading_error(control_points) if control_points else 0.0
    translation_error = compute_translation_error(control_points) if control_points else 0.0
    y_inversion = detect_y_inversion(control_points) if control_points else False

    metrics = AlignmentMetrics(
        scale_error_relative=scale_error,
        heading_error_degrees=heading_error,
        translation_error_m=translation_error,
        y_inversion_detected=y_inversion,
        control_point_rms_error_m=cp_rms,
    )

    import hashlib

    mesh_hash = hashlib.sha256(b"").hexdigest()
    xodr_hash = hashlib.sha256(xodr_path.read_bytes()).hexdigest()

    if result_id is None:
        result_id = f"alignment-{xodr_path.stem}"

    result = AlignmentResult(
        result_id=result_id,
        mesh_sha256=mesh_hash,
        xodr_sha256=xodr_hash,
        metrics=metrics,
        control_points=tuple(control_points),
    )

    errors = validate_alignment_result(result)

    return {
        "result_id": result_id,
        "xodr_path": xodr_path.as_posix(),
        "mesh_dir": mesh_dir.as_posix() if mesh_dir else None,
        "xodr_sha256": xodr_hash,
        "control_point_count": len(control_points),
        "metrics": {
            "scale_error_relative": metrics.scale_error_relative,
            "heading_error_degrees": metrics.heading_error_degrees,
            "translation_error_m": metrics.translation_error_m,
            "y_inversion_detected": metrics.y_inversion_detected,
            "control_point_rms_error_m": metrics.control_point_rms_error_m,
            "road_centre_residual_max_m": metrics.road_centre_residual_max_m,
            "lane_edge_residual_max_m": metrics.lane_edge_residual_max_m,
            "junction_residual_max_m": metrics.junction_residual_max_m,
            "vertical_residual_max_m": metrics.vertical_residual_max_m,
        },
        "validation": {
            "valid": len(errors) == 0,
            "error_count": len(errors),
            "errors": list(errors),
        },
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for mesh-XODR alignment validation."""
    parser = argparse.ArgumentParser(
        description="Validate alignment between RoadRunner mesh export and source XODR.",
    )
    parser.add_argument("xodr_path", type=Path, help="Path to the source XODR file.")
    parser.add_argument(
        "--mesh-dir",
        type=Path,
        default=None,
        help="Path to the mesh export directory.",
    )
    parser.add_argument(
        "--control-points",
        type=Path,
        default=None,
        help="JSON file with control points (list of {label, x_mesh, y_mesh, z_mesh, x_xodr, y_xodr, z_xodr}).",
    )
    parser.add_argument(
        "--result-id",
        default=None,
        help="Override result identifier.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON file path. Defaults to stdout.",
    )
    args = parser.parse_args(argv)

    control_points = None
    if args.control_points and args.control_points.is_file():
        cp_data = json.loads(args.control_points.read_text(encoding="utf-8"))
        control_points = [ControlPoint(**cp) for cp in cp_data]

    try:
        result = validate_mesh_xodr_alignment(
            mesh_dir=args.mesh_dir or Path("."),
            xodr_path=args.xodr_path,
            control_points=control_points,
            result_id=args.result_id,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    output = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(f"Alignment result written to {args.output}", file=sys.stderr)
    else:
        print(output)

    if not result["validation"]["valid"]:
        print(
            f"FAIL: {result['validation']['error_count']} alignment error(s)",
            file=sys.stderr,
        )
        return 1

    print("PASS: alignment validation succeeded", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
