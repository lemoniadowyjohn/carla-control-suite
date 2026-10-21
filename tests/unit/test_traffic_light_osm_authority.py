"""P0 signal authority: traffic lights derive from OSM source evidence.

OSM traffic-signal / signalled-crossing nodes are projected into the map's
LOCAL frame (bare-tmerc native minus the header <offset> rebase), matched to
the nearest signalised-junction incoming road within a bounded radius, and
inserted as grounded <signal>+<controller> pairs with inline provenance
``osm_traffic_signals:node/<id>`` and ``confidence="grounded"``.
"""

import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.enrichment.traffic_light_infer import (
    OSM_SIGNAL_MATCH_RADIUS_M,
    TrafficLightInferer,
    load_osm_signal_nodes,
    osm_signal_nodes_to_local,
)
from ultimate_pipeline.enrichment.osm_polygon_loader import TRANSFORMER

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


def _write_osm(tmp_path, nodes):
    body = ['<?xml version="1.0" encoding="utf-8"?>', "<osm>"]
    for node_id, lat, lon, *tags in nodes:
        tag_xml = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags)
        body.append(
            f'<node id="{node_id}" lat="{lat}" lon="{lon}">{tag_xml}</node>'
        )
    body.append("</osm>")
    path = tmp_path / "signals.osm"
    path.write_text("\n".join(body))
    return str(path)


def _xodr_root(offset):
    root = ET.fromstring(_JUNCTION_XODR)
    hdr = root.find("header")
    ET.SubElement(
        hdr, "offset", x=f"{offset[0]:.6f}", y=f"{offset[1]:.6f}",
        z="0.0", hdg="0.0",
    )
    return root


class _OsPath:
    pass  # unused sentinel


def test_load_osm_signal_nodes_harvests_both_authority_tags(tmp_path):
    osm = _write_osm(tmp_path, [
        ("100", 48.7, 11.4, ("highway", "traffic_signals")),
        ("200", 48.71, 11.41, ("crossing", "traffic_signals")),
        ("300", 48.72, 11.42, ("highway", "street_lamp")),      # not a signal
        ("400", 48.73, 11.43, ("crossing", "zebra")),           # not a signal
    ])
    nodes = load_osm_signal_nodes(osm)
    ids = {n["node_id"] for n in nodes}
    assert ids == {"100", "200"}
    by_id = {n["node_id"]: n for n in nodes}
    assert by_id["100"]["source_tag"] == "highway=traffic_signals"
    assert by_id["200"]["source_tag"] == "crossing=traffic_signals"


def test_osm_nodes_projected_into_local_frame(tmp_path):
    # node 1 m east of road 3's end (20, 0) in LOCAL space:
    lon, lat = 11.4, 48.7
    nx, ny = TRANSFORMER.transform(lon, lat)
    # offset chosen so local position == (21, 0)
    root = _xodr_root((nx - 21.0, ny - 0.0))

    osm = _write_osm(tmp_path, [
        ("100", lat, lon, ("highway", "traffic_signals")),
    ])
    nodes, stats = osm_signal_nodes_to_local(root, osm)
    assert stats["requested"] == 1
    assert nodes[0]["x"] == pytest.approx(21.0, abs=1e-6)
    assert nodes[0]["y"] == pytest.approx(0.0, abs=1e-6)


def test_infer_and_insert_osm_first_grounded(tmp_path):
    lon, lat = 11.4, 48.7
    nx, ny = TRANSFORMER.transform(lon, lat)
    root = _xodr_root((nx - 21.0, ny - 0.0))
    osm = _write_osm(tmp_path, [
        ("100", lat, lon, ("highway", "traffic_signals")),
    ])

    import os as _os
    saved = _os.environ.pop("UP_ENABLE_TL_HEURISTIC_FALLBACK", None)
    try:
        count = TrafficLightInferer.infer_and_insert(root, osm_source_path=osm)
    finally:
        if saved is not None:
            _os.environ["UP_ENABLE_TL_HEURISTIC_FALLBACK"] = saved

    assert count == 1
    stats = TrafficLightInferer.last_run_stats
    assert stats["osm_mapped"] == 1
    assert stats["osm_inserted"] == 1
    assert stats["heuristic_inserted"] == 0  # fallback disabled

    signals = root.findall(".//signal")
    assert len(signals) == 1
    sig = signals[0]
    assert sig.get("type") == "1000001"
    prov = sig.find("./userData/provenance")
    assert prov is not None
    assert prov.get("source_entity") == "osm_traffic_signals:node/100"
    assert prov.get("confidence") == "grounded"

    controllers = [c for c in root.findall(".//controller") if c.get("id")]
    assert controllers, "OSM signals must be grouped under a controller"
    controlled = {c.get("signalId") for c in controllers[0].findall("control")}
    assert controlled == {sig.get("id")}


def test_unmatched_osm_node_is_counted_not_dropped(tmp_path):
    lon, lat = 11.4, 48.7
    nx, ny = TRANSFORMER.transform(lon, lat)
    root = _xodr_root((nx - 21.0, ny - 0.0))
    # second node 100 m north: beyond OSM_SIGNAL_MATCH_RADIUS_M of any road end
    lat_far = lat + 0.001  # ~111 m at this latitude
    osm = _write_osm(tmp_path, [
        ("100", lat, lon, ("highway", "traffic_signals")),
        ("900", lat_far, lon, ("highway", "traffic_signals")),
    ])

    count = TrafficLightInferer.infer_and_insert(root, osm_source_path=osm)
    stats = TrafficLightInferer.last_run_stats
    assert count == 1
    assert stats["osm_requested"] == 2
    assert stats["osm_mapped"] == 1
    assert stats["osm_unmatched"] == 1
    assert OSM_SIGNAL_MATCH_RADIUS_M == 25.0  # pinned, documented radius


def test_fallback_never_overwrites_osm_mapped_junction(tmp_path):
    lon, lat = 11.4, 48.7
    nx, ny = TRANSFORMER.transform(lon, lat)
    root = _xodr_root((nx - 21.0, ny - 0.0))
    osm = _write_osm(tmp_path, [
        ("100", lat, lon, ("highway", "traffic_signals")),
    ])

    count = TrafficLightInferer.infer_and_insert(
        root, osm_source_path=osm, allow_heuristic_fallback=True
    )
    stats = TrafficLightInferer.last_run_stats
    assert count == 1
    assert stats["osm_mapped"] == 1
    # junction 10 already has grounded OSM authority: heuristic must skip it
    assert stats["heuristic_inserted"] == 0
    for sig in root.findall(".//signal"):
        prov = sig.find("./userData/provenance")
        assert prov.get("confidence") == "grounded"


def test_junction_coverage_stats_osm_authority(tmp_path):
    lon, lat = 11.4, 48.7
    nx, ny = TRANSFORMER.transform(lon, lat)
    root = _xodr_root((nx - 21.0, ny - 0.0))
    osm = _write_osm(tmp_path, [
        ("100", lat, lon, ("highway", "traffic_signals")),
    ])
    TrafficLightInferer.infer_and_insert(root, osm_source_path=osm)

    stats = TrafficLightInferer.junction_coverage_stats(root)
    assert stats["eligible_junctions"] == 1
    assert stats["eligible_junctions_with_osm_signal"] == 1
    assert stats["eligible_junctions_with_heuristic_signal"] == 0
    assert stats["eligible_junctions_with_signal"] == 1
    assert "OSM-sourced, grounded" in stats["provenance"]


def test_no_signal_nodes_in_source_inserts_nothing(tmp_path):
    lon, lat = 11.4, 48.7
    nx, ny = TRANSFORMER.transform(lon, lat)
    root = _xodr_root((nx - 21.0, ny - 0.0))
    osm = _write_osm(tmp_path, [("500", lat, lon, ("highway", "street_lamp"))])

    count = TrafficLightInferer.infer_and_insert(root, osm_source_path=osm)
    assert count == 0
    assert root.findall(".//signal") == []
    stats = TrafficLightInferer.last_run_stats
    assert stats["osm_requested"] == 0
