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
