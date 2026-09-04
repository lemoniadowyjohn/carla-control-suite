"""RealismModule._infer_speed() (2026-09-04 fix): the pre-fix implementation
only pattern-matched <type type="..."> against an OSM-style vocabulary
(motorway/primary/secondary/residential). Every road this pipeline actually
generates carries <type type="town"> (OpenDRIVE-standard vocabulary, not the
OSM one), which never matches -- so _infer_speed() always returned None,
StreetFurnitureRules.is_residential(None) was always False, and benches
(ENABLE_BENCHES=True by default) were NEVER placed on any real regen (0 on
the real map-of-record candidate, confirmed directly).

The fix reads the road's own <lane><speed max="X"/> data instead, which the
base OSM-to-XODR conversion stamps on nearly every driving/restricted lane
(34,285/34,291 on the real candidate) with no unit attribute -- OpenDRIVE's
documented default unit for <speed> is m/s, not km/h. The <type> heuristic
is kept only as a fallback for fixtures/other maps with no <speed> data at
all.
"""
import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.realism import RealismModule
from ultimate_pipeline.enrichment.street_furniture_rules import StreetFurnitureRules


def _road_with_lane_speed(max_attr: str, unit: str | None = None, lane_type: str = "driving") -> ET.Element:
    road = ET.Element("road", id="1", junction="-1", length="400.0")
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection", s="0")
    right = ET.SubElement(section, "right")
    lane = ET.SubElement(right, "lane", id="-1", type=lane_type, level="false")
    ET.SubElement(lane, "width", sOffset="0", a="3.5", b="0", c="0", d="0")
    attrs = {"sOffset": "0", "max": max_attr}
    if unit is not None:
        attrs["unit"] = unit
    ET.SubElement(lane, "speed", **attrs)
    return road


def _road_with_type(type_value: str) -> ET.Element:
    road = ET.Element("road", id="1", junction="-1", length="400.0")
    ET.SubElement(road, "type", s="0", type=type_value)
    return road


def test_infer_speed_reads_real_lane_speed_ms_no_unit_attr():
    # 8.33 m/s is the exact value this pipeline's base converter writes for a
    # 30 km/h zone (no unit attribute present == OpenDRIVE's m/s default).
    road = _road_with_lane_speed("8.33")
    assert RealismModule._infer_speed(road) == 30


def test_infer_speed_reads_explicit_kmh_unit():
    # speed_limit_writer.py's own format, on the rare lane it actually fires on.
    road = _road_with_lane_speed("30", unit="km/h")
    assert RealismModule._infer_speed(road) == 30


def test_infer_speed_reads_mph_unit():
    road = _road_with_lane_speed("20", unit="mph")
    assert RealismModule._infer_speed(road) == round(20 * 1.60934)


def test_infer_speed_ignores_non_driving_lanes():
    road = _road_with_lane_speed("8.33", lane_type="sidewalk")
    assert RealismModule._infer_speed(road) is None


def test_infer_speed_falls_back_to_type_when_no_lane_speed_present():
    # Old behavior preserved as a fallback for fixtures/other maps.
    road = _road_with_type("motorway")
    assert RealismModule._infer_speed(road) == 120


def test_infer_speed_town_type_and_no_lane_speed_returns_none():
    # This pipeline's actual real-world case: <type type="town"> (OpenDRIVE
    # vocabulary), no <speed> data at all -- regression guard, must stay None.
    road = _road_with_type("town")
    assert RealismModule._infer_speed(road) is None


def test_infer_speed_none_when_no_type_and_no_lane_speed():
    road = ET.Element("road", id="1", junction="-1", length="400.0")
    assert RealismModule._infer_speed(road) is None


def test_benches_now_fire_via_enrich_on_road_with_real_residential_lane_speed(monkeypatch):
    from ultimate_pipeline.config.settings import SETTINGS

    monkeypatch.setattr(SETTINGS, "ENABLE_REALISM_RULES", True)
    monkeypatch.setattr(SETTINGS, "ENABLE_BENCHES", True)
    monkeypatch.setattr(SETTINGS, "ENABLE_SMART_LAMPS", False)
    monkeypatch.setattr(SETTINGS, "ENABLE_GUARDRAILS", False)
    monkeypatch.setattr(SETTINGS, "ENABLE_TRASH_BINS", False)

    road = _road_with_lane_speed("8.33")  # 30 km/h -- in BENCH_ALLOWED_SPEEDS
    pv = ET.SubElement(road, "planView")
    geom = ET.SubElement(pv, "geometry", s="0", x="0", y="0", hdg="0", length="400.0")
    ET.SubElement(geom, "line")

    root = ET.Element("OpenDRIVE")
    root.append(road)

    RealismModule.enrich(root)

    benches = road.findall(".//objects/object[@type='bench']")
    assert len(benches) == int(400.0 // StreetFurnitureRules.BENCH_INTERVAL)
    assert len(benches) > 0


def test_benches_still_absent_via_enrich_on_type_town_road_with_no_speed_data(monkeypatch):
    # Regression guard for the OLD broken behavior: a road with only
    # <type type="town"> and no <speed> data must NOT get benches.
    from ultimate_pipeline.config.settings import SETTINGS

    monkeypatch.setattr(SETTINGS, "ENABLE_REALISM_RULES", True)
    monkeypatch.setattr(SETTINGS, "ENABLE_BENCHES", True)
    monkeypatch.setattr(SETTINGS, "ENABLE_SMART_LAMPS", False)
    monkeypatch.setattr(SETTINGS, "ENABLE_GUARDRAILS", False)
    monkeypatch.setattr(SETTINGS, "ENABLE_TRASH_BINS", False)

    road = _road_with_type("town")
    pv = ET.SubElement(road, "planView")
    geom = ET.SubElement(pv, "geometry", s="0", x="0", y="0", hdg="0", length="400.0")
    ET.SubElement(geom, "line")

    root = ET.Element("OpenDRIVE")
    root.append(road)

    RealismModule.enrich(root)

    benches = road.findall(".//objects/object[@type='bench']")
    assert len(benches) == 0
