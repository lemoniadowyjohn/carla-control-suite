from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.quality.osm_road_link_topology import (
    audit_osm_road_link_topology,
    build_osm_way_adjacency,
)


def _road(road_id: str, *, predecessor: str = "", successor: str = "") -> str:
    links = ""
    if predecessor:
        links += f'<predecessor elementType="road" elementId="{predecessor}"/>'
    if successor:
        links += f'<successor elementType="road" elementId="{successor}"/>'
    return (
        f'<road id="{road_id}"><link>{links}</link><planView>'
        f'<geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry>'
        "</planView></road>"
    )


def _way(way_id: str, start: str, end: str) -> dict:
    return {
        "id": way_id,
        "geometry": [(0.0, 0.0), (10.0, 0.0)],
        "node_refs": [start, end],
        "metadata": {},
    }


def _association(way_id: str, direction: str = "forward") -> dict:
    return {"class": "EXACT", "osm_way_id": way_id, "osm_direction": direction}


def test_endpoint_adjacency_uses_only_first_and_last_node_references() -> None:
    adjacency = build_osm_way_adjacency([
        {**_way("a", "1", "3"), "node_refs": ["1", "2", "3"]},
        _way("b", "3", "4"),
        _way("c", "2", "5"),
    ])

    assert adjacency["adjacent_by_way_end"][("a", "end")] == ("b",)
    assert adjacency["adjacent_by_way_end"][("a", "start")] == ()
    assert adjacency["summary"]["adjacency_edge_count"] == 1


def test_direct_link_agreement_respects_forward_and_reverse_osm_direction() -> None:
    root = ET.fromstring(
        "<OpenDRIVE>"
        + _road("1", successor="2")
        + _road("2", predecessor="1")
        + "</OpenDRIVE>"
    )
    ways = [_way("a", "n0", "shared"), _way("b", "shared", "n2")]

    forward = audit_osm_road_link_topology(root, ways, associations={"1": _association("a"), "2": _association("b")})
    reverse = audit_osm_road_link_topology(
        root,
        [_way("a", "shared", "n0"), _way("b", "n2", "shared")],
        associations={"1": _association("a", "reverse"), "2": _association("b", "reverse")},
    )

    assert forward["summary_metrics"]["agree"] == 2
    assert forward["summary_metrics"]["disagree"] == 0
    assert reverse["summary_metrics"]["agree"] == 2
    assert reverse["summary_metrics"]["disagree"] == 0


def test_junction_connector_path_reaches_expected_osm_neighbour() -> None:
    root = ET.fromstring(
        "<OpenDRIVE>"
        '<road id="1"><link><successor elementType="junction" elementId="j"/></link><planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView></road>'
        '<road id="9"><link><predecessor elementType="road" elementId="1"/><successor elementType="road" elementId="2"/></link><planView><geometry s="0" x="10" y="0" hdg="0" length="3"><line/></geometry></planView></road>'
        + _road("2", predecessor="9")
        + '<junction id="j"><connection id="c" incomingRoad="1" connectingRoad="9" contactPoint="start"/></junction>'
        + "</OpenDRIVE>"
    )
    report = audit_osm_road_link_topology(
        root,
        [_way("a", "n0", "shared"), _way("b", "shared", "n2")],
        associations={"1": _association("a"), "2": _association("b")},
    )

    record = next(
        item
        for item in report["boundaries"]
        if item["xodr_road_id"] == "1" and item["xodr_endpoint"] == "end"
    )
    assert record["classification"] == "AGREE"
    assert record["resolution"] == "JUNCTION_CONNECTOR"
    assert "2" in record["declared_reachable_xodr_road_ids"]


def test_disagreement_and_missing_neighbour_correspondence_remain_explicit() -> None:
    root = ET.fromstring("<OpenDRIVE>" + _road("1", successor="3") + _road("2") + _road("3") + "</OpenDRIVE>")
    disagree = audit_osm_road_link_topology(
        root,
        [_way("a", "n0", "shared"), _way("b", "shared", "n2")],
        associations={"1": _association("a"), "2": _association("b")},
    )
    incomplete = audit_osm_road_link_topology(
        root,
        [_way("a", "n0", "shared"), _way("b", "shared", "n2")],
        associations={"1": _association("a")},
    )

    assert disagree["status"] == "FAIL"
    assert disagree["summary_metrics"]["disagree"] == 1
    assert incomplete["summary_metrics"]["incomplete_unassociated_osm_neighbours"] == 1
    assert any(item["classification"] == "INCOMPLETE" for item in incomplete["boundaries"])
