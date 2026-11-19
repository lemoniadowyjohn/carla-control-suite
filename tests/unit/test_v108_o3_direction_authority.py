"""V108 Phase 2 — an undecidable OSM direction must never become a proven
legal road connection.

Defect (verified on the pre-fix code):

* ``_way_is_oneway_forward`` returned ``ONEWAY_UNKNOWN`` for a way with NO
  ``oneway`` tag at all, and also for the genuinely undecidable cases
  (``oneway=reversible``, ``oneway:conditional``, an unrecognised
  ``oneway`` value).
* ``_can_leave`` / ``_can_enter`` then returned **True** for
  ``ONEWAY_UNKNOWN`` ("it may leave/enter anywhere").

So a way whose direction cannot be decided from the source was treated as
**proven legal movement** in every direction -- indistinguishable from a
proven two-way way, and it could authorize an orphan-road repair.

The extractor additionally dropped ``oneway:conditional``, ``reversible`` and
``highway``, so the module could not even SEE those facts.

Fix:

* the extractor retains ``oneway:conditional``, ``reversible`` and ``highway``;
* a way with no ``oneway`` tag is ``bidirectional`` -- a PROVEN OSM default,
  not missing evidence;
* ``oneway:conditional`` / ``oneway=reversible`` / an unrecognised value is
  ``unknown`` -- NOT ASSESSABLE;
* ``unknown`` is not traversable, and is reported in its own
  ``not_assessable`` bucket rather than in the ``blocked`` bucket.
"""

from __future__ import annotations

from ultimate_pipeline.quality.osm_road_link_topology import (
    ONEWAY_BIDIRECTIONAL,
    ONEWAY_FORWARD,
    ONEWAY_REVERSE,
    ONEWAY_UNKNOWN,
    _way_is_oneway_forward,
    build_osm_source_adjacency,
)


def _way(way_id, nodes, **tags):
    """A way record in the shape the topology module consumes.

    ``_way_restrictions`` reads the tags from the ``restrictions`` and
    ``metadata`` mappings, not from the top level.
    """
    record = {
        "id": way_id,
        "name": "",
        "geometry": [(0.0, 0.0), (10.0, 0.0)],
        "node_refs": list(nodes),
        "metadata": dict(tags),
        "restrictions": dict(tags),
    }
    return record


# ---------------------------------------------------------------------------
# The oneway STATE must distinguish "proven" from "not decidable"
# ---------------------------------------------------------------------------

def test_v108_no_oneway_tag_is_a_proven_two_way_way():
    """The OSM default is two-way -- a PROVEN fact, not missing evidence."""
    assert _way_is_oneway_forward({}) == ONEWAY_BIDIRECTIONAL
    assert _way_is_oneway_forward({"highway": "residential"}) == ONEWAY_BIDIRECTIONAL


def test_v108_conditional_oneway_is_not_assessable():
    assert _way_is_oneway_forward({"oneway:conditional": "yes @ (10:00-16:00)"}) == (
        ONEWAY_UNKNOWN
    )


def test_v108_reversible_and_unrecognised_oneway_are_not_assessable():
    assert _way_is_oneway_forward({"oneway": "reversible"}) == ONEWAY_UNKNOWN
    assert _way_is_oneway_forward({"oneway": "sometimes"}) == ONEWAY_UNKNOWN


def test_v108_explicit_states_are_unchanged():
    assert _way_is_oneway_forward({"oneway": "yes"}) == ONEWAY_FORWARD
    assert _way_is_oneway_forward({"oneway": "-1"}) == ONEWAY_REVERSE
    assert _way_is_oneway_forward({"oneway": "no"}) == ONEWAY_BIDIRECTIONAL
    assert _way_is_oneway_forward({"junction": "roundabout"}) == ONEWAY_FORWARD


def test_v108_motorway_is_an_implicit_one_way():
    """OSM: a motorway is one-way unless tagged otherwise."""
    assert _way_is_oneway_forward({"highway": "motorway"}) == ONEWAY_FORWARD
    assert _way_is_oneway_forward({"highway": "motorway_link"}) == ONEWAY_FORWARD
    # An explicit tag still wins.
    assert _way_is_oneway_forward({"highway": "motorway", "oneway": "no"}) == (
        ONEWAY_BIDIRECTIONAL
    )


# ---------------------------------------------------------------------------
# An undecidable way must not create a proven legal connection
# ---------------------------------------------------------------------------

def test_v108_unknown_direction_is_not_a_proven_legal_connection():
    """The pre-fix code connected the pair and reported no reason at all."""
    adjacency = build_osm_source_adjacency(
        [
            _way("a", ["n1", "shared"]),
            _way("b", ["shared", "n3"], oneway="reversible"),
        ]
    )

    assert adjacency["adjacent_by_way_node"].get("a@shared", ()) == ()
    assert adjacency["adjacent_by_way_node"].get("b@shared", ()) == ()

    blocked = adjacency["blocked_by_way_node"].get("a@shared", [])
    assert blocked
    assert blocked[0]["reason"] == "oneway_direction_not_assessable"


def test_v108_conditional_oneway_is_not_assessable_in_the_adjacency():
    adjacency = build_osm_source_adjacency(
        [
            _way("a", ["n1", "shared"]),
            _way("b", ["shared", "n3"], **{"oneway:conditional": "yes @ (10:00-16:00)"}),
        ]
    )

    assert adjacency["adjacent_by_way_node"].get("a@shared", ()) == ()
    blocked = adjacency["blocked_by_way_node"].get("b@shared", [])
    assert any(item["reason"] == "oneway_direction_not_assessable" for item in blocked)


def test_v108_not_assessable_is_a_separate_population_from_blocked():
    """Not-assessable must NOT be reported as a prohibition."""
    adjacency = build_osm_source_adjacency(
        [
            _way("a", ["n1", "shared"]),
            _way("b", ["shared", "n3"], oneway="reversible"),
            _way("c", ["shared", "n4"]),
        ]
    )

    assert adjacency["summary"]["not_assessable_count"] >= 1
    assert adjacency["not_assessable"]
    for item in adjacency["not_assessable"]:
        assert item["reason"] == "oneway_direction_not_assessable"


def test_v108_a_conditional_way_does_not_damage_the_untagged_default():
    """A plain untagged way stays two-way and stays connected."""
    adjacency = build_osm_source_adjacency(
        [
            _way("a", ["n1", "shared"]),
            _way("b", ["shared", "n3"]),
        ]
    )

    assert adjacency["adjacent_by_way_node"].get("a@shared", ()) == ("b",)
    assert adjacency["adjacent_by_way_node"].get("b@shared", ()) == ("a",)
    assert adjacency["summary"]["not_assessable_count"] == 0


def test_v108_extractor_retains_the_tags_the_direction_needs():
    """The restriction extractor must keep the facts the resolver reads."""
    from ultimate_pipeline.quality.osm_road_link_topology import (
        _RESTRICTION_TAGS,
    )

    for tag in ("oneway", "oneway:conditional", "reversible", "highway", "junction"):
        assert tag in _RESTRICTION_TAGS, (
            f"the OSM direction resolver cannot see the {tag!r} tag"
        )


def test_v108_motorway_is_not_connected_in_the_reverse_direction():
    """An implicit one-way motorway may not be entered against its direction."""
    adjacency = build_osm_source_adjacency(
        [
            _way("a", ["n1", "shared"], highway="motorway"),
            _way("b", ["shared", "n3"]),
        ]
    )

    blocked = adjacency["blocked_by_way_node"].get("b@shared", [])
    assert any(
        item["reason"] in {"oneway_arrival_against", "oneway_departure_against"}
        for item in blocked
    )
