from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.traffic_light_infer import TrafficLightInferer

_JUNCTION_XODR = """<?xml version="1.0" encoding="utf-8"?>
<OpenDRIVE>
<header revMajor="1" revMinor="6"/>
<road id="1" length="20" junction="-1">
<link><successor elementType="junction" elementId="10"/></link>
<planView><geometry s="0" x="0" y="0" hdg="0" length="20"><line/></geometry></planView>
</road>
<road id="2" length="20" junction="-1">
<link><successor elementType="junction" elementId="10"/></link>
<planView><geometry s="0" x="0" y="20" hdg="1.5708" length="20"><line/></geometry></planView>
</road>
<road id="3" length="20" junction="-1">
<link><successor elementType="junction" elementId="10"/></link>
<planView><geometry s="0" x="20" y="0" hdg="3.14159" length="20"><line/></geometry></planView>
</road>
<junction id="10">
<connection id="0" incomingRoad="1" connectingRoad="100" contactPoint="start"><laneLink from="-1" to="-1"/></connection>
<connection id="1" incomingRoad="2" connectingRoad="101" contactPoint="start"><laneLink from="-1" to="-1"/></connection>
<connection id="2" incomingRoad="3" connectingRoad="102" contactPoint="start"><laneLink from="-1" to="-1"/></connection>
</junction>
</OpenDRIVE>"""


def _load_root() -> ET.Element:
    return ET.fromstring(_JUNCTION_XODR)


def test_default_mode_inserts_nothing_without_source_or_fallback():
    """P0 signal authority: no OSM source + disabled fallback => 0 signals."""
    root = _load_root()
    import os as _os

    saved = _os.environ.pop("UP_OSM_SIGNALS_SOURCE", None)
    saved_fb = _os.environ.pop("UP_ENABLE_TL_HEURISTIC_FALLBACK", None)
    try:
        count = TrafficLightInferer.infer_and_insert(root)
    finally:
        if saved is not None:
            _os.environ["UP_OSM_SIGNALS_SOURCE"] = saved
        if saved_fb is not None:
            _os.environ["UP_ENABLE_TL_HEURISTIC_FALLBACK"] = saved_fb

    assert count == 0
    assert root.findall(".//signal") == []
    stats = TrafficLightInferer.last_run_stats
    assert stats["osm_mapped"] == 0
    assert stats["heuristic_fallback_enabled"] is False


def test_heuristic_fallback_requires_explicit_opt_in():
    """Heuristic signals exist only when explicitly enabled (inferred bucket)."""
    root = _load_root()
    count = TrafficLightInferer.infer_and_insert(
        root, allow_heuristic_fallback=True
    )

    assert count == 3
    objects = root.findall(".//object[@type='traffic_light']")
    assert len(objects) == 3

    signals = root.findall(".//signal")
    assert len(signals) == 3, "each traffic_light object must have a paired <signal>"
    for sig in signals:
        prov = sig.find("./userData/provenance")
        assert prov is not None
        assert prov.get("confidence") == "inferred"


def test_traffic_light_signals_are_functional_not_props():
    root = _load_root()
    TrafficLightInferer.infer_and_insert(root, allow_heuristic_fallback=True)

    signals = root.findall(".//signal")
    assert signals, "expected at least one <signal>"
    for sig in signals:
        # OpenDRIVE generic traffic-light catalog type.
        assert sig.get("type") == "1000001"
        # A traffic light is a dynamic (state-changing) signal.
        assert sig.get("dynamic") == "yes"
        assert sig.get("id")


def test_traffic_light_signals_grouped_under_junction_controller():
    root = _load_root()
    TrafficLightInferer.infer_and_insert(root, allow_heuristic_fallback=True)

    controllers = root.findall(".//controller")
    assert controllers, "expected at least one <controller> grouping the junction's signals"

    all_signal_ids = {s.get("id") for s in root.findall(".//signal")}
    controlled_ids = set()
    for c in controllers:
        for ctrl in c.findall("control"):
            controlled_ids.add(ctrl.get("signalId"))

    assert controlled_ids, "controller must reference signal ids via <control>"
    assert controlled_ids.issubset(all_signal_ids)


def test_heuristic_insert_is_idempotent_for_signals():
    root = _load_root()
    TrafficLightInferer.infer_and_insert(root, allow_heuristic_fallback=True)
    first_signal_count = len(root.findall(".//signal"))

    # Re-running against a junction whose roads already carry signals must
    # not silently duplicate them (mirrors the existing <object> id reuse
    # pattern -- object ids are deterministic "tl_<junction>_<idx>").
    TrafficLightInferer.infer_and_insert(root, allow_heuristic_fallback=True)
    second_signal_count = len(root.findall(".//signal"))

    assert second_signal_count == first_signal_count


def test_junction_coverage_stats_reports_full_coverage_for_qualifying_junction():
    root = _load_root()
    TrafficLightInferer.infer_and_insert(root, allow_heuristic_fallback=True)

    stats = TrafficLightInferer.junction_coverage_stats(root)

    assert stats["total_junctions"] == 1
    assert stats["roundabout_junctions"] == 0
    assert stats["eligible_junctions"] == 1
    assert stats["eligible_junctions_with_signal"] == 1
    assert stats["eligible_junctions_with_heuristic_signal"] == 1
    assert stats["eligible_junctions_with_osm_signal"] == 0
    assert stats["eligible_junction_coverage_fraction"] == 1.0
    assert stats["total_signals"] == 3


def test_junction_coverage_stats_zero_when_no_signals_inserted():
    root = _load_root()
    TrafficLightInferer.infer_and_insert(root)  # governed default: no source

    stats = TrafficLightInferer.junction_coverage_stats(root)
    assert stats["eligible_junctions"] == 1
    assert stats["eligible_junctions_with_signal"] == 0
    assert stats["eligible_junction_coverage_fraction"] == 0.0
    assert "zero inserted" in stats["provenance"]


def test_junction_coverage_stats_excludes_roundabouts_and_sub_threshold_junctions():
    root = ET.Element("OpenDRIVE")
    ET.SubElement(root, "junction", id="rab", isRoundabout="true")
    two_way = ET.SubElement(root, "junction", id="two_way")
    ET.SubElement(two_way, "connection", id="0", incomingRoad="1")
    ET.SubElement(two_way, "connection", id="1", incomingRoad="2")

    stats = TrafficLightInferer.junction_coverage_stats(root)

    assert stats["total_junctions"] == 2
    assert stats["roundabout_junctions"] == 1
    assert stats["eligible_junctions"] == 0
    assert stats["eligible_junctions_with_signal"] == 0
    assert stats["eligible_junction_coverage_fraction"] == 0.0


def test_validate_signal_references_accepts_generated_signal_references():
    root = _load_root()
    TrafficLightInferer.infer_and_insert(root, allow_heuristic_fallback=True)

    bad_refs = TrafficLightInferer.validate_signal_references(root)
    assert bad_refs == []


def test_validate_signal_references_uses_own_road_active_lane_section():
    """A globally present lane ID cannot mask a local, non-zero-s error."""
    root = ET.Element("OpenDRIVE")

    owner = ET.SubElement(root, "road", id="owner", length="20")
    owner_lanes = ET.SubElement(owner, "lanes")
    first = ET.SubElement(owner_lanes, "laneSection", s="0")
    ET.SubElement(ET.SubElement(first, "right"), "lane", id="-1", type="driving")
    second = ET.SubElement(owner_lanes, "laneSection", s="10")
    ET.SubElement(ET.SubElement(second, "right"), "lane", id="-2", type="driving")
    owner_signals = ET.SubElement(owner, "signals")
    ET.SubElement(owner_signals, "signalReference", id="valid", laneId="-2", s="12")
    ET.SubElement(owner_signals, "signalReference", id="invalid", laneId="-1", s="12")

    other = ET.SubElement(root, "road", id="other", length="20")
    other_lanes = ET.SubElement(other, "lanes")
    other_section = ET.SubElement(other_lanes, "laneSection", s="0")
    ET.SubElement(ET.SubElement(other_section, "right"), "lane", id="-1", type="driving")

    errors = TrafficLightInferer.validate_signal_references(root)

    assert len(errors) == 1
    assert "id=invalid" in errors[0]
    assert "road owner at s=12.0" in errors[0]
