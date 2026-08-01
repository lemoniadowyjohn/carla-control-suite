from __future__ import annotations

import xml.etree.ElementTree as ET
import math
from pathlib import Path

from ultimate_pipeline.domain_gap.tile_gap_evaluator import TileGapEvaluator
from ultimate_pipeline.run_full_domain_gap import _build_tile_iou_gate_summary


def _write_line_xodr(
    path: Path,
    x0: float,
    y0: float,
    length: float = 10.0,
    hdg: float = 0.0,
) -> None:
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1", length=str(length), junction="-1")
    plan = ET.SubElement(road, "planView")
    ET.SubElement(
        plan,
        "geometry",
        s="0.0",
        x=str(x0),
        y=str(y0),
        hdg=str(hdg),
        length=str(length),
    )
    tree = ET.ElementTree(root)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def test_compute_skips_unmatched_low_iou_status(tmp_path: Path) -> None:
    manual = tmp_path / "manual.xodr"
    auto = tmp_path / "auto.xodr"
    _write_line_xodr(manual, 0.0, 0.0)
    _write_line_xodr(auto, 0.0, 0.0)

    result = TileGapEvaluator.compute(
        str(manual),
        str(auto),
        match_status="unmatched_low_iou",
        matched_iou=0.9,
    )

    assert result["status"] == "skipped_low_iou"
    assert result["disabled"] is True
    assert result["rmse"] is None
    assert result["hausdorff"] is None
    assert result["skip_reason"] == "tile_match_status=unmatched_low_iou"


def test_compute_skips_when_iou_below_threshold(tmp_path: Path) -> None:
    manual = tmp_path / "manual.xodr"
    auto = tmp_path / "auto.xodr"
    _write_line_xodr(manual, 0.0, 0.0)
    _write_line_xodr(auto, 0.0, 0.0)

    result = TileGapEvaluator.compute(
        str(manual),
        str(auto),
        matched_iou=0.2,
        min_iou=0.5,
    )

    assert result["status"] == "skipped_low_iou"
    assert result["disabled"] is True
    assert result["reason"] == "iou_below_threshold"
    assert result["rmse"] is None
    assert result["hausdorff"] is None
    assert result["matched_iou"] == 0.2
    assert result["min_iou_for_gap"] == 0.5


def test_compute_still_scores_when_iou_meets_threshold(tmp_path: Path) -> None:
    manual = tmp_path / "manual.xodr"
    auto = tmp_path / "auto.xodr"
    _write_line_xodr(manual, 0.0, 0.0)
    _write_line_xodr(auto, 0.0, 0.0)

    result = TileGapEvaluator.compute(
        str(manual),
        str(auto),
        matched_iou=0.8,
        min_iou=0.5,
    )

    assert result["status"] == "ok"
    assert result["rmse"] == 0.0
    assert result["rmse_cropped"] is None
    assert result["hausdorff"] == 0.0


def test_compute_reports_finite_rmse_cropped_for_real_overlap(tmp_path: Path) -> None:
    manual = tmp_path / "manual_overlap.xodr"
    auto = tmp_path / "auto_overlap.xodr"
    diagonal = math.pi / 4.0
    _write_line_xodr(manual, 0.0, 0.0, length=10.0, hdg=diagonal)
    _write_line_xodr(auto, 1.0, 1.0, length=10.0, hdg=diagonal)

    result = TileGapEvaluator.compute(
        str(manual),
        str(auto),
        matched_iou=0.8,
        min_iou=0.5,
    )

    assert result["status"] == "ok"
    assert result["rmse"] is not None
    assert result["rmse_cropped"] is not None
    assert math.isfinite(result["rmse_cropped"])


def test_compute_reports_none_rmse_cropped_when_overlap_area_is_zero(tmp_path: Path) -> None:
    manual = tmp_path / "manual_disjoint.xodr"
    auto = tmp_path / "auto_disjoint.xodr"
    diagonal = math.pi / 4.0
    _write_line_xodr(manual, 0.0, 0.0, length=10.0, hdg=diagonal)
    _write_line_xodr(auto, 20.0, 20.0, length=10.0, hdg=diagonal)

    result = TileGapEvaluator.compute(
        str(manual),
        str(auto),
        matched_iou=0.8,
        min_iou=0.5,
    )

    assert result["status"] == "ok"
    assert result["rmse"] is not None
    assert result["rmse_cropped"] is None


def test_iou_gate_summary_reports_authoritative_gated_case() -> None:
    summary = _build_tile_iou_gate_summary(
        [{"a_id": "tile_0_0", "b_id": "tile_0_0", "iou": 0.1166}],
        iou_gate_threshold=0.2,
        tiles_passed_gate_count=0,
        tiles_gated_count=1,
    )

    assert summary["tiles_gated_count"] == 1
    assert summary["tiles_passed_gate_count"] == 0
    assert summary["max_tile_iou_observed"] == 0.1166
    assert summary["iou_gate_threshold"] == 0.2
