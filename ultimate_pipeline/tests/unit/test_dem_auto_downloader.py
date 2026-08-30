# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/dem/dem_auto_downloader.py.

Live: DEM download/coverage logic used by the elevation-enrichment
stages. Zero prior test coverage.

The bug: download_dem_for_bounds() wrote streamed chunks directly to
out_path inside a single `with open(out_path, "wb")` block. If the
download was interrupted partway through (network drop, server timeout,
disk full -- requests.Response.iter_content() raising mid-stream), the
partially-written file was left sitting at the FINAL path. On any
subsequent run, ensure_dem_exists()'s `os.path.exists(dem_path)` check
would then treat that corrupted/truncated file as a valid, already-
downloaded DEM and skip re-downloading entirely -- silently feeding a
broken DEM into elevation enrichment with no signal that anything went
wrong. Reproduced directly: a response that yields one chunk then raises
ConnectionError leaves a real (truncated) file at out_path; retrying
ensure_dem_exists() against that path returns it as-is.
"""
from __future__ import annotations

import os
from unittest import mock

import pytest

from ultimate_pipeline.dem import dem_auto_downloader as dem_mod


class _FakeResponse:
    def __init__(self, status_code=200, chunks=(b"chunk1", b"chunk2"), raise_after=None):
        self.status_code = status_code
        self._chunks = chunks
        self._raise_after = raise_after

    def iter_content(self, chunk_size=8192):
        for i, chunk in enumerate(self._chunks):
            yield chunk
            if self._raise_after is not None and i == self._raise_after:
                raise ConnectionError("simulated network drop mid-download")


# ---------------------------------------------------------------------------
# download_dem_for_bounds
# ---------------------------------------------------------------------------


def test_successful_download_writes_full_content(tmp_path):
    out_path = tmp_path / "dem.tif"
    with mock.patch.object(
        dem_mod.requests, "get", return_value=_FakeResponse(chunks=(b"abc", b"def"))
    ):
        result = dem_mod.download_dem_for_bounds(0, 1, 0, 1, "COP30", "key", str(out_path))
    assert result == str(out_path)
    assert out_path.read_bytes() == b"abcdef"


def test_http_error_status_raises_and_leaves_no_file(tmp_path):
    out_path = tmp_path / "dem.tif"
    with mock.patch.object(
        dem_mod.requests, "get", return_value=_FakeResponse(status_code=404)
    ):
        with pytest.raises(RuntimeError, match="404"):
            dem_mod.download_dem_for_bounds(0, 1, 0, 1, "COP30", "key", str(out_path))
    assert not out_path.exists()


def test_interrupted_download_does_not_leave_a_partial_file_at_out_path(tmp_path):
    out_path = tmp_path / "dem.tif"
    with mock.patch.object(
        dem_mod.requests,
        "get",
        return_value=_FakeResponse(chunks=(b"partial-data-only",), raise_after=0),
    ):
        with pytest.raises(ConnectionError):
            dem_mod.download_dem_for_bounds(0, 1, 0, 1, "COP30", "key", str(out_path))

    assert not out_path.exists(), (
        "an interrupted download must never leave a truncated/corrupted file "
        "at the final DEM path -- a later ensure_dem_exists() call would "
        "silently treat it as a valid, already-downloaded DEM"
    )
    # No stray temp file left behind either.
    assert list(tmp_path.iterdir()) == []


def test_interrupted_download_then_ensure_dem_exists_retries_instead_of_reusing_junk(
    tmp_path,
):
    out_path = tmp_path / "dem.tif"
    with mock.patch.object(
        dem_mod.requests,
        "get",
        return_value=_FakeResponse(chunks=(b"partial",), raise_after=0),
    ):
        with pytest.raises(ConnectionError):
            dem_mod.download_dem_for_bounds(0, 1, 0, 1, "COP30", "key", str(out_path))

    # Retry via ensure_dem_exists with a working response this time.
    gps_bounds = {"lat_min": 0, "lat_max": 1, "lon_min": 0, "lon_max": 1}
    with mock.patch.object(
        dem_mod.requests, "get", return_value=_FakeResponse(chunks=(b"real-dem-bytes",))
    ):
        result = dem_mod.ensure_dem_exists(gps_bounds, str(out_path), "COP30", "key")

    assert result == str(out_path)
    assert out_path.read_bytes() == b"real-dem-bytes"


# ---------------------------------------------------------------------------
# ensure_dem_exists
# ---------------------------------------------------------------------------


def test_ensure_dem_exists_returns_existing_file_without_downloading(tmp_path):
    out_path = tmp_path / "dem.tif"
    out_path.write_bytes(b"already here")
    with mock.patch.object(dem_mod.requests, "get") as mock_get:
        result = dem_mod.ensure_dem_exists(
            {"lat_min": 0, "lat_max": 1, "lon_min": 0, "lon_max": 1},
            str(out_path), "COP30", "key",
        )
    assert result == str(out_path)
    mock_get.assert_not_called()


def test_ensure_dem_exists_raises_without_api_key_when_missing(tmp_path):
    out_path = tmp_path / "dem.tif"
    with pytest.raises(RuntimeError, match="API key"):
        dem_mod.ensure_dem_exists(
            {"lat_min": 0, "lat_max": 1, "lon_min": 0, "lon_max": 1},
            str(out_path), "COP30", "",
        )


# ---------------------------------------------------------------------------
# _parse_osm_bbox / _apply_margin
# ---------------------------------------------------------------------------


def test_parse_osm_bbox_parses_four_values():
    assert dem_mod._parse_osm_bbox("1.0,2.0,3.0,4.0") == (1.0, 2.0, 3.0, 4.0)


def test_parse_osm_bbox_swaps_reversed_lat():
    # lat_max < lat_min given -> must be swapped so min/max are consistent.
    lat_min, lon_min, lat_max, lon_max = dem_mod._parse_osm_bbox("5.0,2.0,1.0,4.0")
    assert lat_min == 1.0
    assert lat_max == 5.0


def test_parse_osm_bbox_rejects_wrong_count():
    with pytest.raises(ValueError):
        dem_mod._parse_osm_bbox("1.0,2.0,3.0")


def test_apply_margin_expands_bbox_symmetrically():
    result = dem_mod._apply_margin(1.0, 2.0, 3.0, 4.0, 0.5)
    assert result == (0.5, 1.5, 3.5, 4.5)


# ---------------------------------------------------------------------------
# ensure_dem_covers_bbox
# ---------------------------------------------------------------------------


def test_ensure_dem_covers_bbox_returns_existing_path_when_it_fully_covers(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    import numpy as np
    from rasterio.transform import from_bounds
    from rasterio.warp import transform_bounds

    import pyproj

    crs_wkt = pyproj.CRS.from_epsg(4326).to_wkt()

    # ensure_dem_covers_bbox's coverage check calls rasterio.warp.
    # transform_bounds whenever str(src.crs) isn't literally "EPSG:4326"
    # (which is always true for a real WKT-stored CRS) -- and that call
    # hits the same pre-existing, already-documented broken proj.db in
    # this venv as rasterio.crs.CRS.from_epsg
    # (project_env_proj_pyproj_mismatch_20260829: zero real-code-logic
    # impact, all live CRS call sites use pyproj.CRS directly, this is
    # the one place ensure_dem_covers_bbox itself routes through
    # rasterio's broken EPSG machinery). Skip cleanly here rather than
    # asserting behavior this specific venv cannot exercise.
    try:
        transform_bounds(crs_wkt, "EPSG:4326", -1, -1, 2, 2)
    except Exception as e:
        pytest.skip(f"rasterio.warp.transform_bounds broken in this venv: {e}")

    dem_path = tmp_path / "dem.tif"
    transform = from_bounds(-1, -1, 2, 2, 10, 10)
    with rasterio.open(
        str(dem_path), "w", driver="GTiff", height=10, width=10, count=1,
        dtype="float32", crs=crs_wkt, transform=transform,
    ) as dst:
        dst.write(np.zeros((10, 10), dtype="float32"), 1)

    with mock.patch.object(dem_mod.requests, "get") as mock_get:
        result = dem_mod.ensure_dem_covers_bbox(
            {"minx": 0, "miny": 0, "maxx": 1, "maxy": 1},
            str(dem_path), "COP30", "key",
        )
    assert result == str(dem_path)
    mock_get.assert_not_called()


def test_ensure_dem_covers_bbox_downloads_expanded_when_not_covering(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    import numpy as np
    from rasterio.transform import from_bounds

    import pyproj

    dem_path = tmp_path / "dem.tif"
    transform = from_bounds(0, 0, 1, 1, 10, 10)
    crs_wkt = pyproj.CRS.from_epsg(4326).to_wkt()
    with rasterio.open(
        str(dem_path), "w", driver="GTiff", height=10, width=10, count=1,
        dtype="float32", crs=crs_wkt, transform=transform,
    ) as dst:
        dst.write(np.zeros((10, 10), dtype="float32"), 1)

    with mock.patch.object(
        dem_mod.requests, "get", return_value=_FakeResponse(chunks=(b"expanded-dem",))
    ):
        result = dem_mod.ensure_dem_covers_bbox(
            {"minx": 5, "miny": 5, "maxx": 6, "maxy": 6},  # far outside existing DEM
            str(dem_path), "COP30", "key",
        )
    assert os.path.basename(result) == "dem_expanded.tif"
    assert os.path.exists(result)
