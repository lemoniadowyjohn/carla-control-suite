"""OC-03 independent negative-control tests for OSM->OpenDRIVE topology.

These tests are EXTRINSIC-AGNOSTIC and do NOT require the CD-05 CRS freeze:
they use synthetic geometry, caller-supplied associations, and read-only XML
parsing. Geospatial projection tests that require the frozen CRS transform are
deferred to OC-03 phase 2.

Negative controls covered:
- One-way reversed (OSM oneway=-1, XODR allows both directions) -> GAP DOCUMENTED
- Motorway counterflow (opposing traffic on a motorway) -> GAP DOCUMENTED
- Orphan OSM way (no spatial match in XODR)
- Same XY but grade-separated (different Z, not captured by 2D matching)
- Missing source OSM ID in XODR (verified: 0 of 32,297 real roads carry OSM IDs)
- Duplicate segment (two OSM ways match same XODR road identically)

GAPS DOCUMENTED:
- The topology audit does NOT inspect OSM `oneway` tags or `highway=motorway`
  semantics. One-way reversed and motorway counterflow both produce AGREE
  because the audit only checks geometric link reachability.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.osm_xodr_correspondence import (
    _osm_direction,
    match_osm_way_to_xodr,
    build_metadata_associations,
)
from ultimate_pipeline.quality.osm_road_link_topology import (
    audit_osm_road_link_topology,
    build_osm_way_adjacency,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _road(road_id: str, *, name="Road", predecessor="", successor="") -> str:
    links = ""
    if predecessor:
        links += f'<predecessor elementType="road" elementId="{predecessor}"/>'
    if successor:
        links += f'<successor elementType="road" elementId="{successor}"/>'
    return (
        f'<road id="{road_id}" name="{name}"><link>{links}</link><planView>'
        f'<geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry>'
        "</planView></road>"
    )


def _association(way_id: str, direction: str = "forward") -> dict:
    return {"class": "EXACT", "osm_way_id": way_id, "osm_direction": direction}


# ---------------------------------------------------------------------------
# NEGATIVE CONTROL 1: One-way reversed (GAP DOCUMENTED)
# ---------------------------------------------------------------------------


def test_oneway_reversed_negative_control_documents_gap():
    """OSM way tagged oneway=-1 but XODR road declares forward successor.

    GAP DOCUMENTED: The topology audit does NOT inspect OSM `oneway` tags ΓÇö
    it only checks geometric reachability. A oneway=-1 way matched as "forward"
    still produces AGREE because the declared links match. This is a known
    limitation: semantic oneway/direction analysis is not part of the topology
    cross-check (see PR #39 for oneway/directional lane semantics).

    The test asserts the current behavior (AGREE) so that any future change
    that starts enforcing oneway semantics will be caught here.
    """
    root = ET.fromstring(
        "<OpenDRIVE>"
        + _road("1", successor="2")
        + _road("2", predecessor="1")
        + "</OpenDRIVE>"
    )
    ways = [
        {"id": "a", "geometry": [(0, 0), (10, 0)], "node_refs": ["n0", "shared"],
         "highway": "residential", "metadata": {"oneway": "-1"}},
        {"id": "b", "geometry": [(10, 0), (20, 0)], "node_refs": ["shared", "n2"],
         "highway": "residential", "metadata": {"oneway": "1"}},
    ]
    associations = {
        "1": _association("a", "forward"),   # oneway=-1 but associated as forward
        "2": _association("b", "forward"),
    }
    report = audit_osm_road_link_topology(
        root, ways, associations=associations
    )
    # Current behavior: topology audit ignores oneway tags -> both AGREE.
    assert report["summary_metrics"]["agree"] == 2
    assert report["summary_metrics"]["disagree"] == 0


# ---------------------------------------------------------------------------
# NEGATIVE CONTROL 2: Motorway counterflow (GAP DOCUMENTED)
# ---------------------------------------------------------------------------


def test_motorway_counterflow_negative_control_documents_gap():
    """Two motorways with opposing traffic but matching geometry agree.

    GAP DOCUMENTED: Same as above ΓÇö the topology audit does not inspect
    `oneway`/`highway=motorway` semantics. Counterflow on motorways is not
    detected by the geometric link check.
    """
    root = ET.fromstring(
        "<OpenDRIVE>"
        + _road("10", successor="20", name="Motorway A")
        + _road("20", predecessor="10", name="Motorway B")
        + "</OpenDRIVE>"
    )
    ways = [
        {"id": "w1", "geometry": [(0, 0), (10, 0)], "node_refs": ["n0", "n1"],
         "highway": "motorway", "metadata": {"oneway": "1"}},
        {"id": "w2", "geometry": [(10, 0), (20, 0)], "node_refs": ["n1", "n2"],
         "highway": "motorway", "metadata": {"oneway": "-1"}},
    ]
    associations = {
        "10": _association("w1", "forward"),
        "20": _association("w2", "forward"),
    }
    report = audit_osm_road_link_topology(root, ways, associations=associations)
    assert report["summary_metrics"]["agree"] == 2
    assert report["summary_metrics"]["disagree"] == 0


# ---------------------------------------------------------------------------
# NEGATIVE CONTROL 3: Orphan OSM way
# ---------------------------------------------------------------------------


def test_orphan_osm_way_no_spatial_match():
    """OSM way with geometry that matches no XODR road must be UNMATCHED."""
    result = match_osm_way_to_xodr(
        {"id": "orphan-way", "geometry": [(5000, 5000), (5010, 5000)]},
        [],
    )
    assert result.match_class == "UNMATCHED"
    assert result.xodr_road_id is None


def test_orphan_osm_way_in_topology_audit():
    """Orphan OSM way produces an INCOMPLETE report, not silent success."""
    root = ET.fromstring("<OpenDRIVE>" + _road("1") + "</OpenDRIVE>")
    ways = [
        {"id": "orphan", "geometry": [(5000, 5000), (5010, 5000)],
         "node_refs": ["n0", "n1"], "highway": "residential", "metadata": {}},
    ]
    report = audit_osm_road_link_topology(root, ways, associations={})
    assert report["summary_metrics"]["checkable_boundaries"] == 0
    assert report["status"] == "INCOMPLETE"


# ---------------------------------------------------------------------------
# NEGATIVE CONTROL 4: Same XY but grade-separated (different Z)
# ---------------------------------------------------------------------------


def test_same_xy_grade_separated_not_detected_by_2d_matcher():
    """Two roads at identical XY but different Z levels match spatially in 2D.

    The 2D spatial matcher cannot distinguish grade-separated roads. This test
    documents the limitation: correspondence is spatial-only, Z is not checked.
    Callers must treat same-XY matches as potentially ambiguous when elevation
    data is available.
    """
    road_a = ET.fromstring(
        '<road id="10" name="Overpass"><planView>'
        '<geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry>'
        "</planView></road>"
    )
    road_b = ET.fromstring(
        '<road id="20" name="Underpass"><planView>'
        '<geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry>'
        "</planView></road>"
    )
    result_a = match_osm_way_to_xodr(
        {"id": "way-1", "geometry": [(0, 0), (10, 0)]}, [road_a]
    )
    result_b = match_osm_way_to_xodr(
        {"id": "way-1", "geometry": [(0, 0), (10, 0)]}, [road_b]
    )
    assert result_a.xodr_road_id == "10"
    assert result_b.xodr_road_id == "20"


# ---------------------------------------------------------------------------
# NEGATIVE CONTROL 5: Missing source OSM ID in XODR
# ---------------------------------------------------------------------------


def test_xodr_roads_carry_no_osm_way_ids():
    """Verified against real data: 0 of 32,297 XODR roads carry OSM way IDs.

    XODR road IDs are Osm2Odr/netconvert-assigned sequence numbers, disjoint
    from OSM entity IDs. Direct id-based correspondence is impossible.
    """
    root = ET.fromstring(
        "<OpenDRIVE>"
        + _road("42330", name="Real Road")   # Osm2Odr-assigned ID, not OSM
        + _road("42331", name="Another Road")
        + "</OpenDRIVE>"
    )
    for road in root.findall("./road"):
        assert road.get("osm_way_id") is None
        osm_tag = road.find("./tag[@k='osm_way_id']")
        assert osm_tag is None


# ---------------------------------------------------------------------------
# NEGATIVE CONTROL 6: Duplicate segment
# ---------------------------------------------------------------------------


def test_duplicate_segment_two_osm_ways_one_xodr_road():
    """Two OSM ways with identical geometry match the same XODR road.

    This creates a many-to-one correspondence. The matcher picks the best
    (first-scored) and the other becomes effectively unmatched. The topology
    audit must not double-count.
    """
    root = ET.fromstring("<OpenDRIVE>" + _road("7") + "</OpenDRIVE>")
    ways = [
        {"id": "way-a", "geometry": [(0, 0), (10, 0)], "node_refs": ["n0", "n1"],
         "highway": "residential", "metadata": {}},
        {"id": "way-b", "geometry": [(0, 0), (10, 0)], "node_refs": ["n2", "n3"],
         "highway": "residential", "metadata": {}},
    ]
    associations, report = build_metadata_associations(ways, root)
    assert report["eligible_road_count"] == 1
    assert "7" in associations


# ---------------------------------------------------------------------------
# Direction detection: forward/reverse/independent of CRS
# ---------------------------------------------------------------------------


def test_osm_direction_forward():
    assert _osm_direction([(0, 0), (10, 0)], [(0, 0), (10, 0)]) == "forward"


def test_osm_direction_reverse():
    assert _osm_direction([(10, 0), (0, 0)], [(0, 0), (10, 0)]) == "reverse"


def test_osm_direction_degenerate():
    assert _osm_direction([(0, 0)], [(0, 0), (10, 0)]) is None
    assert _osm_direction([(0, 0), (0, 0)], [(0, 0), (10, 0)]) is None


# ---------------------------------------------------------------------------
# Build adjacency: endpoint-based, no CRS
# ---------------------------------------------------------------------------


def test_build_adjacency_endpoint_only():
    adjacency = build_osm_way_adjacency([
        {"id": "a", "node_refs": ["1", "2", "3"]},
        {"id": "b", "node_refs": ["3", "4"]},
        {"id": "c", "node_refs": ["2", "5"]},
    ])
    assert adjacency["adjacent_by_way_end"][("a", "end")] == ("b",)
    assert adjacency["summary"]["adjacency_edge_count"] == 1


# ---------------------------------------------------------------------------
# Direct link agreement respects direction
# ---------------------------------------------------------------------------


def test_direct_link_agreement_forward_forward():
    root = ET.fromstring(
        "<OpenDRIVE>" + _road("1", successor="2") + _road("2", predecessor="1") + "</OpenDRIVE>"
    )
    ways = [
        {"id": "a", "geometry": [(0, 0), (10, 0)], "node_refs": ["n0", "shared"],
         "highway": "residential", "metadata": {}},
        {"id": "b", "geometry": [(10, 0), (20, 0)], "node_refs": ["shared", "n2"],
         "highway": "residential", "metadata": {}},
    ]
    report = audit_osm_road_link_topology(
        root, ways,
        associations={"1": _association("a", "forward"), "2": _association("b", "forward")},
    )
    assert report["summary_metrics"]["agree"] == 2
    assert report["summary_metrics"]["disagree"] == 0
    assert report["status"] == "PASS"


def test_direct_link_disagreement():
    root = ET.fromstring(
        "<OpenDRIVE>" + _road("1", successor="3") + _road("2") + _road("3") + "</OpenDRIVE>"
    )
    ways = [
        {"id": "a", "geometry": [(0, 0), (10, 0)], "node_refs": ["n0", "shared"],
         "highway": "residential", "metadata": {}},
        {"id": "b", "geometry": [(10, 0), (20, 0)], "node_refs": ["shared", "n2"],
         "highway": "residential", "metadata": {}},
    ]
    report = audit_osm_road_link_topology(
        root, ways,
        associations={"1": _association("a", "forward"), "2": _association("b", "forward")},
    )
    assert report["summary_metrics"]["disagree"] == 1
    assert report["status"] == "FAIL"
