from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.speed_limit_writer import (
    _existing_speed_kmh,
    apply_speed_limits,
)


def _road(rid: str, *, speed_max: str | None = None, speed_unit: str | None = None) -> ET.Element:
    attrs = {"id": rid, "length": "10"}
    road = ET.Element("road", attrs)
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection", s="0")
    right = ET.SubElement(section, "right")
    lane = ET.SubElement(right, "lane", id="-1", type="driving")
    if speed_max is not None:
        el = ET.SubElement(lane, "speed", max=speed_max)
        if speed_unit is not None:
            el.set("unit", speed_unit)
    return road


def test_existing_speed_kmh_treats_missing_unit_as_opendrive_default_mps():
    speed_el = ET.Element("speed", max="13.888888888888889")
    assert round(_existing_speed_kmh(speed_el)) == 50


def test_existing_speed_kmh_respects_explicit_kmh():
    speed_el = ET.Element("speed", max="50", unit="km/h")
    assert _existing_speed_kmh(speed_el) == 50.0


def test_existing_speed_kmh_converts_mph():
    speed_el = ET.Element("speed", max="30", unit="mph")
    assert round(_existing_speed_kmh(speed_el), 2) == round(30 * 1.60934, 2)


def test_spatial_overwrite_skipped_when_existing_value_already_agrees():
    """The exact false-rewrite class found on the pinned map: a base-
    conversion speed stored with no unit attribute (OpenDRIVE's documented
    m/s default) that already represents the same real-world speed as the
    OSM value must NOT be rewritten -- doing so only introduces a mixed
    unit convention (unit="km/h" appearing among thousands of unitless
    lanes) for zero real change. 13.888...89 m/s == 50.00 km/h."""
    road = _road("7", speed_max="13.888888888888889")
    root = ET.Element("OpenDRIVE")
    root.append(road)
    associations = {"7": {"class": "HIGH", "metadata": {"maxspeed": "50"}}}

    written = apply_speed_limits(root, {}, correspondence_by_road_id=associations)

    assert written == 0
    speed_el = road.find(".//speed")
    assert speed_el.get("max") == "13.888888888888889"
    assert speed_el.get("unit") is None


def test_spatial_overwrite_applied_when_existing_value_genuinely_disagrees():
    """The exact real-correction class found on the pinned map: an existing
    speed that, correctly unit-interpreted, does NOT match OSM's value must
    still be corrected -- this is real, valuable data repair, not the noise
    the previous naive-string-comparison behaviour also caught."""
    road = _road("7", speed_max="4.37")  # ~15.7 km/h stored, OSM says 100
    root = ET.Element("OpenDRIVE")
    root.append(road)
    associations = {"7": {"class": "HIGH", "metadata": {"maxspeed": "100"}}}

    written = apply_speed_limits(root, {}, correspondence_by_road_id=associations)

    assert written == 1
    speed_el = road.find(".//speed")
    assert speed_el.get("max") == "100"
    assert speed_el.get("unit") == "km/h"


def test_spatial_insert_when_no_existing_speed():
    road = _road("7")
    root = ET.Element("OpenDRIVE")
    root.append(road)
    associations = {"7": {"class": "HIGH", "metadata": {"maxspeed": "50"}}}

    written = apply_speed_limits(root, {}, correspondence_by_road_id=associations)

    assert written == 1
    speed_el = road.find(".//speed")
    assert speed_el.get("max") == "50"
    assert speed_el.get("unit") == "km/h"


def test_legacy_name_mode_remains_insert_only_even_on_disagreement():
    """The legacy street-name-matched mode's correspondence is many-to-many
    and must stay insert-only regardless of value agreement -- unchanged by
    this fix, confirmed explicitly."""
    road = _road("7", speed_max="4.37")
    road.set("name", "Main Street")
    root = ET.Element("OpenDRIVE")
    root.append(road)

    written = apply_speed_limits(root, {"Main Street": {"maxspeed": "100"}})

    assert written == 0
    speed_el = road.find(".//speed")
    assert speed_el.get("max") == "4.37"
