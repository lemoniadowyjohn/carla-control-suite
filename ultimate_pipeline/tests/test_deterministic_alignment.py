from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

from ultimate_pipeline.domain_gap.deterministic_alignment import (
    compute_auto_bbox_and_centroid,
    deterministic_promote_and_align,
    translate_xodr_geometry,
    BBox,
)

try:
    import pyproj  # noqa: F401
    _HAS_PYPROJ = True
except Exception:
    _HAS_PYPROJ = False

def _write_minimal_xodr(path: Path, xs, ys, *, header_offset=None):
    root = ET.Element("OpenDRIVE")
    if header_offset is not None:
        header = ET.SubElement(root, "header")
        ET.SubElement(header, "offset", x=str(header_offset[0]), y=str(header_offset[1]))
    road = ET.SubElement(root, "road", attrib={"name":"r1","length":"1","id":"1","junction":"-1"})
    plan = ET.SubElement(road, "planView")
    for i,(x,y) in enumerate(zip(xs,ys)):
        ET.SubElement(plan, "geometry", attrib={"s":str(i), "x":str(x), "y":str(y), "hdg":"0", "length":"1"})
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


_GPS_BOUNDS = {
    "lat_min": 48.74935649548228,
    "lat_max": 48.77444431571603,
    "lon_min": 11.422268084715878,
    "lon_max": 11.47882091528412,
}
_MANUAL_PROJ = "+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 +datum=WGS84 +units=m +no_defs"

@pytest.mark.skipif(not _HAS_PYPROJ, reason="pyproj not installed in the repo venv")
def test_alignment_maps_centroid_to_projected_gps_center(tmp_path: Path):
    auto = tmp_path/"auto.xodr"
    _write_minimal_xodr(auto, [0,10,5], [0,10,5])

    gps_bounds = {
        "lat_min": 48.74935649548228,
        "lat_max": 48.77444431571603,
        "lon_min": 11.422268084715878,
        "lon_max": 11.47882091528412,
    }
    manual_proj = "+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 +datum=WGS84 +units=m +no_defs"

    out = tmp_path/"auto_aligned.xodr"
    deterministic_promote_and_align(
        auto_xodr_in=auto,
        manual_proj=manual_proj,
        gps_bounds=gps_bounds,
        manual_bbox=None,
        out_aligned_xodr=out,
        out_validity_json=tmp_path/"validity.json",
        require_overlap=False,
    )

    _, (cx,cy), _ = compute_auto_bbox_and_centroid(out)
    # We don't assert numeric values here (depends on pyproj); the key is "it runs"
    assert isinstance(cx, float) and isinstance(cy, float)


# ---------------------------------------------------------------------------
# A translated output is in the target CRS.  Retaining a source-frame XY
# header offset would make consumers apply a second translation.  A non-zero
# source XY offset must therefore be explicitly rebased to zero in the output;
# a non-zero header rotation remains unsupported and must fail closed.
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_PYPROJ, reason="pyproj not installed in the repo venv")
def test_nonzero_header_offset_is_rebased_to_target_crs_frame(tmp_path: Path):
    auto = tmp_path / "auto.xodr"
    _write_minimal_xodr(auto, [0, 10, 5], [0, 10, 5], header_offset=(123.0, 456.0))

    out = tmp_path / "auto_aligned.xodr"
    validity = deterministic_promote_and_align(
        auto_xodr_in=auto,
        manual_proj=_MANUAL_PROJ,
        gps_bounds=_GPS_BOUNDS,
        manual_bbox=None,
        out_aligned_xodr=out,
        require_overlap=False,
    )
    assert validity["status"] == "ok"
    assert validity["input_header_offset_xy"]["mag_m"] == pytest.approx(472.297576, rel=1e-3)
    assert validity["output_header_offset_xy"] == {"x": 0.0, "y": 0.0}
    header = ET.parse(out).getroot().find("header")
    assert header is not None
    assert float(header.find("offset").get("x")) == 0.0
    assert float(header.find("offset").get("y")) == 0.0
    assert header.find("geoReference").text == _MANUAL_PROJ


@pytest.mark.skipif(not _HAS_PYPROJ, reason="pyproj not installed in the repo venv")
def test_zero_header_offset_remains_zero_after_alignment(tmp_path: Path):
    auto = tmp_path / "auto.xodr"
    _write_minimal_xodr(auto, [0, 10, 5], [0, 10, 5], header_offset=(0.0, 0.0))

    out = tmp_path / "auto_aligned.xodr"
    validity = deterministic_promote_and_align(
        auto_xodr_in=auto,
        manual_proj=_MANUAL_PROJ,
        gps_bounds=_GPS_BOUNDS,
        manual_bbox=None,
        out_aligned_xodr=out,
        require_overlap=False,
    )
    assert validity["status"] == "ok"
    assert validity["input_header_offset_xy"]["mag_m"] == 0.0
    assert validity["output_header_offset_xy"] == {"x": 0.0, "y": 0.0}


@pytest.mark.skipif(not _HAS_PYPROJ, reason="pyproj not installed in the repo venv")
def test_rotated_header_offset_refuses_unhandled_coordinate_transform(tmp_path: Path):
    auto = tmp_path / "auto.xodr"
    _write_minimal_xodr(auto, [0, 10, 5], [0, 10, 5], header_offset=(123.0, 456.0))
    tree = ET.parse(auto)
    tree.getroot().find("./header/offset").set("hdg", "0.1")
    tree.write(auto, encoding="utf-8", xml_declaration=True)

    with pytest.raises(RuntimeError, match="non-zero header offset rotation"):
        deterministic_promote_and_align(
            auto_xodr_in=auto,
            manual_proj=_MANUAL_PROJ,
            gps_bounds=_GPS_BOUNDS,
            manual_bbox=None,
            out_aligned_xodr=tmp_path / "auto_aligned.xodr",
            require_overlap=False,
        )


@pytest.mark.skipif(not _HAS_PYPROJ, reason="pyproj not installed in the repo venv")
def test_malformed_header_offset_refuses_alignment_instead_of_assuming_zero(tmp_path: Path):
    auto = tmp_path / "auto.xodr"
    _write_minimal_xodr(auto, [0, 10, 5], [0, 10, 5], header_offset=(123.0, 456.0))
    tree = ET.parse(auto)
    tree.getroot().find("./header/offset").set("x", "not-a-number")
    tree.write(auto, encoding="utf-8", xml_declaration=True)

    with pytest.raises(ValueError, match="invalid header offset"):
        deterministic_promote_and_align(
            auto_xodr_in=auto,
            manual_proj=_MANUAL_PROJ,
            gps_bounds=_GPS_BOUNDS,
            manual_bbox=None,
            out_aligned_xodr=tmp_path / "auto_aligned.xodr",
            require_overlap=False,
        )


@pytest.mark.skipif(not _HAS_PYPROJ, reason="pyproj not installed in the repo venv")
def test_require_overlap_fails_when_aligned_bbox_misses_manual_bbox(tmp_path: Path):
    """require_overlap=True (the production default) must raise when the aligned
    auto bbox and the manual bbox don't overlap -- this is the fail-fast safety net
    the module docstring promises ("we can fail fast")."""
    auto = tmp_path / "auto.xodr"
    _write_minimal_xodr(auto, [0, 10, 5], [0, 10, 5])

    # A manual bbox placed far away from where the GPS-center anchor will land,
    # so the aligned auto bbox cannot possibly overlap it.
    far_away_manual_bbox = BBox(minx=10_000_000.0, miny=10_000_000.0, maxx=10_000_100.0, maxy=10_000_100.0)

    with pytest.raises(RuntimeError, match="Alignment validity failed"):
        deterministic_promote_and_align(
            auto_xodr_in=auto,
            manual_proj=_MANUAL_PROJ,
            gps_bounds=_GPS_BOUNDS,
            manual_bbox=far_away_manual_bbox,
            out_aligned_xodr=tmp_path / "auto_aligned.xodr",
            out_validity_json=tmp_path / "validity.json",
            require_overlap=True,
        )


def test_bbox_overlaps_touching_edges_counts_as_overlap():
    a = BBox(minx=0.0, miny=0.0, maxx=10.0, maxy=10.0)
    b = BBox(minx=10.0, miny=0.0, maxx=20.0, maxy=10.0)
    assert a.overlaps(b) is True
    assert b.overlaps(a) is True


def test_bbox_overlaps_disjoint_returns_false():
    a = BBox(minx=0.0, miny=0.0, maxx=10.0, maxy=10.0)
    b = BBox(minx=100.0, miny=100.0, maxx=110.0, maxy=110.0)
    assert a.overlaps(b) is False
    assert b.overlaps(a) is False


# ---------------------------------------------------------------------------
# translate_xodr_geometry shifts every planView geometry point by (dx, dy) but
# used to leave <header west/east/south/north> completely untouched. Real
# consumers read those attributes directly -- xodr_compare_gate.py's
# north>=south/east>=west sanity check and dem_crs_contract.py's CRS-
# consistency check -- so after a real alignment shift (which can be on the
# order of hundreds of kilometers, moving near-origin local coordinates into
# a real-world CRS neighborhood) the header silently described a bounding box
# that no longer matched the file's own geometry.
# ---------------------------------------------------------------------------

def test_translate_xodr_geometry_updates_stale_header_bbox(tmp_path: Path):
    auto = tmp_path / "auto.xodr"
    _write_minimal_xodr(auto, [0, 10, 5], [0, 10, 5])
    # Bolt on a pre-existing header bbox that describes the un-translated
    # local coordinates, the way a real pipeline-generated map does.
    tree = ET.parse(auto)
    header = ET.Element("header")
    header.set("west", "0.0")
    header.set("east", "10.0")
    header.set("south", "0.0")
    header.set("north", "10.0")
    header.set("geometryFrozen", "true")
    header.set("geometryFreezeHash", "source-freeze-hash")
    tree.getroot().insert(0, header)
    tree.write(auto, encoding="utf-8", xml_declaration=True)

    out = tmp_path / "translated.xodr"
    dx, dy = 500000.0, 300000.0
    result = translate_xodr_geometry(auto, out, dx, dy)

    out_header = ET.parse(out).getroot().find("header")
    assert float(out_header.get("west")) == pytest.approx(0.0 + dx)
    assert float(out_header.get("east")) == pytest.approx(10.0 + dx)
    assert float(out_header.get("south")) == pytest.approx(0.0 + dy)
    assert float(out_header.get("north")) == pytest.approx(10.0 + dy)
    assert out_header.get("geometryFrozen") is None
    assert out_header.get("geometryFreezeHash") is None
    assert result["source_geometry_freeze_invalidated"] is True


def test_translate_xodr_geometry_inserts_header_bbox_when_missing(tmp_path: Path):
    auto = tmp_path / "auto_no_header.xodr"
    _write_minimal_xodr(auto, [0, 10, 5], [0, 20, 5])  # no header element at all

    out = tmp_path / "translated_no_header.xodr"
    dx, dy = 1000.0, 2000.0
    translate_xodr_geometry(auto, out, dx, dy)

    out_root = ET.parse(out).getroot()
    out_header = out_root.find("header")
    assert out_header is not None
    assert out_root[0] is out_header
    assert float(out_header.get("west")) == pytest.approx(0.0 + dx)
    assert float(out_header.get("east")) == pytest.approx(10.0 + dx)
    assert float(out_header.get("south")) == pytest.approx(0.0 + dy)
    assert float(out_header.get("north")) == pytest.approx(20.0 + dy)


# ---------------------------------------------------------------------------
# Malformed numeric planView x/y attributes must not crash the whole parse,
# and -- critically -- a geometry where x parses but y doesn't (or vice
# versa) must not silently desynchronize the xs/ys populations. Appending x
# then having y's conversion raise leaves xs one element ahead of ys, so the
# next iteration's y value gets paired with THIS iteration's x in the
# centroid/bbox math -- a real, verified bug this test locks closed.
# ---------------------------------------------------------------------------

def test_malformed_geometry_xy_is_skipped_without_desyncing_xs_ys(tmp_path: Path) -> None:
    xodr = tmp_path / "malformed.xodr"
    # Geometry 0: x valid, y malformed -> must be skipped entirely.
    # Geometry 1: fully valid -> the only point that should survive.
    _write_minimal_xodr(xodr, [1.0, 2.0], [10.0, 3.0])
    tree = ET.parse(xodr)
    geoms = tree.getroot().find("road/planView").findall("geometry")
    geoms[0].set("y", "not-a-number")
    tree.write(xodr, encoding="utf-8", xml_declaration=True)

    bbox, centroid, n = compute_auto_bbox_and_centroid(xodr)

    assert n == 1
    assert centroid == pytest.approx((2.0, 3.0))
    assert bbox == BBox(minx=2.0, miny=3.0, maxx=2.0, maxy=3.0)


def test_malformed_geometry_x_is_skipped_without_desyncing_xs_ys(tmp_path: Path) -> None:
    xodr = tmp_path / "malformed_x.xodr"
    _write_minimal_xodr(xodr, [1.0, 2.0], [10.0, 3.0])
    tree = ET.parse(xodr)
    geoms = tree.getroot().find("road/planView").findall("geometry")
    geoms[0].set("x", "not-a-number")
    tree.write(xodr, encoding="utf-8", xml_declaration=True)

    bbox, centroid, n = compute_auto_bbox_and_centroid(xodr)

    assert n == 1
    assert centroid == pytest.approx((2.0, 3.0))


def test_all_malformed_geometry_raises_no_points_found(tmp_path: Path) -> None:
    xodr = tmp_path / "all_malformed.xodr"
    _write_minimal_xodr(xodr, [1.0], [1.0])
    tree = ET.parse(xodr)
    geoms = tree.getroot().find("road/planView").findall("geometry")
    geoms[0].set("x", "garbage")
    tree.write(xodr, encoding="utf-8", xml_declaration=True)

    with pytest.raises(ValueError, match="No planView geometry points found"):
        compute_auto_bbox_and_centroid(xodr)


def test_valid_geometry_still_computes_correct_centroid(tmp_path: Path) -> None:
    xodr = tmp_path / "valid.xodr"
    _write_minimal_xodr(xodr, [0.0, 10.0], [0.0, 10.0])

    bbox, centroid, n = compute_auto_bbox_and_centroid(xodr)

    assert n == 2
    assert centroid == pytest.approx((5.0, 5.0))


def test_translate_xodr_geometry_raises_clear_error_on_malformed_xy(tmp_path: Path) -> None:
    xodr = tmp_path / "malformed_translate.xodr"
    _write_minimal_xodr(xodr, [1.0], [1.0])
    tree = ET.parse(xodr)
    geoms = tree.getroot().find("road/planView").findall("geometry")
    geoms[0].set("y", "garbage")
    tree.write(xodr, encoding="utf-8", xml_declaration=True)

    with pytest.raises(RuntimeError, match="non-numeric planView geometry"):
        translate_xodr_geometry(xodr, tmp_path / "out.xodr", 1.0, 1.0)


@pytest.mark.skipif(not _HAS_PYPROJ, reason="pyproj not installed in the repo venv")
def test_project_center_from_gps_bounds_raises_clear_error_on_malformed_value() -> None:
    from ultimate_pipeline.domain_gap.deterministic_alignment import project_center_from_gps_bounds

    bad_bounds = {"lat_min": "not-a-number", "lat_max": 48.77, "lon_min": 11.42, "lon_max": 11.48}
    with pytest.raises(ValueError, match="invalid gps_bounds value"):
        project_center_from_gps_bounds(bad_bounds, _MANUAL_PROJ)
