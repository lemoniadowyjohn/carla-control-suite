# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/quality/lane_width_invariants.py.

Live: main_pipeline.py imports both default_report_path and
enforce_lane_width_invariants_on_root at module level. Zero prior test
coverage. Reviewed for the same class of bug found earlier this session
in lane_width_clamp.py (an XPath depth mismatch that made a safety clamp
a silent no-op against real 3-level-nested laneSection/side/lane
structure) -- this file's _iter_lane_contexts correctly uses
`lane_section.findall(".//lane")` (any depth), so no bug found here.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.quality.lane_width_invariants import (
    default_report_path,
    enforce_lane_width_invariants,
    enforce_lane_width_invariants_on_root,
    write_lane_width_invariants_report,
)


def _road_with_lane(lane_id: str, lane_type: str, with_width: bool) -> str:
    width_xml = '<width sOffset="0" a="3.5" b="0" c="0" d="0"/>' if with_width else ""
    return (
        f'<road name="r1" length="10" id="1" junction="-1">'
        f'<planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>'
        f"<lanes><laneSection s=\"0\">"
        f'<center><lane id="0" type="driving" level="false"/></center>'
        f'<right><lane id="{lane_id}" type="{lane_type}" level="false">{width_xml}</lane></right>'
        f"</laneSection></lanes>"
        f"</road>"
    )


def _parse(xml_body: str) -> ET.Element:
    return ET.fromstring(f'<OpenDRIVE>{xml_body}</OpenDRIVE>')


# ---------------------------------------------------------------------------
# default_report_path
# ---------------------------------------------------------------------------


def test_default_report_path_creates_qa_stage_reports_dir_and_names_file(tmp_path):
    path = default_report_path(tmp_path, "08_final")
    assert Path(path).parent == tmp_path / "qa_stage_reports"
    assert (tmp_path / "qa_stage_reports").is_dir()
    assert path.endswith("08_final__lane_width_invariants.json")


def test_default_report_path_sanitizes_unsafe_stage_characters(tmp_path):
    path = default_report_path(tmp_path, "08/final stage!")
    assert "/" not in Path(path).name
    assert " " not in Path(path).name
    assert "!" not in Path(path).name


# ---------------------------------------------------------------------------
# enforce_lane_width_invariants_on_root
# ---------------------------------------------------------------------------


def test_inserts_default_width_for_lane_missing_it():
    root = _parse(_road_with_lane("-1", "driving", with_width=False))
    rep = enforce_lane_width_invariants_on_root(root, default_width_m=3.5)

    assert rep["ok"] is True
    assert rep["severity"] == "warn"
    assert rep["totals"]["missing_width_lanes_found"] == 1
    assert rep["totals"]["missing_width_lanes_fixed"] == 1
    assert rep["totals"]["missing_width_lanes_unfixed"] == 0

    lane = root.find(".//lane[@id='-1']")
    width = lane.find("width")
    assert width is not None
    assert width.attrib["a"] == "3.500"


def test_lane_already_has_width_is_left_untouched():
    root = _parse(_road_with_lane("-1", "driving", with_width=True))
    rep = enforce_lane_width_invariants_on_root(root)

    assert rep["ok"] is True
    assert rep["severity"] == "pass"
    assert rep["totals"]["missing_width_lanes_found"] == 0
    lane = root.find(".//lane[@id='-1']")
    assert len(lane.findall("width")) == 1


def test_center_lane_id_zero_never_requires_width():
    root = _parse(_road_with_lane("-1", "driving", with_width=True))
    rep = enforce_lane_width_invariants_on_root(root)
    center_lane = root.find(".//lane[@id='0']")
    assert center_lane.find("width") is None
    # center lane's absence of width must never be counted as a violation
    assert rep["totals"]["missing_width_lanes_found"] == 0


def test_lane_type_outside_allowed_set_is_skipped():
    root = _parse(_road_with_lane("-1", "bidirectional", with_width=False))
    rep = enforce_lane_width_invariants_on_root(
        root, lane_types=("driving", "shoulder")
    )
    assert rep["totals"]["missing_width_lanes_found"] == 0
    lane = root.find(".//lane[@id='-1']")
    assert lane.find("width") is None


def test_lane_missing_type_attribute_is_conservatively_enforced():
    # An empty/missing type attribute must not be treated as "some excluded
    # type" -- the code's own docstring says "be conservative: enforce".
    root = _parse(_road_with_lane("-1", "", with_width=False))
    rep = enforce_lane_width_invariants_on_root(root)
    assert rep["totals"]["missing_width_lanes_found"] == 1
    assert rep["totals"]["missing_width_lanes_fixed"] == 1


def test_nested_laneseparation_at_any_depth_is_found():
    # Real OpenDRIVE nests <lane> as laneSection/{left,center,right}/lane --
    # confirm this module (unlike the separate lane_width_clamp.py bug
    # found earlier) correctly searches at that depth, not just direct
    # children of <laneSection>.
    root = _parse(_road_with_lane("-1", "driving", with_width=False))
    lane = root.find(".//lane[@id='-1']")
    assert lane.find("width") is None
    rep = enforce_lane_width_invariants_on_root(root)
    assert rep["totals"]["missing_width_lanes_found"] == 1


def test_examples_list_is_capped_at_max_examples():
    roads_xml = "".join(
        f'<road name="r{i}" length="10" id="{i}" junction="-1">'
        f'<planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>'
        f'<lanes><laneSection s="0">'
        f'<right><lane id="-1" type="driving" level="false"/></right>'
        f"</laneSection></lanes></road>"
        for i in range(1, 6)
    )
    root = _parse(roads_xml)
    rep = enforce_lane_width_invariants_on_root(root, max_examples=2)
    assert rep["totals"]["missing_width_lanes_found"] == 5
    assert len(rep["examples"]) == 2


# ---------------------------------------------------------------------------
# write_lane_width_invariants_report
# ---------------------------------------------------------------------------


def test_write_lane_width_invariants_report_writes_valid_json(tmp_path):
    rep = {"ok": True, "severity": "pass"}
    path = write_lane_width_invariants_report(rep, tmp_path)
    assert Path(path).name == "lane_width_invariants_report.json"
    on_disk = json.loads(Path(path).read_text(encoding="utf-8"))
    assert on_disk == rep


# ---------------------------------------------------------------------------
# enforce_lane_width_invariants (file-based wrapper)
# ---------------------------------------------------------------------------


def test_file_based_wrapper_writes_back_xodr_only_when_fixed(tmp_path):
    xodr = tmp_path / "in.xodr"
    xodr.write_text(
        f'<?xml version="1.0"?><OpenDRIVE>{_road_with_lane("-1", "driving", False)}</OpenDRIVE>',
        encoding="utf-8",
    )
    before = xodr.read_text(encoding="utf-8")

    report_path = tmp_path / "report.json"
    rep = enforce_lane_width_invariants(str(xodr), report_path=str(report_path))

    assert rep["totals"]["missing_width_lanes_fixed"] == 1
    assert rep["stage"] == "lane_width_invariants"
    assert rep["xodr_path"] == str(xodr)

    after = xodr.read_text(encoding="utf-8")
    assert after != before  # file was rewritten with the inserted <width>
    assert "<width" in after

    on_disk_report = json.loads(report_path.read_text(encoding="utf-8"))
    assert on_disk_report["totals"]["missing_width_lanes_fixed"] == 1


def test_file_based_wrapper_does_not_rewrite_file_when_nothing_missing(tmp_path):
    xodr = tmp_path / "in.xodr"
    xodr.write_text(
        f'<?xml version="1.0"?><OpenDRIVE>{_road_with_lane("-1", "driving", True)}</OpenDRIVE>',
        encoding="utf-8",
    )
    before_mtime = xodr.stat().st_mtime_ns
    before_bytes = xodr.read_bytes()

    enforce_lane_width_invariants(str(xodr))

    assert xodr.read_bytes() == before_bytes
    assert xodr.stat().st_mtime_ns == before_mtime
