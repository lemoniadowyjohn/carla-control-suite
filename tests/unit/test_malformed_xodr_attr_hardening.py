"""Tests for defensive validation of malformed numeric XODR attributes.

Each test constructs minimal malformed input and verifies the function
either skips the bad element gracefully or raises a clear error — never
an opaque ValueError/TypeError traceback.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# File 1: osm_polygon_loader — unguarded float() on node lat/lon (lines 88-89)
# ---------------------------------------------------------------------------
class TestOSMPolygonLoaderMalformedNodes:
    """load_buildings_from_osm must skip OSM nodes with non-numeric lat/lon
    instead of crashing the whole parse."""

    @staticmethod
    def _write_osm(path: Path, nodes_xml: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<osm version="0.6">\n'
            f'{nodes_xml}\n'
            '</osm>',
            encoding="utf-8",
        )
        return path

    def test_malformed_lat_skips_node(self, tmp_path: Path):
        """After fix: malformed lat → node skipped, no crash, returns empty list."""
        osm = self._write_osm(
            tmp_path / "test.osm",
            '<node id="1" lat="not_a_number" lon="11.0"/>',
        )
        from ultimate_pipeline.enrichment.osm_polygon_loader import OSMPolygonLoader
        result = OSMPolygonLoader.load_buildings_from_osm(str(osm))
        assert result == [], "malformed node should be skipped, yielding 0 buildings"

    def test_malformed_lon_skips_node(self, tmp_path: Path):
        """After fix: malformed lon → node skipped, no crash."""
        osm = self._write_osm(
            tmp_path / "test_lon.osm",
            '<node id="3" lat="48.0" lon="garbage"/>',
        )
        from ultimate_pipeline.enrichment.osm_polygon_loader import OSMPolygonLoader
        result = OSMPolygonLoader.load_buildings_from_osm(str(osm))
        assert result == [], "malformed lon node should be skipped"

    def test_valid_nodes_still_work(self, tmp_path: Path):
        """After fix: well-formed nodes still parse correctly (no regression)."""
        osm = self._write_osm(
            tmp_path / "test_valid.osm",
            '<node id="10" lat="48.0" lon="11.0"/>\n'
            '<node id="11" lat="49.0" lon="12.0"/>\n'
            '<node id="12" lat="48.5" lon="11.5"/>',
        )
        from ultimate_pipeline.enrichment.osm_polygon_loader import OSMPolygonLoader
        result = OSMPolygonLoader.load_buildings_from_osm(str(osm))
        # No building ways in the OSM → 0 buildings, but no crash
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# File 2: deterministic_alignment — gps_bounds values (lines 61-62)
# ---------------------------------------------------------------------------
class TestDeterministicAlignmentMalformedGPSBounds:
    """project_center_from_gps_bounds must fail closed with a clear error
    on non-numeric gps_bounds values."""

    def test_malformed_gps_bounds_raises_clear_error(self):
        """After fix: non-numeric gps_bounds → ValueError with clear message."""
        from ultimate_pipeline.domain_gap.deterministic_alignment import (
            project_center_from_gps_bounds,
        )
        bad_bounds = {
            "lat_min": "not_a_number",
            "lat_max": "49.0",
            "lon_min": "11.0",
            "lon_max": "12.0",
        }
        with pytest.raises(ValueError, match="invalid gps_bounds"):
            project_center_from_gps_bounds(bad_bounds, "+proj=tmerc +datum=WGS84 +units=m +no_defs")

    def test_valid_gps_bounds_still_work(self):
        """After fix: well-formed gps_bounds still compute correctly (no regression)."""
        from ultimate_pipeline.domain_gap.deterministic_alignment import (
            project_center_from_gps_bounds,
        )
        good_bounds = {
            "lat_min": "48.0",
            "lat_max": "49.0",
            "lon_min": "11.0",
            "lon_max": "12.0",
        }
        x, y = project_center_from_gps_bounds(good_bounds, "+proj=tmerc +datum=WGS84 +units=m +no_defs")
        assert math.isfinite(x)
        assert math.isfinite(y)


# ---------------------------------------------------------------------------
# File 3: deterministic_alignment — geometry x/y (lines 88-89, 145-146)
# ---------------------------------------------------------------------------
class TestDeterministicAlignmentMalformedGeometryXY:
    """compute_auto_bbox_and_centroid and translate_xodr_geometry must handle
    non-numeric geometry x/y attributes gracefully."""

    @staticmethod
    def _write_xodr(tmp_path: Path, geom_attrs: str) -> Path:
        xodr = tmp_path / "test.xodr"
        xodr.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<OpenDRIVE>\n"
            '  <header revMajor="1" revMinor="6"/>\n'
            '  <road name="" length="50.0" id="0" junction="-1">\n'
            "    <planView>\n"
            f'      <geometry s="0" {geom_attrs}>\n'
            "        <line/>\n"
            "      </geometry>\n"
            "    </planView>\n"
            "  </road>\n"
            "</OpenDRIVE>\n",
            encoding="utf-8",
        )
        return xodr

    def test_malformed_geometry_xy_in_centroid_skips_gracefully(self, tmp_path: Path):
        """After fix: malformed x/y → geometry skipped → no crash, falls back."""
        xodr = self._write_xodr(tmp_path, 'x="garbage" y="48.0" hdg="0.0" length="50.0"')
        from ultimate_pipeline.domain_gap.deterministic_alignment import (
            compute_auto_bbox_and_centroid,
        )
        # Malformed geometry is skipped → no valid points → raises ValueError("No planView geometry points")
        with pytest.raises(ValueError, match="No planView geometry points"):
            compute_auto_bbox_and_centroid(xodr)

    def test_missing_geometry_xy_in_centroid_skips_today(self, tmp_path: Path):
        """RECORD: missing x/y is already handled (None check at line 86)."""
        xodr = self._write_xodr(tmp_path, 'hdg="0.0" length="50.0"')
        from ultimate_pipeline.domain_gap.deterministic_alignment import (
            compute_auto_bbox_and_centroid,
        )
        with pytest.raises(ValueError, match="No planView geometry points"):
            compute_auto_bbox_and_centroid(xodr)

    def test_malformed_geometry_xy_in_translate_raises_clear_error(self, tmp_path: Path):
        """After fix: malformed x/y → RuntimeError with element context."""
        xodr_in = self._write_xodr(tmp_path, 'x="garbage" y="48.0" hdg="0.0" length="50.0"')
        xodr_out = tmp_path / "out.xodr"
        from ultimate_pipeline.domain_gap.deterministic_alignment import (
            translate_xodr_geometry,
        )
        with pytest.raises(RuntimeError, match="non-numeric planView geometry"):
            translate_xodr_geometry(xodr_in, xodr_out, dx=0.0, dy=0.0)

    def test_valid_geometry_xy_still_works(self, tmp_path: Path):
        """After fix: well-formed geometry x/y still translates correctly (no regression)."""
        xodr_in = self._write_xodr(tmp_path, 'x="10.0" y="20.0" hdg="0.0" length="50.0"')
        xodr_out = tmp_path / "out.xodr"
        from ultimate_pipeline.domain_gap.deterministic_alignment import (
            translate_xodr_geometry,
        )
        result = translate_xodr_geometry(xodr_in, xodr_out, dx=100.0, dy=200.0)
        assert result["translated_geometry_points"] == 1
        assert result["dx"] == 100.0
        assert result["dy"] == 200.0
