import pytest
import tempfile
import os

# Test if pyproj is available
try:
    from pyproj import CRS, Transformer
    PYPROJ_AVAILABLE = True
except Exception:
    PYPROJ_AVAILABLE = False


def test_dem_identity_geographic_crs_bounds():
    """Test that geographic CRS DEM bounds are correctly interpreted as degrees."""
    if not PYPROJ_AVAILABLE:
        pytest.skip("pyproj not available")

    from ultimate_pipeline.dem.dem_identity import _transform_bounds_to_wgs84

    # Geographic CRS (EPSG:4326) - bounds should remain unchanged
    bounds = {"left": 10.0, "bottom": 50.0, "right": 11.0, "top": 51.0}
    result = _transform_bounds_to_wgs84(bounds, "EPSG:4326")

    assert result is not None
    assert result["lon_min"] == pytest.approx(10.0, abs=1e-6)
    assert result["lat_min"] == pytest.approx(50.0, abs=1e-6)
    assert result["lon_max"] == pytest.approx(11.0, abs=1e-6)
    assert result["lat_max"] == pytest.approx(51.0, abs=1e-6)


def test_dem_identity_projected_crs_bounds_transformed():
    """Test that projected CRS DEM bounds are transformed to degrees."""
    if not PYPROJ_AVAILABLE:
        pytest.skip("pyproj not available")

    from ultimate_pipeline.dem.dem_identity import _transform_bounds_to_wgs84

    # UTM Zone 32N (EPSG:32632) - typical for Ingolstadt
    # Example bounds in UTM meters
    bounds = {
        "left": 670000.0,
        "bottom": 5400000.0,
        "right": 680000.0,
        "top": 5410000.0,
    }
    result = _transform_bounds_to_wgs84(bounds, "EPSG:32632")

    assert result is not None
    # Check that bounds are transformed to plausible lat/lon
    # Ingolstadt area: ~11.4E, 48.8N
    assert 10.0 < result["lon_min"] < 13.0
    assert 47.0 < result["lat_min"] < 50.0
    assert 10.0 < result["lon_max"] < 13.0
    assert 47.0 < result["lat_max"] < 50.0


def test_dem_identity_coverage_gate_bbox_area_fraction():
    """Test the new bbox_intersection_area_fraction metric."""
    if not PYPROJ_AVAILABLE:
        pytest.skip("pyproj not available")

    from ultimate_pipeline.dem.dem_identity import dem_coverage_gate

    # Identity with valid WGS84 bounds
    identity = {
        "ok": True,
        "bounds_wgs84": {
            "lon_min": 11.0,
            "lat_min": 48.0,
            "lon_max": 12.0,
            "lat_max": 49.0,
        },
    }

    # Map extent fully inside DEM
    map_extent = {
        "lon_min": 11.2,
        "lat_min": 48.2,
        "lon_max": 11.8,
        "lat_max": 48.8,
    }

    result = dem_coverage_gate(identity, map_extent)
    assert result["ok"] is True
    assert result["fully_covered"] is True
    assert "bbox_intersection_area_fraction" in result
    assert result["bbox_intersection_area_fraction"] == pytest.approx(1.0, abs=1e-3)


def test_dem_identity_coverage_gate_partial_overlap():
    """Test partial overlap gives correct area fraction."""
    if not PYPROJ_AVAILABLE:
        pytest.skip("pyproj not available")

    from ultimate_pipeline.dem.dem_identity import dem_coverage_gate

    identity = {
        "ok": True,
        "bounds_wgs84": {
            "lon_min": 11.0,
            "lat_min": 48.0,
            "lon_max": 11.5,
            "lat_max": 48.5,
        },
    }

    map_extent = {
        "lon_min": 11.0,
        "lat_min": 48.0,
        "lon_max": 12.0,
        "lat_max": 49.0,
    }

    result = dem_coverage_gate(identity, map_extent)
    assert result["ok"] is False
    assert result["fully_covered"] is False
    assert "bbox_intersection_area_fraction" in result
    # Intersection is 0.5x0.5 = 0.25 deg², map is 1x1 = 1 deg²
    # Area fraction should be around 0.25 (approximate due to cos(lat))
    assert 0.15 < result["bbox_intersection_area_fraction"] < 0.35


def test_dem_identity_coverage_gate_no_overlap():
    """Test no overlap returns zero area fraction."""
    if not PYPROJ_AVAILABLE:
        pytest.skip("pyproj not available")

    from ultimate_pipeline.dem.dem_identity import dem_coverage_gate

    identity = {
        "ok": True,
        "bounds_wgs84": {
            "lon_min": 10.0,
            "lat_min": 47.0,
            "lon_max": 10.5,
            "lat_max": 47.5,
        },
    }

    map_extent = {
        "lon_min": 11.0,
        "lat_min": 48.0,
        "lon_max": 12.0,
        "lat_max": 49.0,
    }

    result = dem_coverage_gate(identity, map_extent)
    assert result["ok"] is False
    assert result["fully_covered"] is False
    assert result["bbox_intersection_area_fraction"] == 0.0


def test_dem_identity_projected_raster_not_interpreted_as_degrees():
    """Regression test: projected raster bounds (e.g., 600000m) must NOT be interpreted as 600000 degrees."""
    if not PYPROJ_AVAILABLE:
        pytest.skip("pyproj not available")

    from ultimate_pipeline.dem.dem_identity import _transform_bounds_to_wgs84

    # Large UTM coordinates - if interpreted as degrees, would be absurd
    bounds = {
        "left": 600000.0,
        "bottom": 5400000.0,
        "right": 700000.0,
        "top": 5500000.0,
    }
    result = _transform_bounds_to_wgs84(bounds, "EPSG:32632")

    assert result is not None
    # Should be transformed to plausible lat/lon, NOT 600000 degrees
    assert -180 <= result["lon_min"] <= 180
    assert -90 <= result["lat_min"] <= 90
    assert -180 <= result["lon_max"] <= 180
    assert -90 <= result["lat_max"] <= 90


if __name__ == "__main__":
    pytest.main([__file__, "-v"])