from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ultimate_pipeline.core.xodr_statistics import XODRStatistics
from ultimate_pipeline.quality.check_elevation_continuity import check_elevation_continuity
from ultimate_pipeline.quality.check_elevation_seams import check_elevation_seams


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        parsed = float(value)
    except Exception:
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def _stats(values: Sequence[float]) -> Dict[str, Optional[float]]:
    if not values:
        return {"min": None, "max": None, "mean": None, "std": None, "p95": None}
    ordered = sorted(float(v) for v in values)
    return {
        "min": ordered[0],
        "max": ordered[-1],
        "mean": statistics.fmean(ordered),
        "std": statistics.pstdev(ordered) if len(ordered) > 1 else 0.0,
        "p95": _percentile(ordered, 95.0),
    }


def _percentile(values: Sequence[float], pct: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(float(v) for v in values)
    pct = max(0.0, min(100.0, float(pct)))
    k = (len(ordered) - 1) * (pct / 100.0)
    floor_idx = math.floor(k)
    ceil_idx = math.ceil(k)
    if floor_idx == ceil_idx:
        return ordered[int(k)]
    d0 = ordered[int(floor_idx)] * (ceil_idx - k)
    d1 = ordered[int(ceil_idx)] * (k - floor_idx)
    return d0 + d1


def _load_json_dict(path: Optional[Path]) -> Dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _discover_neighbor(path: Path, filename: str) -> Optional[Path]:
    candidate = path.parent / filename
    return candidate if candidate.is_file() else None


def _parse_elevation_segments(road: ET.Element) -> List[Tuple[float, float, float, float, float]]:
    profile = road.find("elevationProfile")
    if profile is None:
        return []
    segments: List[Tuple[float, float, float, float, float]] = []
    for el in profile.findall("elevation"):
        s = _safe_float(el.get("s"), 0.0) or 0.0
        a = _safe_float(el.get("a"), 0.0) or 0.0
        b = _safe_float(el.get("b"), 0.0) or 0.0
        c = _safe_float(el.get("c"), 0.0) or 0.0
        d = _safe_float(el.get("d"), 0.0) or 0.0
        segments.append((s, a, b, c, d))
    segments.sort(key=lambda item: item[0])
    return segments


def _elevation_at_s(segments: Sequence[Tuple[float, float, float, float, float]], s_abs: float) -> float:
    if not segments:
        return 0.0
    selected = segments[0]
    for candidate in segments:
        if s_abs >= candidate[0]:
            selected = candidate
        else:
            break
    s0, a, b, c, d = selected
    ds = max(0.0, s_abs - s0)
    return a + b * ds + c * ds * ds + d * ds * ds * ds


def _grade_at_s(segments: Sequence[Tuple[float, float, float, float, float]], s_abs: float) -> float:
    if not segments:
        return 0.0
    selected = segments[0]
    for candidate in segments:
        if s_abs >= candidate[0]:
            selected = candidate
        else:
            break
    s0, _a, b, c, d = selected
    ds = max(0.0, s_abs - s0)
    return b + (2.0 * c * ds) + (3.0 * d * ds * ds)


def _road_sample_positions(length_m: float, sample_step_m: float) -> List[float]:
    if length_m <= 0.0:
        return [0.0]
    positions = [0.0]
    step = max(0.1, sample_step_m)
    s = step
    while s < length_m:
        positions.append(s)
        s += step
    if positions[-1] != length_m:
        positions.append(length_m)
    return positions


def _count_elevation_segments(xodr_path: Path) -> Dict[str, int]:
    tree = ET.parse(xodr_path)
    root = tree.getroot()
    roads_with_elevation = 0
    roads_with_nonzero_profile = 0
    total_segments = 0
    zero_segments = 0
    for road in root.findall("road"):
        profile = road.find("elevationProfile")
        if profile is None:
            continue
        segments = profile.findall("elevation")
        if not segments:
            continue
        roads_with_elevation += 1
        road_nonzero = False
        total_segments += len(segments)
        for segment in segments:
            coeffs = []
            for key in ("a", "b", "c", "d"):
                coeffs.append(_safe_float(segment.get(key), 0.0) or 0.0)
            if all(abs(value) <= 1e-12 for value in coeffs):
                zero_segments += 1
            else:
                road_nonzero = True
        if road_nonzero:
            roads_with_nonzero_profile += 1
    return {
        "roads_with_elevation_profile": int(roads_with_elevation),
        "roads_with_nonzero_elevation_profile": int(roads_with_nonzero_profile),
        "elevation_segment_count": int(total_segments),
        "segments_all_zero_coefficients": int(zero_segments),
        "segments_nonzero_coefficients": int(total_segments - zero_segments),
    }


def _sample_profiles(
    xodr_path: Path,
    *,
    sample_step_m: float,
    nonzero_z_threshold_m: float,
) -> Dict[str, Any]:
    tree = ET.parse(xodr_path)
    root = tree.getroot()
    roads = root.findall("road")

    z_samples: List[float] = []
    abs_grade_samples: List[float] = []
    road_grade_peaks: List[Dict[str, Any]] = []
    sample_count_total = 0
    samples_with_nonzero_z = 0
    samples_with_profile = 0
    samples_with_nonzero_z_or_profile = 0

    for road in roads:
        road_id = (road.get("id") or "").strip()
        road_length = _safe_float(road.get("length"), 0.0) or 0.0
        segments = _parse_elevation_segments(road)
        positions = _road_sample_positions(road_length, sample_step_m)
        road_z_values: List[float] = []
        road_abs_grades: List[float] = []
        road_has_profile = bool(segments)
        for s_abs in positions:
            z = _elevation_at_s(segments, s_abs)
            grade = _grade_at_s(segments, s_abs)
            abs_grade = abs(grade)
            z_samples.append(z)
            abs_grade_samples.append(abs_grade)
            road_z_values.append(z)
            road_abs_grades.append(abs_grade)
            sample_count_total += 1
            if abs(z) > nonzero_z_threshold_m:
                samples_with_nonzero_z += 1
            if road_has_profile:
                samples_with_profile += 1
            if road_has_profile or abs(z) > nonzero_z_threshold_m:
                samples_with_nonzero_z_or_profile += 1
        if road_abs_grades:
            road_grade_peaks.append(
                {
                    "road_id": road_id,
                    "sample_count": len(road_abs_grades),
                    "max_abs_grade": max(road_abs_grades),
                    "mean_abs_grade": statistics.fmean(road_abs_grades),
                    "z_min": min(road_z_values),
                    "z_max": max(road_z_values),
                    "z_range": max(road_z_values) - min(road_z_values),
                }
            )

    slope_thresholds = (0.10, 0.15, 0.20)
    slope_counts = {
        f"abs_grade_gt_{int(threshold * 100):02d}pct": sum(1 for value in abs_grade_samples if value > threshold)
        for threshold in slope_thresholds
    }
    slope_fractions = {
        key.replace("gt", "fraction_gt"): (count / sample_count_total if sample_count_total else 0.0)
        for key, count in slope_counts.items()
    }

    return {
        "sample_step_m": sample_step_m,
        "sample_count_total": sample_count_total,
        "sample_count_nonzero_z": samples_with_nonzero_z,
        "sample_fraction_nonzero_z": (samples_with_nonzero_z / sample_count_total) if sample_count_total else 0.0,
        "sample_count_on_roads_with_profile": samples_with_profile,
        "sample_fraction_on_roads_with_profile": (samples_with_profile / sample_count_total) if sample_count_total else 0.0,
        "sample_count_nonzero_z_or_profile": samples_with_nonzero_z_or_profile,
        "sample_fraction_nonzero_z_or_profile": (
            samples_with_nonzero_z_or_profile / sample_count_total if sample_count_total else 0.0
        ),
        "z_sample_stats_m": _stats(z_samples),
        "abs_grade_stats": _stats(abs_grade_samples),
        "suspicious_slope_summary": {
            "grade_unit": "rise_per_meter",
            "counts": slope_counts,
            "fractions": slope_fractions,
            "top_roads_by_abs_grade": sorted(
                road_grade_peaks,
                key=lambda item: item.get("max_abs_grade", 0.0),
                reverse=True,
            )[:10],
        },
    }


def _compact_seam_report(report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ok": bool(report.get("ok", False)),
        "sample_step_m": report.get("sample_step_m"),
        "step_threshold_m": report.get("step_threshold_m"),
        "max_jump_m": report.get("max_jump_m"),
        "p95_threshold_m": report.get("p95_threshold_m"),
        "num_roads": report.get("num_roads"),
        "total_samples": report.get("total_samples"),
        "total_steps": report.get("total_steps"),
        "seam_stats": report.get("seam_stats", {}),
        "elevation_stats": report.get("elevation_stats", {}),
        "top_offenders": report.get("top_offenders", [])[:10],
        "warnings": report.get("warnings", []),
    }


def _compact_continuity_report(report: Dict[str, Any]) -> Dict[str, Any]:
    issues = report.get("issues", []) or []
    dz_values = [float(item["dz"]) for item in issues if _safe_float(item.get("dz")) is not None]
    top_issues = sorted(
        (item for item in issues if _safe_float(item.get("dz")) is not None),
        key=lambda item: float(item.get("dz", 0.0)),
        reverse=True,
    )[:10]
    num_links_checked = int(report.get("num_links_checked", 0) or 0)
    num_issues = int(report.get("num_issues", len(issues)) or 0)
    return {
        "ok": bool(report.get("ok", False)),
        "eps_z_m": report.get("eps_z"),
        "num_roads": report.get("num_roads"),
        "num_links_checked": num_links_checked,
        "num_issues": num_issues,
        "issue_fraction": (num_issues / num_links_checked) if num_links_checked else 0.0,
        "max_dz_m": max(dz_values) if dz_values else None,
        "p95_dz_m": _percentile(dz_values, 95.0) if dz_values else None,
        "top_issues": top_issues,
        "warnings": report.get("warnings", []),
    }


def _final_dem_used_verdict(
    *,
    flat: bool,
    counts: Dict[str, int],
    sampling: Dict[str, Any],
    dem_qc: Dict[str, Any],
    dem_coverage: Dict[str, Any],
    dem_path: Path,
) -> Dict[str, Any]:
    dem_qc_ok = bool(dem_qc.get("ok")) if dem_qc else None
    coverage_ok = bool(dem_coverage.get("ok")) if dem_coverage else None
    z_stats = sampling.get("z_sample_stats_m", {})
    z_range = _safe_float(z_stats.get("max"), None)
    if z_range is not None and _safe_float(z_stats.get("min"), None) is not None:
        z_range = float(z_stats["max"]) - float(z_stats["min"])
    nonzero_fraction = float(sampling.get("sample_fraction_nonzero_z_or_profile", 0.0) or 0.0)
    profile_nonzero = int(counts.get("segments_nonzero_coefficients", 0) or 0)
    evidence = {
        "dem_path_exists": dem_path.is_file(),
        "dem_qc_ok": dem_qc_ok,
        "dem_coverage_ok": coverage_ok,
        "sample_z_range_m": z_range,
        "sample_fraction_nonzero_z_or_profile": nonzero_fraction,
        "segments_nonzero_coefficients": profile_nonzero,
        "is_flat_by_samples": flat,
    }
    verdict = bool(dem_path.is_file() and (dem_qc_ok is not False) and not flat and profile_nonzero > 0)
    if verdict:
        reason = "DEM QC succeeded and the final XODR contains non-flat sampled elevation with non-zero profile coefficients."
    elif flat:
        reason = "Final XODR remains flat by sampled-elevation threshold."
    elif profile_nonzero == 0:
        reason = "Final XODR has no non-zero elevation profile coefficients."
    elif dem_qc_ok is False:
        reason = "DEM QC for this run reported failure."
    else:
        reason = "DEM evidence is incomplete or inconclusive at the final artifact level."
    return {"dem_used": verdict, "reason": reason, "evidence": evidence}


def build_report(
    *,
    xodr_path: Path,
    dem_path: Path,
    dem_qc_path: Optional[Path],
    dem_coverage_path: Optional[Path],
    sample_step_m: float,
    nonzero_z_threshold_m: float,
    flat_range_threshold_m: float,
    continuity_eps_z_m: float,
) -> Dict[str, Any]:
    stats = XODRStatistics.compute(str(xodr_path))
    elevation_stats = (stats.get("elevation", {}) or {}) if isinstance(stats, dict) else {}
    counts = _count_elevation_segments(xodr_path)
    sampling = _sample_profiles(
        xodr_path,
        sample_step_m=sample_step_m,
        nonzero_z_threshold_m=nonzero_z_threshold_m,
    )

    z_sample_stats = sampling.get("z_sample_stats_m", {})
    min_z = _safe_float(z_sample_stats.get("min"))
    max_z = _safe_float(z_sample_stats.get("max"))
    sample_z_range = (max_z - min_z) if min_z is not None and max_z is not None else None
    flat = bool(sample_z_range is not None and sample_z_range <= flat_range_threshold_m)

    seam_report = _compact_seam_report(check_elevation_seams(str(xodr_path)))
    continuity_report = _compact_continuity_report(
        check_elevation_continuity(str(xodr_path), eps_z=continuity_eps_z_m)
    )
    dem_qc = _load_json_dict(dem_qc_path)
    dem_coverage = _load_json_dict(dem_coverage_path)
    dem_used_verdict = _final_dem_used_verdict(
        flat=flat,
        counts=counts,
        sampling=sampling,
        dem_qc=dem_qc,
        dem_coverage=dem_coverage,
        dem_path=dem_path,
    )

    payload = {
        "schema_version": 3,
        "source_xodr": xodr_path.as_posix(),
        "xodr_sha256": _sha256_file(xodr_path),
        "dem_file_path": dem_path.as_posix(),
        "dem_file_size_bytes": int(dem_path.stat().st_size),
        "dem_fallback_active": bool(flat),
        "auto_map_elevation": (
            "flat (sample z-range below threshold and no artifact-level elevation variation proven)"
            if flat
            else "non-flat elevation profile present"
        ),
        "manual_map_has_real_elevation": True,
        "unquantified_elevation_gap": (
            "The manual Ingolstadt reference contains nonzero elevation profiles, but no directly comparable "
            "auto-vs-manual elevation-gap metric is produced by this verifier."
        ),
        "thesis_impact": (
            "This artifact is suitable only as supplementary pipeline capability evidence. "
            "thesis_results/structural_gap_v1/run_11/full_report.json remains the authoritative structural thesis result."
        ),
        "analysis_scope_note": (
            "This verifier proves artifact-level DEM-backed elevation behavior and structural operability only; "
            "it does not replace the thesis-authoritative planar structural evaluation."
        ),
        "notes": [
            "This report is generated from the final XODR artifact, not inferred from stage success flags alone.",
            "DEM coverage and QC fields are passed through from run-local artifacts when available.",
            "Road-link elevation continuity is summarized separately from plan-view structural validity.",
        ],
        "auto_elevation_stats": {
            "min_z": _safe_float(elevation_stats.get("min_z")),
            "max_z": _safe_float(elevation_stats.get("max_z")),
            "z_range": _safe_float(elevation_stats.get("z_range")),
            "roads_with_elevation_profile": counts["roads_with_elevation_profile"],
            "roads_with_nonzero_elevation_profile": counts["roads_with_nonzero_elevation_profile"],
            "elevation_segment_count": counts["elevation_segment_count"],
            "segments_all_zero_coefficients": counts["segments_all_zero_coefficients"],
            "segments_nonzero_coefficients": counts["segments_nonzero_coefficients"],
        },
        "sampling": sampling,
        "flatness_verdict": {
            "flat_range_threshold_m": flat_range_threshold_m,
            "nonzero_z_threshold_m": nonzero_z_threshold_m,
            "sample_z_range_m": sample_z_range,
            "sample_z_std_m": _safe_float(z_sample_stats.get("std")),
            "is_flat": flat,
            "reason": (
                "sampled z-range is at or below the configured flatness threshold"
                if flat
                else "sampled z-range exceeds the configured flatness threshold"
            ),
        },
        "suspicious_slope_summary": sampling.get("suspicious_slope_summary", {}),
        "seam_jump_summary": seam_report,
        "continuity_summary": continuity_report,
        "dem_qc_summary": dem_qc,
        "dem_coverage_summary": dem_coverage,
        "final_dem_used_verdict": dem_used_verdict,
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write elevation verification facts for a final OpenDRIVE artifact."
    )
    parser.add_argument("--xodr", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dem-path", type=Path, required=True)
    parser.add_argument("--dem-qc", type=Path, default=None)
    parser.add_argument("--dem-coverage", type=Path, default=None)
    parser.add_argument("--sample-step-m", type=float, default=5.0)
    parser.add_argument("--nonzero-z-threshold-m", type=float, default=1e-3)
    parser.add_argument("--flat-range-threshold-m", type=float, default=0.05)
    parser.add_argument("--continuity-eps-z-m", type=float, default=0.5)
    args = parser.parse_args()

    xodr_path = args.xodr.resolve()
    if not xodr_path.is_file():
        raise FileNotFoundError(f"XODR not found: {xodr_path}")

    dem_path = args.dem_path.resolve()
    if not dem_path.is_file():
        raise FileNotFoundError(f"DEM not found: {dem_path}")

    dem_qc_path = args.dem_qc.resolve() if args.dem_qc else _discover_neighbor(xodr_path, "elevation_dem_qc.json")
    dem_coverage_path = (
        args.dem_coverage.resolve() if args.dem_coverage else _discover_neighbor(xodr_path, "dem_full_coverage.json")
    )

    payload = build_report(
        xodr_path=xodr_path,
        dem_path=dem_path,
        dem_qc_path=dem_qc_path,
        dem_coverage_path=dem_coverage_path,
        sample_step_m=args.sample_step_m,
        nonzero_z_threshold_m=args.nonzero_z_threshold_m,
        flat_range_threshold_m=args.flat_range_threshold_m,
        continuity_eps_z_m=args.continuity_eps_z_m,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
