# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/quality/check_lane_connectivity.py.

Live: CARLA-critical lane connectivity checks/repairs. Zero prior test
coverage. Directly relevant to this branch's scope (lane/junction
correctness -- CARLA can crash/ASSERT on a driving lane with no
successor).

The bug: downgrade_broken_driving_lanes_to_none() matches broken lanes by
the key (road_id, lane_id) -- NOT laneSection-specific. Roads with
multiple laneSections commonly reuse the same lane id across sections
(e.g. a lane-count/width transition partway down the road, all sections
using -1/-2/0/1/2 numbering). If ONE laneSection's lane is genuinely
broken (missing successor) while ANOTHER laneSection's lane with the SAME
id is correctly linked, both get downgraded to type="none" with their
<link> removed -- destroying a perfectly valid lane as collateral damage.
autofix_missing_lane_successors is NOT affected by the same input,
because it separately re-checks each specific lane's own current
link/successor state before acting (an "already has successor" guard)
rather than trusting the (road_id, lane_id) key alone -- confirmed by a
dedicated non-regression test below.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.quality.check_lane_connectivity import (
    assert_all_lanes_have_successors,
    autofix_missing_lane_successors,
    downgrade_broken_driving_lanes_to_none,
    find_broken_lanes,
    find_broken_lanes_detailed,
    write_lane_connectivity_report,
)


def _multi_lanesection_xodr(tmp_path: Path) -> Path:
    # Road with TWO laneSections both using lane id=-1 (normal, common
    # pattern). Section 0 (s=0) is correctly linked; section 1 (s=5, the
    # LAST section) is genuinely broken (no <link> at all). junction="5"
    # so the dead-end exemption never suppresses the real violation.
    xodr = tmp_path / "multi_lanesection.xodr"
    xodr.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<OpenDRIVE>"
        '<road name="r1" length="10" id="1" junction="5">'
        '<link><successor elementType="road" elementId="2" contactPoint="start"/></link>'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>'
        "<lanes>"
        '<laneSection s="0">'
        '<right><lane id="-1" type="driving" level="false">'
        '<link><successor id="-1"/></link>'
        '<width sOffset="0" a="3.5" b="0" c="0" d="0"/>'
        "</lane></right>"
        "</laneSection>"
        '<laneSection s="5">'
        '<right><lane id="-1" type="driving" level="false">'
        '<width sOffset="0" a="3.5" b="0" c="0" d="0"/>'
        "</lane></right>"
        "</laneSection>"
        "</lanes>"
        "</road>"
        "</OpenDRIVE>\n",
        encoding="utf-8",
    )
    return xodr


# ---------------------------------------------------------------------------
# find_broken_lanes_detailed / find_broken_lanes
# ---------------------------------------------------------------------------


def test_finds_missing_link_as_broken(tmp_path):
    xodr = _multi_lanesection_xodr(tmp_path)
    broken = find_broken_lanes_detailed(xodr, allow_dead_ends=True)
    assert broken == [
        {"road_id": "1", "lane_id": "-1", "junction": "5", "reason": "missing_link"}
    ]


def test_dead_end_road_with_no_successor_is_exempted(tmp_path):
    xodr = tmp_path / "deadend.xodr"
    xodr.write_text(
        '<?xml version="1.0"?><OpenDRIVE>'
        '<road name="r1" length="10" id="1" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>'
        '<lanes><laneSection s="0"><right>'
        '<lane id="-1" type="driving" level="false"/>'
        "</right></laneSection></lanes>"
        "</road></OpenDRIVE>",
        encoding="utf-8",
    )
    broken = find_broken_lanes_detailed(xodr, allow_dead_ends=True)
    assert broken == []


def test_dead_end_exemption_disabled_flags_the_lane(tmp_path):
    xodr = tmp_path / "deadend.xodr"
    xodr.write_text(
        '<?xml version="1.0"?><OpenDRIVE>'
        '<road name="r1" length="10" id="1" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>'
        '<lanes><laneSection s="0"><right>'
        '<lane id="-1" type="driving" level="false"/>'
        "</right></laneSection></lanes>"
        "</road></OpenDRIVE>",
        encoding="utf-8",
    )
    broken = find_broken_lanes_detailed(xodr, allow_dead_ends=False)
    assert len(broken) == 1


def test_find_broken_lanes_returns_human_readable_messages(tmp_path):
    xodr = _multi_lanesection_xodr(tmp_path)
    msgs = find_broken_lanes(xodr, allow_dead_ends=True)
    assert msgs == ["Road 1 lane -1: missing <link>"]


def test_accepts_root_element_directly(tmp_path):
    xodr = _multi_lanesection_xodr(tmp_path)
    root = ET.parse(str(xodr)).getroot()
    broken = find_broken_lanes_detailed(root, allow_dead_ends=True)
    assert len(broken) == 1


def test_rejects_unsupported_input_type():
    try:
        find_broken_lanes_detailed(12345)  # type: ignore[arg-type]
        assert False, "expected TypeError"
    except TypeError:
        pass


# ---------------------------------------------------------------------------
# write_lane_connectivity_report
# ---------------------------------------------------------------------------


def test_write_lane_connectivity_report_writes_valid_json(tmp_path):
    xodr = _multi_lanesection_xodr(tmp_path)
    out_json = tmp_path / "report.json"
    report = write_lane_connectivity_report(
        xodr_path=xodr, out_json=out_json, allow_dead_ends=True
    )
    assert report["broken_count"] == 1
    on_disk = json.loads(out_json.read_text(encoding="utf-8"))
    assert on_disk == report


# ---------------------------------------------------------------------------
# downgrade_broken_driving_lanes_to_none -- THE BUG
# ---------------------------------------------------------------------------


def test_downgrade_does_not_touch_a_correctly_linked_lane_in_a_sibling_lanesection(
    tmp_path,
):
    xodr = _multi_lanesection_xodr(tmp_path)
    out_xodr = tmp_path / "out.xodr"

    report = downgrade_broken_driving_lanes_to_none(
        xodr_in=xodr, xodr_out=out_xodr, allow_dead_ends=True
    )

    assert report["broken_count"] == 1
    assert report["downgraded_count"] == 1, (
        "only the genuinely broken lane (laneSection s=5) may be downgraded -- "
        "the correctly-linked lane in laneSection s=0 sharing the same lane id "
        "must be left untouched"
    )

    out_root = ET.parse(out_xodr).getroot()
    lane_sections = out_root.findall(".//laneSection")
    assert len(lane_sections) == 2

    good_section_lane = lane_sections[0].find(".//lane[@id='-1']")
    assert good_section_lane.get("type") == "driving", (
        "the correctly-linked sibling lane must not be downgraded"
    )
    assert good_section_lane.find("link/successor") is not None, (
        "the correctly-linked sibling lane's successor must be preserved"
    )

    broken_section_lane = lane_sections[1].find(".//lane[@id='-1']")
    assert broken_section_lane.get("type") == "none", (
        "the genuinely broken lane must still be downgraded"
    )


def test_downgrade_fixes_a_single_lanesection_road_normally(tmp_path):
    xodr = tmp_path / "simple.xodr"
    xodr.write_text(
        '<?xml version="1.0"?><OpenDRIVE>'
        '<road name="r1" length="10" id="1" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>'
        '<lanes><laneSection s="0"><right>'
        '<lane id="-1" type="driving" level="false"/>'
        "</right></laneSection></lanes>"
        "</road></OpenDRIVE>",
        encoding="utf-8",
    )
    out_xodr = tmp_path / "out.xodr"
    report = downgrade_broken_driving_lanes_to_none(
        xodr_in=xodr, xodr_out=out_xodr, allow_dead_ends=False
    )
    assert report["downgraded_count"] == 1
    lane = ET.parse(out_xodr).getroot().find(".//lane[@id='-1']")
    assert lane.get("type") == "none"
    assert lane.find("link") is None


# ---------------------------------------------------------------------------
# autofix_missing_lane_successors -- confirmed NOT affected by the same
# input (it re-verifies each lane's own current link/successor state).
# ---------------------------------------------------------------------------


def test_autofix_does_not_touch_a_correctly_linked_lane_in_a_sibling_lanesection(
    tmp_path,
):
    xodr = _multi_lanesection_xodr(tmp_path)
    report = autofix_missing_lane_successors(str(xodr), allow_dead_ends=True)

    assert report["fixed_count"] == 1
    assert report["fixed"][0]["laneSection_index"] == 1

    out_root = ET.parse(report["output_xodr"]).getroot()
    lane_sections = out_root.findall(".//laneSection")
    good_section_successor = lane_sections[0].find(".//lane[@id='-1']/link/successor")
    assert good_section_successor.attrib == {"id": "-1"}  # untouched, still valid


# ---------------------------------------------------------------------------
# assert_all_lanes_have_successors
# ---------------------------------------------------------------------------


def test_assert_raises_on_broken_lanes(tmp_path):
    xodr = _multi_lanesection_xodr(tmp_path)
    try:
        assert_all_lanes_have_successors(xodr, allow_dead_ends=True)
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "CARLA-FATAL" in str(e)


def test_assert_does_not_raise_when_clean(tmp_path):
    xodr = tmp_path / "clean.xodr"
    xodr.write_text(
        '<?xml version="1.0"?><OpenDRIVE>'
        '<road name="r1" length="10" id="1" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>'
        '<lanes><laneSection s="0"><right>'
        '<lane id="-1" type="driving" level="false">'
        '<link><successor id="-1"/></link>'
        "</lane></right></laneSection></lanes>"
        "</road></OpenDRIVE>",
        encoding="utf-8",
    )
    assert_all_lanes_have_successors(xodr, allow_dead_ends=True)  # must not raise


# ---------------------------------------------------------------------------
# GAP-048 closure: junction-routed exemption.
#
# A terminal driving lane on a road whose successor is a junction is NOT
# broken when a valid laneLink routes it (connection incomingRoad matches,
# contactPoint valid, connecting road exists, target lane exists at the
# contact section). Cross-junction connectivity is authoritatively defined
# by laneLinks; the lane-level successor element cannot express road choice.
# ---------------------------------------------------------------------------


def _junction_routed_xodr(tmp_path, lane_link_pairs, contact="start", lane_link_state="missing_successor"):
    """Incoming road R1 (successor=junction J1) + connecting road C1.

    lane_link_pairs: list of (from, to) laneLink entries on the connection.
    lane_link_state: "missing_successor" (empty <link>) or "missing_link" (no <link>).
    """
    links = "".join(
        f'<laneLink from="{frm}" to="{to}"/>' for frm, to in lane_link_pairs
    )
    if lane_link_state == "missing_successor":
        lane_inner = "<link/>" + '<width sOffset="0" a="3.5" b="0" c="0" d="0"/>'
    else:
        lane_inner = '<width sOffset="0" a="3.5" b="0" c="0" d="0"/>'
    xodr = tmp_path / "junction_routed.xodr"
    xodr.write_text(
        '<?xml version="1.0"?><OpenDRIVE>'
        '<road name="r1" length="10" id="R1" junction="-1">'
        '<link><successor elementType="junction" elementId="J1" contactPoint="start"/></link>'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>'
        '<lanes><laneSection s="0"><right>'
        '<lane id="-1" type="driving" level="false">'
        f"{lane_inner}"
        "</lane></right></laneSection></lanes>"
        "</road>"
        '<road name="c1" length="10" id="C1" junction="J1">'
        '<planView><geometry s="0" x="10" y="0" hdg="0" length="10"><line/></geometry></planView>'
        '<lanes><laneSection s="0"><right>'
        '<lane id="-1" type="driving" level="false">'
        '<link><successor id="-1"/></link>'
        '<width sOffset="0" a="3.5" b="0" c="0" d="0"/>'
        "</lane></right></laneSection></lanes>"
        "</road>"
        '<junction id="J1" type="default">'
        f'<connection id="0" incomingRoad="R1" connectingRoad="C1" contactPoint="{contact}">'
        f"{links}"
        "</connection>"
        "</junction>"
        "</OpenDRIVE>",
        encoding="utf-8",
    )
    return xodr


def test_junction_routed_lane_missing_successor_is_exempt(tmp_path):
    # R1 lane -1 has NO successor element but IS routed via laneLink.
    xodr = _junction_routed_xodr(tmp_path, [(-1, -1)])
    broken = find_broken_lanes_detailed(xodr, allow_dead_ends=True)
    assert broken == []


def test_junction_routed_lane_missing_link_is_exempt(tmp_path):
    # Same but the lane has no <link> at all: routing still exists.
    xodr = _junction_routed_xodr(tmp_path, [(-1, -1)], lane_link_state="missing_link")
    broken = find_broken_lanes_detailed(xodr, allow_dead_ends=True)
    assert broken == []


def test_junction_routed_exemption_ignores_allow_dead_ends_flag(tmp_path):
    # Routing exemption is independent of the dead-end policy.
    xodr = _junction_routed_xodr(tmp_path, [(-1, -1)])
    broken = find_broken_lanes_detailed(xodr, allow_dead_ends=False)
    assert broken == []


def test_junction_lane_without_lanelink_still_flagged(tmp_path):
    # Same topology but the connection carries NO laneLink for this lane.
    xodr = _junction_routed_xodr(tmp_path, [(7, -1)])
    broken = find_broken_lanes_detailed(xodr, allow_dead_ends=True)
    assert len(broken) == 1
    assert broken[0]["road_id"] == "R1"


def test_junction_routed_invalid_target_still_flagged(tmp_path):
    # laneLink points at a target lane that does not exist on C1.
    xodr = _junction_routed_xodr(tmp_path, [(-1, -9)])
    broken = find_broken_lanes_detailed(xodr, allow_dead_ends=True)
    assert len(broken) == 1


def test_junction_routed_bad_contact_point_still_flagged(tmp_path):
    xodr = _junction_routed_xodr(tmp_path, [(-1, -1)], contact="middle")
    broken = find_broken_lanes_detailed(xodr, allow_dead_ends=True)
    assert len(broken) == 1


def test_junction_routed_missing_junction_still_flagged(tmp_path):
    xodr = _junction_routed_xodr(tmp_path, [(-1, -1)])
    root = ET.parse(str(xodr)).getroot()
    root.remove(root.find("junction"))
    broken = find_broken_lanes_detailed(root, allow_dead_ends=True)
    assert len(broken) == 1


def test_junction_routed_non_terminal_lane_still_flagged(tmp_path):
    # laneLink-backed but in a NON-terminal section: needs intra-road successor.
    xodr = tmp_path / "nonterm.xodr"
    xodr.write_text(
        '<?xml version="1.0"?><OpenDRIVE>'
        '<road name="r1" length="20" id="R1" junction="-1">'
        '<link><successor elementType="junction" elementId="J1" contactPoint="start"/></link>'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="20"><line/></geometry></planView>'
        "<lanes>"
        '<laneSection s="0"><right>'
        '<lane id="-1" type="driving" level="false">'
        '<width sOffset="0" a="3.5" b="0" c="0" d="0"/>'
        "</lane></right></laneSection>"
        '<laneSection s="10"><right>'
        '<lane id="-1" type="driving" level="false">'
        '<link><successor id="-1"/></link>'
        '<width sOffset="0" a="3.5" b="0" c="0" d="0"/>'
        "</lane></right></laneSection>"
        "</lanes>"
        "</road>"
        '<road name="c1" length="10" id="C1" junction="J1">'
        '<planView><geometry s="0" x="20" y="0" hdg="0" length="10"><line/></geometry></planView>'
        '<lanes><laneSection s="0"><right>'
        '<lane id="-1" type="driving" level="false">'
        '<link><successor id="-1"/></link>'
        '<width sOffset="0" a="3.5" b="0" c="0" d="0"/>'
        "</lane></right></laneSection></lanes>"
        "</road>"
        '<junction id="J1" type="default">'
        '<connection id="0" incomingRoad="R1" connectingRoad="C1" contactPoint="start">'
        '<laneLink from="-1" to="-1"/>'
        "</connection>"
        "</junction>"
        "</OpenDRIVE>",
        encoding="utf-8",
    )
    broken = find_broken_lanes_detailed(xodr, allow_dead_ends=True)
    # Only the non-terminal section-0 lane is broken; terminal has successor.
    assert len(broken) == 1


def test_junction_routed_road_successor_lane_still_flagged(tmp_path):
    # Road-level successor is a ROAD (not junction): exemption does not apply.
    xodr = tmp_path / "roadsucc.xodr"
    xodr.write_text(
        '<?xml version="1.0"?><OpenDRIVE>'
        '<road name="r1" length="10" id="R1" junction="-1">'
        '<link><successor elementType="road" elementId="R2" contactPoint="start"/></link>'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>'
        '<lanes><laneSection s="0"><right>'
        '<lane id="-1" type="driving" level="false">'
        '<width sOffset="0" a="3.5" b="0" c="0" d="0"/>'
        "</lane></right></laneSection></lanes>"
        "</road>"
        '<road name="r2" length="10" id="R2" junction="-1">'
        '<planView><geometry s="0" x="10" y="0" hdg="0" length="10"><line/></geometry></planView>'
        '<lanes><laneSection s="0"><right>'
        '<lane id="-1" type="driving" level="false">'
        '<link><successor id="-1"/></link>'
        '<width sOffset="0" a="3.5" b="0" c="0" d="0"/>'
        "</lane></right></laneSection></lanes>"
        "</road>"
        "</OpenDRIVE>",
        encoding="utf-8",
    )
    broken = find_broken_lanes_detailed(xodr, allow_dead_ends=True)
    assert len(broken) == 1
    assert broken[0]["road_id"] == "R1"
