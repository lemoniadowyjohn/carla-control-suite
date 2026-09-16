"""Malformed lat/lon on an OSM <node> element must not crash the whole parse.

``load_buildings_from_osm`` previously did ``float(n.get("lat", "0"))`` with no error
handling -- a single malformed node (a real-world hazard in hand-edited or third-party
OSM exports) raised ValueError and aborted parsing every building in the file, not just
the one referencing that node.
"""
from __future__ import annotations

from pathlib import Path

from ultimate_pipeline.enrichment.osm_polygon_loader import OSMPolygonLoader


def _write_osm(path: Path, *, malformed_node_id: str | None = None) -> None:
    # A simple 4-node square building way, plus one extra valid building elsewhere.
    nodes = {
        "1": ("48.7500", "11.4200"),
        "2": ("48.7501", "11.4200"),
        "3": ("48.7501", "11.4201"),
        "4": ("48.7500", "11.4201"),
        "10": ("48.7600", "11.4300"),
        "11": ("48.7601", "11.4300"),
        "12": ("48.7601", "11.4301"),
        "13": ("48.7600", "11.4301"),
    }
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<osm>"]
    for nid, (lat, lon) in nodes.items():
        if nid == malformed_node_id:
            lines.append(f'  <node id="{nid}" lat="not-a-number" lon="{lon}"/>')
        else:
            lines.append(f'  <node id="{nid}" lat="{lat}" lon="{lon}"/>')
    lines.append(
        '  <way id="100"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/>'
        '<tag k="building" v="yes"/></way>'
    )
    lines.append(
        '  <way id="101"><nd ref="10"/><nd ref="11"/><nd ref="12"/><nd ref="13"/><nd ref="10"/>'
        '<tag k="building" v="yes"/></way>'
    )
    lines.append("</osm>")
    path.write_text("\n".join(lines), encoding="utf-8")


def test_malformed_node_lat_does_not_crash_parse(tmp_path: Path) -> None:
    osm = tmp_path / "malformed.osm"
    _write_osm(osm, malformed_node_id="1")

    # Building 100 loses one of its 4 corners (node 1) but still has 3 -> should still
    # produce a footprint (a triangle); building 101 is fully unaffected.
    buildings = OSMPolygonLoader.load_buildings_from_osm(str(osm))

    assert len(buildings) == 2


def test_all_nodes_malformed_returns_empty_list(tmp_path: Path) -> None:
    osm = tmp_path / "all_malformed.osm"
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<osm>",
        '  <node id="1" lat="garbage" lon="garbage"/>',
        '  <node id="2" lat="garbage" lon="garbage"/>',
        '  <node id="3" lat="garbage" lon="garbage"/>',
        '  <way id="100"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="1"/>'
        '<tag k="building" v="yes"/></way>',
        "</osm>",
    ]
    osm.write_text("\n".join(lines), encoding="utf-8")

    buildings = OSMPolygonLoader.load_buildings_from_osm(str(osm))

    assert buildings == []


def test_valid_osm_still_parses_correctly(tmp_path: Path) -> None:
    osm = tmp_path / "valid.osm"
    _write_osm(osm, malformed_node_id=None)

    buildings = OSMPolygonLoader.load_buildings_from_osm(str(osm))

    assert len(buildings) == 2
