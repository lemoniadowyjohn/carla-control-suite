"""Unit tests for ultimate_pipeline.enrichment.overpass_to_osm_xml.

Closes the gap documented in
reports/production_readiness/20260915T101124Z_FBX_REGEN_CURRENT_PIN/README.md:
OSM2World only reads OSM XML/PBF, but the pinned building source
(ingolstadt_buildings_overpass.json et al) is Overpass JSON. These tests
check structural correctness (node/way counts, tag preservation, id-space
safety) and that the output is XML OSM2World's own OSM-XML reader logic can
actually parse (well-formed <osm><node/><way><nd/><tag/></way></osm>, exactly
the shape ultimate_pipeline.enrichment.osm_polygon_loader.OSMPolygonLoader
already parses for the same purpose elsewhere in this codebase) -- not just
"the function returns without raising".
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.enrichment.overpass_to_osm_xml import (
    convert_overpass_json_to_osm_xml,
    merge_osm_xml_files,
)
from ultimate_pipeline.enrichment.osm_polygon_loader import OSMPolygonLoader


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _square_geometry(lat0: float, lon0: float, size: float = 0.0005):
    """A small closed 4-corner square ring (Overpass repeats the first point last)."""
    return [
        {"lat": lat0, "lon": lon0},
        {"lat": lat0, "lon": lon0 + size},
        {"lat": lat0 + size, "lon": lon0 + size},
        {"lat": lat0 + size, "lon": lon0},
        {"lat": lat0, "lon": lon0},
    ]


@pytest.fixture()
def sample_overpass_json(tmp_path) -> Path:
    data = {
        "version": 0.6,
        "generator": "Overpass API test fixture",
        "elements": [
            {
                "type": "way",
                "id": 111,
                "tags": {"building": "yes", "height": "12", "name": "Building A"},
                "nodes": [1, 2, 3, 4, 1],
                "geometry": _square_geometry(48.75, 11.42),
            },
            {
                "type": "way",
                "id": 222,
                "tags": {"building": "residential", "building:levels": "3"},
                "nodes": [5, 6, 7, 8, 5],
                "geometry": _square_geometry(48.76, 11.43),
            },
            {
                # A way with no building tag but present in the export (Overpass
                # multipolygon fetches can include tagless outline ways) -- still
                # converted (this module preserves everything it's given; the
                # caller/OSM2World config decides what to render).
                "type": "way",
                "id": 333,
                "tags": {},
                "nodes": [9, 10, 11, 9],
                "geometry": [
                    {"lat": 48.77, "lon": 11.44},
                    {"lat": 48.77, "lon": 11.441},
                    {"lat": 48.771, "lon": 11.4405},
                    {"lat": 48.77, "lon": 11.44},
                ],
            },
            {
                "type": "relation",
                "id": 999,
                "tags": {"type": "multipolygon", "building": "apartments", "name": "Courtyard Block"},
                "members": [
                    {
                        "type": "way",
                        "ref": 444,
                        "role": "outer",
                        "geometry": _square_geometry(48.78, 11.45, size=0.001),
                    },
                    {
                        "type": "way",
                        "ref": 555,
                        "role": "inner",
                        "geometry": _square_geometry(48.7805, 11.4505, size=0.0002),
                    },
                ],
            },
            {
                # Degenerate: fewer than 3 points -- must be skipped, not crash.
                "type": "way",
                "id": 666,
                "tags": {"building": "shed"},
                "nodes": [12, 13],
                "geometry": [{"lat": 48.79, "lon": 11.46}, {"lat": 48.79, "lon": 11.461}],
            },
        ],
    }
    path = tmp_path / "buildings_overpass.json"
    _write_json(path, data)
    return path


def test_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        convert_overpass_json_to_osm_xml(str(tmp_path / "nope.json"), str(tmp_path / "out.osm"))


def test_non_overpass_json_raises_value_error(tmp_path):
    bad = tmp_path / "not_overpass.json"
    _write_json(bad, {"type": "FeatureCollection", "features": []})
    with pytest.raises(ValueError, match="elements"):
        convert_overpass_json_to_osm_xml(str(bad), str(tmp_path / "out.osm"))


def test_convert_produces_well_formed_osm_xml(tmp_path, sample_overpass_json):
    out_path = tmp_path / "buildings.osm"
    stats = convert_overpass_json_to_osm_xml(str(sample_overpass_json), str(out_path))

    assert out_path.exists()
    # Must parse as well-formed XML (ElementTree raises ParseError otherwise).
    tree = ET.parse(out_path)
    root = tree.getroot()
    assert root.tag == "osm"
    assert root.get("version") == "0.6"


def test_way_and_relation_counts(tmp_path, sample_overpass_json):
    out_path = tmp_path / "buildings.osm"
    stats = convert_overpass_json_to_osm_xml(str(sample_overpass_json), str(out_path))

    # 4 plain ways (111, 222, 333, 666) but 666 is degenerate (2 points) -> skipped.
    # Relation 999 contributes 1 outer way (444); inner (555) is not emitted as a way.
    assert stats["ways_in"] == 4
    assert stats["relations_in"] == 1
    assert stats["skipped_degenerate"] == 1
    assert stats["ways_written"] == 4  # 111, 222, 333 + relation's outer(444)
    assert stats["relations_written"] == 0  # emit_relations defaults to False

    tree = ET.parse(out_path)
    root = tree.getroot()
    ways = root.findall("way")
    assert len(ways) == stats["ways_written"] == 4


def test_tags_are_preserved_on_converted_ways(tmp_path, sample_overpass_json):
    out_path = tmp_path / "buildings.osm"
    convert_overpass_json_to_osm_xml(str(sample_overpass_json), str(out_path))

    root = ET.parse(out_path).getroot()
    ways = root.findall("way")

    tag_sets = []
    for way in ways:
        tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
        tag_sets.append(tags)

    # Way 111's tags (building=yes, height=12, name=Building A) must appear verbatim.
    assert {"building": "yes", "height": "12", "name": "Building A"} in tag_sets
    # Way 222's tags.
    assert {"building": "residential", "building:levels": "3"} in tag_sets
    # The relation's outer way must carry the RELATION's tags (building=apartments),
    # not the (tagless) member way's own tags -- matches OSMPolygonLoader's C28 convention.
    assert any(
        t.get("building") == "apartments" and t.get("name") == "Courtyard Block"
        for t in tag_sets
    )


def test_node_ids_are_negative_synthetic_and_unique(tmp_path, sample_overpass_json):
    out_path = tmp_path / "buildings.osm"
    convert_overpass_json_to_osm_xml(str(sample_overpass_json), str(out_path))

    root = ET.parse(out_path).getroot()
    node_ids = [int(n.get("id")) for n in root.findall("node")]
    way_ids = [int(w.get("id")) for w in root.findall("way")]

    assert node_ids, "expected at least one node"
    assert all(nid < 0 for nid in node_ids), "node ids must be synthetic negative ids"
    assert len(node_ids) == len(set(node_ids)), "node ids must be unique"
    assert all(wid < 0 for wid in way_ids), "way ids must be synthetic negative ids"
    assert len(way_ids) == len(set(way_ids)), "way ids must be unique"
    # Node and way id spaces must not collide with each other.
    assert set(node_ids).isdisjoint(set(way_ids))


def test_coincident_corners_are_deduplicated_to_one_node(tmp_path):
    """Two ways sharing an exact corner coordinate should share one <node>,
    not two coincident nodes -- this is what prevents the duplicate-point
    polygon failure mode documented in the FBX regen README."""
    shared_lat, shared_lon = 48.80, 11.47
    data = {
        "elements": [
            {
                "type": "way",
                "id": 1,
                "tags": {"building": "yes"},
                "geometry": [
                    {"lat": shared_lat, "lon": shared_lon},
                    {"lat": shared_lat, "lon": shared_lon + 0.0005},
                    {"lat": shared_lat + 0.0005, "lon": shared_lon + 0.0005},
                    {"lat": shared_lat, "lon": shared_lon},
                ],
            },
            {
                "type": "way",
                "id": 2,
                "tags": {"building": "yes"},
                "geometry": [
                    {"lat": shared_lat, "lon": shared_lon},  # same corner as way 1
                    {"lat": shared_lat - 0.0005, "lon": shared_lon},
                    {"lat": shared_lat - 0.0005, "lon": shared_lon - 0.0005},
                    {"lat": shared_lat, "lon": shared_lon},
                ],
            },
        ]
    }
    src = tmp_path / "shared.json"
    _write_json(src, data)
    out_path = tmp_path / "out.osm"
    stats = convert_overpass_json_to_osm_xml(str(src), str(out_path))

    # Way 1: 3 distinct corners (4-point ring with closing repeat collapsed).
    # Way 2: 3 distinct corners, one of which (the shared corner) is reused
    # from way 1's pool instead of creating a new node. Total unique nodes:
    # 3 + (3 - 1 shared) = 5, not 3 + 3 = 6.
    assert stats["nodes_written"] == 5

    root = ET.parse(out_path).getroot()
    ways = root.findall("way")
    refs_by_way = [[nd.get("ref") for nd in w.findall("nd")] for w in ways]
    # The shared corner's node id must appear in BOTH ways' nd ref lists.
    common_refs = set(refs_by_way[0]) & set(refs_by_way[1])
    assert len(common_refs) == 1


def test_rings_are_closed(tmp_path, sample_overpass_json):
    out_path = tmp_path / "buildings.osm"
    convert_overpass_json_to_osm_xml(str(sample_overpass_json), str(out_path))

    root = ET.parse(out_path).getroot()
    for way in root.findall("way"):
        refs = [nd.get("ref") for nd in way.findall("nd")]
        assert len(refs) >= 4, "a closed polygon way needs >= 3 distinct + 1 repeat"
        assert refs[0] == refs[-1], f"way {way.get('id')} ring is not closed"


def test_all_way_node_refs_resolve_to_declared_nodes(tmp_path, sample_overpass_json):
    """OSM2World (and any strict OSM XML parser) will reject a way whose <nd
    ref=...> points at a node id that was never declared."""
    out_path = tmp_path / "buildings.osm"
    convert_overpass_json_to_osm_xml(str(sample_overpass_json), str(out_path))

    root = ET.parse(out_path).getroot()
    declared_node_ids = {n.get("id") for n in root.findall("node")}
    for way in root.findall("way"):
        for nd in way.findall("nd"):
            assert nd.get("ref") in declared_node_ids


def test_output_is_parseable_by_osm_polygon_loader(tmp_path, sample_overpass_json):
    """End-to-end structural check: feed the converted .osm back through this
    codebase's existing OSM-XML building reader and confirm it recovers
    building footprints with the same tags -- i.e. the converter's output is
    not just well-formed XML, but semantically a valid OSM buildings file by
    this codebase's own established reader."""
    out_path = tmp_path / "buildings.osm"
    convert_overpass_json_to_osm_xml(str(sample_overpass_json), str(out_path))

    footprints = OSMPolygonLoader.load_buildings_from_osm(str(out_path), min_area=0.0)
    # Way 333 has no building tag -> excluded by the loader (it requires
    # "building" in tags). Way 666 was degenerate -> never written. So we
    # expect footprints for way 111, way 222, and the relation's outer way.
    assert len(footprints) == 3
    names = {fp.name for fp in footprints if fp.name}
    assert "Building A" in names


def test_emit_relations_flag_adds_relation_elements(tmp_path, sample_overpass_json):
    out_path = tmp_path / "buildings.osm"
    stats = convert_overpass_json_to_osm_xml(
        str(sample_overpass_json), str(out_path), emit_relations=True
    )
    assert stats["relations_written"] == 1

    root = ET.parse(out_path).getroot()
    relations = root.findall("relation")
    assert len(relations) == 1
    members = relations[0].findall("member")
    assert len(members) == 1
    assert members[0].get("type") == "way"
    assert members[0].get("role") == "outer"
    rel_tags = {t.get("k"): t.get("v") for t in relations[0].findall("tag")}
    assert rel_tags.get("building") == "apartments"


def test_degenerate_only_input_raises_value_error(tmp_path):
    data = {
        "elements": [
            {"type": "way", "id": 1, "tags": {"building": "yes"}, "geometry": [{"lat": 1, "lon": 1}]},
        ]
    }
    src = tmp_path / "degenerate.json"
    _write_json(src, data)
    with pytest.raises(ValueError, match="0 usable ways"):
        convert_overpass_json_to_osm_xml(str(src), str(tmp_path / "out.osm"))


def test_null_geometry_points_are_skipped_not_fatal(tmp_path):
    data = {
        "elements": [
            {
                "type": "way",
                "id": 1,
                "tags": {"building": "yes"},
                "geometry": [
                    {"lat": 48.5, "lon": 11.5},
                    None,
                    {"lat": 48.501, "lon": 11.5},
                    {"lat": 48.501, "lon": 11.501},
                ],
            }
        ]
    }
    src = tmp_path / "nullpt.json"
    _write_json(src, data)
    out_path = tmp_path / "out.osm"
    stats = convert_overpass_json_to_osm_xml(str(src), str(out_path))
    assert stats["ways_written"] == 1


# ---------------------------------------------------------------------------
# merge_osm_xml_files
# ---------------------------------------------------------------------------


def _write_roads_osm(path: Path) -> None:
    root = ET.Element("osm", {"version": "0.6", "generator": "test"})
    ET.SubElement(root, "node", {"id": "100", "lat": "48.70", "lon": "11.40"})
    ET.SubElement(root, "node", {"id": "101", "lat": "48.701", "lon": "11.40"})
    way = ET.SubElement(root, "way", {"id": "200"})
    ET.SubElement(way, "nd", {"ref": "100"})
    ET.SubElement(way, "nd", {"ref": "101"})
    ET.SubElement(way, "tag", {"k": "highway", "v": "residential"})
    ET.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)


def test_merge_combines_roads_and_buildings_without_id_collision(tmp_path, sample_overpass_json):
    buildings_osm = tmp_path / "buildings.osm"
    convert_overpass_json_to_osm_xml(str(sample_overpass_json), str(buildings_osm))

    roads_osm = tmp_path / "roads.osm"
    _write_roads_osm(roads_osm)

    merged_path = tmp_path / "merged.osm"
    stats = merge_osm_xml_files(str(roads_osm), str(buildings_osm), str(merged_path))

    assert stats["primary_ways"] == 1
    assert stats["secondary_ways"] == 4
    # Roads use small positive ids (100/101/200); buildings use negative
    # synthetic ids -- no collision, so nothing should need renumbering.
    assert stats["renumbered"] == 0

    root = ET.parse(merged_path).getroot()
    all_way_ids = [w.get("id") for w in root.findall("way")]
    assert len(all_way_ids) == len(set(all_way_ids)), "merged way ids must be unique"
    all_node_ids = [n.get("id") for n in root.findall("node")]
    assert len(all_node_ids) == len(set(all_node_ids)), "merged node ids must be unique"

    # Original roads way + tag must still be present, untouched.
    highway_ways = [
        w for w in root.findall("way")
        if any(t.get("k") == "highway" for t in w.findall("tag"))
    ]
    assert len(highway_ways) == 1
    assert highway_ways[0].get("id") == "200"

    # All nd refs (roads + buildings) must resolve inside the merged doc.
    declared = {n.get("id") for n in root.findall("node")}
    for way in root.findall("way"):
        for nd in way.findall("nd"):
            assert nd.get("ref") in declared


def test_merge_renumbers_on_genuine_id_collision(tmp_path):
    # Two files that DO collide on ids (e.g. two independently-synthesized
    # converter outputs, both starting node ids at -1).
    primary = tmp_path / "a.osm"
    secondary = tmp_path / "b.osm"

    root_a = ET.Element("osm", {"version": "0.6"})
    ET.SubElement(root_a, "node", {"id": "-1", "lat": "1.0", "lon": "1.0"})
    way_a = ET.SubElement(root_a, "way", {"id": "-1"})
    ET.SubElement(way_a, "nd", {"ref": "-1"})
    ET.ElementTree(root_a).write(primary, encoding="UTF-8", xml_declaration=True)

    root_b = ET.Element("osm", {"version": "0.6"})
    ET.SubElement(root_b, "node", {"id": "-1", "lat": "2.0", "lon": "2.0"})
    way_b = ET.SubElement(root_b, "way", {"id": "-1"})
    ET.SubElement(way_b, "nd", {"ref": "-1"})
    ET.SubElement(way_b, "tag", {"k": "building", "v": "yes"})
    ET.ElementTree(root_b).write(secondary, encoding="UTF-8", xml_declaration=True)

    merged_path = tmp_path / "merged.osm"
    stats = merge_osm_xml_files(str(primary), str(secondary), str(merged_path))

    assert stats["renumbered"] == 2  # secondary's node -1 and way -1 both collide

    root = ET.parse(merged_path).getroot()
    node_ids = [n.get("id") for n in root.findall("node")]
    way_ids = [w.get("id") for w in root.findall("way")]
    assert len(node_ids) == len(set(node_ids)) == 2
    assert len(way_ids) == len(set(way_ids)) == 2

    # The renumbered building way's nd ref must point at the renumbered node,
    # not the (now primary-owned) original id.
    building_way = next(w for w in root.findall("way") if any(t.get("k") == "building" for t in w.findall("tag")))
    refs = [nd.get("ref") for nd in building_way.findall("nd")]
    assert refs[0] in node_ids
    assert refs[0] != "-1"  # must have been remapped away from the colliding id


def test_merge_output_still_loadable_by_osm_polygon_loader(tmp_path, sample_overpass_json):
    buildings_osm = tmp_path / "buildings.osm"
    convert_overpass_json_to_osm_xml(str(sample_overpass_json), str(buildings_osm))
    roads_osm = tmp_path / "roads.osm"
    _write_roads_osm(roads_osm)
    merged_path = tmp_path / "merged.osm"
    merge_osm_xml_files(str(roads_osm), str(buildings_osm), str(merged_path))

    footprints = OSMPolygonLoader.load_buildings_from_osm(str(merged_path), min_area=0.0)
    assert len(footprints) == 3  # same buildings survive the merge
