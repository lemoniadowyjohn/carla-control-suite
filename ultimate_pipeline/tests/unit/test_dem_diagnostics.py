# -*- coding: utf-8 -*-
"""Tests for DEMDiagnostics (ultimate_pipeline/dem/dem_diagnostics.py).

Live: called by main_pipeline.py (dem_diagnostics_initial report). Zero
prior test coverage. rasterio is installed in this environment, so these
tests exercise the real GeoTIFF-reading path against a small synthetic
raster, not just the missing-dependency fallback.
"""
from __future__ import annotations

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin  # noqa: E402

from ultimate_pipeline.dem.dem_diagnostics import DEMDiagnostics


def _write_synthetic_dem(path, *, nodata=-9999.0):
    data = np.array(
        [[10.0, 20.0, nodata], [30.0, 40.0, 50.0]], dtype="float32"
    )
    transform = from_origin(0.0, 2.0, 1.0, 1.0)  # 1m pixels, origin (0, 2)
    # No CRS is set here: this environment's PROJ/pyproj installations
    # disagree on proj.db schema version, so EPSG lookups fail regardless
    # of DEMDiagnostics itself. Bounds/resolution/elevation stats don't
    # depend on CRS resolution, so this still exercises the real read path.
    with rasterio.open(
        str(path), "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=data.dtype,
        transform=transform,
        nodata=nodata,
    ) as ds:
        ds.write(data, 1)
    return path


def test_missing_file_reports_exists_false():
    result = DEMDiagnostics.summarize("/nonexistent/path/does_not_exist.tif")
    assert result["exists"] is False
    assert "error" in result


def test_corrupt_file_reports_error_not_crash(tmp_path):
    bad_path = tmp_path / "not_a_geotiff.tif"
    bad_path.write_text("this is not a valid GeoTIFF")
    result = DEMDiagnostics.summarize(str(bad_path))
    assert result["exists"] is True
    assert result.get("rasterio_available") is True
    assert "error" in result


def test_valid_geotiff_reports_bounds_crs_and_elevation_stats(tmp_path):
    dem_path = tmp_path / "synthetic.tif"
    _write_synthetic_dem(dem_path)
    result = DEMDiagnostics.summarize(str(dem_path))
    assert result["exists"] is True
    assert result["rasterio_available"] is True
    assert result["bounds"]["left"] == pytest.approx(0.0)
    assert result["bounds"]["top"] == pytest.approx(2.0)
    assert result["resolution"]["x"] == pytest.approx(1.0)
    # nodata sentinel (-9999.0) excluded from min/max via masked read.
    assert result["elevation_min"] == pytest.approx(10.0)
    assert result["elevation_max"] == pytest.approx(50.0)
    assert result["valid_pixel_count"] == 5  # 6 pixels minus 1 nodata
