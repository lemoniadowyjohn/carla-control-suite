"""C28: load_buildings_from_geojson must consume Overpass 'elements' multipolygon
RELATIONS — the LIVE production path (main_pipeline.py wires this loader, not the
.osm/load_buildings_from_osm path fixed in C25). The pinned
campaigns/.../ingolstadt_buildings_overpass.json has 19 relation elements tagged
building=* (confirmed real, e.g. "Reduit Tilly"), all currently silently dropped —
the elements-loop only handles elem.get("type") == "way".

Overpass 'out geom' relations embed each member's full point list directly
(no node-ref table to stitch), so this is simpler than the C25 OSM-XML case:
member["geometry"] is already an ordered list of {"lat","lon"} for that member way.
"""
import json

from ultimate_pipeline.enrichment.osm_polygon_loader import OSMPolygonLoader

_OVERPASS_JSON = {
    "elements": [
        {
            "type": "way", "id": 301,
            "tags": {"building": "yes", "name": "Standalone Way Building"},
            "geometry": [
                {"lat": 48.7510, "lon": 11.4230}, {"lat": 48.7510, "lon": 11.4233},
                {"lat": 48.7512, "lon": 11.4233}, {"lat": 48.7512, "lon": 11.4230},
                {"lat": 48.7510, "lon": 11.4230},
            ],
        },
        {
            "type": "relation", "id": 201,
            "tags": {"type": "multipolygon", "building": "yes", "name": "Courtyard Building"},
            "members": [
                {"type": "way", "ref": 101, "role": "outer", "geometry": [
                    {"lat": 48.7500, "lon": 11.4220}, {"lat": 48.7500, "lon": 11.4223},
                    {"lat": 48.7502, "lon": 11.4223}, {"lat": 48.7502, "lon": 11.4220},
                    {"lat": 48.7500, "lon": 11.4220},
                ]},
                {"type": "way", "ref": 102, "role": "inner", "geometry": [
                    {"lat": 48.75008, "lon": 11.42208}, {"lat": 48.75008, "lon": 11.42212},
                    {"lat": 48.75012, "lon": 11.42212}, {"lat": 48.75012, "lon": 11.42208},
                    {"lat": 48.75008, "lon": 11.42208},
                ]},
            ],
        },
    ]
}


def _load(tmp_path, data=None):
    p = tmp_path / "buildings.json"
    p.write_text(json.dumps(data if data is not None else _OVERPASS_JSON), encoding="utf-8")
    return OSMPolygonLoader.load_buildings_from_geojson(str(p))


def test_multipolygon_relation_building_is_loaded(tmp_path):
    blds = _load(tmp_path)
    names = {b.name for b in blds}
    assert "Courtyard Building" in names, f"multipolygon relation building missing; got {names}"


def test_way_building_still_loads(tmp_path):
    blds = _load(tmp_path)
    names = {b.name for b in blds}
    assert "Standalone Way Building" in names  # backward compat, unchanged path


def test_multipolygon_building_uses_outer_ring(tmp_path):
    blds = _load(tmp_path)
    mp = next(b for b in blds if b.name == "Courtyard Building")
    assert len(mp.footprint) >= 4
    assert mp.footprint[0] == mp.footprint[-1]


def test_relation_missing_outer_geometry_does_not_crash(tmp_path):
    data = json.loads(json.dumps(_OVERPASS_JSON))
    del data["elements"][1]["members"][0]["geometry"]  # corrupt the outer member
    blds = _load(tmp_path, data)  # must not raise
    assert any(b.name == "Standalone Way Building" for b in blds)


def test_real_pinned_overpass_json_yields_19_relation_buildings():
    real = "campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_buildings_overpass.json"
    blds = OSMPolygonLoader.load_buildings_from_geojson(real)
    rel_ids = {b.id for b in blds if (b.id or "").startswith("osm_bld_rel_")}
    assert len(rel_ids) >= 15  # allow a few to be dropped by min_area/degeneracy, not silently all 19
