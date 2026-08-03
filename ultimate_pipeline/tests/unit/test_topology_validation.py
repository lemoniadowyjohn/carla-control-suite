"""TOP-JCT-RAB-LLK-001 tests — fail-closed topology validation.

Covers: connector candidate acceptance (pose/tangent/length/gap),
self-intersection, LaneLink matching with ambiguity rejection,
reciprocity violations, roundabout closed-ring validation.
"""
import math
import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.topology.topology_validation import (
    ConnectorCandidate,
    EndpointPose,
    LaneLinkCandidate,
    check_connector_self_intersection,
    match_lane_link,
    resolve_lane_link_targets,
    road_endpoint_pose,
    validate_connector_candidate,
    validate_road_link_reciprocity,
    validate_roundabout_ring,
)


# ---------------------------------------------------------------------------
# Connector candidates
# ---------------------------------------------------------------------------
def _good_candidate():
    return ConnectorCandidate(
        junction_id="J1", connector_road_id="100", incoming_road_id="1",
        outgoing_road_id="2",
        start_pose=EndpointPose(0.0, 0.0, 0.0),
        end_pose=EndpointPose(10.0, 0.0, 0.0),
        length_m=10.0, max_gap_m=0.1,
    )


def test_connector_valid_candidate_accepted():
    c = validate_connector_candidate(_good_candidate())
    assert c.accepted
    assert not c.rejections


def test_connector_missing_pose_rejected():
    c = _good_candidate()
    c.end_pose = None
    c = validate_connector_candidate(c)
    assert not c.accepted
    assert "missing endpoint pose" in c.rejections


def test_connector_zero_length_rejected():
    c = _good_candidate()
    c.end_pose = EndpointPose(0.0, 0.0, 0.0)
    c.length_m = 0.0
    c = validate_connector_candidate(c)
    assert not c.accepted
    assert "zero-length" in " ".join(c.rejections)


def test_connector_gap_threshold_rejected():
    c = _good_candidate()
    c.max_gap_m = 5.0
    c = validate_connector_candidate(c)
    assert not c.accepted
    assert "gap" in " ".join(c.rejections)


def test_connector_tangent_mismatch_rejected():
    c = _good_candidate()
    # heading points away from destination -> tangent mismatch
    c.end_pose = EndpointPose(-10.0, 0.0, math.pi)
    c = validate_connector_candidate(c)
    assert not c.accepted


def test_connector_self_intersection_guard_runs():
    c = _good_candidate()
    c = check_connector_self_intersection(c)
    assert c.accepted  # straight chord is fine


# ---------------------------------------------------------------------------
# LaneLink matching
# ---------------------------------------------------------------------------
def test_lane_link_valid_match_accepted():
    c = match_lane_link(
        from_lane_type="driving", to_lane_type="driving",
        from_direction="+", to_direction="+",
        from_width_m=3.5, to_width_m=3.5,
        endpoint_distance_m=0.2, heading_diff_rad=0.05,
        travel_compatible=True,
    )
    assert not c.rejected
    assert c.match_score > 0.0


def test_lane_link_type_mismatch_rejected():
    c = match_lane_link(
        from_lane_type="driving", to_lane_type="sidewalk",
        from_direction="+", to_direction="+",
        from_width_m=3.5, to_width_m=3.5,
        endpoint_distance_m=0.2, heading_diff_rad=0.05,
        travel_compatible=True,
    )
    assert c.rejected
    assert "type mismatch" in c.rejection_reason


def test_lane_link_reversed_travel_rejected():
    c = match_lane_link(
        from_lane_type="driving", to_lane_type="driving",
        from_direction="+", to_direction="+",
        from_width_m=3.5, to_width_m=3.5,
        endpoint_distance_m=0.2, heading_diff_rad=0.05,
        travel_compatible=False,
    )
    assert c.rejected
    assert "travel" in c.rejection_reason


def test_lane_link_distance_rejected():
    c = match_lane_link(
        from_lane_type="driving", to_lane_type="driving",
        from_direction="+", to_direction="+",
        from_width_m=3.5, to_width_m=3.5,
        endpoint_distance_m=20.0, heading_diff_rad=0.05,
        travel_compatible=True,
    )
    assert c.rejected


def test_lane_link_width_ratio_rejected():
    c = match_lane_link(
        from_lane_type="driving", to_lane_type="driving",
        from_direction="+", to_direction="+",
        from_width_m=1.0, to_width_m=12.0,
        endpoint_distance_m=0.2, heading_diff_rad=0.05,
        travel_compatible=True,
    )
    assert c.rejected
    assert "width" in c.rejection_reason


def test_lane_link_ambiguity_rejected():
    a = match_lane_link(
        from_lane_type="driving", to_lane_type="driving",
        from_direction="+", to_direction="+",
        from_width_m=3.5, to_width_m=3.5,
        endpoint_distance_m=0.2, heading_diff_rad=0.05,
        travel_compatible=True,
    )
    a.from_lane_id = 1
    a.to_lane_id = 1
    b = match_lane_link(
        from_lane_type="driving", to_lane_type="driving",
        from_direction="+", to_direction="+",
        from_width_m=3.5, to_width_m=3.5,
        endpoint_distance_m=4.9, heading_diff_rad=0.5,
        travel_compatible=True,
    )
    b.from_lane_id = 1
    b.to_lane_id = 1
    accepted, rejected = resolve_lane_link_targets([a, b])
    assert len(accepted) == 0  # competing matches for same lane pair -> reject both
    assert any("ambiguous" in r for r in rejected)


# ---------------------------------------------------------------------------
# Reciprocity
# ---------------------------------------------------------------------------
def _recip_doc():
    root = ET.Element("OpenDRIVE")
    r1 = ET.SubElement(root, "road", id="1", length="10")
    pv1 = ET.SubElement(r1, "planView")
    ET.SubElement(pv1, "geometry", s="0", x="0", y="0", hdg="0", length="10", geometry="line")
    r2 = ET.SubElement(root, "road", id="2", length="10")
    pv2 = ET.SubElement(r2, "planView")
    ET.SubElement(pv2, "geometry", s="0", x="10", y="0", hdg="0", length="10", geometry="line")
    link1 = ET.SubElement(r1, "link")
    ET.SubElement(link1, "successor", elementType="road", elementId="2", contactPoint="start")
    return root


def test_reciprocity_ok_when_mutual():
    root = _recip_doc()
    viol = validate_road_link_reciprocity(root)
    assert any(v["road"] == "1" and v["type"] == "road_link_not_reciprocated" for v in viol)


def test_reciprocity_ok_when_mutual2():
    root = _recip_doc()
    r2 = root.find(".//road[@id='2']")
    link2 = ET.SubElement(r2, "link")
    ET.SubElement(link2, "predecessor", elementType="road", elementId="1", contactPoint="end")
    viol = validate_road_link_reciprocity(root)
    assert not any(v["road"] == "1" for v in viol)
    assert not any(v["road"] == "2" for v in viol)


def test_reciprocity_missing_target():
    root = _recip_doc()
    r2 = root.find(".//road[@id='2']")
    root.remove(r2)
    viol = validate_road_link_reciprocity(root)
    assert any(v["type"] == "road_link_target_missing" for v in viol)


# ---------------------------------------------------------------------------
# Roundabout ring
# ---------------------------------------------------------------------------
def _ring_doc():
    root = ET.Element("OpenDRIVE")
    roads = {}
    for i in range(1, 5):
        r = ET.SubElement(root, "road", id=str(i), length="10")
        pv = ET.SubElement(r, "planView")
        ET.SubElement(pv, "geometry", s="0", x=str(i * 10), y="0", hdg="0", length="10", geometry="arc", curvature="0.1")
        roads[str(i)] = r
    ET.SubElement(roads["1"].find("road") if False else roads["1"], "link")
    for cur, nxt in ((1, 2), (2, 3), (3, 4), (4, 1)):
        link = roads[str(cur)].find("link")
        if link is None:
            link = ET.SubElement(roads[str(cur)], "link")
        ET.SubElement(link, "successor", elementType="road", elementId=str(nxt), contactPoint="start")
    return root, roads


def test_roundabout_ring_closed():
    root, roads = _ring_doc()
    res = validate_roundabout_ring(["1", "2", "3", "4"], roads)
    assert res["closed"] is True
    assert res["unreachable"] == []


def test_roundabout_ring_broken():
    root, roads = _ring_doc()
    # break the ring: road 4 no longer links back to 1
    link4 = roads["4"].find("link")
    succ = link4.find("successor")
    succ.set("elementId", "5")
    res = validate_roundabout_ring(["1", "2", "3", "4"], roads)
    assert res["closed"] is False
    assert "broken" in res["reason"]


def test_roundabout_missing_road_fails():
    root, roads = _ring_doc()
    res = validate_roundabout_ring(["1", "2", "9"], roads)
    assert res["closed"] is False
    assert "9" in res["missing_roads"]


# ---------------------------------------------------------------------------
# Endpoint pose helpers
# ---------------------------------------------------------------------------
def test_road_endpoint_pose_start():
    root, _ = _ring_doc()
    r1 = root.find(".//road[@id='1']")
    pose = road_endpoint_pose(r1, "start")
    assert pose.x == pytest.approx(10.0)
    assert pose.y == pytest.approx(0.0)


def test_road_endpoint_pose_line_end():
    root = ET.Element("OpenDRIVE")
    r = ET.SubElement(root, "road", id="1", length="10")
    pv = ET.SubElement(r, "planView")
    ET.SubElement(pv, "geometry", s="0", x="0", y="0", hdg="0.5", length="10", geometry="line")
    pose = road_endpoint_pose(r, "end")
    assert pose.x == pytest.approx(10.0 * math.cos(0.5))
    assert pose.y == pytest.approx(10.0 * math.sin(0.5))
