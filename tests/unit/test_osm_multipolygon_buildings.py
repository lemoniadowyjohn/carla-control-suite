"""C25: osm_polygon_loader must consume OSM `<relation type=multipolygon>` buildings.

Previously the loader only iterated `<way building=...>`, silently skipping multipolygon
relation buildings (the C7 report estimated ~19 unconsumed on the Ingolstadt OSM). Member
ways of a relation carry the `building` tag on the RELATION, not the ways, so they were
never assembled. BuildingFootprint has no hole support, so the OUTER ring is emitted
(inner/holes documented as a minor over-fill).
"""
import textwrap

from ultimate_pipeline.enrichment.osm_polygon_loader import OSMPolygonLoader

# a ~22x22 m outer ring (way 101) with an inner courtyard (way 102), tied by relation 201;
# plus a standalone way building (way 301) to prove the way path still works.
_OSM = textwrap.dedent("""\
<osm version="0.6">
  <node id="1" lat="48.7500" lon="11.4220"/>
  <node id="2" lat="48.7500" lon="11.4223"/>
  <node id="3" lat="48.7502" lon="11.4223"/>
  <node id="4" lat="48.7502" lon="11.4220"/>
  <node id="5" lat="48.75008" lon="11.42208"/>
  <node id="6" lat="48.75008" lon="11.42212"/>
  <node id="7" lat="48.75012" lon="11.42212"/>
  <node id="8" lat="48.75012" lon="11.42208"/>
  <node id="11" lat="48.7510" lon="11.4230"/>
  <node id="12" lat="48.7510" lon="11.4233"/>
  <node id="13" lat="48.7512" lon="11.4233"/>
  <node id="14" lat="48.7512" lon="11.4230"/>
  <way id="101">
    <nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/>
  </way>
  <way id="102">
    <nd ref="5"/><nd ref="6"/><nd ref="7"/><nd ref="8"/><nd ref="5"/>
  </way>
  <way id="301">
    <nd ref="11"/><nd ref="12"/><nd ref="13"/><nd ref="14"/><nd ref="11"/>
    <tag k="building" v="yes"/>
    <tag k="name" v="Standalone Way Building"/>
  </way>
  <relation id="201">
    <member type="way" ref="101" role="outer"/>
    <member type="way" ref="102" role="inner"/>
    <tag k="type" v="multipolygon"/>
    <tag k="building" v="yes"/>
    <tag k="name" v="Courtyard Building"/>
  </relation>
</osm>
""")


def _load(tmp_path):
    p = tmp_path / "mp.osm"
    p.write_text(_OSM, encoding="utf-8")
    return OSMPolygonLoader.load_buildings_from_osm(str(p))


def test_multipolygon_relation_building_is_loaded(tmp_path):
    blds = _load(tmp_path)
    names = {b.name for b in blds}
    assert "Courtyard Building" in names, f"multipolygon building missing; got {names}"


def test_way_building_still_loads(tmp_path):
    blds = _load(tmp_path)
    names = {b.name for b in blds}
    assert "Standalone Way Building" in names  # backward compat


def test_multipolygon_building_uses_outer_ring_and_relation_tags(tmp_path):
    blds = _load(tmp_path)
    mp = next(b for b in blds if b.name == "Courtyard Building")
    # outer ring is a closed quad (5 pts incl. closing point)
    assert len(mp.footprint) >= 4
    assert mp.footprint[0] == mp.footprint[-1]


def test_degenerate_relation_does_not_crash(tmp_path):
    osm = _OSM.replace('<member type="way" ref="101" role="outer"/>',
                       '<member type="way" ref="999" role="outer"/>')  # missing member way
    p = tmp_path / "bad.osm"
    p.write_text(osm, encoding="utf-8")
    blds = OSMPolygonLoader.load_buildings_from_osm(str(p))  # must not raise
    # the standalone way building still loads
    assert any(b.name == "Standalone Way Building" for b in blds)
