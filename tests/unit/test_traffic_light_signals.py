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


def test_infer_and_insert_emits_object_and_paired_signal():
    root = _load_root()

    count = TrafficLightInferer.infer_and_insert(root)

    assert count == 3
    objects = root.findall(".//object[@type='traffic_light']")
    assert len(objects) == 3

    signals = root.findall(".//signal")
    assert len(signals) == 3, "each traffic_light object must have a paired <signal>"


def test_traffic_light_signals_are_functional_not_props():
    root = _load_root()
    TrafficLightInferer.infer_and_insert(root)

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
    TrafficLightInferer.infer_and_insert(root)

    controllers = root.findall(".//controller")
    assert controllers, "expected at least one <controller> grouping the junction's signals"

    all_signal_ids = {s.get("id") for s in root.findall(".//signal")}
    controlled_ids = set()
    for c in controllers:
        for ctrl in c.findall("control"):
            controlled_ids.add(ctrl.get("signalId"))

    assert controlled_ids, "controller must reference signal ids via <control>"
    assert controlled_ids.issubset(all_signal_ids)


def test_infer_and_insert_is_idempotent_for_signals():
    root = _load_root()
    TrafficLightInferer.infer_and_insert(root)
    first_signal_count = len(root.findall(".//signal"))

    # Re-running against a junction whose roads already carry signals must
    # not silently duplicate them (mirrors the existing <object> id reuse
    # pattern -- object ids are deterministic "tl_<junction>_<idx>").
    TrafficLightInferer.infer_and_insert(root)
    second_signal_count = len(root.findall(".//signal"))

    assert second_signal_count == first_signal_count


def test_validate_signal_references_accepts_generated_signal_references():
    root = _load_root()
    TrafficLightInferer.infer_and_insert(root)

    bad_refs = TrafficLightInferer.validate_signal_references(root)
    assert bad_refs == []
