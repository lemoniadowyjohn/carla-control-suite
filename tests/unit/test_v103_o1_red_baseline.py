"""V103-O1 — fail-before baseline (registry T01 / T02).

This file deliberately uses **only the pre-existing public API**
(``driving_lane_counts``) so that it can be executed unchanged on the
unmodified production base.  On the old base it FAILS; on the fixed source
it PASSES.  That is the fail-before / pass-after proof for:

* **T01** — a one-way road with ``lanes=2`` must not gain a counterflow
  driving lane.
* **T02** — a reversed XODR reference line must map the OSM forward lanes
  onto the correct carriageway.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.lane_width_policy import driving_lane_counts


def _road(road_id: str = "1") -> ET.Element:
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id=road_id, junction="-1", length="100.0")
    ET.SubElement(road, "lanes")
    return road


def test_baseline_oneway_two_lane_road_has_no_counterflow():
    """Old base: ``driving_lane_counts`` split ``lanes=2`` into (1, 1).

    A one-way road carries all of its lanes in the legal direction, so the
    correct answer is (backward=0, forward=2).
    """
    backward, forward, _source, _confidence = driving_lane_counts(
        _road(),
        structural_osm_meta={"1": {"oneway": "yes", "lanes": "2"}},
    )

    assert (backward, forward) == (0, 2), (
        "oneway=yes lanes=2 produced a phantom counterflow driving lane: "
        f"backward={backward} forward={forward}"
    )


def test_baseline_reversed_xodr_road_maps_lanes_to_the_correct_carriageway():
    """Old base: the orientation was discarded, so the counts were not swapped."""
    backward, forward, _source, _confidence = driving_lane_counts(
        _road(),
        structural_osm_meta={
            "1": {"oneway": "yes", "lanes": "2", "_osm_direction": "reverse"}
        },
    )

    assert (backward, forward) == (2, 0), (
        "a reversed XODR reference line did not swap the carriageways: "
        f"backward={backward} forward={forward}"
    )


def test_baseline_oneway_reverse_keeps_the_single_lane_in_the_reverse_direction():
    backward, forward, _source, _confidence = driving_lane_counts(
        _road(),
        structural_osm_meta={"1": {"oneway": "-1", "lanes": "1"}},
    )

    assert (backward, forward) == (1, 0), (
        f"oneway=-1 lanes=1 produced backward={backward} forward={forward}"
    )
