from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
RUN11_DIR = REPO_ROOT / "thesis_results" / "structural_gap_v1" / "run_11"
RUN03_REPORT = REPO_ROOT / "thesis_results" / "structural_gap_v1" / "run_03" / "full_report.json"
RUN11_REPORT = RUN11_DIR / "full_report.json"
RUN11_OBJECT_GAP = RUN11_DIR / "object_gap_table.json"
RUN11_SUPPLEMENTARY = RUN11_DIR / "supplementary_metrics.json"
RUN12_CONNECTIVITY = REPO_ROOT / "thesis_results" / "structural_gap_v1" / "run_12" / "connectivity_gap.json"
TILE_IOU_REPORT = REPO_ROOT / "thesis_results" / "tile_analysis" / "tile_iou_report.json"
CURVATURE_BASIS = REPO_ROOT / "docs" / "submission" / "CURVATURE_CLAIM_BASIS.json"
DETERMINISM_REPORT = (
    REPO_ROOT
    / "artifacts"
    / "final_runs"
    / "scenario_b_audit"
    / "evidence"
    / "determinism"
    / "determinism_report.json"
)

OUT_COMBINED = RUN11_DIR / "full_report_combined.json"
OUT_SUMMARY = RUN11_DIR / "summary.csv"
CANONICAL_MANUAL_XODR = "cities/ingolstadt/manual_grid0828.xodr"
CANONICAL_AUTO_XODR = "artifacts/final_runs/scenario_b_audit/contract_run/08_final_structural_gap.xodr"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"Expected object in {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["metric", "value", "unit", "source", "notes"])
        writer.writeheader()
        writer.writerows(rows)


def _junction_ratio(connectivity: dict[str, Any]) -> float:
    manual = float(
        (((connectivity.get("manual") or {}).get("junction_degree") or {}).get("total_connections_per_junction") or {}).get(
            "count", 0
        )
    )
    auto = float(
        (((connectivity.get("auto") or {}).get("junction_degree") or {}).get("total_connections_per_junction") or {}).get(
            "count", 0
        )
    )
    return auto / manual if manual else 0.0


def _tile_gate_summary(tile_iou: dict[str, Any]) -> dict[str, Any]:
    total = int(tile_iou.get("total_tiles", 0) or 0)
    passed = int(tile_iou.get("tiles_above_0.5", 0) or 0)
    return {
        "max_tile_iou_observed": float(tile_iou.get("max_iou", 0.0) or 0.0),
        "mean_tile_iou_observed": float(tile_iou.get("mean_iou", 0.0) or 0.0),
        "tiles_passed_gate_count": passed,
        "tiles_gated_count": max(total - passed, 0),
        "iou_gate_threshold": 0.5,
        "finding": tile_iou.get("finding", ""),
    }


def main() -> int:
    run11 = _read_json(RUN11_REPORT)
    run03 = _read_json(RUN03_REPORT)
    object_gap = _read_json(RUN11_OBJECT_GAP)
    supplementary = _read_json(RUN11_SUPPLEMENTARY)
    connectivity = _read_json(RUN12_CONNECTIVITY)
    tile_iou = _read_json(TILE_IOU_REPORT)
    curvature_basis = _read_json(CURVATURE_BASIS)
    determinism = _read_json(DETERMINISM_REPORT)

    corrected_curvature = dict(curvature_basis.get("corrected_curvature") or {})
    geometry = dict(((run11.get("structural_domain_gap") or {}).get("geometry") or {}))
    intersection = dict((((run03.get("aggregation") or {}).get("components") or {}).get("intersection") or {}))
    road_classification = dict(
        ((((run03.get("aggregation") or {}).get("components") or {}).get("road_classification") or {}))
    )
    semantic = dict((((run03.get("aggregation") or {}).get("components") or {}).get("semantic") or {}))
    tile_gate_summary = _tile_gate_summary(tile_iou)
    coverage_context = dict((supplementary.get("coverage_context") or {}))
    fit_metric_provenance = dict((supplementary.get("fit_metric_provenance") or {}))
    aligned_auto = RUN11_DIR / "auto_aligned_rigid.xodr"

    combined: dict[str, Any] = {
        "schema_version": 1,
        "status": "reconciled_companion",
        "manual_xodr": CANONICAL_MANUAL_XODR,
        "auto_xodr": CANONICAL_AUTO_XODR,
        "aligned_auto_xodr": aligned_auto.as_posix() if aligned_auto.is_file() else None,
        "source_crs": run11.get("source_crs"),
        "target_crs": run11.get("target_crs"),
        "alignment": run11.get("alignment"),
        "structural_domain_gap": {
            "geometry": geometry,
            "curvature": corrected_curvature,
            "intersection": intersection,
            "road_classification": road_classification,
            "semantic": semantic,
            "object_gap_table": object_gap,
            "connectivity": connectivity,
            "elevation": {
                "disabled": True,
                "reason": "planar_map_dem_unavailable",
            },
        },
        "tile_iou_gate_summary": tile_gate_summary,
        "determinism": {
            "status": determinism.get("status"),
            "verdict": determinism.get("verdict"),
            "runs_requested": determinism.get("runs_requested"),
            "runs_successful": determinism.get("runs_successful"),
            "coefficient_of_variation": determinism.get("coefficient_of_variation"),
        },
        "coverage_context": coverage_context,
        "fit_metric_provenance": fit_metric_provenance,
        "provenance": {
            "geometry_source": "thesis_results/structural_gap_v1/run_11/full_report.json",
            "corrected_curvature_source": "docs/submission/CURVATURE_CLAIM_BASIS.json",
            "intersection_source": "thesis_results/structural_gap_v1/run_03/full_report.json",
            "road_classification_source": "thesis_results/structural_gap_v1/run_03/full_report.json",
            "semantic_source": "thesis_results/structural_gap_v1/run_11/object_gap_table.json",
            "connectivity_source": "thesis_results/structural_gap_v1/run_12/connectivity_gap.json",
            "tile_iou_source": "thesis_results/tile_analysis/tile_iou_report.json",
            "determinism_source": "artifacts/final_runs/scenario_b_audit/evidence/determinism/determinism_report.json",
            "combined_by": "T-COMBINED-REPORT-001",
            "canonical_manual_xodr": CANONICAL_MANUAL_XODR,
            "canonical_auto_xodr": CANONICAL_AUTO_XODR,
            "notes": (
                "Convenience artifact only. It does not replace the authoritative source artifacts named above. "
                "run_11 remains the geometry authority; corrected curvature comes from the governed basis file; "
                "connectivity comes from the governed run_12 companion artifact."
            ),
        },
    }

    summary_rows = [
        {
            "metric": "geometry_rmse_whole_map",
            "value": geometry.get("rmse"),
            "unit": "m",
            "source": "run_11",
            "notes": "Whole-network geometry gap after CRS reprojection and rigid SE(2) alignment with scale locked to 1.0.",
        },
        {
            "metric": "geometry_rmse_matched_subset",
            "value": geometry.get("rmse_matched"),
            "unit": "m",
            "source": "run_11",
            "notes": "Matched-subset RMSE at the 50 m correspondence threshold.",
        },
        {
            "metric": "matched_fraction",
            "value": geometry.get("matched_fraction"),
            "unit": "ratio",
            "source": "run_11",
            "notes": "Fraction of manual-road samples matched within 50 m after alignment.",
        },
        {
            "metric": "hausdorff_distance",
            "value": geometry.get("hausdorff"),
            "unit": "m",
            "source": "run_11",
            "notes": "Whole-network Hausdorff distance after rigid alignment.",
        },
        {
            "metric": "bbox_iou_after_reprojection",
            "value": geometry.get("bbox_iou_after_reprojection"),
            "unit": "ratio",
            "source": "run_11",
            "notes": "Bounding-box IoU after explicit CRS reprojection into the manual frame.",
        },
        {
            "metric": "rigid_scale_fixed",
            "value": geometry.get("rigid_scale_fixed"),
            "unit": "ratio",
            "source": "run_11",
            "notes": "Alignment scale lock; must remain 1.0.",
        },
        {
            "metric": "corrected_curvature_kl_divergence",
            "value": corrected_curvature.get("kl_divergence"),
            "unit": "nats",
            "source": "docs/submission/CURVATURE_CLAIM_BASIS.json",
            "notes": "Corrected paramPoly3-aware curvature comparison on the authoritative run_11 measurement pair.",
        },
        {
            "metric": "corrected_curvature_std_auto",
            "value": corrected_curvature.get("std_auto"),
            "unit": "m-1",
            "source": "docs/submission/CURVATURE_CLAIM_BASIS.json",
            "notes": "Auto-map curvature standard deviation from the corrected curvature basis.",
        },
        {
            "metric": "corrected_curvature_std_manual",
            "value": corrected_curvature.get("std_manual"),
            "unit": "m-1",
            "source": "docs/submission/CURVATURE_CLAIM_BASIS.json",
            "notes": "Manual-map curvature standard deviation from the corrected curvature basis.",
        },
        {
            "metric": "road_length_ratio",
            "value": coverage_context.get("coverage_ratio_auto_to_manual"),
            "unit": "ratio",
            "source": "run_11/supplementary_metrics.json",
            "notes": "Auto total road length divided by manual total road length in the governed coverage context.",
        },
        {
            "metric": "junction_count_ratio",
            "value": _junction_ratio(connectivity),
            "unit": "ratio",
            "source": "run_12/connectivity_gap.json",
            "notes": "Auto junction count divided by manual junction count from the governed connectivity companion artifact.",
        },
        {
            "metric": "connectivity_auto_predecessor_declared_rate",
            "value": (((connectivity.get("auto") or {}).get("road_link") or {}).get("predecessor_declared_rate")),
            "unit": "rate",
            "source": "run_12/connectivity_gap.json",
            "notes": "Fraction of auto roads that declare a predecessor in OpenDRIVE XML.",
        },
        {
            "metric": "connectivity_auto_successor_declared_rate",
            "value": (((connectivity.get("auto") or {}).get("road_link") or {}).get("successor_declared_rate")),
            "unit": "rate",
            "source": "run_12/connectivity_gap.json",
            "notes": "Fraction of auto roads that declare a successor in OpenDRIVE XML.",
        },
        {
            "metric": "connectivity_junction_lane_link_completeness",
            "value": (((connectivity.get("auto") or {}).get("lane_link") or {}).get("junction_lane_link_completeness_rate")),
            "unit": "rate",
            "source": "run_12/connectivity_gap.json",
            "notes": "Fraction of auto junction laneLink elements with both from/to attributes populated.",
        },
        {
            "metric": "tile_max_iou",
            "value": tile_gate_summary.get("max_tile_iou_observed"),
            "unit": "ratio",
            "source": "tile_analysis",
            "notes": "Maximum per-tile spatial overlap between auto and manual tiles.",
        },
        {
            "metric": "tiles_passing_iou_gate",
            "value": tile_gate_summary.get("tiles_passed_gate_count"),
            "unit": "count",
            "source": "tile_analysis",
            "notes": "Tiles with IoU at or above the 0.5 thesis gate.",
        },
        {
            "metric": "determinism_road_count_cv",
            "value": ((determinism.get("coefficient_of_variation") or {}).get("road_count")),
            "unit": "cv",
            "source": "rq1_audit",
            "notes": "Coefficient of variation of road count across the restored 5-run determinism audit.",
        },
        {
            "metric": "determinism_junction_count_cv",
            "value": ((determinism.get("coefficient_of_variation") or {}).get("junction_count")),
            "unit": "cv",
            "source": "rq1_audit",
            "notes": "Coefficient of variation of junction count across the restored 5-run determinism audit.",
        },
    ]

    _write_json(OUT_COMBINED, combined)
    _write_summary_csv(OUT_SUMMARY, summary_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
