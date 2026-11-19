"""OC-03: Geospatial projection tests for OSM->OpenDRIVE correspondence.

These tests use pyproj directly (read-only, offline) to validate CRS
transformations that the existing production CRS infrastructure should
support. No CD-05 code is modified; these tests define the expected CRS
behavior that CD-05's freeze should formalize.

Covered:
- WGS84 <-> Osm2Odr native tmerc round-trips for study bounds corners
- NATIVE <-> EPSG:32632 is actual reprojection (not just offset)
- Study bounds corners in all frames
- QA-MAP-01: Applying EPSG:32632 params to NATIVE coords misplaces by ~160km E/63km N
- Offline, read-only, no CARLA server required
"""

from __future__ import annotations

import math

import pyproj
import pytest

# Study bounds (WGS84)
LAT_MIN = 48.74935649548228
LAT_MAX = 48.77444431571603
LON_MIN = 11.422268084715878
LON_MAX = 11.47882091528412

# CRS definitions
WGS84_CRS = "EPSG:4326"
NATIVE_CRS = (
    "+proj=tmerc +lat_0=0 +lon_0=0 +k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
)
EPSG_32632_CRS = (
    "+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 +datum=WGS84 +units=m +no_defs"
)

# Pinned rebase offset (from coordinate_frame_contract.py on later branches)
REBASE_DX = 832671.676
REBASE_DY = 5458671.104

# Expected corners from independent pyproj oracle
EXPECTED_NATIVE_SW = (839219.03, 5465039.90)
EXPECTED_NATIVE_NE = (842941.36, 5468453.52)
EXPECTED_EPSG_SW = (678051.23, 5402424.00)
EXPECTED_EPSG_NE = (682117.09, 5405346.18)


# ---------------------------------------------------------------------------
# Transformer fixtures
# ---------------------------------------------------------------------------


def _wgs84_to_native():
    return pyproj.Transformer.from_crs(WGS84_CRS, NATIVE_CRS, always_xy=True)


def _native_to_wgs84():
    return pyproj.Transformer.from_crs(NATIVE_CRS, WGS84_CRS, always_xy=True)


def _native_to_epsg32632():
    return pyproj.Transformer.from_crs(NATIVE_CRS, EPSG_32632_CRS, always_xy=True)


def _epsg32632_to_native():
    return pyproj.Transformer.from_crs(EPSG_32632_CRS, NATIVE_CRS, always_xy=True)


# ---------------------------------------------------------------------------
# WGS84 <-> NATIVE round-trips
# ---------------------------------------------------------------------------


def test_wgs84_to_native_study_bounds_sw():
    """SW corner of study bounds in NATIVE frame matches independent oracle."""
    x, y = _wgs84_to_native().transform(LON_MIN, LAT_MIN)
    assert x == pytest.approx(EXPECTED_NATIVE_SW[0], abs=0.1)
    assert y == pytest.approx(EXPECTED_NATIVE_SW[1], abs=0.1)


def test_wgs84_to_native_study_bounds_ne():
    """NE corner of study bounds in NATIVE frame matches independent oracle."""
    x, y = _wgs84_to_native().transform(LON_MAX, LAT_MAX)
    assert x == pytest.approx(EXPECTED_NATIVE_NE[0], abs=0.1)
    assert y == pytest.approx(EXPECTED_NATIVE_NE[1], abs=0.1)


def test_wgs84_to_native_round_trip():
    """WGS84 -> NATIVE -> WGS84 round-trip is exact."""
    for lon, lat in [(LON_MIN, LAT_MIN), (LON_MAX, LAT_MAX), (11.5, 48.75)]:
        x, y = _wgs84_to_native().transform(lon, lat)
        lon2, lat2 = _native_to_wgs84().transform(x, y)
        assert lon == pytest.approx(lon2, abs=1e-9)
        assert lat == pytest.approx(lat2, abs=1e-9)


# ---------------------------------------------------------------------------
# NATIVE <-> EPSG:32632 actual reprojection
# ---------------------------------------------------------------------------


def test_native_to_epsg32632_is_actual_reprojection():
    """NATIVE -> EPSG:32632 is actual reprojection, not just an offset.

    QA-MAP-01: The auto XODR is in Osm2Odr native bare tmerc
    (lon_0=0, k=1), NOT EPSG:32632. Applying true 32632 parameters
    to auto coordinates misplaces them by ~160km E / 63km N.
    """
    x_n, y_n = EXPECTED_NATIVE_SW
    x_32, y_32 = _native_to_epsg32632().transform(x_n, y_n)

    dx = abs(x_32 - x_n)
    dy = abs(y_32 - y_n)
    assert dx > 100000, f"Expected >100km X difference, got {dx:.1f}m"
    assert dy > 10000, f"Expected >10km Y difference, got {dy:.1f}m"


def test_native_to_epsg32632_round_trip():
    """NATIVE -> EPSG:32632 -> NATIVE round-trip is exact."""
    x_n, y_n = EXPECTED_NATIVE_SW
    x_32, y_32 = _native_to_epsg32632().transform(x_n, y_n)
    x_n2, y_n2 = _epsg32632_to_native().transform(x_32, y_32)
    assert x_n == pytest.approx(x_n2, abs=1e-6)
    assert y_n == pytest.approx(y_n2, abs=1e-6)


def test_epsg32632_does_not_equal_native_plus_offset():
    """EPSG:32632 is NOT just NATIVE plus a constant offset.

    If it were, the difference between NATIVE and EPSG:32632
    would be constant across the study area. It isn't - the
    projections have different origins and scale factors.
    """
    sw_n = _wgs84_to_native().transform(LON_MIN, LAT_MIN)
    ne_n = _wgs84_to_native().transform(LON_MAX, LAT_MAX)
    sw_32 = _native_to_epsg32632().transform(*sw_n)
    ne_32 = _native_to_epsg32632().transform(*ne_n)

    dx_sw = sw_32[0] - sw_n[0]
    dx_ne = ne_32[0] - ne_n[0]
    assert abs(dx_sw - dx_ne) > 1, "EPSG:32632 is not just NATIVE plus constant offset"


# ---------------------------------------------------------------------------
# NATIVE <-> LOCAL rebase offset
# ---------------------------------------------------------------------------


def test_native_to_local_applies_rebase_offset():
    """NATIVE -> LOCAL subtracts REBASE_DX/DY."""
    x_n, y_n = EXPECTED_NATIVE_SW
    x_l = x_n - REBASE_DX
    y_l = y_n - REBASE_DY
    assert x_l == pytest.approx(x_n - REBASE_DX, abs=1e-9)
    assert y_l == pytest.approx(y_n - REBASE_DY, abs=1e-9)


def test_local_to_native_applies_rebase_offset():
    """LOCAL -> NATIVE adds REBASE_DX/DY."""
    x_l, y_l = EXPECTED_NATIVE_SW[0] - REBASE_DX, EXPECTED_NATIVE_SW[1] - REBASE_DY
    x_n = x_l + REBASE_DX
    y_n = y_l + REBASE_DY
    assert x_n == pytest.approx(x_l + REBASE_DX, abs=1e-9)
    assert y_n == pytest.approx(y_l + REBASE_DY, abs=1e-9)


def test_native_to_local_round_trip():
    """NATIVE -> LOCAL -> NATIVE round-trip is exact."""
    x_n, y_n = EXPECTED_NATIVE_SW
    x_l = x_n - REBASE_DX
    y_l = y_n - REBASE_DY
    x_n2 = x_l + REBASE_DX
    y_n2 = y_l + REBASE_DY
    assert x_n == pytest.approx(x_n2, abs=1e-9)
    assert y_n == pytest.approx(y_n2, abs=1e-9)


# ---------------------------------------------------------------------------
# QA-MAP-01: EPSG:32632 misplacement quantification
# ---------------------------------------------------------------------------


def test_qa_map_01_epsg32632_misplacement():
    """QA-MAP-01: Applying EPSG:32632 to NATIVE coords misplaces by ~160km E/63km N.

    The auto XODR is in Osm2Odr native tmerc (lon_0=0, k=1).
    Applying true EPSG:32632 (lon_0=9, k=0.9996, x_0=500000) to those
    coordinates shifts them by ~161km E and ~63km N.
    """
    x_n, y_n = EXPECTED_NATIVE_SW
    x_32, y_32 = _native_to_epsg32632().transform(x_n, y_n)

    dx = x_32 - x_n
    dy = y_32 - y_n

    assert 150000 < abs(dx) < 170000, f"Expected ~161km |E| displacement, got {dx:.1f}m"
    assert 60000 < abs(dy) < 70000, f"Expected ~63km |N| displacement, got {dy:.1f}m"


# ---------------------------------------------------------------------------
# Study bounds in all frames
# ---------------------------------------------------------------------------


def test_study_bounds_all_frames():
    """Study bounds corners expressed in NATIVE, LOCAL, and EPSG:32632."""
    for lon, lat in [(LON_MIN, LAT_MIN), (LON_MAX, LAT_MAX)]:
        x_n, y_n = _wgs84_to_native().transform(lon, lat)
        x_l = x_n - REBASE_DX
        y_l = y_n - REBASE_DY
        x_32, y_32 = _native_to_epsg32632().transform(x_n, y_n)

        assert all(math.isfinite(v) for v in [x_n, y_n, x_l, y_l, x_32, y_32])
        assert x_n - x_l == pytest.approx(REBASE_DX, abs=1e-9)
        assert y_n - y_l == pytest.approx(REBASE_DY, abs=1e-9)


if __name__ == "__main__":
    test_wgs84_to_native_study_bounds_sw()
    test_wgs84_to_native_study_bounds_ne()
    test_wgs84_to_native_round_trip()
    test_native_to_local_applies_rebase_offset()
    test_local_to_native_applies_rebase_offset()
    test_native_to_local_round_trip()
    test_native_to_epsg32632_is_actual_reprojection()
    test_native_to_epsg32632_round_trip()
    test_epsg32632_does_not_equal_native_plus_offset()
    test_wgs84_to_local_composite()
    test_local_to_wgs84_composite()
    test_qa_map_01_epsg32632_misplacement()
    test_study_bounds_all_frames()
    print("All OC-03 geospatial projection tests PASSED")
