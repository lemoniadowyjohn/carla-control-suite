"""C29 bug 1: osm_polygon_loader.py projected buildings via a GPS-bbox-corner tmerc origin
(+lat_0=<gps.lat_min> +lon_0=<gps.lon_min>), while the road network (Osm2Odr output) uses a
BARE tmerc origin (implicit lat_0=0/lon_0=0). Two different projection origins -> on the real
pinned pair, a verified 7,665m centroid offset between buildings and roads.

Fix: buildings must project through the SAME bare-tmerc frame as roads
(matches ultimate_pipeline.domain_gap.local_registration.BARE_TMERC_DEFAULT), so raw building
coordinates land in the same (pre-rebase) global frame as road planView geometry.
"""
from __future__ import annotations

from pyproj import CRS, Transformer

import ultimate_pipeline.enrichment.osm_polygon_loader as loader


def test_proj_string_has_no_gps_bbox_origin():
    # The old bug: lat_0/lon_0 pinned to the GPS bbox corner. Bare tmerc has neither.
    assert "lat_0" not in loader.PROJ_STRING
    assert "lon_0" not in loader.PROJ_STRING
    assert "+proj=tmerc" in loader.PROJ_STRING


def test_proj_string_matches_local_registration_bare_tmerc():
    from ultimate_pipeline.domain_gap.local_registration import BARE_TMERC_DEFAULT

    # Both must project a known point identically (same frame roads use).
    t_loader = Transformer.from_crs("EPSG:4326", CRS.from_proj4(loader.PROJ_STRING), always_xy=True)
    t_roads = Transformer.from_crs("EPSG:4326", CRS.from_proj4(BARE_TMERC_DEFAULT), always_xy=True)
    lon, lat = 11.4230, 48.7500  # a point inside the Ingolstadt bbox
    xa, ya = t_loader.transform(lon, lat)
    xb, yb = t_roads.transform(lon, lat)
    assert abs(xa - xb) < 1e-6
    assert abs(ya - yb) < 1e-6


def test_latlon_to_xy_uses_bare_tmerc_global_frame():
    # A bare-tmerc projection of a point at ~48.75N should land far from the map-local origin
    # (hundreds of thousands of meters, matching Osm2Odr's own pre-rebase global convention) --
    # NOT the small GPS-bbox-relative numbers the old bug produced.
    x, y = loader.OSMPolygonLoader._latlon_to_xy(48.7500, 11.4230)
    assert abs(x) > 100_000 or abs(y) > 100_000
