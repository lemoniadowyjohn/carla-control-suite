"""OSM meta-index enrichment feature was silently 100% non-functional on real data.

Verified against the real pinned auto map + OSM source (2026-08-26): XODR road ids
(e.g. "42330", assigned by Osm2Odr/netconvert) and OSM way ids (e.g. "4058127", the
original OSM entity id) are DISJOINT numbering schemes -- 0 of 32,297 real roads
matched any of the 11,885 enrichment-tagged OSM ways by direct id lookup, despite the
module's docstring and the wiring commit both claiming "XODR road id == OSM way id".
The feature ran on every real regen, logged "0 speed limits / 0 turn markings / 0
signs", and nobody noticed because it fails open (no error), not closed.

Fix: match by STREET NAME instead (verified viable: 969/1073, 90.3%, of distinct
enrichment-tagged OSM way names have a matching XODR road name on the real pinned
map). This is a many-to-many correspondence at the street level (one street often
has multiple constituent OSM ways *and* multiple XODR road segments after netconvert
splits at intersections) -- appropriate for a street-level attribute like maxspeed,
but an honest caveat for position-specific tags (turn:lanes, traffic_sign): they may
now be applied to every same-named segment, not just the one segment they truly
describe on OSM. Documented, not hidden.
"""
import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.osm_meta_index import build_osm_meta_index


def _write_osm(tmp_path, ways_xml):
    p = tmp_path / "test.osm"
    p.write_text(f'<osm version="0.6">{ways_xml}</osm>', encoding="utf-8")
    return str(p)


def test_indexes_by_street_name_not_way_id(tmp_path):
    osm = _write_osm(tmp_path, """
        <way id="4058127">
          <tag k="name" v="Bahnhofstrasse"/>
          <tag k="maxspeed" v="50"/>
        </way>
    """)
    idx = build_osm_meta_index(osm)
    assert "4058127" not in idx  # not keyed by way id -- id spaces don't correspond
    assert "Bahnhofstrasse" in idx
    assert idx["Bahnhofstrasse"]["maxspeed"] == "50"


def test_unnamed_way_is_not_indexed():
    # A way with enrichment tags but no name tag cannot be matched by name --
    # correctly excluded rather than silently indexed under an empty-string key.
    import tempfile, os
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "test.osm")
        with open(p, "w", encoding="utf-8") as f:
            f.write('<osm version="0.6"><way id="1"><tag k="maxspeed" v="30"/></way></osm>')
        idx = build_osm_meta_index(p)
    assert idx == {}


def test_multiple_ways_same_street_name_are_merged(tmp_path):
    # A long street split into several OSM ways (common) -- both contribute distinct
    # tags to the same name-keyed entry rather than the later way silently discarding
    # the earlier one's data.
    osm = _write_osm(tmp_path, """
        <way id="1">
          <tag k="name" v="Hauptstrasse"/>
          <tag k="maxspeed" v="50"/>
        </way>
        <way id="2">
          <tag k="name" v="Hauptstrasse"/>
          <tag k="turn:lanes" v="left|through"/>
        </way>
    """)
    idx = build_osm_meta_index(osm)
    assert idx["Hauptstrasse"]["maxspeed"] == "50"
    assert idx["Hauptstrasse"]["turn_lanes"] == "left|through"


def test_real_pinned_data_yields_nonzero_matches():
    # End-to-end sanity check against the real pinned map + OSM source: must not
    # regress to the old 0.0000% match rate.
    CAND = ("campaigns/ingolstadt_cooked_perception_v1/candidate/"
            "ingolstadt_perception_map_of_record_20260819_160350.xodr")
    OSM = "campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm"
    idx = build_osm_meta_index(OSM)
    root = ET.parse(CAND).getroot()
    road_names = {r.get("name", "").strip() for r in root.findall("road") if r.get("name", "").strip()}
    matched = road_names & set(idx.keys())
    assert len(matched) > 500, f"expected substantial name-based match coverage, got {len(matched)}"
