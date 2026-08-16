"""Compute a compact elevation summary directly from OpenDRIVE elevation profiles."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from ultimate_pipeline.core.odr_io import load_xodr


def _safe_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _stats(values: List[float]) -> Dict[str, Optional[float]]:
    if not values:
        return {"min": None, "max": None}
    return {"min": min(values), "max": max(values)}


def _eval_elevation_poly(a: float, b: float, c: float, d: float, s_local: float) -> float:
    """Evaluate the OpenDRIVE elevation cubic z = a + b*s + c*s^2 + d*s^3."""
    return a + b * s_local + c * s_local * s_local + d * s_local * s_local * s_local


def summarize_elevation(xodr_path: str) -> Dict[str, Any]:
    _tree, root = load_xodr(xodr_path)
    roads = root.findall(".//road")

    coeffs: Dict[str, List[float]] = {"a": [], "b": [], "c": [], "d": []}
    invalid_coefficients = 0
    roads_with_elevation_profile = 0
    elevation_segment_count = 0
    max_abs_grade_estimate: Optional[float] = None
    true_elevation_values: List[float] = []

    for road in roads:
        segments = road.findall("./elevationProfile/elevation")
        if segments:
            roads_with_elevation_profile += 1

        road_len = _safe_float(road.get("length")) or 0.0

        for idx, elev in enumerate(segments):
            elevation_segment_count += 1

            s0 = _safe_float(elev.get("s")) or 0.0
            next_s = road_len
            if idx + 1 < len(segments):
                next_s = _safe_float(segments[idx + 1].get("s")) or next_s
            ds = max(0.0, next_s - s0)

            parsed: Dict[str, Optional[float]] = {
                "a": _safe_float(elev.get("a")),
                "b": _safe_float(elev.get("b")),
                "c": _safe_float(elev.get("c")),
                "d": _safe_float(elev.get("d")),
            }

            for key, value in parsed.items():
                if value is None:
                    invalid_coefficients += 1
                    value = 0.0
                coeffs[key].append(value)

            a = parsed["a"] if parsed["a"] is not None else 0.0
            b = parsed["b"] if parsed["b"] is not None else 0.0
            c = parsed["c"] if parsed["c"] is not None else 0.0
            d = parsed["d"] if parsed["d"] is not None else 0.0
            grade_start = b
            grade_end = b + (2.0 * c * ds) + (3.0 * d * ds * ds)
            local_max = max(abs(grade_start), abs(grade_end))
            if max_abs_grade_estimate is None or local_max > max_abs_grade_estimate:
                max_abs_grade_estimate = local_max

            # Sample the true absolute elevation (the cubic evaluated over
            # the segment), not just the 'a' coefficient at the segment
            # start, so a sloped single-record segment reports its real
            # min/max rather than only its local offset.
            true_elevation_values.append(_eval_elevation_poly(a, b, c, d, 0.0))
            true_elevation_values.append(_eval_elevation_poly(a, b, c, d, ds))
            # Interior extremum of the quadratic derivative (grade), when it
            # falls inside the segment, can be a local min/max of elevation.
            if abs(d) > 1e-15:
                # dz/ds = b + 2c*s + 3d*s^2 = 0
                disc = (2.0 * c) ** 2 - 4.0 * (3.0 * d) * b
                if disc >= 0.0:
                    sqrt_disc = math.sqrt(disc)
                    for s_extremum in (
                        (-2.0 * c + sqrt_disc) / (6.0 * d),
                        (-2.0 * c - sqrt_disc) / (6.0 * d),
                    ):
                        if 0.0 < s_extremum < ds:
                            true_elevation_values.append(
                                _eval_elevation_poly(a, b, c, d, s_extremum)
                            )
            elif abs(c) > 1e-15:
                s_extremum = -b / (2.0 * c)
                if 0.0 < s_extremum < ds:
                    true_elevation_values.append(_eval_elevation_poly(a, b, c, d, s_extremum))

    mode = "flat_or_missing" if elevation_segment_count == 0 else "elevation_profile"
    true_stats = _stats(true_elevation_values)
    true_min = true_stats["min"]
    true_max = true_stats["max"]
    span = (true_max - true_min) if (true_min is not None and true_max is not None) else None
    return {
        "xodr_path": xodr_path,
        "mode": mode,
        "road_count": len(roads),
        "roads_with_elevation_profile": roads_with_elevation_profile,
        "elevation_segment_count": elevation_segment_count,
        "invalid_coefficient_count": invalid_coefficients,
        "max_abs_grade_estimate": max_abs_grade_estimate,
        "min": true_min,
        "max": true_max,
        "span": span,
        "coefficient_stats": {
            "a": _stats(coeffs["a"]),
            "b": _stats(coeffs["b"]),
            "c": _stats(coeffs["c"]),
            "d": _stats(coeffs["d"]),
        },
    }


def main(xodr_path: str) -> Dict[str, Any]:
    summary = summarize_elevation(xodr_path)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def _cli_main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize OpenDRIVE elevation profile coefficients (a,b,c,d)."
    )
    parser.add_argument("xodr_path", help="Path to input .xodr")
    parser.add_argument(
        "--out",
        dest="out_json",
        default="",
        help="Optional output JSON path for the summary.",
    )
    args = parser.parse_args()

    summary = main(args.xodr_path)
    if args.out_json:
        out_path = Path(args.out_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli_main())
