from __future__ import annotations

import argparse
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict

from ultimate_pipeline.domain_gap.curvature_gap import CurvatureGap
from ultimate_pipeline.domain_gap.intersection_gap import IntersectionGap
from ultimate_pipeline.domain_gap.semantic_gap import SemanticGap
from ultimate_pipeline.tools.xodr_structural_summary import summarize_xodr


def _read_json_if_exists(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _stable_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _normalized_l1_over2(a_dist: Dict[str, float], b_dist: Dict[str, float]) -> float | None:
    keys = set(a_dist) | set(b_dist)
    if not keys:
        return None
    total_a = sum(float(a_dist.get(key, 0.0)) for key in keys)
    total_b = sum(float(b_dist.get(key, 0.0)) for key in keys)
    if total_a <= 0.0 or total_b <= 0.0:
        return None
    l1 = 0.0
    for key in keys:
        pa = float(a_dist.get(key, 0.0)) / total_a
        pb = float(b_dist.get(key, 0.0)) / total_b
        l1 += abs(pa - pb)
    return l1 / 2.0


def _bbox_from_planview(xodr_path: Path) -> tuple[float, float, float, float]:
    root = ET.parse(xodr_path).getroot()
    xs: list[float] = []
    ys: list[float] = []
    for geometry in root.findall(".//planView/geometry"):
        try:
            x = float(geometry.get("x", "0"))
            y = float(geometry.get("y", "0"))
            hdg = float(geometry.get("hdg", "0"))
            length = float(geometry.get("length", "0"))
        except Exception:
            continue
        xs.append(x)
        ys.append(y)
        xs.append(x + length * math.cos(hdg))
        ys.append(y + length * math.sin(hdg))
    if not xs or not ys:
        raise RuntimeError(f"No planView geometry found in {xodr_path}")
    return (min(xs), min(ys), max(xs), max(ys))


def _bbox_iou(a_bbox: tuple[float, float, float, float], b_bbox: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a_bbox
    bx1, by1, bx2, by2 = b_bbox
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    inter_w = max(0.0, ix2 - ix1)
    inter_h = max(0.0, iy2 - iy1)
    inter = inter_w * inter_h
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0.0 else 0.0


def _fit_metric_payload(existing_payload: Dict[str, Any]) -> Dict[str, Any]:
    prior = existing_payload.get("fit_metric_provenance")
    if not isinstance(prior, dict):
        return {
            "status": "missing_in_governed_worktree",
            "diagnostic_field": "alignment.diagnostics.icp_rmse_history",
            "reported_fit_metric_worsened_monotonically": None,
            "metric_not_equivalent_to_icp_objective": None,
            "true_divergence_supported": False,
            "verified_safe_conclusion": "unsupported_by_governed_artifacts",
            "note": (
                "The governed worktree does not preserve run_11 alignment/full-report artifacts, so "
                "run_11 fit-history claims cannot be reverified here."
            ),
        }
    return {
        "status": "carried_forward_from_prior_patch_output_not_reverified_in_governed_worktree",
        "diagnostic_field": "alignment.diagnostics.icp_rmse_history",
        "reported_fit_metric_worsened_monotonically": prior.get("reported_fit_metric_worsened_monotonically"),
        "metric_not_equivalent_to_icp_objective": prior.get("metric_not_equivalent_to_icp_objective", True),
        "true_divergence_supported": False,
        "verified_safe_conclusion": prior.get(
            "verified_safe_conclusion",
            "reported_fit_metric_worsened_monotonically",
        ),
        "note": (
            "This pass preserves only the prior conservative run_11 fit-metric boundary from the existing "
            "governed addendum. It is not newly reverified from governed run_11 source artifacts."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute governed structural supplementary metrics and conservative run_11 claim boundaries."
    )
    parser.add_argument("--manual-xodr", type=Path, required=True)
    parser.add_argument("--auto-xodr", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--expected-run11-auto-xodr", type=Path, default=Path("thesis_results/structural_gap_v1/run_11/auto_aligned_rigid.xodr"))
    parser.add_argument("--surrogate-run-id", default="")
    args = parser.parse_args()

    manual_xodr = args.manual_xodr.resolve()
    auto_xodr = args.auto_xodr.resolve()
    if not manual_xodr.is_file():
        raise FileNotFoundError(f"Manual XODR not found: {manual_xodr}")
    if not auto_xodr.is_file():
        raise FileNotFoundError(f"Auto XODR not found: {auto_xodr}")

    existing_payload = _read_json_if_exists(args.out.resolve())

    manual_summary = summarize_xodr(manual_xodr)
    auto_summary = summarize_xodr(auto_xodr)
    manual_length = float(manual_summary.get("total_road_length_m") or 0.0)
    auto_length = float(auto_summary.get("total_road_length_m") or 0.0)
    coverage_ratio = auto_length / manual_length if manual_length > 0.0 else None

    curvature = CurvatureGap.compute(str(manual_xodr), str(auto_xodr))
    semantic = SemanticGap.compute(str(manual_xodr), str(auto_xodr))
    intersection = IntersectionGap.compute(str(manual_xodr), str(auto_xodr))
    semantic_gap = _normalized_l1_over2(
        dict((semantic.get("road_types") or {}).get("manual_length") or {}),
        dict((semantic.get("road_types") or {}).get("auto_length") or {}),
    )
    bbox_iou = _bbox_iou(_bbox_from_planview(auto_xodr), _bbox_from_planview(manual_xodr))

    expected_run11 = args.expected_run11_auto_xodr.resolve()
    computed_on_run11_alignment = bool(expected_run11.is_file() and expected_run11 == auto_xodr)
    payload = {
        "schema_version": 2,
        "run_id": "run_11",
        "governed_reconciliation_date_utc": "2026-03-25",
        "artifact_resolution": {
            "requested_run11_aligned_auto_xodr": args.expected_run11_auto_xodr.as_posix(),
            "requested_run11_aligned_auto_xodr_exists": bool(expected_run11.is_file()),
            "governed_surrogate_run_id": str(args.surrogate_run_id or ""),
            "governed_surrogate_auto_xodr": auto_xodr.as_posix(),
            "manual_xodr": manual_xodr.as_posix(),
            "status": (
                "computed_on_governed_run11_alignment"
                if computed_on_run11_alignment
                else "governed_run11_alignment_missing_used_governed_surrogate_alignment"
            ),
        },
        "fit_metric_provenance": _fit_metric_payload(existing_payload),
        "coverage_context": {
            "auto_road_length_m": auto_length,
            "manual_road_length_m": manual_length,
            "coverage_ratio_auto_to_manual": coverage_ratio,
            "road_length_delta_m": auto_length - manual_length,
            "bbox_iou": bbox_iou,
            "bbox_iou_method": "planView_geometry_envelope_iou_from_geometry_start_and_end_points",
            "partial_overlap": True,
            "major_coverage_mismatch": bool(
                coverage_ratio is not None and abs(float(coverage_ratio) - 1.0) >= 0.25
            ),
            "interpretation": (
                "Whole-network structural metrics must be interpreted under partial overlap and a large "
                "coverage mismatch; they do not isolate matched-area local registration quality."
            ),
        },
        "computed_metrics": {
            "computed_on_run11_alignment": bool(computed_on_run11_alignment),
            "run11_alignment_artifact_status": (
                "present" if computed_on_run11_alignment else "missing_in_governed_worktree"
            ),
            "computed_on_governed_surrogate_alignment": bool(not computed_on_run11_alignment),
            "governed_surrogate_run_id": str(args.surrogate_run_id or ""),
            "auto_xodr": auto_xodr.as_posix(),
            "manual_xodr": manual_xodr.as_posix(),
            "curvature_kl_divergence": _stable_float(curvature.get("kl_divergence")),
            "semantic_gap_normalized": _stable_float(semantic_gap),
            "intersection_gap_normalized": _stable_float(intersection.get("normalized_gap")),
            "auto_road_length_m": auto_length,
            "manual_road_length_m": manual_length,
            "metric_source_modules": [
                "ultimate_pipeline.domain_gap.curvature_gap.CurvatureGap.compute",
                "ultimate_pipeline.domain_gap.semantic_gap.SemanticGap.compute",
                "ultimate_pipeline.domain_gap.intersection_gap.IntersectionGap.compute",
                "ultimate_pipeline.run_full_domain_gap._normalized_l1_over2",
            ],
            "notes": [
                (
                    "Metrics were recomputed offline from the governed run_11 aligned pair."
                    if computed_on_run11_alignment
                    else "Metrics were recomputed offline from a governed surrogate aligned pair because a governed run_11 aligned XODR pair is not present."
                ),
                "Values should be interpreted as 2D planView structural metrics only.",
            ],
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
