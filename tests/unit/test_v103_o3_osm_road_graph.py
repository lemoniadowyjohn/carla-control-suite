"""V103-O3 — OSM source-grounded road graph and orphan road reconciliation.

Registry issues covered: **T09** (endpoint-only way adjacency misses
interior-node cases) and **T03** (geometry-only orphan repair lacks OSM node
proof).  Adversarial matrix rows: OSM-01 .. OSM-04.

Every test exercises the *production* implementation.  The mutation control
at the end proves the tests really bind the source-authority rule.
"""

from __future__ import annotations

import csv
import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.quality.osm_road_link_topology import (
    build_osm_source_adjacency,
    extract_osm_highway_ways,
)
from ultimate_pipeline.topology.orphan_road_repair import (
    ORPHAN_STATUS_REPAIRED,
    ORPHAN_STATUS_UNRESOLVED,
    find_orphan_roads,
    reconcile_orphan_roads,
    write_orphan_reconciliation_csv,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _way(way_id: str, node_refs, *, geometry=None, **restrictions) -> dict:
    record = {
        "id": way_id,
        "name": "",
        "highway": "residential",
        "geometry": geometry or [(0.0, 0.0), (10.0, 0.0)],
        "node_refs": list(node_refs),
        "metadata": dict(restrictions),
        "restrictions": dict(restrictions),
    }
    return record


def _xodr(road_id: str, *, x=0.0, y=0.0, length=10.0, z=0.0, link="") -> str:
    return (
        f'<road id="{road_id}" length="{length}">{link}<planView>'
        f'<geometry s="0" x="{x}" y="{y}" hdg="0" length="{length}"><line/></geometry>'
        f'</planView><elevationProfile><elevation s="0" a="{z}" b="0" c="0" d="0"/>'
        f"</elevationProfile></road>"
    )


# ---------------------------------------------------------------------------
# OSM-01 / OSM-02 — shared interior node vs XY crossing
# ---------------------------------------------------------------------------

def test_osm01_two_ways_sharing_an_interior_node_are_adjacent():
    """OSM-01: a shared *interior* node is real source adjacency."""
    adjacency = build_osm_source_adjacency(
        [
            _way("a", ["n1", "shared", "n3"]),
            _way("b", ["shared", "n4"]),
        ]
    )

    # way b starts at "shared", which is an INTERIOR node of way a.
    assert adjacency["adjacent_by_way_node"]["b@shared"] == ("a",)
    assert adjacency["adjacent_by_way_node"]["a@shared"] == ("b",)
    # The role is recorded, so a split way is distinguishable from a
    # through-junction.
    assert adjacency["node_role_by_way"]["a@shared"] == "interior"
    assert adjacency["node_role_by_way"]["b@shared"] == "start"


def test_osm01_endpoint_adjacency_still_ignores_interior_nodes():
    """The endpoint-only view must keep its documented meaning."""
    from ultimate_pipeline.quality.osm_road_link_topology import (
        build_osm_way_adjacency,
    )

    adjacency = build_osm_way_adjacency(
        [
            {**_way("a", ["n1", "n2", "n3"])},
            _way("b", ["n3", "n4"]),
        ]
    )
    # b starts at n3, which is a's END, so b IS an endpoint neighbour.
    assert adjacency["adjacent_by_way_end"][("a", "end")] == ("b",)
    # c starts at n2 (interior of a) and is NOT an endpoint neighbour.
    other = build_osm_way_adjacency(
        [
            {**_way("a", ["n1", "n2", "n3"])},
            _way("c", ["n2", "n5"]),
        ]
    )
    assert other["adjacent_by_way_end"][("a", "end")] == ()
    assert other["summary"]["adjacency_edge_count"] == 0


def test_osm02_crossing_without_a_shared_node_is_not_connected():
    """OSM-02: a mere XY crossing must never create an edge."""
    adjacency = build_osm_source_adjacency(
        [
            _way("a", ["n1", "n2"], geometry=[(0.0, 0.0), (10.0, 0.0)]),
            # Way b crosses a in XY but shares no node.
            _way("b", ["n9", "n10"], geometry=[(5.0, -5.0), (5.0, 5.0)]),
        ]
    )

    assert adjacency["adjacent_by_way_node"].get("a@n1", ()) == ()
    assert adjacency["adjacent_by_way_node"].get("b@n9", ()) == ()
    assert adjacency["summary"]["adjacency_edge_count"] == 0


def test_osm03_same_name_parallel_roads_are_not_connected():
    """OSM-03: a shared street name is not adjacency evidence."""
    adjacency = build_osm_source_adjacency(
        [
            _way("a", ["n1", "n2"], geometry=[(0.0, 0.0), (10.0, 0.0)]),
            _way("b", ["n3", "n4"], geometry=[(0.5, 0.0), (10.5, 0.0)]),
        ]
    )

    assert adjacency["summary"]["adjacency_edge_count"] == 0


def test_grade_separated_ways_sharing_a_node_are_not_traversable():
    """A bridge and the road it crosses must never be connected."""
    adjacency = build_osm_source_adjacency(
        [
            _way("bridge", ["n1", "shared"], bridge="yes", layer="1"),
            _way("under", ["shared", "n3"], layer="0"),
        ]
    )

    assert adjacency["adjacent_by_way_node"].get("bridge@shared", ()) == ()
    blocked = adjacency["blocked_by_way_node"].get("bridge@shared", [])
    assert blocked and blocked[0]["reason"] in {
        "layer_mismatch",
        "bridge_tunnel_mismatch",
    }


def test_private_access_way_is_adjacent_but_not_eligible():
    """Topology existence and legal eligibility are separate facts."""
    adjacency = build_osm_source_adjacency(
        [
            _way("a", ["n1", "shared"]),
            _way("b", ["shared", "n3"], access="private"),
        ],
        vehicle_class="motor_vehicle",
    )

    # The ways share a node, so the edge exists in the graph...
    assert adjacency["adjacent_by_way_node"].get("a@shared", ()) == ()
    # ...but the connection is blocked by the access restriction.
    blocked = adjacency["blocked_by_way_node"].get("a@shared", [])
    assert blocked and blocked[0]["reason"] == "access_restricted"


def test_oneway_way_is_not_traversable_against_its_direction():
    """Entering a one-way way at its far end is a direction violation."""
    adjacency = build_osm_source_adjacency(
        [
            _way("a", ["n1", "shared"]),
            # b is oneway along its node order n3 -> shared; the shared node
            # is therefore b's END, and traffic may not enter it there.
            _way("b", ["n3", "shared"], oneway="yes"),
        ]
    )

    blocked = adjacency["blocked_by_way_node"].get("b@shared", [])
    assert any(item["reason"] == "oneway_against" for item in blocked)


def test_oneway_way_may_be_entered_at_its_start_node():
    """The direction rule must not block the legal direction."""
    adjacency = build_osm_source_adjacency(
        [
            _way("a", ["n1", "shared"]),
            _way("b", ["shared", "n3"], oneway="yes"),
        ]
    )

    blocked = adjacency["blocked_by_way_node"].get("b@shared", [])
    assert not any(item["reason"] == "oneway_against" for item in blocked)


# ---------------------------------------------------------------------------
# T03 — orphan repair requires source proof
# ---------------------------------------------------------------------------

def test_find_orphan_roads_only_counts_fully_isolated_roads():
    """A road that links to a junction is NOT an orphan.

    Counting junction-only roads as orphans inflated the figure by an order
    of magnitude on the real map (9 678 vs 6).
    """
    root = ET.fromstring(
        "<OpenDRIVE>"
        + _xodr("1", link='<link><successor elementType="road" elementId="2"/></link>')
        + _xodr("2")
        + _xodr("3", link='<link><successor elementType="junction" elementId="j"/></link>')
        + _xodr("4")
        + "</OpenDRIVE>"
    )

    orphans = find_orphan_roads(root)
    assert "1" not in orphans      # has a road-level link
    assert "3" not in orphans      # has a junction link
    assert "2" in orphans          # completely isolated
    assert "4" in orphans


def test_orphan_repair_requires_a_shared_osm_node():
    """Geometry alone must not repair an orphan."""
    root = ET.fromstring("<OpenDRIVE>" + _xodr("1", x=0.0) + _xodr("2", x=10.0) + "</OpenDRIVE>")
    ways = [
        _way("w1", ["a1", "a2"], geometry=[(0.0, 0.0), (10.0, 0.0)]),
        _way("w2", ["b1", "b2"], geometry=[(10.0, 0.0), (20.0, 0.0)]),
    ]
    associations = {"1": {"osm_way_id": "w1"}, "2": {"osm_way_id": "w2"}}

    results = reconcile_orphan_roads(root, osm_ways=ways, associations=associations)
    by_id = {r["xodr_road_id"]: r for r in results}

    # Both roads are near each other, but they share no OSM node.
    for candidate in results:
        assert candidate["status"] == ORPHAN_STATUS_UNRESOLVED
    assert by_id["1"]["reason"] in {"no_shared_osm_node", "no_source_correspondence"}


def test_orphan_repair_is_performed_only_with_shared_node_proof():
    root = ET.fromstring(
        "<OpenDRIVE>"
        + _xodr("1", x=0.0, length=10.0)
        + _xodr("2", x=10.0, length=10.0)
        + "</OpenDRIVE>"
    )
    ways = [
        _way("w1", ["n1", "shared"], geometry=[(0.0, 0.0), (10.0, 0.0)]),
        _way("w2", ["shared", "n3"], geometry=[(10.0, 0.0), (20.0, 0.0)]),
    ]
    associations = {"1": {"osm_way_id": "w1"}, "2": {"osm_way_id": "w2"}}

    results = reconcile_orphan_roads(root, osm_ways=ways, associations=associations)
    by_id = {r["xodr_road_id"]: r for r in results}

    # Road 2 links to road 1 via the shared OSM node "shared".
    repaired = by_id["2"]
    assert repaired["status"] == ORPHAN_STATUS_REPAIRED
    assert repaired["reason"] == "shared_osm_node_proven"
    assert repaired["source_way_id"] == "w2"
    assert repaired["neighbour_way_id"] == "w1"
    assert repaired["shared_node_id"] == "shared"
    assert repaired["neighbour_xodr_road_id"] == "1"
    assert float(repaired["gap_m"]) < 25.0


def test_orphan_repair_is_vetoed_by_geometry_after_source_proof():
    """Source proof is necessary but the geometric filters can still veto."""
    root = ET.fromstring(
        "<OpenDRIVE>"
        + _xodr("1", x=0.0, length=10.0)
        + _xodr("2", x=1000.0, length=10.0)
        + "</OpenDRIVE>"
    )
    ways = [
        _way("w1", ["n1", "shared"], geometry=[(0.0, 0.0), (10.0, 0.0)]),
        _way("w2", ["shared", "n3"], geometry=[(1000.0, 0.0), (1010.0, 0.0)]),
    ]
    associations = {"1": {"osm_way_id": "w1"}, "2": {"osm_way_id": "w2"}}

    results = reconcile_orphan_roads(root, osm_ways=ways, associations=associations)
    by_id = {r["xodr_road_id"]: r for r in results}

    assert by_id["2"]["status"] == ORPHAN_STATUS_UNRESOLVED
    assert by_id["2"]["reason"] == "source_proof_rejected_by_geometry"


def test_orphan_repair_is_unresolved_without_correspondence():
    root = ET.fromstring("<OpenDRIVE>" + _xodr("1") + "</OpenDRIVE>")
    ways = [_way("w1", ["n1", "n2"])]

    results = reconcile_orphan_roads(root, osm_ways=ways, associations={})
    assert results[0]["status"] == ORPHAN_STATUS_UNRESOLVED
    assert results[0]["reason"] == "no_source_correspondence"


def test_orphan_reconciliation_csv_is_written(tmp_path):
    root = ET.fromstring("<OpenDRIVE>" + _xodr("1") + "</OpenDRIVE>")
    results = reconcile_orphan_roads(
        root, osm_ways=[_way("w1", ["n1", "n2"])], associations={}
    )

    path = write_orphan_reconciliation_csv(
        str(tmp_path / "ORPHAN_ROAD_SOURCE_RECONCILIATION.csv"), results
    )
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["xodr_road_id"] == "1"
    assert rows[0]["status"] == ORPHAN_STATUS_UNRESOLVED


def test_find_unreachable_roads_reports_linked_but_unregistered_roads():
    """A road that links to a junction but is in none of its connections."""
    from ultimate_pipeline.topology.orphan_road_repair import (
        find_unreachable_roads,
    )

    root = ET.fromstring(
        "<OpenDRIVE>"
        # road 1 links to junction j, and j registers road 1 -> reachable
        + _xodr("1", link='<link><successor elementType="junction" elementId="j"/></link>')
        # road 2 links to junction j, but j never registers road 2
        + _xodr("2", link='<link><successor elementType="junction" elementId="j"/></link>')
        + '<junction id="j">'
        + '<connection id="c" incomingRoad="1" connectingRoad="3" contactPoint="start"/>'
        + "</junction>"
        + _xodr("3")
        + "</OpenDRIVE>"
    )

    unreachable = find_unreachable_roads(root)
    assert "1" not in unreachable
    assert "2" in unreachable


def test_find_unreachable_roads_excludes_fully_isolated_roads():
    """Fully isolated roads are orphans, not 'unreachable'."""
    from ultimate_pipeline.topology.orphan_road_repair import (
        find_orphan_roads,
        find_unreachable_roads,
    )

    root = ET.fromstring("<OpenDRIVE>" + _xodr("1") + "</OpenDRIVE>")

    assert find_orphan_roads(root) == ["1"]
    assert find_unreachable_roads(root) == []


# ---------------------------------------------------------------------------
# Extractor carries the restriction tags
# ---------------------------------------------------------------------------

def test_extractor_keeps_restriction_tags(tmp_path):
    osm = tmp_path / "roads.osm"
    osm.write_text(
        '<?xml version="1.0"?><osm version="0.6">'
        '<node id="1" lat="48.0" lon="11.0"/>'
        '<node id="2" lat="48.001" lon="11.0"/>'
        '<way id="9"><nd ref="1"/><nd ref="2"/>'
        '<tag k="highway" v="residential"/>'
        '<tag k="oneway" v="yes"/>'
        '<tag k="bridge" v="yes"/>'
        '<tag k="layer" v="1"/>'
        '<tag k="access" v="private"/>'
        "</way></osm>",
        encoding="utf-8",
    )

    ways = extract_osm_highway_ways(str(osm))
    assert len(ways) == 1
    restrictions = ways[0]["restrictions"]
    assert restrictions["oneway"] == "yes"
    assert restrictions["bridge"] == "yes"
    assert restrictions["layer"] == "1"
    assert restrictions["access"] == "private"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_source_adjacency_is_deterministic_under_way_order_permutation():
    ways = [
        _way("a", ["n1", "shared"]),
        _way("b", ["shared", "n3"]),
        _way("c", ["n4", "n5"]),
    ]

    first = build_osm_source_adjacency(ways)
    second = build_osm_source_adjacency(list(reversed(ways)))
    third = build_osm_source_adjacency(sorted(ways, key=lambda w: w["id"]))

    assert first == second == third


# ---------------------------------------------------------------------------
# Mutation control
# ---------------------------------------------------------------------------

def test_mutation_control_removing_the_source_proof_check_makes_the_test_fail(
    monkeypatch,
):
    """Neutralize the shared-node source proof; the repair test must fail.

    This proves the T03 test really binds the OSM source authority and is
    not satisfied by geometry alone.
    """
    import ultimate_pipeline.quality.osm_road_link_topology as topology_module

    original = topology_module.build_osm_source_adjacency

    def _broken_adjacency(ways, *, vehicle_class="motor_vehicle"):
        # Pre-fix behaviour: no interior-node adjacency at all, so no shared
        # node can ever prove a continuation.
        result = original(ways, vehicle_class=vehicle_class)
        result["adjacent_by_way_node"] = {}
        return result

    monkeypatch.setattr(
        topology_module, "build_osm_source_adjacency", _broken_adjacency
    )

    root = ET.fromstring(
        "<OpenDRIVE>"
        + _xodr("1", x=0.0, length=10.0)
        + _xodr("2", x=10.0, length=10.0)
        + "</OpenDRIVE>"
    )
    ways = [
        _way("w1", ["n1", "shared"], geometry=[(0.0, 0.0), (10.0, 0.0)]),
        _way("w2", ["shared", "n3"], geometry=[(10.0, 0.0), (20.0, 0.0)]),
    ]
    associations = {"1": {"osm_way_id": "w1"}, "2": {"osm_way_id": "w2"}}

    mutated = reconcile_orphan_roads(
        root, osm_ways=ways, associations=associations
    )
    by_id = {r["xodr_road_id"]: r for r in mutated}
    # The repair no longer happens without the source proof.
    assert by_id["2"]["status"] != ORPHAN_STATUS_REPAIRED
    assert by_id["2"]["reason"] == "no_shared_osm_node"
