from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

from ultimate_pipeline.domain_gap.deterministic_alignment import (
    compute_auto_bbox_and_centroid,
    deterministic_promote_and_align,
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
# Double-translation guard: deterministic_alignment.py's own docstring says it
# "refuses to translate a map with non-zero <header><offset>...to avoid
# double-translation corruption". This safety check had zero test coverage --
# exactly the kind of guard that can silently regress (or never have worked)
# without anyone noticing, per this session's audit focus.
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_PYPROJ, reason="pyproj not installed in the repo venv")
def test_nonzero_header_offset_refuses_alignment_by_default(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("UP_ALLOW_ALIGNMENT_WITH_HEADER_OFFSET", raising=False)
    auto = tmp_path / "auto.xodr"
    _write_minimal_xodr(auto, [0, 10, 5], [0, 10, 5], header_offset=(123.0, 456.0))

    with pytest.raises(RuntimeError, match="non-zero <header><offset>"):
        deterministic_promote_and_align(
            auto_xodr_in=auto,
            manual_proj=_MANUAL_PROJ,
            gps_bounds=_GPS_BOUNDS,
            manual_bbox=None,
            out_aligned_xodr=tmp_path / "auto_aligned.xodr",
            require_overlap=False,
        )


@pytest.mark.skipif(not _HAS_PYPROJ, reason="pyproj not installed in the repo venv")
def test_nonzero_header_offset_allowed_with_explicit_env_override(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("UP_ALLOW_ALIGNMENT_WITH_HEADER_OFFSET", "1")
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
    assert validity["header_offset_xy"]["mag_m"] == pytest.approx(472.297576, rel=1e-3)


@pytest.mark.skipif(not _HAS_PYPROJ, reason="pyproj not installed in the repo venv")
def test_zero_header_offset_does_not_trigger_guard(tmp_path: Path, monkeypatch):
    """A zero (or absent) header offset must never require the env override."""
    monkeypatch.delenv("UP_ALLOW_ALIGNMENT_WITH_HEADER_OFFSET", raising=False)
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
    assert validity["header_offset_xy"]["mag_m"] == 0.0


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
