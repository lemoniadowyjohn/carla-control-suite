"""V108 Phase 3 -- the lane semantics that must be LEGAL DIRECTIONAL
GEOMETRY, not fabricated through lanes.

V106 P1 item 8 / V108 Phase 3 ask for ``lanes:both_ways`` and ``lanes=1``
to be **tested** as legal directional geometry.  A probe of the current
implementation showed the behaviour is already correct:

  lanes=1, oneway=yes      -> 0 backward, 1 forward   (one lane, legal direction)
  lanes=1, oneway=no       -> 0 backward, 1 forward   (historical assignment)
  lanes=2, oneway=yes      -> 0 backward, 2 forward
  lanes=3, oneway=no       -> 1 backward, 2 forward   (historical assignment)
  lanes=3 + both_ways=1    -> 1 backward, 2 forward   (the shared lane is NOT
                                                       added to either side)
  lanes=2 + both_ways=1    -> 0 backward, 2 forward

No case fabricates a lane: the resolved total never exceeds the OSM lane
total, and no lane is placed in a direction the source forbids.

**What was missing was the test that pins this.**  These tests are that
pin, and each has a mutation control: if the behaviour regresses, the
corresponding test fails.
"""

from __future__ import annotations

import pytest

from ultimate_pipeline.enrichment.osm_direction import (
    resolve_directional_lane_counts,
)


def _resolve(tags, *, direction="forward"):
    return resolve_directional_lane_counts(tags, osm_direction=direction)


# ---------------------------------------------------------------------------
# lanes=1 -- a single lane must not become a two-lane road
# ---------------------------------------------------------------------------


def test_phase3_a_single_lane_one_way_road_keeps_one_lane():
    resolved = _resolve({"lanes": "1", "oneway": "yes"})
    assert resolved.backward == 0
    assert resolved.forward == 1
    assert resolved.backward + resolved.forward == 1
    assert resolved.state == "ok"


def test_phase3_a_single_lane_two_way_road_keeps_one_lane():
    resolved = _resolve({"lanes": "1", "oneway": "no"})
    assert resolved.backward + resolved.forward == 1
    assert resolved.state == "ok"


def test_phase3_a_single_lane_without_a_oneway_tag_is_not_assumed():
    """With no ``oneway`` tag the direction of a lone lane is ambiguous."""
    resolved = _resolve({"lanes": "1"})
    assert resolved.backward + resolved.forward == 1
    assert resolved.state == "unsupported"
    assert any("oneway" in note for note in resolved.notes)


# ---------------------------------------------------------------------------
# lanes:both_ways -- a shared centre lane is not added to either side
# ---------------------------------------------------------------------------


def test_phase3_lanes_both_ways_is_not_added_to_either_direction():
    """``lanes:both_ways`` counts CENTRE lanes, not directional ones.

    Adding them to a side would fabricate a lane the source does not
    describe on that side.
    """
    without = _resolve({"lanes": "3", "oneway": "no"})
    with_shared = _resolve({"lanes": "3", "lanes:both_ways": "1", "oneway": "no"})

    assert (with_shared.backward, with_shared.forward) == (
        without.backward,
        without.forward,
    )
    assert with_shared.backward + with_shared.forward == 3
    assert any("both_ways" in note for note in with_shared.notes)


def test_phase3_lanes_both_ways_does_not_fabricate_on_a_one_way_road():
    resolved = _resolve({"lanes": "2", "lanes:both_ways": "1", "oneway": "yes"})
    assert resolved.backward == 0
    assert resolved.forward == 2
    assert resolved.backward + resolved.forward == 2


def test_phase3_a_lanes_total_is_never_exceeded():
    """The resolved total must never exceed the OSM lane total."""
    for lanes, oneway, both_ways in (
        ("1", "yes", None),
        ("2", "yes", "1"),
        ("3", "no", "1"),
        ("4", "no", None),
        ("2", "no", "1"),
    ):
        tags = {"lanes": lanes, "oneway": oneway}
        if both_ways:
            tags["lanes:both_ways"] = both_ways
        resolved = _resolve(tags)
        assert resolved.backward + resolved.forward <= int(lanes), (
            f"lanes={lanes} oneway={oneway} both_ways={both_ways} produced "
            f"{resolved.backward + resolved.forward} lanes"
        )


def test_phase3_no_lane_is_placed_against_a_one_way_direction():
    for lanes in ("1", "2", "3", "4"):
        resolved = _resolve({"lanes": lanes, "oneway": "yes"})
        assert resolved.backward == 0, (
            f"lanes={lanes} oneway=yes produced a backward lane"
        )


# ---------------------------------------------------------------------------
# The odd-total historical assignment is preserved
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lanes", "expected_backward", "expected_forward"),
    [
        ("1", 0, 1),
        ("2", 1, 1),
        ("3", 1, 2),
        ("4", 2, 2),
        ("5", 2, 3),
    ],
)
def test_phase3_the_odd_total_assignment_is_the_historical_one(
    lanes, expected_backward, expected_forward
):
    """``total // 2`` backward and the remainder forward, unchanged."""
    resolved = _resolve({"lanes": lanes, "oneway": "no"})
    assert (resolved.backward, resolved.forward) == (
        expected_backward,
        expected_forward,
    )


def test_phase3_directional_tags_win_over_the_total():
    resolved = _resolve(
        {"lanes": "2", "lanes:forward": "1", "lanes:backward": "1", "oneway": "no"}
    )
    assert (resolved.backward, resolved.forward) == (1, 1)
    assert resolved.source == "osm:lanes:forward+backward"


def test_phase3_the_orientation_swaps_the_directional_result():
    """A reversed OSM way swaps forward and backward."""
    forward = _resolve({"lanes": "2", "oneway": "yes"}, direction="forward")
    reverse = _resolve({"lanes": "2", "oneway": "yes"}, direction="reverse")
    assert (forward.backward, forward.forward) == (0, 2)
    assert (reverse.backward, reverse.forward) == (2, 0)
