"""GAP-048: through-junction lane-successor inference (source stage only).

Strategy 1 (road->road same ID) and strategy 3 (ROAD_SUCCESSOR_IS_JUNCTION:
incoming road -> junction successor -> connection/laneLink -> unique
(connectingRoad, to-lane)) are specified here. No synthetic IDs, no geometric
fallback, no guessing: ambiguous or unproven cases stay unresolved.

Phase 4 regression: test_junction_path_repairs_incoming_lane fails on the old
implementation (strategy-2 elif dead: junction_mapped always 0, incoming lane
untouched) and passes with strategy 3 -- it pins the working path so a silent
return to always-zero breaks the suite.
"""
import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.lane_successor_topology import (
    infer_lane_successors_from_topology,
    resolve_through_junction,
)


def _section(lane_ids, s="0"):
    sec = ET.Element("laneSection", {"s": s})
    for side_name, ids in (("left", []), ("center", [0]), ("right", lane_ids)):
        side = ET.SubElement(sec, side_name)
        for i in ids:
            ET.SubElement(side, "lane", {"id": str(i), "type": "driving",
                                         "level": "false"})
    return sec


def _road(rid, lane_ids, *, junction="-1", successor=None):
    road = ET.Element("road", {"id": rid, "junction": junction, "length": "10.0"})
    if successor is not None:
        link = ET.SubElement(road, "link")
        ET.SubElement(link, "successor",
                      {"elementType": successor[0], "elementId": successor[1],
                       "contactPoint": successor[2]})
    lanes = ET.SubElement(road, "lanes")
    lanes.append(_section(lane_ids))
    return road


def _junction(jid, connections):
    # connections: [(incoming, connecting, contact, [(from, to), ...]), ...]
    junction = ET.Element("junction", {"id": jid})
    for n, (incoming, connecting, contact, links) in enumerate(connections):
        conn = ET.SubElement(
            junction, "connection",
            {"id": str(n), "incomingRoad": incoming,
             "connectingRoad": connecting, "contactPoint": contact})
        for frm, to in links:
            ET.SubElement(conn, "laneLink", {"from": str(frm), "to": str(to)})
    return junction


def _successor_of(lane):
    link = lane.find("link")
    if link is None:
        return None
    succ = link.find("successor")
    return None if succ is None else succ.get("id")


def _lanes_by_id(root, road_id):
    road = next(r for r in root.findall("road") if r.get("id") == road_id)
    return {int(lane.get("id")): lane
            for lane in road.findall(".//lane")
            if lane.get("type") == "driving"}


def _base_tree():
    # R1 (plain) -> junction J=10 -> C1 (connecting). R1 lane 1 links to C1 -2.
    root = ET.Element("OpenDRIVE")
    root.append(_road("R1", [1], successor=("junction", "10", "start")))
    root.append(_road("C1", [-2], junction="10"))
    root.append(_junction("10", [("R1", "C1", "start", [(1, -2)])]))
    return root


# --- strategy 1 ---------------------------------------------------------

def test_road_level_successor_same_id_is_inferred():
    root = ET.Element("OpenDRIVE")
    root.append(_road("A", [-1, -2], successor=("road", "B", "start")))
    root.append(_road("B", [-1, -2]))
    report = infer_lane_successors_from_topology(root)
    lanes = _lanes_by_id(root, "A")
    assert _successor_of(lanes[-1]) == "-1"
    assert _successor_of(lanes[-2]) == "-2"
    assert report["inferred_count"] == 2
    # B's own lanes link nowhere: correctly left alone, not failures.
    assert report["lanes_without_topology"] == 2


# --- strategy 3 (Phase 4 regression: fails on old dead-elif code) --------

def test_junction_path_repairs_incoming_lane():
    root = _base_tree()
    report = infer_lane_successors_from_topology(root)
    lanes = _lanes_by_id(root, "R1")
    assert _successor_of(lanes[1]) == "-2"
    assert report["through_junction_count"] == 1
    assert report["junction_mapped_count"] == 0


def test_junction_path_positive_and_negative_ids():
    root = ET.Element("OpenDRIVE")
    root.append(_road("R1", [-3, 2], successor=("junction", "10", "start")))
    root.append(_road("C1", [-3, 2], junction="10"))
    root.append(_junction("10", [("R1", "C1", "start", [(-3, -3), (2, 2)])]))
    report = infer_lane_successors_from_topology(root)
    lanes = _lanes_by_id(root, "R1")
    assert _successor_of(lanes[-3]) == "-3"
    assert _successor_of(lanes[2]) == "2"
    assert report["through_junction_count"] == 2


def test_junction_path_contact_point_end():
    root = ET.Element("OpenDRIVE")
    root.append(_road("R1", [1], successor=("junction", "10", "end")))
    root.append(_road("C1", [-4], junction="10"))
    root.append(_junction("10", [("R1", "C1", "end", [(1, -4)])]))
    report = infer_lane_successors_from_topology(root)
    assert _successor_of(_lanes_by_id(root, "R1")[1]) == "-4"
    assert report["through_junction_count"] == 1


def test_junction_path_multiple_connections_unique_target():
    # Same (C1,-2) reachable via two connections: one distinct target -> repair.
    root = ET.Element("OpenDRIVE")
    root.append(_road("R1", [1], successor=("junction", "10", "start")))
    root.append(_road("C1", [-2], junction="10"))
    root.append(_junction("10", [("R1", "C1", "start", [(1, -2)]),
                                 ("R1", "C1", "end", [(1, -2)])]))
    report = infer_lane_successors_from_topology(root)
    assert _successor_of(_lanes_by_id(root, "R1")[1]) == "-2"
    assert report["through_junction_count"] == 1


# --- ambiguity / missing data: never guess -------------------------------

def test_ambiguous_multiple_targets_stays_unresolved():
    root = ET.Element("OpenDRIVE")
    root.append(_road("R1", [1], successor=("junction", "10", "start")))
    root.append(_road("C1", [-2], junction="10"))
    root.append(_road("C2", [-5], junction="10"))
    root.append(_junction("10", [("R1", "C1", "start", [(1, -2)]),
                                 ("R1", "C2", "start", [(1, -5)])]))
    report = infer_lane_successors_from_topology(root)
    assert _successor_of(_lanes_by_id(root, "R1")[1]) is None
    assert report["through_junction_count"] == 0
    assert report["lanes_without_topology"] >= 1


def test_missing_junction_stays_unresolved():
    root = ET.Element("OpenDRIVE")
    root.append(_road("R1", [1], successor=("junction", "99", "start")))
    report = infer_lane_successors_from_topology(root)
    assert _successor_of(_lanes_by_id(root, "R1")[1]) is None
    assert report["through_junction_count"] == 0


def test_missing_connecting_road_stays_unresolved():
    root = ET.Element("OpenDRIVE")
    root.append(_road("R1", [1], successor=("junction", "10", "start")))
    root.append(_junction("10", [("R1", "CX", "start", [(1, -2)])]))
    report = infer_lane_successors_from_topology(root)
    assert _successor_of(_lanes_by_id(root, "R1")[1]) is None
    assert report["through_junction_count"] == 0


def test_missing_lanelink_stays_unresolved():
    root = ET.Element("OpenDRIVE")
    root.append(_road("R1", [1], successor=("junction", "10", "start")))
    root.append(_road("C1", [-2], junction="10"))
    root.append(_junction("10", [("R1", "C1", "start", [(7, -2)])]))
    report = infer_lane_successors_from_topology(root)
    assert _successor_of(_lanes_by_id(root, "R1")[1]) is None
    assert report["through_junction_count"] == 0


def test_lanelink_target_missing_stays_unresolved():
    root = ET.Element("OpenDRIVE")
    root.append(_road("R1", [1], successor=("junction", "10", "start")))
    root.append(_road("C1", [-2], junction="10"))
    root.append(_junction("10", [("R1", "C1", "start", [(1, -9)])]))
    report = infer_lane_successors_from_topology(root)
    assert _successor_of(_lanes_by_id(root, "R1")[1]) is None
    assert report["through_junction_count"] == 0


def test_unresolvable_topology_leaves_dead_end_without_guessing():
    root = ET.Element("OpenDRIVE")
    root.append(_road("Z", [-1]))  # no <link> at all
    report = infer_lane_successors_from_topology(root)
    assert _successor_of(_lanes_by_id(root, "Z")[-1]) is None
    assert report["inferred_count"] == 0
    assert report["through_junction_count"] == 0
    assert report["lanes_without_topology"] >= 1


# --- directionality / non-interference ------------------------------------

def test_existing_successor_never_overwritten():
    root = _base_tree()
    lane = _lanes_by_id(root, "R1")[1]
    link = ET.SubElement(lane, "link")
    ET.SubElement(link, "successor", {"id": "-99"})
    report = infer_lane_successors_from_topology(root)
    assert _successor_of(lane) == "-99"
    assert report["through_junction_count"] == 0


def test_no_predecessor_elements_written():
    root = _base_tree()
    infer_lane_successors_from_topology(root)
    for lane in root.findall(".//lane"):
        assert lane.find("predecessor") is None
        link = lane.find("link")
        if link is not None:
            assert link.find("predecessor") is None


def test_non_driving_lanes_untouched():
    root = ET.Element("OpenDRIVE")
    road = _road("R1", [1], successor=("junction", "10", "start"))
    sec = road.find("lanes/laneSection")
    side = sec.find("right")
    ET.SubElement(side, "lane", {"id": "-7", "type": "sidewalk", "level": "false"})
    root.append(road)
    root.append(_road("C1", [-2, -7], junction="10"))
    root.append(_junction("10", [("R1", "C1", "start", [(1, -2)])]))
    infer_lane_successors_from_topology(root)
    sw = [l for l in road.findall(".//lane") if l.get("id") == "-7"][0]
    assert _successor_of(sw) is None


# --- resolver unit level + determinism ------------------------------------

def test_resolver_bucket_names_match_classifier():
    roads = {"R1": _road("R1", [1], successor=("junction", "10", "start"))}
    root = ET.Element("OpenDRIVE")
    for r in roads.values():
        root.append(r)
    junctions = {}
    bucket, target = resolve_through_junction(roads, junctions, "R1", 1)
    assert (bucket, target) == ("NO_JUNCTION_ELEMENT", None)


def test_deterministic_ordering_repeated_runs_agree():
    def run_once():
        root = _base_tree()
        rep = infer_lane_successors_from_topology(root)
        lane = _lanes_by_id(root, "R1")[1]
        return _successor_of(lane), rep["through_junction_count"]
    assert run_once() == run_once() == ("-2", 1)


# --- regression fixtures for Stage-8 invalid links (M3) ---------------------
# These are cases where Stage-8 autofix created invalid lane successors by
# blindly copying lane IDs without validating target existence on successor road.
# The source-stage repair (strategy 3) must NOT infer successors in these cases.

def test_stage8_invalid_link_49289_lane_neg2_no_target():
    """Road 49289 lane -2 -> -2: target lane -2 does not exist on successor road."""
    root = ET.Element("OpenDRIVE")
    # Incoming road with lane -2 at terminal section
    root.append(_road("49289", [-2], successor=("junction", "J1", "start")))
    # Connecting road has NO lane -2 (only -1)
    root.append(_road("50001", [-1], junction="J1"))
    # Junction has laneLink from -2 to -2, but target doesn't exist
    root.append(_junction("J1", [("49289", "50001", "start", [(-2, -2)])]))
    report = infer_lane_successors_from_topology(root)
    lanes = _lanes_by_id(root, "49289")
    # Must NOT infer successor because target lane -2 doesn't exist on connecting road
    assert _successor_of(lanes[-2]) is None
    assert report["through_junction_count"] == 0
    assert report["lanes_without_topology"] >= 1


def test_stage8_invalid_link_51702_lane_2_to_1_no_target():
    """Road 51702 lane 2 -> 1: target lane 1 does not exist on successor road."""
    root = ET.Element("OpenDRIVE")
    root.append(_road("51702", [1, 2], successor=("junction", "J2", "start")))
    # Connecting road has NO lane 1 (only -1, -2)
    root.append(_road("52001", [-1, -2], junction="J2"))
    # Junction has laneLink from 2 to 1, but target doesn't exist
    root.append(_junction("J2", [("51702", "52001", "start", [(2, 1)])]))
    report = infer_lane_successors_from_topology(root)
    lanes = _lanes_by_id(root, "51702")
    assert _successor_of(lanes[2]) is None
    assert report["through_junction_count"] == 0
    assert report["lanes_without_topology"] >= 1


def test_stage8_invalid_link_51702_lane_1_to_1_no_target():
    """Road 51702 lane 1 -> 1: target lane 1 does not exist on successor road."""
    root = ET.Element("OpenDRIVE")
    root.append(_road("51702", [1, 2], successor=("junction", "J3", "start")))
    root.append(_road("52002", [-1, -2], junction="J3"))
    root.append(_junction("J3", [("51702", "52002", "start", [(1, 1)])]))
    report = infer_lane_successors_from_topology(root)
    lanes = _lanes_by_id(root, "51702")
    assert _successor_of(lanes[1]) is None
    assert report["through_junction_count"] == 0
    assert report["lanes_without_topology"] >= 1
