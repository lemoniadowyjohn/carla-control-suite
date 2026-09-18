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

import pytest

from ultimate_pipeline.map_fixes.xodr_junction_links import (
    _geom_end,
    patch_junction_links,
    patch_xodr_junction_links,
)
from ultimate_pipeline.geometry.opendrive_geometry_kernel import endpoint as kernel_endpoint


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


# ---------------------------------------------------------------------------
# _geom_end must match the canonical kernel for every plan-view primitive,
# not just line/paramPoly3. Before the fix, arc/spiral/poly3 final segments
# fell through to `return x, y, hdg` (the segment's *start* pose), which
# silently broke junction-link distance matching for any road ending in a
# curve that wasn't a paramPoly3.
# ---------------------------------------------------------------------------

def _geom(tag: str, length: float = 10.0, x: float = 0.0, y: float = 0.0,
          hdg: float = 0.0, **attrs) -> ET.Element:
    g = ET.Element("geometry", {
        "s": "0", "x": str(x), "y": str(y), "hdg": str(hdg), "length": str(length),
    })
    ET.SubElement(g, tag, {k: str(v) for k, v in attrs.items()})
    return g


def test_geom_end_line_matches_kernel():
    g = _geom("line", length=10.0, x=1.0, y=2.0, hdg=0.3)
    kp = kernel_endpoint(g)
    assert _geom_end(g) == (kp.x, kp.y, kp.heading)


def test_geom_end_arc_matches_kernel():
    g = _geom("arc", length=10.0, curvature="0.1")
    kp = kernel_endpoint(g)
    got = _geom_end(g)
    assert got[0] == pytest.approx(kp.x)
    assert got[1] == pytest.approx(kp.y)
    assert got[2] == pytest.approx(kp.heading)


def test_geom_end_spiral_matches_kernel():
    g = _geom("spiral", length=10.0, curvStart="0.0", curvEnd="0.1")
    kp = kernel_endpoint(g)
    got = _geom_end(g)
    assert got[0] == pytest.approx(kp.x, abs=1e-6)
    assert got[1] == pytest.approx(kp.y, abs=1e-6)
    assert got[2] == pytest.approx(kp.heading, abs=1e-6)


def test_geom_end_poly3_matches_kernel():
    g = _geom("poly3", length=2.0, a=0, b=1, c=0, d=0)
    kp = kernel_endpoint(g)
    got = _geom_end(g)
    assert got[0] == pytest.approx(kp.x)
    assert got[1] == pytest.approx(kp.y)
    assert got[2] == pytest.approx(kp.heading)


def test_geom_end_parampoly3_heading_matches_kernel():
    # Previously the paramPoly3 branch computed the correct endpoint
    # position but always returned the *start* heading unchanged.
    g = _geom("paramPoly3", length=8.0, pRange="normalized",
              aU="0", bU="1", cU="0", dU="0",
              aV="0", bV="0", cV="0.5", dV="0")
    kp = kernel_endpoint(g)
    got = _geom_end(g)
    assert got[0] == pytest.approx(kp.x)
    assert got[1] == pytest.approx(kp.y)
    assert got[2] == pytest.approx(kp.heading)



def _road_with_last_geom(road_id: str, junction: str, first_x: float, first_length: float,
                          last_geom_xml: str, **link_kwargs) -> str:
    return (
        f'<road name="r{road_id}" length="{first_length}" id="{road_id}" junction="{junction}">'
        f'<planView><geometry s="0" x="{first_x}" y="0" hdg="0" length="{first_length}">'
        f'{last_geom_xml}</geometry></planView>'
        f"</road>"
    )


def test_junction_link_matches_for_road_ending_in_arc(tmp_path):
    # Road "1" is a single-geometry arc of length 10, curvature 0.1, starting
    # at the origin heading 0. Its TRUE end is (8.41470984..., 4.59697694...)
    # heading 1.0 rad -- not (0, 0) as the pre-fix `_geom_end` fallback
    # would have reported. Road "2" (a junction connector) starts exactly
    # at that true endpoint, so a correct implementation finds d_end == 0
    # and must NOT flag the match as suspicious.
    #
    # Pre-fix, `_geom_end` collapsed both road 1's start AND end to (0, 0)
    # for any non-line/non-paramPoly3 primitive, so this physically
    # perfectly-aligned junction connection was ~9.6m from BOTH reported
    # endpoints -- beyond the 5m default tolerance -- and got silently
    # flagged as a suspicious/misaligned match even though the map is fine.
    kp = kernel_endpoint(_geom("arc", length=10.0, curvature="0.1"))
    road1 = _road_with_last_geom("1", "-1", first_x=0, first_length=10.0,
                                  last_geom_xml='<arc curvature="0.1"/>')
    road2 = (
        f'<road name="r2" length="5" id="2" junction="5">'
        f'<planView><geometry s="0" x="{kp.x}" y="{kp.y}" hdg="{kp.heading}" length="5">'
        f'<line/></geometry></planView>'
        f"</road>"
    )
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
    assert report["suspicious_matches"] == [], (
        "a physically exact arc-to-connector match must not be reported as "
        "suspicious -- this catches _geom_end silently treating a curved "
        "final geometry segment as a zero-length no-op"
    )
