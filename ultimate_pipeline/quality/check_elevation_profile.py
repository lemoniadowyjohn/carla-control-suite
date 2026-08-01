"""Offline elevation sanity tool to audit OpenDRIVE segments for researcher-grade measurements."""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
import xml.etree.ElementTree as ET

MAX_GRADE_ENV = "UP_ELEVATION_MAX_GRADE"
DEFAULT_MAX_GRADE = 0.2


def _parse_float(value: str | None) -> Tuple[Optional[float], bool]:
    if value is None:
        return None, False
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None, False
    return result, not math.isfinite(result)


def _grade_polynomial(b: float, c: float, d: float, s: float) -> float:
    """
    Return the derivative dz/ds for the OpenDRIVE elevation polynomial:

        z(s) = a + b*s + c*s^2 + d*s^3

    Therefore:

        dz/ds = b + 2*c*s + 3*d*s^2

    Note:
    - The constant term 'a' does not affect grade.
    """
    return b + 2.0 * c * s + 3.0 * d * s * s


def _iter_road_segments(road_elem: ET.Element) -> Iterable[Tuple[float, ET.Element]]:
    for elev in road_elem.findall("./elevationProfile/elevation"):
        s_attr = elev.get("s", "0")
        try:
            start_s = float(s_attr)
        except ValueError:
            start_s = 0.0
        yield start_s, elev


def _threshold() -> float:
    return float(os.environ.get(MAX_GRADE_ENV, DEFAULT_MAX_GRADE))


def _coerce(value: Optional[float]) -> float:
    if value is None:
        return 0.0
    return value


def check_elevation_profile(xodr_path: Path, *, max_grade: Optional[float] = None) -> Tuple[Dict[str, Any], bool]:
    tree = ET.parse(xodr_path)
    root = tree.getroot()
    threshold = max_grade if max_grade is not None else _threshold()
    invalid_found = False
    road_entries: List[Dict[str, Any]] = []

    for road in sorted(root.findall(".//road"), key=lambda elem: elem.get("id", "")):
        road_len_raw, road_len_invalid = _parse_float(road.get("length"))
        road_len = _coerce(road_len_raw)
        invalid_found = invalid_found or road_len_invalid

        segments = sorted(_iter_road_segments(road), key=lambda pair: pair[0])
        has_elevation = bool(segments)
        has_superelevation = bool(road.findall("./superelevationProfile/superelevation"))
        coeff_values: Dict[str, List[float]] = {"a": [], "b": [], "c": [], "d": []}
        spikes: List[Dict[str, Any]] = []

        for idx, (start_s, elev_el) in enumerate(segments):
            a_raw, a_invalid = _parse_float(elev_el.get("a"))
            b_raw, b_invalid = _parse_float(elev_el.get("b"))
            c_raw, c_invalid = _parse_float(elev_el.get("c"))
            d_raw, d_invalid = _parse_float(elev_el.get("d"))
            invalid_found = invalid_found or a_invalid or b_invalid or c_invalid or d_invalid

            a = _coerce(a_raw)
            b = _coerce(b_raw)
            c = _coerce(c_raw)
            d = _coerce(d_raw)

            for key, value in (("a", a), ("b", b), ("c", c), ("d", d)):
                coeff_values[key].append(value)

            next_s = segments[idx + 1][0] if idx + 1 < len(segments) else road_len
            ds = max(0.0, next_s - start_s)
            grades = [_grade_polynomial(b, c, d, 0.0)]
            if ds > 0:
                grades.append(_grade_polynomial(b, c, d, ds))

            max_grade = max(abs(g) for g in grades)
            if max_grade > threshold:
                spikes.append({"s": start_s, "grade": max_grade, "threshold": threshold})

        road_entry: Dict[str, Any] = {
            "road_id": road.get("id", ""),
            "has_elevation_profile": has_elevation,
            "has_superelevation": has_superelevation,
            "segment_count": len(segments),
            "min_a": min(coeff_values["a"]) if coeff_values["a"] else None,
            "max_a": max(coeff_values["a"]) if coeff_values["a"] else None,
            "min_b": min(coeff_values["b"]) if coeff_values["b"] else None,
            "max_b": max(coeff_values["b"]) if coeff_values["b"] else None,
            "min_c": min(coeff_values["c"]) if coeff_values["c"] else None,
            "max_c": max(coeff_values["c"]) if coeff_values["c"] else None,
            "min_d": min(coeff_values["d"]) if coeff_values["d"] else None,
            "max_d": max(coeff_values["d"]) if coeff_values["d"] else None,
            "spikes": spikes,
        }
        if not has_elevation:
            road_entry["mode"] = "flat_or_missing"
        road_entries.append(road_entry)

    global_mode = "flat_or_missing" if not any(entry["has_elevation_profile"] for entry in road_entries) else "elevation_profile"
    report = {
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "threshold": threshold,
        "mode": global_mode,
        "roads": road_entries,
    }
    return report, invalid_found


def write_elevation_report(out_dir: Path, report: Dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "elevation_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit OpenDRIVE elevation profiles.")
    parser.add_argument("--xodr", required=True, type=Path, help="Path to the OpenDRIVE file")
    parser.add_argument("--out", required=True, type=Path, help="Directory to write elevation_report.json")
    parser.add_argument("--max-grade", type=float, help="Override the grade threshold for spike detection")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report, invalid = check_elevation_profile(args.xodr, max_grade=args.max_grade)
    write_elevation_report(args.out, report)
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
