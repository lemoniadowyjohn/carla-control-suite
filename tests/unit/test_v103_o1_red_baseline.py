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


# ---------------------------------------------------------------------------
# Real-map coordinate-frame defect
# ---------------------------------------------------------------------------

DECLARED_CRS = (
    "+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 "
    "+datum=WGS84 +units=m +no_defs"
)
PROBE_LON = 11.4611034
PROBE_LAT = 48.7732712


def test_baseline_projection_uses_the_declared_crs_when_the_map_has_no_offset():
    """A map without ``<offset>`` stores global coordinates in its declared CRS.

    On the unmodified base the OSM source was always projected with the
    hardcoded bare-tmerc default (``lon_0=0``), which places it ~161 km east
    and ~63 km north of such a map.  On the pinned Ingolstadt pair that
    silently turned all 3057 source ways into ``UNMATCHED``.
    """
    from ultimate_pipeline.enrichment.osm_meta_index import (
        project_positioned_osm_metadata_ways,
    )

    root = ET.Element("OpenDRIVE")
    header = ET.SubElement(root, "header")
    geo = ET.SubElement(header, "geoReference")
    geo.text = DECLARED_CRS  # no <offset> element -> global coordinates
    ET.SubElement(root, "road", id="1", length="10")

    ways = [
        {
            "id": "w1",
            "geometry": [(PROBE_LON, PROBE_LAT), (PROBE_LON + 0.001, PROBE_LAT)],
            "metadata": {"lanes": "2"},
        }
    ]

    projected = project_positioned_osm_metadata_ways(ways, root)

    assert len(projected) == 1
    x, y = projected[0]["geometry"][0]

    from pyproj import Transformer

    ref_x, ref_y = Transformer.from_crs(
        "EPSG:4326", DECLARED_CRS, always_xy=True
    ).transform(PROBE_LON, PROBE_LAT)

    assert abs(x - ref_x) < 1.0, (
        f"projected x {x} does not match the map's declared CRS {ref_x}"
    )
    assert abs(y - ref_y) < 1.0, (
        f"projected y {y} does not match the map's declared CRS {ref_y}"
    )
