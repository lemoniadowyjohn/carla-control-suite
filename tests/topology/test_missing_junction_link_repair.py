"""Tests for ultimate_pipeline/topology/missing_junction_link_repair.py.

Zero prior test coverage despite being wired into
stage_02_topology_semantics.py's step 2A-pre, which runs on every real
pipeline invocation before TopologyLinter, to strip <predecessor|successor
elementType="junction" elementId="X"> refs where junction X does not exist
(preventing TL-003 errors and strict-validator crashes).
"""
from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.topology.missing_junction_link_repair import (
    repair_missing_junction_links,
    repair_missing_junction_links_file,
)


def _root(xml_body: str) -> ET.Element:
    return ET.fromstring(f'<?xml version="1.0"?>\n<OpenDRIVE>\n{xml_body}\n</OpenDRIVE>')


def test_removes_predecessor_ref_to_missing_junction():
    root = _root(
        """
  <road id="1">
    <link><predecessor elementType="junction" elementId="99" contactPoint="start"/></link>
  </road>
"""
    )
    report = repair_missing_junction_links(root)
    assert report["num_removed"] == 1
    assert report["roads_affected"] == ["1"]
    assert report["missing_junction_ids_referenced"] == ["99"]

    road = root.find("./road[@id='1']")
    link = road.find("link")
    # Link element removed entirely since it's now empty.
    assert link is None


def test_removes_successor_ref_to_missing_junction():
    root = _root(
        """
  <road id="1">
    <link><successor elementType="junction" elementId="42" contactPoint="end"/></link>
  </road>
"""
    )
    report = repair_missing_junction_links(root)
    assert report["num_removed"] == 1
    removal = report["removals"][0]
    assert removal["road_id"] == "1"
    assert removal["link_type"] == "successor"
    assert removal["missing_junction_id"] == "42"


def test_keeps_valid_junction_ref():
    root = _root(
        """
  <junction id="10"/>
  <road id="1">
    <link><predecessor elementType="junction" elementId="10" contactPoint="start"/></link>
  </road>
"""
    )
    report = repair_missing_junction_links(root)
    assert report["num_removed"] == 0
    road = root.find("./road[@id='1']")
    link = road.find("link")
    assert link is not None
    assert link.find("predecessor") is not None


def test_keeps_road_type_link_untouched():
    """Only elementType="junction" refs are ever removed; road links are left alone
    even if the target road id does not exist (that's TopologyLinter/TopologyRepair's job)."""
    root = _root(
        """
  <road id="1">
    <link><predecessor elementType="road" elementId="999" contactPoint="start"/></link>
  </road>
"""
    )
    report = repair_missing_junction_links(root)
    assert report["num_removed"] == 0
    road = root.find("./road[@id='1']")
    link = road.find("link")
    assert link is not None
    assert link.find("predecessor") is not None


def test_mixed_link_removes_only_invalid_junction_entry():
    root = _root(
        """
  <junction id="5"/>
  <road id="1">
    <link>
      <predecessor elementType="junction" elementId="5" contactPoint="start"/>
      <successor elementType="junction" elementId="404" contactPoint="end"/>
    </link>
  </road>
"""
    )
    report = repair_missing_junction_links(root)
    assert report["num_removed"] == 1
    road = root.find("./road[@id='1']")
    link = road.find("link")
    assert link is not None
    assert link.find("predecessor") is not None
    assert link.find("successor") is None


def test_no_junctions_no_roads_no_crash():
    root = _root("")
    report = repair_missing_junction_links(root)
    assert report["ok"] is True
    assert report["num_removed"] == 0
    assert report["num_junctions_in_file"] == 0


def test_road_without_link_element_skipped():
    root = _root('<road id="1"/>')
    report = repair_missing_junction_links(root)
    assert report["num_removed"] == 0


def test_report_written_to_logs_dir(tmp_path):
    root = _root(
        """
  <road id="1">
    <link><predecessor elementType="junction" elementId="7" contactPoint="start"/></link>
  </road>
"""
    )
    logs_dir = str(tmp_path / "logs")
    report = repair_missing_junction_links(root, logs_dir=logs_dir)
    report_path = os.path.join(logs_dir, "missing_junction_link_repair.json")
    assert os.path.exists(report_path)
    with open(report_path, encoding="utf-8") as f:
        on_disk = json.load(f)
    assert on_disk["num_removed"] == report["num_removed"]


def test_removals_truncated_flag_and_cap():
    body_lines = []
    for i in range(150):
        body_lines.append(
            f'<road id="{i}"><link><predecessor elementType="junction" '
            f'elementId="missing{i}" contactPoint="start"/></link></road>'
        )
    root = _root("\n".join(body_lines))
    report = repair_missing_junction_links(root)
    assert report["num_removed"] == 150
    assert len(report["removals"]) == 100
    assert report["removals_truncated"] is True


def test_repair_missing_junction_links_file_modifies_disk_when_removed(tmp_path):
    xodr_path = tmp_path / "map.xodr"
    xodr_path.write_text(
        '<?xml version="1.0"?>\n<OpenDRIVE>\n'
        '<road id="1"><link><predecessor elementType="junction" '
        'elementId="99" contactPoint="start"/></link></road>\n'
        "</OpenDRIVE>",
        encoding="utf-8",
    )
    report = repair_missing_junction_links_file(str(xodr_path))
    assert report["num_removed"] == 1
    assert report["file_modified"] is True

    # Re-parse from disk to confirm the write actually happened.
    tree = ET.parse(str(xodr_path))
    road = tree.getroot().find("./road[@id='1']")
    assert road.find("link") is None


def test_repair_missing_junction_links_file_no_write_when_nothing_removed(tmp_path):
    xodr_path = tmp_path / "map.xodr"
    original = (
        '<?xml version="1.0"?>\n<OpenDRIVE>\n'
        '<junction id="10"/>\n'
        '<road id="1"><link><predecessor elementType="junction" '
        'elementId="10" contactPoint="start"/></link></road>\n'
        "</OpenDRIVE>"
    )
    xodr_path.write_text(original, encoding="utf-8")
    mtime_before = xodr_path.stat().st_mtime_ns

    report = repair_missing_junction_links_file(str(xodr_path))
    assert report["num_removed"] == 0
    assert report["file_modified"] is False
    # File should be untouched (no rewrite attempted).
    assert xodr_path.stat().st_mtime_ns == mtime_before


def test_repair_missing_junction_links_file_missing_input_raises(tmp_path):
    missing = tmp_path / "does_not_exist.xodr"
    with pytest.raises(FileNotFoundError):
        repair_missing_junction_links_file(str(missing))
