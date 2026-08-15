# F1 — CRS contract: the frozen candidate must be sampled in its verified
# geographic frame, never in a merely-claimed header CRS.
from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.dem.dem_crs_contract import (
    OSM2ODR_NATIVE_PROJ4,
    WP1_CONTROL_POINT,
    osm2odr_native_crs,
    resolve_sampling_crs,
    verify_crs_contract,
)
from ultimate_pipeline.dem.dem_identity import (
    dem_coverage_gate,
    dem_identity_record,
    dem_identity_valid,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PINNED_CANDIDATE = (
    REPO_ROOT
    / "campaigns"
    / "ingolstadt_cooked_perception_v1"
    / "candidate"
    / "raw_xodr_run_1_epsg32632_header_pinned.xodr"
)
OSM_SOURCE = (
    REPO_ROOT
    / "campaigns"
    / "ingolstadt_cooked_perception_v1"
    / "source"
    / "ingolstadt_authoritative.osm"
)

#: Header bounds of the pinned candidate (native tmerc(0,0) frame).
PINNED_HEADER_BOUNDS = {
    "north": 5472743.54,
    "south": 5458671.57,
    "east": 845943.06,
    "west": 832672.90,
}

#: True Ingolstadt OSM node bounds (from the authoritative source).
INGOLSTADT_OSM_BOUNDS = {
    "lat_min": 48.6843318,
    "lat_max": 48.8143429,
    "lon_min": 11.3266919,
    "lon_max": 11.5382271,
}


def _xodr_with_header(bounds: dict, georef: str, offset: dict | None = None) -> str:
    root = ET.Element(
        "OpenDRIVE",
        {"version": "1.4"},
    )
    header = ET.SubElement(
        root,
        "header",
        {
            "north": f"{bounds['north']:.2f}",
            "south": f"{bounds['south']:.2f}",
            "east": f"{bounds['east']:.2f}",
            "west": f"{bounds['west']:.2f}",
        },
    )
    geo = ET.SubElement(header, "geoReference")
    geo.text = f"<![CDATA[{georef}]]>"
    if offset is not None:
        ET.SubElement(
            header,
            "offset",
            {
                "x": str(offset.get("x", 0.0)),
                "y": str(offset.get("y", 0.0)),
                "z": str(offset.get("z", 0.0)),
                "hdg": str(offset.get("hdg", 0.0)),
            },
        )
    road = ET.SubElement(
        root,
        "road",
        {"id": "1", "length": "10.0", "junction": "-1"},
    )
    pv = ET.SubElement(road, "planView")
    ET.SubElement(
        pv,
        "geometry",
        {
            "s": "0.0",
            "x": f"{WP1_CONTROL_POINT['xodr_x']:.6f}",
            "y": f"{WP1_CONTROL_POINT['xodr_y']:.6f}",
            "hdg": "0.0",
            "length": "10.0",
        },
    ).append(ET.Element("line"))
    path = REPO_ROOT / "reports" / "post_audit_hardening" / "_f1_test_tmp"
    path.mkdir(parents=True, exist_ok=True)
    out = path / f"xodr_{abs(hash(georef))}.xodr"
    ET.ElementTree(root).write(out, encoding="utf-8", xml_declaration=True)
    text = out.read_text(encoding="utf-8")
    text = text.replace(
        "&lt;![CDATA[" + georef + "]]&gt;", "<![CDATA[" + georef + "]]>"
    )
    out.write_text(text, encoding="utf-8")
    return str(out)


CLAIMED_UTM32N = (
    "+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 "
    "+datum=WGS84 +units=m +no_defs"
)


class TestVerifyCrsContract:
    def test_pinned_header_claim_is_disproven(self, tmp_path):
        xodr = _xodr_with_header(PINNED_HEADER_BOUNDS, CLAIMED_UTM32N)
        rec = verify_crs_contract(
            xodr, INGOLSTADT_OSM_BOUNDS, osm_path=str(tmp_path / "none.osm")
        )
        assert rec["verdict"] == "OSM2ODR_NATIVE_VERIFIED"
        assert rec["claimed_plausible"] is False
        assert rec["native_plausible"] is True

    def test_claimed_crs_would_place_map_outside_osm(self, tmp_path):
        xodr = _xodr_with_header(PINNED_HEADER_BOUNDS, CLAIMED_UTM32N)
        rec = verify_crs_contract(xodr, INGOLSTADT_OSM_BOUNDS)
        cw = rec["claimed_crs_header_bounds_wgs84"]
        assert cw["lon_min"] > INGOLSTADT_OSM_BOUNDS["lon_max"] + 1.0
        assert cw["lat_min"] > INGOLSTADT_OSM_BOUNDS["lat_max"] + 0.2

    def test_native_frame_matches_osm(self, tmp_path):
        xodr = _xodr_with_header(PINNED_HEADER_BOUNDS, CLAIMED_UTM32N)
        rec = verify_crs_contract(xodr, INGOLSTADT_OSM_BOUNDS)
        nw = rec["native_frame_header_bounds_wgs84"]
        margin = 0.15
        assert nw["lon_min"] >= INGOLSTADT_OSM_BOUNDS["lon_min"] - margin
        assert nw["lon_max"] <= INGOLSTADT_OSM_BOUNDS["lon_max"] + margin
        assert nw["lat_min"] >= INGOLSTADT_OSM_BOUNDS["lat_min"] - margin
        assert nw["lat_max"] <= INGOLSTADT_OSM_BOUNDS["lat_max"] + margin

    def test_local_bounds_with_header_offset_match_osm(self, tmp_path):
        local_bounds = {
            "north": 14072.79,
            "south": 0.0,
            "east": 13267.13,
            "west": 0.0,
        }
        offset = {
            "x": 832671.61,
            "y": 5458670.93,
            "z": 0.0,
            "hdg": 0.0,
        }
        xodr = _xodr_with_header(local_bounds, "+proj=tmerc", offset=offset)

        rec = verify_crs_contract(xodr, INGOLSTADT_OSM_BOUNDS)

        assert rec["verdict"] in {"OSM2ODR_NATIVE_VERIFIED", "AMBIGUOUS"}
        assert rec["header_offset"]["x"] == offset["x"]
        assert rec["header_bounds_with_offset"]["west"] == offset["x"]
        nw = rec["native_frame_header_bounds_wgs84"]
        margin = 0.15
        assert nw["lon_min"] >= INGOLSTADT_OSM_BOUNDS["lon_min"] - margin
        assert nw["lon_max"] <= INGOLSTADT_OSM_BOUNDS["lon_max"] + margin
        assert nw["lat_min"] >= INGOLSTADT_OSM_BOUNDS["lat_min"] - margin
        assert nw["lat_max"] <= INGOLSTADT_OSM_BOUNDS["lat_max"] + margin

    def test_wp1_control_point_error_is_isolated_to_claimed_crs(self, tmp_path):
        xodr = _xodr_with_header(PINNED_HEADER_BOUNDS, CLAIMED_UTM32N)
        rec = verify_crs_contract(xodr, INGOLSTADT_OSM_BOUNDS)
        err = rec["wp1_control_point_error_m_if_claimed_crs"]
        assert err is not None and err > 100_000.0

    def test_unresolved_without_osm_source(self, tmp_path):
        xodr = _xodr_with_header(PINNED_HEADER_BOUNDS, CLAIMED_UTM32N)
        rec = verify_crs_contract(xodr, None, osm_path=str(tmp_path / "missing.osm"))
        assert rec["verdict"] == "UNRESOLVED"

    def test_fail_closed_without_osm_source(self, tmp_path):
        xodr = _xodr_with_header(PINNED_HEADER_BOUNDS, CLAIMED_UTM32N)
        with pytest.raises(RuntimeError):
            resolve_sampling_crs(xodr, strict=True)


class TestResolveSamplingCrs:
    def test_resolves_to_osm2odr_native_for_pinned_candidate(self, tmp_path):
        from pyproj import CRS

        xodr = _xodr_with_header(PINNED_HEADER_BOUNDS, CLAIMED_UTM32N)
        crs, source, record = resolve_sampling_crs(
            xodr, osm_bounds=INGOLSTADT_OSM_BOUNDS
        )
        assert source == "osm2odr_native_verified"
        assert CRS.from_proj4(OSM2ODR_NATIVE_PROJ4) == crs

    def test_native_transform_places_control_point_in_ingolstadt(self, tmp_path):
        xodr = _xodr_with_header(PINNED_HEADER_BOUNDS, CLAIMED_UTM32N)
        crs, _, _ = resolve_sampling_crs(xodr, osm_bounds=INGOLSTADT_OSM_BOUNDS)
        from pyproj import CRS, Transformer

        tf = Transformer.from_crs(crs, CRS.from_epsg(4326), always_xy=True)
        lon, lat = tf.transform(
            WP1_CONTROL_POINT["xodr_x"], WP1_CONTROL_POINT["xodr_y"]
        )
        assert abs(lon - WP1_CONTROL_POINT["wgs84_lon"]) < 1e-5
        assert abs(lat - WP1_CONTROL_POINT["wgs84_lat"]) < 1e-5


class TestDemIdentityAndCoverage:
    def test_identity_requires_rasterio_and_file(self, tmp_path):
        rec = dem_identity_record(
            str(tmp_path / "missing.tif"),
            provider="COP30",
            licence="Copernicus",
            vertical_datum="EGM2008",
        )
        assert rec["ok"] is False
        assert rec["reason"] == "file_missing"

    def test_identity_validity_requires_datum(self, tmp_path):
        rec = {
            "ok": True,
            "crs": "EPSG:4326",
            "vertical_datum": None,
            "sha256": "x",
        }
        assert dem_identity_valid(rec) is False

    def test_coverage_gate_fails_closed_for_study_box_dem(self):
        identity = {
            "ok": True,
            "bounds_wgs84": {
                "lon_min": 11.4220833,
                "lat_min": 48.7495833,
                "lon_max": 11.47875,
                "lat_max": 48.7745833,
            },
        }
        full_map_extent = {
            "lon_min": INGOLSTADT_OSM_BOUNDS["lon_min"],
            "lat_min": INGOLSTADT_OSM_BOUNDS["lat_min"],
            "lon_max": INGOLSTADT_OSM_BOUNDS["lon_max"],
            "lat_max": INGOLSTADT_OSM_BOUNDS["lat_max"],
        }
        gate = dem_coverage_gate(identity, full_map_extent)
        assert gate["ok"] is False
        assert gate["reason"] == "map_extent_not_covered"

    def test_coverage_gate_passes_when_dem_covers_map(self):
        identity = {
            "ok": True,
            "bounds_wgs84": {
                "lon_min": 11.2,
                "lat_min": 48.6,
                "lon_max": 11.7,
                "lat_max": 49.0,
            },
        }
        gate = dem_coverage_gate(identity, {
            "lon_min": 11.327,
            "lat_min": 48.684,
            "lon_max": 11.538,
            "lat_max": 48.814,
        })
        assert gate["ok"] is True
