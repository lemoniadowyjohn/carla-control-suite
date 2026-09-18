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


def summarize_elevation(xodr_path: str) -> Dict[str, Any]:
    _tree, root = load_xodr(xodr_path)
    roads = root.findall(".//road")

    coeffs: Dict[str, List[float]] = {"a": [], "b": [], "c": [], "d": []}
    invalid_coefficients = 0
    roads_with_elevation_profile = 0
    elevation_segment_count = 0
    max_abs_grade_estimate: Optional[float] = None

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

            b = parsed["b"] if parsed["b"] is not None else 0.0
            c = parsed["c"] if parsed["c"] is not None else 0.0
            d = parsed["d"] if parsed["d"] is not None else 0.0
            grade_start = b
            grade_end = b + (2.0 * c * ds) + (3.0 * d * ds * ds)
            local_max = max(abs(grade_start), abs(grade_end))
            if max_abs_grade_estimate is None or local_max > max_abs_grade_estimate:
                max_abs_grade_estimate = local_max

    mode = "flat_or_missing" if elevation_segment_count == 0 else "elevation_profile"
    return {
        "xodr_path": xodr_path,
        "mode": mode,
        "road_count": len(roads),
        "roads_with_elevation_profile": roads_with_elevation_profile,
        "elevation_segment_count": elevation_segment_count,
        "invalid_coefficient_count": invalid_coefficients,
        "max_abs_grade_estimate": max_abs_grade_estimate,
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
