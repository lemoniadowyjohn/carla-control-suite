from __future__ import annotations

import math
from pathlib import Path
from textwrap import dedent

import pytest

from ultimate_pipeline.roadrunner import (
    AlignmentMetrics,
    BoundingBox,
    compute_alignment,
    extract_mesh_bbox_points,
    extract_xodr_points,
)
from ultimate_pipeline.roadrunner.exceptions import RoadRunnerContractError


_XODR_SIMPLE = dedent("""\
<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
  <header revMajor="1" revMinor="4" name="test" version="1.00" date="2026-07-28" north="0" south="0" east="0" west="0"/>
  <road id="1" junction="-1" length="100.0">
    <planView>
      <geometry s="0.0" x="0.0" y="0.0" hdg="0.0" length="100.0">
        <line/>
      </geometry>
    </planView>
    <lanes>
      <laneSection s="0.0">
        <center><lane id="0" type="driving" level="0"/></center>
      </laneSection>
    </lanes>
  </road>
  <road id="2" junction="-1" length="50.0">
    <planView>
      <geometry s="0.0" x="100.0" y="50.0" hdg="0.0" length="50.0">
        <line/>
      </geometry>
    </planView>
    <lanes>
      <laneSection s="0.0">
        <center><lane id="0" type="driving" level="0"/></center>
      </laneSection>
    </lanes>
  </road>
</OpenDRIVE>
""")


@pytest.fixture
def simple_xodr(tmp_path: Path) -> Path:
    p = tmp_path / "simple.xodr"
    p.write_text(_XODR_SIMPLE, encoding="utf-8")
    return p


class TestAlignmentMetrics:
    def test_valid_metrics(self) -> None:
        m = AlignmentMetrics(
            scale=1.0,
            translation_x=0.0,
            translation_y=0.0,
            heading_deg=0.0,
            y_inverted=False,
            rmse=0.0,
            point_count=10,
        )
        assert m.scale == 1.0
        assert m.rmse == 0.0

    def test_rejects_negative_scale(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="positive"):
            AlignmentMetrics(
                scale=-1.0, translation_x=0, translation_y=0, heading_deg=0,
                y_inverted=False, rmse=0, point_count=0,
            )

    def test_rejects_negative_rmse(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="non-negative"):
            AlignmentMetrics(
                scale=1.0, translation_x=0, translation_y=0, heading_deg=0,
                y_inverted=False, rmse=-0.1, point_count=0,
            )


class TestComputeAlignment:
    def test_identical_points(self) -> None:
        pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        result = compute_alignment(pts, pts)
        assert abs(result.scale - 1.0) < 0.01
        assert abs(result.translation_x) < 0.01
        assert abs(result.heading_deg) < 0.01
        assert result.y_inverted is False
        assert result.point_count == 4

    def test_translation(self) -> None:
        src = [(0.0, 0.0), (1.0, 0.0)]
        dst = [(5.0, 10.0), (6.0, 10.0)]
        result = compute_alignment(src, dst)
        assert abs(result.translation_x - 5.0) < 0.1
        assert abs(result.translation_y - 10.0) < 0.1

    def test_y_inversion_detected(self) -> None:
        src = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
        dst = [(0.0, 0.0), (1.0, 0.0), (0.0, -1.0), (1.0, -1.0)]
        result = compute_alignment(src, dst, detect_y_inv=True)
        assert result.y_inverted is True
        assert any("y_inversion" in n for n in result.notes)

    def test_y_inversion_skippable(self) -> None:
        src = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
        dst = [(0.0, 0.0), (1.0, 0.0), (0.0, -1.0), (1.0, -1.0)]
        result = compute_alignment(src, dst, detect_y_inv=False)
        assert result.y_inverted is False

    def test_empty_points_raises(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="non-empty"):
            compute_alignment([], [(0.0, 0.0)])

    def test_single_point_raises(self) -> None:
        with pytest.raises(RoadRunnerContractError, match="at least 2"):
            compute_alignment([(0.0, 0.0)], [(1.0, 1.0)])

    def test_scale_detection(self) -> None:
        src = [(0.0, 0.0), (0.0, 1.0)]
        dst = [(0.0, 0.0), (0.0, 2.0)]
        result = compute_alignment(src, dst)
        assert abs(result.scale - 2.0) < 0.1

    def test_heading_estimation(self) -> None:
        src = [(0.0, 0.0), (1.0, 0.0)]
        dst = [(0.0, 0.0), (0.0, 1.0)]
        result = compute_alignment(src, dst)
        assert abs(abs(result.heading_deg) - 90.0) < 5.0


class TestDetectYInversion:
    def test_no_inversion_flat(self) -> None:
        from ultimate_pipeline.roadrunner.alignment import detect_y_inversion
        src = [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)]
        dst = [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)]
        assert detect_y_inversion(src, dst) is False

    def test_inverted(self) -> None:
        from ultimate_pipeline.roadrunner.alignment import detect_y_inversion
        src = [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)]
        dst = [(0.0, 0.0), (1.0, -1.0), (2.0, -2.0)]
        assert detect_y_inversion(src, dst) is True

    def test_insufficient_points(self) -> None:
        from ultimate_pipeline.roadrunner.alignment import detect_y_inversion
        assert detect_y_inversion([(0.0, 0.0)], [(1.0, 1.0)]) is False


class TestExtractXodrPoints:
    def test_extracts_from_valid_xodr(self, simple_xodr: Path) -> None:
        pts = extract_xodr_points(simple_xodr)
        assert len(pts) >= 4

    def test_invalid_xml_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.xodr"
        p.write_text("<not-xodr/>", encoding="utf-8")
        with pytest.raises(RoadRunnerContractError, match="OpenDRIVE"):
            extract_xodr_points(p)


class TestExtractMeshBboxPoints:
    def test_corner_points(self) -> None:
        bbox = BoundingBox(min_x=0, min_y=0, min_z=0, max_x=10, max_y=20, max_z=5)
        pts = extract_mesh_bbox_points(bbox)
        assert len(pts) == 4
        assert (0, 0) in pts
        assert (10, 0) in pts
        assert (0, 20) in pts
        assert (10, 20) in pts
