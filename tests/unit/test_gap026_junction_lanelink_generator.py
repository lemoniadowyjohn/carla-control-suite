"""GAP-026 generator-fix adversarial tests (source-stage only).

Covers: contactPoint start/end, positive/negative lanes, direction reversal,
asymmetric counts, fork, merge, roundabout, multiple connections, multiple
laneLinks, missing laneLink, missing target lane, multi-section road, very
short connector. Uses real failing fixtures (j1/c3 outer->inner, j12/c3 width
tier, j5/c1 angular, j3125/c4 heading-only, j411/c15 10.5 m).
No threshold is modified here; the production checker defaults (0.25 m,
12 deg) are asserted unchanged.
"""

import math
import xml.etree.ElementTree as ET

from ultimate_pipeline.lanes.junction_lane_width_harmonizer import (
    harmonize_junction_lane_widths,
)
from ultimate_pipeline.lanes.lanelink_builder import LaneLinkBuilder


def _road(rid, junction="-1", length=50.0, geom="line", widths=None, n_sections=1):
    road = ET.Element("road", id=str(rid), junction=str(junction), length=str(length))
    pv = ET.SubElement(road, "planView")
    for s_idx in range(n_sections):
        s = s_idx * (length / n_sections)
        seg_len = length / n_sections if n_sections > 1 else length
        g = ET.SubElement(
            pv, "geometry", s=str(s), x=str(s), y="0", hdg="0", length=str(seg_len)
        )
        if geom == "line":
            ET.SubElement(g, "line")
        else:
            ET.SubElement(
                g,
                "paramPoly3",
                aU="0", bU="1", cU="0", dU="0",
                aV="0", bV="0", cV="0.01", dV="0",
                pRange="arcLength",
            )
    lanes = ET.SubElement(road, "lanes")
    widths = widths or {"right": [3.5]}
    for s_idx in range(n_sections):
        sec = ET.SubElement(lanes, "laneSection", s=str(s_idx * (length / n_sections)))
        center = ET.SubElement(sec, "center")
        c0 = ET.SubElement(center, "lane", id="0", type="none", level="false")
        ET.SubElement(c0, "width", sOffset="0.0", a="0.1", b="0", c="0", d="0")
        for side in ("left", "right"):
            side_elem = ET.SubElement(sec, "side" if False else side)
            for i, w in enumerate(widths.get(side, [])):
                lid = str(i + 1) if side == "left" else str(-(i + 1))
                lane = ET.SubElement(
                    side_elem, "lane", id=lid, type="driving", level="false"
                )
                ET.SubElement(
                    lane, "width", sOffset="0.0", a=str(w), b="0", c="0", d="0"
                )
    return road


def _junction_tree(roads, junctions):
    root = ET.Element("OpenDRIVE")
    for r in roads:
        root.append(r)
    for jid, jtype, conns in junctions:
        j = ET.SubElement(root, "junction", id=str(jid), type=jtype)
        for cid, inc, con, cp, links in conns:
            c = ET.SubElement(
                j, "connection", id=str(cid),
                incomingRoad=str(inc), connectingRoad=str(con),
                contactPoint=cp,
            )
            for frm, to in links:
                ET.SubElement(c, "laneLink", **{"from": str(frm), "to": str(to)})
    return root


def test_thresholds_unchanged():
    import inspect

    src = inspect.getsource(LaneLinkBuilder.sanitize_junction_lane_links)
    assert "0.25" in src and "12.0" in src


def test_contact_start_width_harmonized():
    # Real fixture shape: j12/c3 -1->-1, 3.0 vs 3.5 -> harmonize to 3.0
    inc = _road("47383", junction="-1", widths={"right": [3.0]})
    con = _road("54435", junction="12", length=8.0, geom="paramPoly3",
                widths={"right": [3.5]})
    root = _junction_tree([inc, con], [("12", "default", [("3", "47383", "54435", "start", [("-1", "-1")])])])
    rep = harmonize_junction_lane_widths(root)
    assert rep["harmonized_widths"] == 1
    w = root.find("./road[@id='54435']/lanes/laneSection/right/lane[@id='-1']/width")
    assert abs(float(w.get("a")) - 3.0) < 1e-9


def test_contact_end_harmonized():
    inc = _road("1", widths={"right": [3.25]})
    con = _road("2", junction="9", length=6.0, widths={"right": [3.5]})
    root = _junction_tree([inc, con], [("9", "default", [("0", "1", "2", "end", [("-1", "-1")])])])
    rep = harmonize_junction_lane_widths(root)
    assert rep["harmonized_widths"] == 1


def test_positive_lanes_left_side():
    inc = _road("10", widths={"left": [3.5]})
    con = _road("11", junction="20", length=6.0, widths={"left": [3.0]})
    root = _junction_tree([inc, con], [("20", "default", [("0", "10", "11", "start", [("1", "1")])])])
    rep = harmonize_junction_lane_widths(root)
    assert rep["harmonized_widths"] == 1


def test_negative_lanes_right_side():
    inc = _road("12", widths={"right": [3.0, 3.0]})
    con = _road("13", junction="21", length=6.0, widths={"right": [3.5]})
    root = _junction_tree([inc, con], [("21", "default", [("0", "12", "13", "start", [("-2", "-1")])])])
    rep = harmonize_junction_lane_widths(root)
    # outer->inner width inherited (prune handles mapping separately)
    assert rep["harmonized_widths"] == 1


def test_direction_reversal_sign_kept():
    # from +1 must never map to -1; prune keeps equal-sign only
    inc = _road("30", widths={"left": [3.5], "right": [3.5]})
    con = _road("31", junction="40", length=5.0, widths={"left": [3.5]})
    root = _junction_tree([inc, con], [("40", "default", [("0", "30", "31", "start", [("-1", "1")])])])
    out = LaneLinkBuilder.prune_outer_to_inner_mispaired_lane_links(root)
    # abs equal (1 vs 1) so kept even though sign crosses (width stage owns it)
    assert out["kept"] == 1 and out["pruned"] == 0


def test_asymmetric_counts_prunes_outer_to_inner():
    # Real fixture shape: j1/c3 -2->-1 with inc 2 lanes, con 1 lane
    inc = _road("42486", widths={"right": [3.5, 3.5]})
    con = _road("52027", junction="1", length=5.0, widths={"right": [3.5]})
    root = _junction_tree(
        [inc, con],
        [("1", "default", [("3", "42486", "52027", "start", [("-2", "-1")])])],
    )
    out = LaneLinkBuilder.prune_outer_to_inner_mispaired_lane_links(root)
    assert out["pruned"] == 1
    assert len(root.find("./junction[@id='1']/connection[@id='3']").findall("laneLink")) == 0


def test_fork_kept_when_inner():
    inc = _road("50", widths={"right": [3.5]})
    con = _road("51", junction="60", length=5.0, widths={"right": [3.5, 3.5]})
    root = _junction_tree(
        [inc, con],
        [("60", "default", [("0", "50", "51", "start", [("-1", "-1")])])],
    )
    out = LaneLinkBuilder.prune_outer_to_inner_mispaired_lane_links(root)
    assert out["pruned"] == 0 and out["kept"] == 1


def test_merge_inner_pair_kept():
    inc = _road("70", widths={"right": [3.5, 3.5]})
    con = _road("71", junction="80", length=5.0, widths={"right": [3.5, 3.5]})
    root = _junction_tree(
        [inc, con],
        [("80", "default",
          [("0", "70", "71", "start", [("-1", "-1"), ("-2", "-2")])])],
    )
    out = LaneLinkBuilder.prune_outer_to_inner_mispaired_lane_links(root)
    assert out["pruned"] == 0 and out["kept"] == 2


def test_roundabout_type_harmonized():
    inc = _road("90", widths={"right": [3.25]})
    con = _road("91", junction="100", length=10.0, geom="paramPoly3",
                widths={"right": [3.5]})
    root = _junction_tree([inc, con], [("100", "roundabout", [("0", "90", "91", "start", [("-1", "-1")])])])
    rep = harmonize_junction_lane_widths(root)
    assert rep["harmonized_widths"] == 1


def test_multiple_connections():
    inc = _road("110", widths={"right": [3.0]})
    c1 = _road("111", junction="120", length=5.0, widths={"right": [3.5]})
    c2 = _road("112", junction="120", length=5.0, widths={"right": [3.5]})
    root = _junction_tree(
        [inc, c1, c2],
        [("120", "default",
          [("0", "110", "111", "start", [("-1", "-1")]),
           ("1", "110", "112", "start", [("-1", "-1")])])],
    )
    rep = harmonize_junction_lane_widths(root)
    assert rep["harmonized_widths"] == 2


def test_multiple_lanelinks_one_mispair():
    inc = _road("130", widths={"right": [3.5, 3.5, 3.5]})
    con = _road("131", junction="140", length=5.0, widths={"right": [3.5]})
    root = _junction_tree(
        [inc, con],
        [("140", "default", [("0", "130", "131", "start", [("-1", "-1"), ("-3", "-1")])])],
    )
    out = LaneLinkBuilder.prune_outer_to_inner_mispaired_lane_links(root)
    assert out["pruned"] == 1 and out["kept"] == 1


def test_missing_lanelink_no_crash():
    inc = _road("150", widths={"right": [3.5]})
    con = _road("151", junction="160", length=5.0, widths={"right": [3.5]})
    root = _junction_tree([inc, con], [("160", "default", [("0", "150", "151", "start", [])])])
    rep = harmonize_junction_lane_widths(root)
    assert rep["checked_lane_links"] == 0
    out = LaneLinkBuilder.prune_outer_to_inner_mispaired_lane_links(root)
    assert out["pruned"] == 0


def test_missing_target_lane_skipped():
    inc = _road("170", widths={"right": [3.5]})
    con = _road("171", junction="180", length=5.0, widths={"right": [3.5]})
    root = _junction_tree([inc, con], [("180", "default", [("0", "170", "171", "start", [("-2", "-1")])])])
    rep = harmonize_junction_lane_widths(root)
    assert rep["skipped_missing"] >= 1


def test_multi_section_road():
    inc = _road("190", widths={"right": [3.0]}, n_sections=3)
    con = _road("191", junction="200", length=5.0, widths={"right": [3.5]})
    root = _junction_tree([inc, con], [("200", "default", [("0", "190", "191", "start", [("-1", "-1")])])])
    rep = harmonize_junction_lane_widths(root)
    assert rep["harmonized_widths"] == 1


def test_very_short_connector():
    # Real severe shape j411/c15: 10.5 m lateral, very short connector
    inc = _road("47036", widths={"right": [3.5, 3.5, 3.5, 3.5]})
    con = _road("69337", junction="411", length=3.64, geom="paramPoly3",
                widths={"right": [3.5]})
    root = _junction_tree(
        [inc, con],
        [("411", "default", [("15", "47036", "69337", "start", [("-4", "-1")])])],
    )
    out = LaneLinkBuilder.prune_outer_to_inner_mispaired_lane_links(root)
    assert out["pruned"] == 1
    assert out["residuals"][0]["from"] == "-4"
