from __future__ import annotations

"""GAP-021 regression test.

Before this fix, ``ultimate_pipeline/osm/osm_to_xodr_wrapper.py`` built a
``carla.Osm2OdrSettings`` object and called ``carla.Osm2Odr.convert()`` with
it, but never assigned ``settings.proj_string`` anywhere in the file. This
meant every conversion silently inherited whatever ``carla.Osm2OdrSettings()``
itself defaults to for the installed CARLA build -- undocumented and
version-fragile -- instead of the codebase's own already-established,
already-verified geometry CRS (``ultimate_pipeline.dem.dem_crs_contract
.OSM2ODR_NATIVE_PROJ4`` / ``ultimate_pipeline.enrichment.coordinate_control
.VERIFIED_XODR_GEOMETRY_CRS_PROJ4``).

This test converts a tiny, real-world-coordinate OSM fixture (a short
residential way near Ingolstadt, real lat/lon values) through the actual
production conversion path (``convert_osm_to_xodr`` with the default
``OSMToXODRConfig()``, exactly as ``main_pipeline.py`` calls it), then:

1. Asserts ``proj_string`` is explicitly configured to the codebase's
   canonical native frame (not merely "whatever the field happens to be" --
   this catches someone silently deleting the assignment again).
2. Asserts the produced XODR's ``<geoReference>`` header is non-empty, and
   that it round-trips a header-bounds control point back to the fixture's
   real-world location within a tight tolerance -- proving the header
   honestly documents the frame the geometry is actually in (a naive
   consumer trusting the header without independent CRS-contract detection
   must not be misled the way GAP-021 originally described).
3. Asserts the resolved CRS's parameters match the NATIVE frame
   (lon_0 == 0, k == 1, x_0 == 0) and explicitly do NOT match true EPSG:32632
   (lon_0 == 9, k == 0.9996, x_0 == 500000) -- guarding against "fixing" this
   the wrong way (reprojecting into true EPSG:32632), which was verified
   during investigation to shift produced geometry by >150 km relative to
   the frame the rest of this pipeline (osm_polygon_loader.py,
   coordinate_control.py, dem_crs_contract.py, tile_fbx_generator.py, and
   the frozen auto_map_of_record candidate's rebase math) is built against.
"""

import math
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.osm.osm_to_xodr_wrapper import (
    DEFAULT_OSM2ODR_PROJ_STRING,
    OSMToXODRConfig,
    convert_osm_to_xodr,
)
from ultimate_pipeline.dem.dem_crs_contract import OSM2ODR_NATIVE_PROJ4
from ultimate_pipeline.enrichment.osm_polygon_loader import PROJ_STRING as OSM_POLYGON_LOADER_PROJ_STRING

pytest.importorskip("carla")

# A short residential way with real Ingolstadt-area coordinates (well within
# the authoritative OSM extract's bounds). Small enough to convert in well
# under a second, unlike the full ~11 MB authoritative OSM file.
_FIXTURE_OSM = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="gap021-regression-test">
  <bounds minlat="48.7460" minlon="11.4320" maxlat="48.7480" maxlon="11.4360"/>
  <node id="1" lat="48.7465" lon="11.4325"/>
  <node id="2" lat="48.7470" lon="11.4335"/>
  <node id="3" lat="48.7475" lon="11.4345"/>
  <node id="4" lat="48.7478" lon="11.4355"/>
  <way id="100">
    <nd ref="1"/>
    <nd ref="2"/>
    <nd ref="3"/>
    <nd ref="4"/>
    <tag k="highway" v="residential"/>
    <tag k="name" v="Gap021ReproStrasse"/>
  </way>
</osm>
"""

# Real-world ground truth for node id=1, the SW-most fixture node (also the
# SW corner of the produced XODR header bounds, verified below).
_REAL_LAT = 48.7465
_REAL_LON = 11.4325
_TOLERANCE_M = 5.0  # generous; observed round-trip error is ~0.005 m


def _haversine_flat_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Small-distance planar approximation -- fine at this scale (~metres)."""
    return math.hypot(
        (lon1 - lon2) * 111320.0 * math.cos(math.radians((lat1 + lat2) / 2.0)),
        (lat1 - lat2) * 110540.0,
    )


def test_default_config_pins_proj_string_to_native_frame() -> None:
    pytest.importorskip("pyproj")
    from pyproj import CRS

    cfg = OSMToXODRConfig()
    assert cfg.proj_string == DEFAULT_OSM2ODR_PROJ_STRING
    # Literal match with OSMPolygonLoader.PROJ_STRING: stage_04_enrichment.py
    # / main_pipeline.py already run a *textual* "georef_proj_consistency"
    # check against exactly this string, so using anything else (even a
    # numerically-equivalent spelling) would leave that existing gate
    # perpetually failing.
    assert cfg.proj_string == OSM_POLYGON_LOADER_PROJ_STRING

    # Numerically this bare string must resolve to the SAME CRS as the
    # fully-expanded native frame constant used elsewhere in the codebase
    # (dem_crs_contract.OSM2ODR_NATIVE_PROJ4 / coordinate_control's
    # VERIFIED_XODR_GEOMETRY_CRS_PROJ4) -- lat_0=0/lon_0=0/k=1/x_0=0/y_0=0 by
    # PROJ's own defaulting for the params the bare string omits.
    resolved = CRS.from_proj4(cfg.proj_string).to_dict()
    native = CRS.from_proj4(OSM2ODR_NATIVE_PROJ4).to_dict()
    for key in ("lat_0", "lon_0", "k", "x_0", "y_0"):
        assert abs(resolved.get(key, 0.0) - native.get(key, 0.0)) < 1e-9

    # And must explicitly NOT resolve to true EPSG:32632 (that would
    # silently move every produced XODR's geometry by >150 km relative to
    # the frame this pipeline's DEM/enrichment/tiling code already assumes).
    assert abs(resolved.get("lon_0", 0.0) - 9.0) > 1.0
    assert abs(resolved.get("k", 1.0) - 0.9996) > 1e-4
    assert abs(resolved.get("x_0", 0.0) - 500000.0) > 1.0

    # Companion settings that keep the coordinate system unshifted end to
    # end (CARLA's own defaults are center_map=True, use_offsets=True; both
    # must be explicitly False or Osm2Odr cannot even write a geoReference).
    assert cfg.center_map is False
    assert cfg.use_offsets is False


def test_conversion_header_georeference_resolves_to_real_world_location(tmp_path: Path) -> None:
    pyproj = pytest.importorskip("pyproj")
    from pyproj import CRS, Transformer

    osm_path = tmp_path / "gap021_fixture.osm"
    osm_path.write_text(_FIXTURE_OSM, encoding="utf-8")
    xodr_path = tmp_path / "gap021_fixture.xodr"

    result_path = convert_osm_to_xodr(osm_path, xodr_path, cfg=OSMToXODRConfig())
    assert result_path == xodr_path
    assert xodr_path.exists()

    root = ET.parse(xodr_path).getroot()
    header = root.find("header")
    assert header is not None
    geo = header.find("geoReference")
    assert geo is not None
    claimed_raw = (geo.text or "").strip()
    assert claimed_raw, "GAP-021: <geoReference> must not be empty/absent"

    claimed_crs = CRS.from_user_input(claimed_raw)

    # --- (1) header round-trips to the real-world fixture location -------
    # The SW corner of the header bounds corresponds to node 1 (the
    # southwesternmost fixture node) because center_map/use_offsets are both
    # False (unshifted coordinate system).
    west = float(header.get("west"))
    south = float(header.get("south"))
    tf_inv = Transformer.from_crs(claimed_crs, "EPSG:4326", always_xy=True)
    inv_lon, inv_lat = tf_inv.transform(west, south)
    err_m = _haversine_flat_m(inv_lon, inv_lat, _REAL_LON, _REAL_LAT)
    assert err_m < _TOLERANCE_M, (
        f"GAP-021 regression: header geoReference does not resolve back to "
        f"the real-world fixture location (error={err_m:.1f} m, tolerance="
        f"{_TOLERANCE_M} m). claimed_raw={claimed_raw!r}"
    )

    # --- (2) header parameters match the NATIVE frame, not EPSG:32632 -----
    claimed_params = claimed_crs.to_dict()
    assert abs(claimed_params.get("lon_0", 0.0) - 0.0) < 1e-6
    assert abs(claimed_params.get("k", 1.0) - 1.0) < 1e-6
    assert abs(claimed_params.get("x_0", 0.0) - 0.0) < 1e-6

    # --- (3) the header text is the EXACT literal OSMPolygonLoader.PROJ_STRING,
    # so stage_04_enrichment.py's / main_pipeline.py's pre-existing
    # "georef_proj_consistency" textual-equality check now genuinely passes
    # (reproducing that check's own logic here rather than importing the
    # pipeline stage, since it runs inline inside a much larger stage
    # method).
    assert claimed_raw == OSM_POLYGON_LOADER_PROJ_STRING


# ---------------------------------------------------------------------------
# 20260924 coordinate/OSM consistency audit: extend GAP-021's regression
# coverage past the XODR-header level. The two tests above prove the road
# geometry's <geoReference> round-trips correctly; they do NOT prove that
# (a) OSMPolygonLoader's building footprints land in the SAME frame as the
# road network produced by this same conversion (the historical C29 "7,665m
# building/road offset" defect and the J5 "165,943m origin-shift" defect are
# both instances of exactly this class of bug), or (b) the DEM-sampling CRS
# resolution path (ultimate_pipeline.dem.dem_crs_contract.resolve_sampling_crs,
# the same function ultimate_pipeline.enrichment.elevation_importer's
# _resolve_f1_sampling_crs delegates to) genuinely resolves a fresh,
# non-pinned conversion's frame and round-trips back to the real-world
# location -- the existing F1 control-point check in dem_crs_contract.py is
# hardcoded to the one pinned auto_map_of_record candidate, not exercised
# against an arbitrary freshly-generated XODR+OSM pair.
# ---------------------------------------------------------------------------

# Same road as _FIXTURE_OSM plus one small real building footprint close to
# node id=1 (real-world separation computed independently below via
# _haversine_flat_m, not hardcoded, so this isn't circular).
_FIXTURE_OSM_WITH_BUILDING = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="gap021-regression-test">
  <bounds minlat="48.7460" minlon="11.4320" maxlat="48.7480" maxlon="11.4360"/>
  <node id="1" lat="48.7465" lon="11.4325"/>
  <node id="2" lat="48.7470" lon="11.4335"/>
  <node id="3" lat="48.7475" lon="11.4345"/>
  <node id="4" lat="48.7478" lon="11.4355"/>
  <way id="100">
    <nd ref="1"/>
    <nd ref="2"/>
    <nd ref="3"/>
    <nd ref="4"/>
    <tag k="highway" v="residential"/>
    <tag k="name" v="Gap021ReproStrasse"/>
  </way>
  <node id="10" lat="48.7470" lon="11.4337"/>
  <node id="11" lat="48.7471" lon="11.4337"/>
  <node id="12" lat="48.7471" lon="11.4338"/>
  <node id="13" lat="48.7470" lon="11.4338"/>
  <way id="200">
    <nd ref="10"/>
    <nd ref="11"/>
    <nd ref="12"/>
    <nd ref="13"/>
    <nd ref="10"/>
    <tag k="building"/>
  </way>
</osm>
"""

_BUILDING_TOLERANCE_M = 5.0


def test_full_chain_building_frame_matches_road_frame_and_dem_crs_contract_resolves(
    tmp_path: Path,
) -> None:
    """Real end-to-end: OSM -> XODR (osm_to_xodr_wrapper) -> road frame, AND
    OSM -> building footprint (osm_polygon_loader) -> building frame, agree
    with no relative offset; AND the DEM-sampling CRS contract
    (dem_crs_contract.resolve_sampling_crs, what elevation_importer.py
    actually calls) resolves the fresh conversion and round-trips to the
    real-world fixture location.
    """
    pyproj = pytest.importorskip("pyproj")
    from pyproj import CRS, Transformer

    from ultimate_pipeline.enrichment.osm_polygon_loader import OSMPolygonLoader
    from ultimate_pipeline.dem.dem_crs_contract import resolve_sampling_crs

    osm_path = tmp_path / "gap021_building_fixture.osm"
    osm_path.write_text(_FIXTURE_OSM_WITH_BUILDING, encoding="utf-8")
    xodr_path = tmp_path / "gap021_building_fixture.xodr"

    convert_osm_to_xodr(osm_path, xodr_path, cfg=OSMToXODRConfig())
    assert xodr_path.exists()

    # --- (A) road frame: use the header's (west, south) corner as the
    # known real-world anchor -- proven in
    # test_conversion_header_georeference_resolves_to_real_world_location to
    # correspond exactly to node id=1 (the SW-most fixture node) when
    # center_map=use_offsets=False. We anchor on the header rather than an
    # arbitrary `<road>` element because Osm2Odr may split one OSM way into
    # multiple XODR roads in document order that does not match geometric
    # (westmost-first) order -- the header bounds are order-independent.
    root = ET.parse(xodr_path).getroot()
    header = root.find("header")
    assert header is not None
    road_x = float(header.get("west"))
    road_y = float(header.get("south"))

    # --- (B) building frame: OSMPolygonLoader projects the SAME OSM file's
    # building way through its own module-level TRANSFORMER. -------------
    buildings = OSMPolygonLoader.load_buildings_from_osm(str(osm_path), min_area=1.0)
    assert len(buildings) == 1, "fixture defines exactly one building footprint"
    footprint = buildings[0].footprint
    bld_x = sum(p[0] for p in footprint) / len(footprint)
    bld_y = sum(p[1] for p in footprint) / len(footprint)

    # --- (C) the two frames must agree: projected separation (road point to
    # building centroid, both already in meters, same tmerc frame) must
    # match the independently-computed real-world separation. A frame
    # mismatch (origin-shift, wrong central meridian, wrong k) would show up
    # here as a large residual -- this is precisely the class of bug C29
    # (7,665 m building/road offset) and J5 (165,943 m origin-shift) were.
    projected_separation_m = math.hypot(bld_x - road_x, bld_y - road_y)
    real_world_separation_m = _haversine_flat_m(
        _REAL_LON, _REAL_LAT,  # node id=1 (the header's west/south anchor)
        11.43375, 48.74705,  # building centroid (avg of the 4 fixture corners)
    )
    assert (
        abs(projected_separation_m - real_world_separation_m) < _BUILDING_TOLERANCE_M
    ), (
        "GAP-021 audit regression: building footprint (osm_polygon_loader.py) "
        "and road geometry (osm_to_xodr_wrapper.py) do not agree on the same "
        f"coordinate frame. projected separation={projected_separation_m:.2f} m, "
        f"real-world separation={real_world_separation_m:.2f} m."
    )

    # --- (D) the DEM-sampling CRS contract (what elevation_importer.py
    # actually calls before sampling a DEM) must resolve this fresh
    # conversion's frame -- not UNRESOLVED -- and the resolved CRS must
    # round-trip the road point back to the real-world fixture location.
    contract_crs, contract_source, record = resolve_sampling_crs(
        str(xodr_path), osm_path=str(osm_path), strict=True
    )
    assert contract_crs is not None
    assert record["verdict"] in (
        "CLAIMED_CRS_VERIFIED",
        "OSM2ODR_NATIVE_VERIFIED",
        "AMBIGUOUS",
    ), f"F1 CRS contract failed to resolve a fresh conversion: {record}"

    tf_inv = Transformer.from_crs(contract_crs, "EPSG:4326", always_xy=True)
    inv_lon, inv_lat = tf_inv.transform(road_x, road_y)
    dem_err_m = _haversine_flat_m(inv_lon, inv_lat, _REAL_LON, _REAL_LAT)
    assert dem_err_m < _TOLERANCE_M, (
        "GAP-021 audit regression: DEM-sampling CRS contract's resolved frame "
        f"does not round-trip to the real-world fixture location (error="
        f"{dem_err_m:.2f} m). sampling_crs_source={contract_source!r}"
    )
