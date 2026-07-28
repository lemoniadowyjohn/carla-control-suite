from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

import pytest

from ultimate_pipeline.roadrunner import (
    compare_xodr_files,
    compare_xodr_semantic,
)
from ultimate_pipeline.roadrunner.exceptions import RoadRunnerContractError
from ultimate_pipeline.roadrunner.semantic_manifest import SemanticDiffDetail


def _sha(suffix: str = "a") -> str:
    return hashlib.sha256(suffix.encode()).hexdigest()


_XODR_FRAGMENT = dedent("""\
<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
  <header revMajor="1" revMinor="4" name="test" version="1.00" date="2026-07-28" north="0" south="0" east="0" west="0"/>
  <road id="1" junction="-1" length="100.0">
    <planView>
      <geometry s="0.0000000000000000e+00" x="0.0000000000000000e+00" y="0.0000000000000000e+00" hdg="0.0000000000000000e+00" length="100.0">
        <line/>
      </geometry>
    </planView>
    <lanes>
      <laneOffset s="0.0000000000000000e+00" a="0.0" b="0.0" c="0.0" d="0.0"/>
      <laneSection s="0.0000000000000000e+00">
        <center>
          <lane id="0" type="driving" level="0"/>
        </center>
        <right>
          <lane id="-1" type="driving" level="0">
            <width sOffset="0.0000000000000000e+00" a="3.5000000000000000e+00" b="0.0000000000000000e+00" c="0.0000000000000000e+00" d="0.0000000000000000e+00"/>
          </lane>
        </right>
        <left>
        </left>
      </laneSection>
    </lanes>
  </road>
  <road id="2" junction="-1" length="50.0">
    <planView>
      <geometry s="0.0000000000000000e+00" x="100.0" y="0.0" hdg="0.0" length="50.0">
        <line/>
      </geometry>
    </planView>
    <lanes>
      <laneOffset s="0.0000000000000000e+00" a="0.0" b="0.0" c="0.0" d="0.0"/>
      <laneSection s="0.0000000000000000e+00">
        <center>
          <lane id="0" type="driving" level="0"/>
        </center>
        <right>
          <lane id="-1" type="driving" level="0">
            <width sOffset="0.0000000000000000e+00" a="3.5000000000000000e+00" b="0.0000000000000000e+00" c="0.0000000000000000e+00" d="0.0000000000000000e+00"/>
          </lane>
        </right>
      </laneSection>
    </lanes>
  </road>
  <junction id="1">
    <connection id="0" incomingRoad="1" connectingRoad="2" contactPoint="start"/>
  </junction>
</OpenDRIVE>
""")


@pytest.fixture
def identical_xodr(tmp_path: Path) -> tuple[Path, Path]:
    p = tmp_path / "parent.xodr"
    c = tmp_path / "candidate.xodr"
    p.write_text(_XODR_FRAGMENT, encoding="utf-8")
    c.write_text(_XODR_FRAGMENT, encoding="utf-8")
    return p, c


@pytest.fixture
def modified_geometry_xodr(tmp_path: Path) -> tuple[Path, Path]:
    p = tmp_path / "parent.xodr"
    c = tmp_path / "candidate.xodr"
    p.write_text(_XODR_FRAGMENT, encoding="utf-8")
    candidate_xml = _XODR_FRAGMENT.replace('length="100.0"', 'length="120.0"')
    candidate_xml = candidate_xml.replace(
        "<line/>\n      </geometry>",
        "<line/>\n      </geometry>\n      <geometry s=\"50.0\" x=\"50.0\" y=\"0.0\" hdg=\"0.0\" length=\"70.0\">\n        <arc curvature=\"0.01\"/>\n      </geometry>",
    )
    c.write_text(candidate_xml, encoding="utf-8")
    return p, c


@pytest.fixture
def lane_diff_xodr(tmp_path: Path) -> tuple[Path, Path]:
    p = tmp_path / "parent.xodr"
    c = tmp_path / "candidate.xodr"
    p.write_text(_XODR_FRAGMENT, encoding="utf-8")
    candidate_xml = _XODR_FRAGMENT.replace(
        "</right>",
        "</right>\n        <left>\n          <lane id=\"1\" type=\"driving\" level=\"0\">\n            <width sOffset=\"0.0\" a=\"3.0\" b=\"0.0\" c=\"0.0\" d=\"0.0\"/>\n          </lane>\n        </left>",
    )
    c.write_text(candidate_xml, encoding="utf-8")
    return p, c


@pytest.fixture
def removed_lane_xodr(tmp_path: Path) -> tuple[Path, Path]:
    p = tmp_path / "parent.xodr"
    c = tmp_path / "candidate.xodr"
    p.write_text(_XODR_FRAGMENT, encoding="utf-8")
    candidate_xml = _XODR_FRAGMENT.replace(
        '<lane id="-1" type="driving" level="0">\n            <width sOffset="0.0000000000000000e+00" a="3.5000000000000000e+00" b="0.0000000000000000e+00" c="0.0000000000000000e+00" d="0.0000000000000000e+00"/>\n          </lane>',
        "",
    )
    c.write_text(candidate_xml, encoding="utf-8")
    return p, c


@pytest.fixture
def authority_escalation_xodr(tmp_path: Path) -> tuple[Path, Path]:
    p = tmp_path / "parent.xodr"
    c = tmp_path / "candidate.xodr"
    p.write_text(_XODR_FRAGMENT, encoding="utf-8")
    candidate_xml = _XODR_FRAGMENT.replace(
        '<lane id="-1" type="driving" level="0">\n            <width sOffset="0.0000000000000000e+00" a="3.5000000000000000e+00" b="0.0000000000000000e+00" c="0.0000000000000000e+00" d="0.0000000000000000e+00"/>\n          </lane>',
        '<lane id="-1" type="driving" level="0">\n            <width sOffset="0.0" a="3.5" b="0.0" c="0.0" d="0.0"/>\n          </lane>\n          <lane id="-2" type="driving" level="0">\n            <width sOffset="0.0" a="3.5" b="0.0" c="0.0" d="0.0"/>\n          </lane>',
    )
    c.write_text(candidate_xml, encoding="utf-8")
    return p, c


class TestCompareXodrSemantic:
    def test_identical_files_match(self, identical_xodr: tuple[Path, Path]) -> None:
        p, c = identical_xodr
        detail = compare_xodr_semantic(p, c)
        assert detail.roads_identical is True
        assert detail.authority_escalation is False
        assert len(detail.road_diffs) == 0
        assert len(detail.lane_diffs) == 0
        assert len(detail.junction_diffs) == 0
        summary = detail.to_summary()
        assert summary.added_elements == 0
        assert summary.removed_elements == 0
        assert summary.changed_elements == 0

    def test_compare_xodr_files_returns_summary(
        self, identical_xodr: tuple[Path, Path]
    ) -> None:
        p, c = identical_xodr
        summary = compare_xodr_files(p, c)
        assert summary.parent_sha256 == summary.candidate_sha256
        assert summary.changed_elements == 0

    def test_modified_geometry_produces_delta(
        self, modified_geometry_xodr: tuple[Path, Path]
    ) -> None:
        p, c = modified_geometry_xodr
        detail = compare_xodr_semantic(p, c)
        assert detail.roads_identical is False
        assert len(detail.road_diffs) >= 1
        road_diffs_by_id = {r.road_id: r for r in detail.road_diffs}
        assert "1" in road_diffs_by_id
        rd = road_diffs_by_id["1"]
        assert rd.status == "modified"
        assert rd.length_delta is not None
        assert abs(rd.length_delta - 20.0) < 0.01 or abs(rd.length_delta + 20.0) < 0.01
        summary = detail.to_summary()
        assert summary.changed_elements > 0

    def test_added_lane_detected(
        self, lane_diff_xodr: tuple[Path, Path]
    ) -> None:
        p, c = lane_diff_xodr
        detail = compare_xodr_semantic(p, c)
        assert detail.roads_identical is False
        lane_added = [
            l for l in detail.lane_diffs if l.status == "added" and l.lane_id == 1
        ]
        assert len(lane_added) >= 1
        summary = detail.to_summary()
        assert summary.added_elements > 0

    def test_removed_lane_detected(
        self, removed_lane_xodr: tuple[Path, Path]
    ) -> None:
        p, c = removed_lane_xodr
        detail = compare_xodr_semantic(p, c)
        assert detail.roads_identical is False
        lane_removed = [
            l for l in detail.lane_diffs if l.status == "removed" and l.lane_id == -1
        ]
        assert len(lane_removed) >= 1
        summary = detail.to_summary()
        assert summary.removed_elements > 0

    def test_authority_escalation_blocked(
        self, authority_escalation_xodr: tuple[Path, Path]
    ) -> None:
        p, c = authority_escalation_xodr
        detail = compare_xodr_semantic(p, c, detect_authority_escalation=True)
        assert detail.authority_escalation is True
        assert len(detail.authority_violations) >= 1
        summary = detail.to_summary()
        assert any("authority_escalation" in c for c in summary.critical_changes)
        assert any("lane_addition" in c for c in summary.critical_changes)

    def test_authority_escalation_skippable(
        self, authority_escalation_xodr: tuple[Path, Path]
    ) -> None:
        p, c = authority_escalation_xodr
        detail = compare_xodr_semantic(p, c, detect_authority_escalation=False)
        assert detail.authority_escalation is False
        assert len(detail.authority_violations) == 0

    def test_invalid_xml_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "invalid.xodr"
        p.write_text("<not-xodr/>", encoding="utf-8")
        c = tmp_path / "candidate.xodr"
        c.write_text("<not-xodr/>", encoding="utf-8")
        with pytest.raises(RoadRunnerContractError, match="OpenDRIVE"):
            compare_xodr_semantic(p, c)

    def test_junction_diff_detected(self, tmp_path: Path) -> None:
        p = tmp_path / "parent.xodr"
        c = tmp_path / "candidate.xodr"
        p.write_text(_XODR_FRAGMENT, encoding="utf-8")
        candidate_xml = _XODR_FRAGMENT.replace(
            "<junction id=\"1\">",
            "<junction id=\"1\">\n    <connection id=\"1\" incomingRoad=\"2\" connectingRoad=\"1\" contactPoint=\"start\"/>",
        )
        c.write_text(candidate_xml, encoding="utf-8")
        detail = compare_xodr_semantic(p, c)
        junction_diffs = [j for j in detail.junction_diffs if j.status == "modified"]
        assert len(junction_diffs) >= 1

    def test_semantic_diff_detail_roundtrip(self, identical_xodr):
        p, c = identical_xodr
        detail = compare_xodr_semantic(p, c)
        summary = detail.to_summary()
        assert isinstance(summary.parent_sha256, str)
        assert len(summary.parent_sha256) == 64
        assert isinstance(summary.candidate_sha256, str)
        assert len(summary.candidate_sha256) == 64

    def test_sha256_from_content(self, tmp_path: Path) -> None:
        p = tmp_path / "a.xodr"
        c = tmp_path / "b.xodr"
        p.write_text(_XODR_FRAGMENT, encoding="utf-8")
        c.write_text(_XODR_FRAGMENT.replace("100.0", "200.0"), encoding="utf-8")
        summary = compare_xodr_files(p, c)
        assert summary.parent_sha256 != summary.candidate_sha256
        assert summary.changed_elements > 0
