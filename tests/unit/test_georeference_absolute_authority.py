"""P0-E acceptance: absolute OpenDRIVE georeference authority.

The map-of-record family stores plan-view coordinates in a LOCAL frame:
local = native_tmerc(lat_0=0/lon_0=0/k=1) - REBASE, and a bare
``+proj=tmerc`` geoReference carried no absolute origin, so WGS84 -> XODR ->
CARLA GNSS was not invertible. The truthful single-CRS encoding re-expresses
the SAME rebase in the projection's +x_0/+y_0 (proj false easting/northing
are pure post-translations, so this is exact, with no second offset and no
coordinate mutation).
"""

import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "ultimate_pipeline")):
    if p not in sys.path:
        sys.path.insert(0, p)

from ultimate_pipeline.geometry.coordinate_frame_contract import (  # noqa: E402
    REBASE_DX,
    REBASE_DY,
    has_absolute_georeference_origin,
    open_drive_georeference,
    open_drive_to_wgs84,
    wgs84_to_local,
)

# True geodetic anchor of the map frame: WP1 control point (WP1-verified,
# round-trip error 0.0 m): its OpenDRIVE-native coordinates minus the rebase
# land INSIDE the map's plan-view bbox.
WP1_LON, WP1_LAT = 11.434291, 48.747103
WP1_NATIVE_X = 840138.71778614
WP1_NATIVE_Y = 5464923.98146263
WP1_LOCAL_X = WP1_NATIVE_X - REBASE_DX  # ~7467.042
WP1_LOCAL_Y = WP1_NATIVE_Y - REBASE_DY  # ~6252.877

INGOLSTADT_OSM_BOUNDS = {
    "lat_min": 48.6843318,
    "lat_max": 48.8143429,
    "lon_min": 11.3266919,
    "lon_max": 11.5382271,
}


def _xodr_text(georef: str, offset: dict | None, geom: tuple | None) -> str:
    off = offset or {"x": REBASE_DX, "y": REBASE_DY}
    parts = [
        "<OpenDRIVE>",
        '<header revMajor="1" revMinor="4" name="t" version="1.00" '
        'north="57" south="0" east="13267.063" west="0.0">',
        f"<geoReference>{georef}</geoReference>",
        f'<offset hdg="0.0" z="0.0" x="{off.get("x", 0.0):.6f}" '
        f'y="{off.get("y", 0.0):.6f}" />',
        "</header>",
    ]
    if geom is not None:
        x, y, hdg, length = geom
        parts.append(
            '<road id="1" name="r" junction="-1" length="{L}">'
            "<planView>"
            '<geometry s="0" x="{x}" y="{y}" hdg="{h}" length="{L}">'
            '<line/></geometry>'
            "</planView>"
            '<lanes><laneSection><left><lane id="1" type="driving"/></left>'
            '</laneSection></lanes></road>'.format(x=x, y=y, h=hdg, L=length)
        )
    parts.append("</OpenDRIVE>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# (a) pyproj numeric proof: georef forward == contract wgs84_to_local, exact
# ---------------------------------------------------------------------------


def _pyproj_forward(georef: str, lon: float, lat: float):
    from pyproj import CRS, Transformer

    if georef is None:
        pytest.skip("pyproj unavailable")
    t = Transformer.from_crs(
        CRS.from_epsg(4326), CRS.from_proj4(georef), always_xy=True
    )
    return t.transform(lon, lat)


def test_contract_georef_reexpresses_rebase_exactly():
    geo = open_drive_georeference()
    # The string embeds minus the pinned rebase as false easting/northing:
    assert f"+x_0={-REBASE_DX:.3f}" in geo
    assert f"+y_0={-REBASE_DY:.3f}" in geo
    # ...and the native origin parameters (lat_0=0 lon_0=0 k=1):
    assert "+lat_0=0" in geo and "+lon_0=0" in geo and "+k=1" in geo


def test_georef_forward_equals_contract_chain_at_wp1():
    geo = open_drive_georeference()
    gx, gy = _pyproj_forward(geo, WP1_LON, WP1_LAT)
    cx, cy = wgs84_to_local(WP1_LON, WP1_LAT)
    assert (gx, gy) == pytest.approx((cx, cy), abs=1e-6)
    # The WP1 control point lands at native - rebase, inside the map bbox.
    assert (cx, cy) == pytest.approx((WP1_LOCAL_X, WP1_LOCAL_Y), abs=0.05)


def test_wgs84_roundtrip_invertible():
    geo = open_drive_georeference()
    fwd = _pyproj_forward(geo, WP1_LON, WP1_LAT)
    lon, lat = open_drive_to_wgs84(*fwd)
    assert lon == pytest.approx(WP1_LON, abs=1e-9)
    assert lat == pytest.approx(WP1_LAT, abs=1e-9)
    # contract inverse vs pyproj inverse agree exactly
    from pyproj import CRS, Transformer

    inv = Transformer.from_crs(
        CRS.from_proj4(geo), CRS.from_epsg(4326), always_xy=True
    )
    lon2, lat2 = inv.transform(*fwd)
    assert (lon, lat) == pytest.approx((lon2, lat2), abs=1e-9)


def test_osm_bbox_corners_map_into_planview_frame():
    geo = open_drive_georeference()
    sw = _pyproj_forward(geo, INGOLSTADT_OSM_BOUNDS["lon_min"],
                         INGOLSTADT_OSM_BOUNDS["lat_min"])
    ne = _pyproj_forward(geo, INGOLSTADT_OSM_BOUNDS["lon_max"],
                         INGOLSTADT_OSM_BOUNDS["lat_max"])
    # Same frame as native-minus-rebase (sub-millimetre agreement), and the
    # node bbox (superset of the road network) brackets the map extent.
    assert (sw[0] + REBASE_DX) == pytest.approx(833295.411, abs=0.01)
    assert (ne[0] + REBASE_DX) == pytest.approx(846615.847, abs=0.01)


def test_has_absolute_georeference_origin():
    assert has_absolute_georeference_origin(open_drive_georeference())
    assert not has_absolute_georeference_origin("+proj=tmerc")
    assert not has_absolute_georeference_origin(
        "+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996"
    )


def test_georef_describes_local_coords_exact_rule():
    from ultimate_pipeline.core.georef_utils import georef_describes_local_coords

    geo = open_drive_georeference()
    assert georef_describes_local_coords(geo, REBASE_DX, REBASE_DY)
    # anything else (bare tmerc, other offsets, no offset) is not local-desc:
    assert not georef_describes_local_coords("+proj=tmerc", REBASE_DX, REBASE_DY)
    assert not georef_describes_local_coords(geo, 500000.0, 0.0)
    assert not georef_describes_local_coords(geo, 0.0, 0.0)


# ---------------------------------------------------------------------------
# (b) sanitizer: missing-geoReference default becomes the contract string
# ---------------------------------------------------------------------------


def test_sanitizer_missing_georef_default_is_contract(tmp_path):
    from ultimate_pipeline.core.xodr_sanitizer import XODRSanitizer

    root = ET.fromstring(
        "<OpenDRIVE><header revMajor='1' revMinor='4'/></OpenDRIVE>"
    )
    XODRSanitizer._ensure_header(root)
    geo = root.find("header").find("geoReference")
    assert geo is not None
    assert (geo.text or "") == open_drive_georeference()


def test_parse_georeference_params_complete_on_new_string():
    from ultimate_pipeline.core.georef_utils import parse_georeference

    valid, params_complete, norm = parse_georeference(open_drive_georeference())
    assert valid is True
    assert params_complete is True
    assert norm == open_drive_georeference()


# ---------------------------------------------------------------------------
# (d) step-8 embed path (synthetic XODR + tmpdir, no full pipeline)
# ---------------------------------------------------------------------------


def _final_map(tmp_path: Path, georef: str, offset: dict | None) -> Path:
    final = tmp_path / "candidate_final.xodr"
    final.write_text(_xodr_text(georef, offset, geom=(7467.042, 6252.877, 0.9, 25.0)))
    return final


def _pipeline_shell(tmp_path: Path):
    from ultimate_pipeline.main_pipeline import MainPipeline

    inst = MainPipeline.__new__(MainPipeline)
    inst.out_dir = str(tmp_path)
    return inst


def test_step8_embeds_pinned_rebase(monkeypatch, tmp_path):
    monkeypatch.delenv("UP_MANUAL_XODR_GRID0828", raising=False)
    monkeypatch.delenv("UP_MANUAL_XODR", raising=False)
    monkeypatch.delenv("UP_DISABLE_GEOF_ABSOLUTE_AUTOPIN", raising=False)

    final = _final_map(tmp_path, "+proj=tmerc", None)
    before = _xodr_text  # coordinates must not mutate
    tree0 = ET.parse(str(final))
    geom0 = tree0.getroot().find(".//planView/geometry")
    coord0 = (geom0.get("x"), geom0.get("y"))

    inst = _pipeline_shell(tmp_path)
    inst._maybe_override_final_georef(str(final))

    root = ET.parse(str(final)).getroot()
    geo = root.find("header").find("geoReference")
    assert geo.text == open_drive_georeference()

    geom1 = root.find(".//planView/geometry")
    assert (geom1.get("x"), geom1.get("y")) == coord0  # no coordinate mutation

    prov = (tmp_path / "georef_override.json")
    assert prov.exists()
    record = __import__("json").loads(prov.read_text())
    assert record["action"] == "embed_rebase_autopin"
    assert record["contract_georef"] == open_drive_georeference()
    assert record["rebase_embedded"] == {"x_0": -REBASE_DX, "y_0": -REBASE_DY}
    assert record["auto_xodr_sha256_before"] != record["auto_xodr_sha256_after"]


def test_step8_embed_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.delenv("UP_MANUAL_XODR_GRID0828", raising=False)
    monkeypatch.delenv("UP_MANUAL_XODR", raising=False)
    monkeypatch.delenv("UP_DISABLE_GEOF_ABSOLUTE_AUTOPIN", raising=False)

    final = _final_map(tmp_path, open_drive_georeference(), None)
    inst = _pipeline_shell(tmp_path)
    inst._maybe_override_final_georef(str(final))
    prov = __import__("json").loads((tmp_path / "georef_override.json").read_text())
    # already embedded -> no second write of a different string; action skipped
    assert prov["action"] != "embed_rebase_autopin"
    root = ET.parse(str(final)).getroot()
    assert root.find("header").find("geoReference").text == open_drive_georeference()


def test_step8_refuses_non_pinned_offset(monkeypatch, tmp_path):
    monkeypatch.delenv("UP_MANUAL_XODR_GRID0828", raising=False)
    monkeypatch.delenv("UP_MANUAL_XODR", raising=False)

    final = _final_map(tmp_path, "+proj=tmerc", {"x": 500000.0, "y": 0.0})
    inst = _pipeline_shell(tmp_path)
    inst._maybe_override_final_georef(str(final))
    prov = __import__("json").loads((tmp_path / "georef_override.json").read_text())
    assert prov["action"] != "embed_rebase_autopin"
    assert "offset_not_pinned_rebase" in prov["reason"]
    root = ET.parse(str(final)).getroot()
    assert root.find("header").find("geoReference").text == "+proj=tmerc"


def test_step8_respects_opt_out_env(monkeypatch, tmp_path):
    monkeypatch.setenv("UP_DISABLE_GEOF_ABSOLUTE_AUTOPIN", "1")
    monkeypatch.delenv("UP_MANUAL_XODR_GRID0828", raising=False)
    monkeypatch.delenv("UP_MANUAL_XODR", raising=False)

    final = _final_map(tmp_path, "+proj=tmerc", None)
    inst = _pipeline_shell(tmp_path)
    inst._maybe_override_final_georef(str(final))
    prov = __import__("json").loads((tmp_path / "georef_override.json").read_text())
    assert prov["action"] != "embed_rebase_autopin"
    assert "embed_autopin_disabled_by_env" in prov["reason"]


def test_step8_does_not_fight_manual_override(monkeypatch, tmp_path):
    manual = tmp_path / "manual.xodr"
    manual.write_text(
        _xodr_text("+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 "
                   "+datum=WGS84 +units=m +no_defs", None, None)
    )
    monkeypatch.setenv("UP_MANUAL_XODR_GRID0828", str(manual.resolve()))
    monkeypatch.delenv("UP_DISABLE_GEOF_ABSOLUTE_AUTOPIN", raising=False)

    final = _final_map(tmp_path, "+proj=tmerc", None)
    inst = _pipeline_shell(tmp_path)
    inst._maybe_override_final_georef(str(final))
    prov = __import__("json").loads((tmp_path / "georef_override.json").read_text())
    # manual override path keeps precedence (legacy behavior preserved)
    assert prov["action"] in ("applied", "skipped")
    root = ET.parse(str(final)).getroot()
    text = root.find("header").find("geoReference").text
    assert text != open_drive_georeference()
    assert "+lon_0=9" in text


# ---------------------------------------------------------------------------
# (e) local_registration: no double offset subtraction with embedded georef
# ---------------------------------------------------------------------------


def test_local_registration_effective_offset_zero_when_embedded():
    from ultimate_pipeline.domain_gap.local_registration import (
        effective_auto_offset,
    )

    assert effective_auto_offset(open_drive_georeference(),
                                 (REBASE_DX, REBASE_DY)) == (0.0, 0.0)
    # legacy bare tmerc keeps the header offset behavior
    assert effective_auto_offset("+proj=tmerc", (REBASE_DX, REBASE_DY)) == (
        REBASE_DX, REBASE_DY,
    )


def test_local_registration_no_double_subtract_at_wp1(pytestconfig):
    from ultimate_pipeline.domain_gap.local_registration import (
        building_frame_shift_to_auto_local,
    )

    shift = building_frame_shift_to_auto_local(
        WP1_LAT, WP1_LON, open_drive_georeference(), (REBASE_DX, REBASE_DY)
    )
    legacy_shift = building_frame_shift_to_auto_local(
        WP1_LAT, WP1_LON, "+proj=tmerc +lat_0=0 +lon_0=0 +k=1 +datum=WGS84 "
        "+units=m +no_defs", (REBASE_DX, REBASE_DY)
    )
    # embedded: single translation; legacy explicit-native+offset: same math
    assert (shift[0], shift[1]) == pytest.approx(legacy_shift, abs=1e-6)


# ---------------------------------------------------------------------------
# (f) dem_crs_contract: truthful WGS84 extent for an embedded-georef map
# ---------------------------------------------------------------------------


def test_map_wgs84_extent_truthful_for_embedded_map(tmp_path):
    from ultimate_pipeline.dem.dem_crs_contract import (
        map_wgs84_extent,
        verify_crs_contract,
    )

    final = tmp_path / "embedded_map.xodr"
    final.write_text(_xodr_text(open_drive_georeference(), None,
                                geom=(7467.042, 6252.877, 0.9, 25.0)))

    rec = verify_crs_contract(final, INGOLSTADT_OSM_BOUNDS)
    # sampling flow unchanged: native frame still resolves (zero pipeline
    # regression), while the additive evidence records the embedded truth.
    assert rec["verdict"] == "OSM2ODR_NATIVE_VERIFIED"
    assert rec["claimed_crs_local_embedded"] is True
    cw = rec["claimed_wgs84_geodetic_local_embedded"]
    assert cw is not None
    assert INGOLSTADT_OSM_BOUNDS["lon_min"] <= cw["lon_min"] <= cw["lon_max"] \
        <= INGOLSTADT_OSM_BOUNDS["lon_max"] + 0.5
    assert INGOLSTADT_OSM_BOUNDS["lat_min"] <= cw["lat_min"] <= cw["lat_max"] \
        <= INGOLSTADT_OSM_BOUNDS["lat_max"] + 0.5

    ext = map_wgs84_extent(final, osm_bounds=INGOLSTADT_OSM_BOUNDS)
    assert ext["sampling_crs_source"] == "claimed_geoReference_local_embedded"
    ew = ext["extent_wgs84"]
    assert ew is not None
    assert INGOLSTADT_OSM_BOUNDS["lon_min"] - 0.2 <= ew["lon_min"] <= \
        INGOLSTADT_OSM_BOUNDS["lon_max"] + 0.2
    assert INGOLSTADT_OSM_BOUNDS["lat_min"] - 0.2 <= ew["lat_min"] <= \
        INGOLSTADT_OSM_BOUNDS["lat_max"] + 0.2
