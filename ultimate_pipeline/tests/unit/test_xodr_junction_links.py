# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/map_fixes/xodr_junction_links.py.

Live: patch_junction_links is imported by main_pipeline.py (line 682) with
explicit guarded error messages if this module or export is missing. Zero
prior test coverage. Directly relevant to this branch's stated purpose
(junction/roundabout link repair).
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.map_fixes.xodr_junction_links import (
    patch_junction_links,
    patch_xodr_junction_links,
)


def _write_xodr(path: Path, road_xml: str) -> None:
    xml_text = f'<?xml version="1.0" encoding="UTF-8"?>\n<OpenDRIVE>\n{road_xml}\n</OpenDRIVE>\n'
    path.write_text(xml_text, encoding="utf-8")


def _simple_road_xml(
    road_id: str,
    x: float,
    length: float,
    junction: str = "-1",
    existing_successor_road_id: str | None = None,
    existing_predecessor_road_id: str | None = None,
) -> str:
    link_children = ""
    if existing_predecessor_road_id is not None:
        link_children += (
            f'<predecessor elementType="road" elementId="{existing_predecessor_road_id}" '
            f'contactPoint="end"/>'
        )
    if existing_successor_road_id is not None:
        link_children += (
            f'<successor elementType="road" elementId="{existing_successor_road_id}" '
            f'contactPoint="start"/>'
        )
    link_xml = f"<link>{link_children}</link>" if link_children else ""
    return (
        f'<road name="r{road_id}" length="{length}" id="{road_id}" junction="{junction}">'
        f"{link_xml}"
        f'<planView><geometry s="0" x="{x}" y="0" hdg="0" length="{length}">'
        f'<line/></geometry></planView>'
        f"</road>"
    )


def test_adds_missing_junction_successor_link(tmp_path):
    # Road "1" ends at x=10; the junction's connecting road "2" starts there.
    road1 = _simple_road_xml("1", x=0, length=10)
    road2 = _simple_road_xml("2", x=10, length=5, junction="5")
    junction_xml = (
        '<junction id="5">'
        '<connection id="0" incomingRoad="1" connectingRoad="2" contactPoint="start"/>'
        "</junction>"
    )
    in_xodr = tmp_path / "in.xodr"
    _write_xodr(in_xodr, road1 + road2 + junction_xml)

    report = patch_junction_links(
        in_xodr, tmp_path / "out.xodr", tmp_path / "report.json"
    )

    assert report["added_junction_links"] == 1
    assert report["missing_road_to_junction_links_after"] == 0

    out_root = ET.parse(tmp_path / "out.xodr").getroot()
    out_road1 = out_root.find("road[@id='1']")
    successors = out_road1.findall("link/successor")
    assert len(successors) == 1
    assert successors[0].attrib["elementType"] == "junction"
    assert successors[0].attrib["elementId"] == "5"


def test_does_not_duplicate_existing_successor_link(tmp_path):
    # Road "1" already has a successor pointing to a normal road ("99"), at
    # the SAME physical location a junction connection also needs to attach.
    # Correct behaviour: the existing link slot must not be silently
    # duplicated with a second, conflicting <successor> element -- OpenDRIVE
    # allows at most one predecessor/successor per road.
    road1 = _simple_road_xml("1", x=0, length=10, existing_successor_road_id="99")
    road2 = _simple_road_xml("2", x=10, length=5, junction="5")
    junction_xml = (
        '<junction id="5">'
        '<connection id="0" incomingRoad="1" connectingRoad="2" contactPoint="start"/>'
        "</junction>"
    )
    in_xodr = tmp_path / "in.xodr"
    _write_xodr(in_xodr, road1 + road2 + junction_xml)

    report = patch_junction_links(
        in_xodr, tmp_path / "out.xodr", tmp_path / "report.json"
    )

    out_root = ET.parse(tmp_path / "out.xodr").getroot()
    out_road1 = out_root.find("road[@id='1']")
    successors = out_road1.findall("link/successor")
    assert len(successors) == 1, "must never create a second <successor> element"
    assert successors[0].attrib["elementId"] == "99", "existing link must be preserved"

    assert report["added_junction_links"] == 0
    assert report["link_slot_conflicts"] == [
        {
            "road_id": "1",
            "junction_id": "5",
            "slot": "successor",
            "existing_element_type": "road",
            "existing_element_id": "99",
        }
    ]
    # The road is still genuinely missing its junction link -- must be
    # reported as such, not silently dropped.
    assert report["missing_road_to_junction_links_after"] == 1
    assert "1" in report["remaining_unlinked_incoming_road_ids"]


def test_does_not_duplicate_existing_predecessor_link(tmp_path):
    # Road "1" starts at x=0; junction connecting road "2" ends there
    # (contactPoint="end" means we attach at road2's end == x=0). Road "1"
    # already has a predecessor pointing elsewhere.
    road1 = _simple_road_xml("1", x=0, length=10, existing_predecessor_road_id="88")
    road2 = _simple_road_xml("2", x=-5, length=5, junction="5")
    junction_xml = (
        '<junction id="5">'
        '<connection id="0" incomingRoad="1" connectingRoad="2" contactPoint="end"/>'
        "</junction>"
    )
    in_xodr = tmp_path / "in.xodr"
    _write_xodr(in_xodr, road1 + road2 + junction_xml)

    report = patch_junction_links(
        in_xodr, tmp_path / "out.xodr", tmp_path / "report.json"
    )

    out_root = ET.parse(tmp_path / "out.xodr").getroot()
    out_road1 = out_root.find("road[@id='1']")
    predecessors = out_road1.findall("link/predecessor")
    assert len(predecessors) == 1, "must never create a second <predecessor> element"
    assert predecessors[0].attrib["elementId"] == "88"

    assert report["added_junction_links"] == 0
    assert report["link_slot_conflicts"][0]["slot"] == "predecessor"


def test_already_has_junction_link_is_not_reported_as_conflict(tmp_path):
    # Road already correctly linked to the SAME junction -- must be a no-op,
    # not a conflict (matches _has_junction_link's existing dedup guard).
    road1 = ET.Element("road", name="r1", length="10", id="1", junction="-1")
    link1 = ET.SubElement(road1, "link")
    ET.SubElement(
        link1, "successor", elementType="junction", elementId="5", contactPoint="start"
    )
    pv1 = ET.SubElement(road1, "planView")
    g1 = ET.SubElement(pv1, "geometry", s="0", x="0", y="0", hdg="0", length="10")
    ET.SubElement(g1, "line")
    road1_xml = ET.tostring(road1, encoding="unicode")

    road2 = _simple_road_xml("2", x=10, length=5, junction="5")
    junction_xml = (
        '<junction id="5">'
        '<connection id="0" incomingRoad="1" connectingRoad="2" contactPoint="start"/>'
        "</junction>"
    )
    in_xodr = tmp_path / "in.xodr"
    _write_xodr(in_xodr, road1_xml + road2 + junction_xml)

    report = patch_junction_links(
        in_xodr, tmp_path / "out.xodr", tmp_path / "report.json"
    )

    assert report["added_junction_links"] == 0
    assert report["link_slot_conflicts"] == []
    assert report["missing_road_to_junction_links_after"] == 0


def test_report_json_written_and_matches_return_value(tmp_path):
    road1 = _simple_road_xml("1", x=0, length=10)
    road2 = _simple_road_xml("2", x=10, length=5, junction="5")
    junction_xml = (
        '<junction id="5">'
        '<connection id="0" incomingRoad="1" connectingRoad="2" contactPoint="start"/>'
        "</junction>"
    )
    in_xodr = tmp_path / "in.xodr"
    _write_xodr(in_xodr, road1 + road2 + junction_xml)

    report_path = tmp_path / "report.json"
    report = patch_junction_links(in_xodr, tmp_path / "out.xodr", report_path)

    on_disk = json.loads(report_path.read_text(encoding="utf-8"))
    assert on_disk == report


def test_no_missing_links_copies_file_unmodified(tmp_path):
    road1 = _simple_road_xml("1", x=0, length=10)
    in_xodr = tmp_path / "in.xodr"
    _write_xodr(in_xodr, road1)

    report = patch_junction_links(
        in_xodr, tmp_path / "out.xodr", tmp_path / "report.json"
    )

    assert report["added_junction_links"] == 0
    assert report["modified"] is False
    assert report["input_xodr_sha256"] == report["output_xodr_sha256"]


def test_patch_xodr_junction_links_alias_delegates(tmp_path):
    road1 = _simple_road_xml("1", x=0, length=10)
    road2 = _simple_road_xml("2", x=10, length=5, junction="5")
    junction_xml = (
        '<junction id="5">'
        '<connection id="0" incomingRoad="1" connectingRoad="2" contactPoint="start"/>'
        "</junction>"
    )
    in_xodr = tmp_path / "in.xodr"
    _write_xodr(in_xodr, road1 + road2 + junction_xml)

    report = patch_xodr_junction_links(
        in_xodr, tmp_path / "out.xodr", tmp_path / "report.json"
    )
    assert report["added_junction_links"] == 1
