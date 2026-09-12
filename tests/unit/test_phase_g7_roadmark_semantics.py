from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.tools.phase_g7_roadmark_semantics import (
    audit_roadmarks,
    repair_roadmarks,
    run_fixtures,
)


def _root_with_markings() -> ET.Element:
    return ET.fromstring(
        """<OpenDRIVE><road id="1"><lanes><laneSection s="0">
        <right>
          <lane id="-1" type="driving"><roadMark type="solid" width="0"/></lane>
          <lane id="-2" type="sidewalk"><roadMark type="solid"/></lane>
        </right>
        </laneSection></lanes></road></OpenDRIVE>"""
    )


def test_sidewalk_boundary_is_advisory_not_a_zero_width_traffic_defect():
    audit = audit_roadmarks(_root_with_markings())

    assert audit["visible_zero_width"] == [{"road": "1", "lane": "-1", "type": "solid", "width": "0"}]
    assert audit["solid_lanechange_missing"] == [{"road": "1", "lane": "-1"}]
    assert audit["advisory"] == [{
        "road": "1",
        "lane": "-2",
        "lane_type": "sidewalk",
        "kind": "non_traffic_visible_marking",
        "type": "solid",
        "width": None,
    }]


def test_repair_changes_driving_marking_but_never_sidewalk_boundary():
    root = _root_with_markings()

    repair = repair_roadmarks(root)

    driving = root.find(".//lane[@id='-1']/roadMark")
    sidewalk = root.find(".//lane[@id='-2']/roadMark")
    assert repair == {"widths_fixed": 1, "lanechange_fixed": 1}
    assert driving is not None and driving.get("width") == "0.13"
    assert driving.get("laneChange") == "none"
    assert sidewalk is not None and sidewalk.get("width") is None
    assert sidewalk.get("laneChange") is None


def test_lane_type_boundary_is_covered_by_the_standalone_fixture_corpus():
    result = run_fixtures()

    assert result["fixtures_ok"] is True
    assert result["fixtures"]["sidewalk_boundary"]["ok"] is True
