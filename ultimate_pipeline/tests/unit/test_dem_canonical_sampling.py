# -*- coding: utf-8 -*-
"""Regression tests for the OC-53 DEM/elevation canonical-sampling fix cluster.

Covers the 8 documented bugs from the DEM/elevation sampling audit:

1. check_dem_coverage.py's _get_road_sample_points() used a heading-
   approximated midpoint/endpoint instead of real curve sampling.
2. check_dem_full_coverage.py only sampled line+arc primitives, silently
   ignoring spiral/poly3/paramPoly3.
3. rasterio unavailable produced a false green (report.ok=True on
   ImportError) instead of failing closed.
4. _safe_float defaulted malformed attributes to 0.0 in production
   sampling instead of failing (a malformed attribute must not silently
   fabricate a phantom sample point).
5. ElevationImporter's endpoint computation used a straight-line
   approximation for curved roads instead of the canonical geometry kernel.
6. ElevationGap._sample_geometry_points() had its own duplicate,
   incomplete geometry evaluator (arc+paramPoly3 only).
7. dem_provenance.py accepted declared CRS/bounds without verifying
   against the actual raster.
8. No real vertical-datum truth (inferred from horizontal CRS instead).

Each fixture uses a real curved-geometry XODR (arc / paramPoly3) and
compares sampled coordinates against an INDEPENDENTLY computed closed-form
expected position -- not merely "the code calls the canonical kernel" (which
would be tautological), but "the sampled coordinates are geometrically
correct for a curved road," which is what the old heading-approximation
code got wrong.
"""
from __future__ import annotations

import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Tuple

import pytest


def _write(tmp_path: Path, name: str, xml_text: str) -> str:
    path = tmp_path / name
    path.write_text(xml_text, encoding="utf-8")
    return str(path)


# Shared arc fixture: curvature k=0.05 (radius 20m), length=10m, hdg0=0,
# starting at origin. Independently computed (not via the kernel under test):
#   local_x = sin(k*s)/k, local_y = (1 - cos(k*s))/k
K = 0.05
LENGTH = 10.0


def _arc_expected_xy(s: float, x0: float = 0.0, y0: float = 0.0, hdg0: float = 0.0) -> Tuple[float, float]:
    local_x = math.sin(K * s) / K
    local_y = (1.0 - math.cos(K * s)) / K
    x = x0 + math.cos(hdg0) * local_x - math.sin(hdg0) * local_y
    y = y0 + math.sin(hdg0) * local_x + math.cos(hdg0) * local_y
    return x, y


def _straight_line_approx_xy(s: float, x0: float = 0.0, y0: float = 0.0, hdg0: float = 0.0) -> Tuple[float, float]:
    """What the OLD (buggy) heading-approximation code would have produced."""
    return x0 + math.cos(hdg0) * s, y0 + math.sin(hdg0) * s


def _arc_road_xodr(tmp_path: Path, name: str, *, road_id: str = "1") -> str:
    return _write(
        tmp_path,
        name,
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE>"
        f'<road id="{road_id}" length="{LENGTH}" junction="-1">'
        f'<planView><geometry s="0" x="0" y="0" hdg="0" length="{LENGTH}">'
        f'<arc curvature="{K}"/></geometry></planView>'
        "</road>"
        "</OpenDRIVE>",
    )


# ---------------------------------------------------------------------------
# Issue 1: check_dem_coverage.py real curve sampling (not heading-approx)
# ---------------------------------------------------------------------------

from ultimate_pipeline.quality.check_dem_coverage import _get_road_sample_points


def test_get_road_sample_points_arc_matches_canonical_curve_not_straight_line(tmp_path: Path) -> None:
    """A curved (arc) road's midpoint/endpoint samples must lie on the true
    arc, not on the straight-line extrapolation the old code produced."""
    xodr = _arc_road_xodr(tmp_path, "arc.xodr")
    root = ET.parse(xodr).getroot()

    points = _get_road_sample_points(root, max_roads=50, samples_per_road=3)

    assert len(points) == 3
    s_values = (0.0, LENGTH / 2.0, LENGTH)
    for (x, y, rid), s in zip(points, s_values):
        assert rid == "1"
        expected = _arc_expected_xy(s)
        assert x == pytest.approx(expected[0], abs=1e-6)
        assert y == pytest.approx(expected[1], abs=1e-6)
        # Sanity: for the midpoint/endpoint, the true arc position must
        # diverge measurably from the old straight-line approximation --
        # otherwise this fixture wouldn't actually distinguish the fix.
        if s > 0:
            wrong = _straight_line_approx_xy(s)
            assert math.hypot(x - wrong[0], y - wrong[1]) > 0.5


def test_get_road_sample_points_single_sample_uses_canonical_start_pose(tmp_path: Path) -> None:
    """samples_per_road<=1 path (start-only sampling) must also go through
    the canonical evaluator, not first-geometry raw attributes."""
    xodr = _arc_road_xodr(tmp_path, "arc_single.xodr")
    root = ET.parse(xodr).getroot()

    points = _get_road_sample_points(root, max_roads=50, samples_per_road=1)

    assert len(points) == 1
    x, y, rid = points[0]
    assert (x, y) == pytest.approx((0.0, 0.0))
    assert rid == "1"


# ---------------------------------------------------------------------------
# Issue 2: check_dem_full_coverage.py must sample paramPoly3 (not skip it)
# ---------------------------------------------------------------------------

from ultimate_pipeline.quality.check_dem_full_coverage import check_dem_full_coverage


def _parampoly3_road_xodr(tmp_path: Path, name: str) -> str:
    # x = 10*p, y = 5*p^2, p = s/length (normalized), length=10
    return _write(
        tmp_path,
        name,
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE>"
        '<road id="1" length="10.0" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10.0">'
        '<paramPoly3 aU="0" bU="10" cU="0" dU="0" '
        'aV="0" bV="0" cV="5" dV="0" pRange="normalized"/>'
        "</geometry></planView>"
        "</road>"
        "</OpenDRIVE>",
    )


def _flat_dem_tif(tmp_path: Path, name: str = "dem.tif") -> str:
    import rasterio
    from rasterio.transform import from_origin
    import numpy as np

    path = tmp_path / name
    data = np.full((10, 10), 100.0, dtype="float32")
    transform = from_origin(0, 10, 1, 1)
    with rasterio.open(
        str(path), "w", driver="GTiff", height=10, width=10, count=1,
        dtype="float32", transform=transform, nodata=-9999.0,
    ) as dst:
        dst.write(data, 1)
    return str(path)


def test_check_dem_full_coverage_samples_parampoly3_instead_of_skipping(tmp_path: Path) -> None:
    """Before the fix, check_dem_full_coverage only recognized line/arc
    primitives -- a paramPoly3-only road produced prim=None -> pts=[] ->
    ZERO samples, silently passing coverage checks with no real evidence.
    After the fix it must produce real samples that trace the true
    parametric curve."""
    xodr = _parampoly3_road_xodr(tmp_path, "pp3.xodr")
    dem = _flat_dem_tif(tmp_path)
    out_json = tmp_path / "pp3_report.json"

    captured: List[Tuple[float, float]] = []

    def capturing_sampler(x: float, y: float):
        captured.append((x, y))
        return (100.0, True)

    report = check_dem_full_coverage(
        xodr_path=xodr, dem_tif_path=dem, out_json=str(out_json),
        step_m=2.0, threshold=0.6, sampler=capturing_sampler,
    )

    assert report["total_samples"] > 0, (
        "paramPoly3 geometry must not be silently skipped (0 samples)"
    )
    assert report["ok"] is True

    # Verify sampled points actually trace the parametric curve x=10p, y=5p^2
    # rather than being fabricated/degenerate (e.g. all at the origin).
    xs = [p[0] for p in captured]
    ys = [p[1] for p in captured]
    assert max(xs) == pytest.approx(10.0, abs=1e-6)
    assert max(ys) == pytest.approx(5.0, abs=1e-6)
    # A point partway along must satisfy y == 0.05 * x^2 (from y=5p^2, x=10p
    # => p=x/10 => y=5*(x/10)^2 = x^2/20 = 0.05*x^2).
    mid_x, mid_y = captured[len(captured) // 2]
    assert mid_y == pytest.approx(0.05 * mid_x * mid_x, abs=1e-3)


# ---------------------------------------------------------------------------
# Issue 3: rasterio unavailable must fail closed, not silently pass
# ---------------------------------------------------------------------------

from ultimate_pipeline.quality.check_dem_coverage import check_dem_coverage


def test_check_dem_coverage_rasterio_unavailable_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If rasterio cannot be imported, the gate must FAIL (ok=False,
    reason='rasterio_unavailable'), not silently report ok=True with just
    a warning (the old false-green behavior)."""
    xodr = _arc_road_xodr(tmp_path, "arc_rasterio.xodr")

    # Force `import rasterio` to raise ImportError even though it is
    # actually installed in this environment.
    monkeypatch.setitem(sys.modules, "rasterio", None)

    report = check_dem_coverage(xodr, str(tmp_path / "whatever.tif"), threshold=0.6)

    assert report["ok"] is False
    assert report["reason"] == "rasterio_unavailable"


# ---------------------------------------------------------------------------
# Issue 4: malformed attributes must not silently default to 0.0
# ---------------------------------------------------------------------------


def test_get_road_sample_points_malformed_length_skips_road_not_zero(tmp_path: Path) -> None:
    """A road with a malformed (non-numeric) length attribute must be
    skipped and reported via warnings, not silently treated as length=0.0
    (which would previously inject a bogus single sample at the road's raw
    geometry start coordinates regardless of validity)."""
    xodr = _write(
        tmp_path,
        "bad_length.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE>"
        '<road id="1" length="not-a-number" junction="-1">'
        '<planView><geometry s="0" x="5" y="5" hdg="0" length="10.0"><line/></geometry></planView>'
        "</road>"
        '<road id="2" length="10.0" junction="-1">'
        '<planView><geometry s="0" x="20" y="20" hdg="0" length="10.0"><line/></geometry></planView>'
        "</road>"
        "</OpenDRIVE>",
    )
    root = ET.parse(xodr).getroot()
    warnings: List[str] = []

    points = _get_road_sample_points(root, max_roads=50, samples_per_road=3, warnings=warnings)

    road_ids_sampled = {rid for (_x, _y, rid) in points}
    assert "1" not in road_ids_sampled, "malformed-length road must be skipped, not silently sampled"
    assert "2" in road_ids_sampled
    assert any("1" in w and "length" in w for w in warnings)


def test_get_road_sample_points_malformed_geometry_attribute_skips_point(tmp_path: Path) -> None:
    """A road whose geometry x/hdg attribute is malformed must not
    contribute a phantom (0, 0)-style fallback point."""
    xodr = _write(
        tmp_path,
        "bad_geom_attr.xodr",
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE>"
        '<road id="1" length="10.0" junction="-1">'
        '<planView><geometry s="0" x="not-a-number" y="5" hdg="0" length="10.0"><line/></geometry></planView>'
        "</road>"
        "</OpenDRIVE>",
    )
    root = ET.parse(xodr).getroot()
    warnings: List[str] = []

    points = _get_road_sample_points(root, max_roads=50, samples_per_road=1, warnings=warnings)

    assert points == [], "a road whose only geometry has a malformed x must yield no fabricated point"
    assert any("1" in w for w in warnings)


# ---------------------------------------------------------------------------
# Issue 5: ElevationImporter endpoint must use canonical curve, not straight line
# ---------------------------------------------------------------------------

from ultimate_pipeline.enrichment.elevation_importer import ElevationImporter


def test_apply_dem_linear_grade_uses_canonical_arc_endpoint(tmp_path: Path) -> None:
    """On a curved (arc) road, the linear-grade endpoint sample must be
    taken at the TRUE curved endpoint position, not the straight-line
    extrapolation from the start heading. We prove this by using a
    position-dependent elevation sampler (z = 0.1 * x) -- if the endpoint
    x-coordinate is wrong (straight-line approx), the resulting slope
    (b coefficient) will be measurably different from the value computed
    from the true arc endpoint."""
    xodr = _arc_road_xodr(tmp_path, "arc_grade.xodr")
    root = ET.parse(xodr).getroot()

    def position_dependent_sampler(x: float, y: float):
        return (0.1 * x, True)

    qc = ElevationImporter.apply_dem(
        root, position_dependent_sampler, linear_grade=True, collect_qc=True
    )

    assert "1" in qc.get("linear_grade_road_ids", []), f"expected linear grade applied; qc={qc}"

    road = root.find("./road[@id='1']")
    elevation = road.find("./elevationProfile/elevation")
    assert elevation is not None
    b_coeff = float(elevation.get("b"))

    true_end_x, _true_end_y = _arc_expected_xy(LENGTH)
    z0 = 0.1 * 0.0  # start x is 0
    z_end_true = 0.1 * true_end_x
    expected_b = (z_end_true - z0) / LENGTH

    wrong_end_x, _ = _straight_line_approx_xy(LENGTH)
    z_end_wrong = 0.1 * wrong_end_x
    wrong_b = (z_end_wrong - z0) / LENGTH

    assert b_coeff == pytest.approx(expected_b, abs=1e-3)
    # Make sure this fixture actually distinguishes the two behaviors.
    assert abs(expected_b - wrong_b) > 1e-3


# ---------------------------------------------------------------------------
# Issue 6: ElevationGap._sample_geometry_points delegates to canonical kernel
# AND correctly re-applies the header offset (regression for a bug found
# while completing this fix: the offset was computed but never added back
# onto pose_at_s()'s result).
# ---------------------------------------------------------------------------

from ultimate_pipeline.domain_gap.elevation_gap import _sample_geometry_points, ElevationGap


def test_sample_geometry_points_arc_matches_canonical_curve(tmp_path: Path) -> None:
    geom = ET.Element("geometry", s="0.0", x="0", y="0", hdg="0", length=str(LENGTH))
    ET.SubElement(geom, "arc", curvature=str(K))

    points = _sample_geometry_points(geom, offset_x=0.0, offset_y=0.0)

    assert len(points) == 3
    for (x, y), s in zip(points, (0.0, LENGTH / 2.0, LENGTH)):
        expected = _arc_expected_xy(s)
        assert x == pytest.approx(expected[0], abs=1e-6)
        assert y == pytest.approx(expected[1], abs=1e-6)


def test_sample_geometry_points_applies_header_offset(tmp_path: Path) -> None:
    """Regression: pose_at_s() evaluates in the geometry's own offset-less
    frame; the header offset must be added back on. Before the fix this
    function silently dropped the offset in the (normal, non-exception)
    canonical-evaluator path."""
    geom = ET.Element("geometry", s="0.0", x="0", y="0", hdg="0", length="20.0")
    ET.SubElement(geom, "line")

    points = _sample_geometry_points(geom, offset_x=1000.0, offset_y=2000.0)

    assert points[0] == pytest.approx((1000.0, 2000.0))
    assert points[-1] == pytest.approx((1020.0, 2000.0))


def test_elevation_gap_end_to_end_matches_with_header_offset(tmp_path: Path) -> None:
    """End-to-end regression for the same bug via the public API: two
    roads that are the SAME physical road (one with an unapplied header
    offset) must match once the offset is correctly re-applied during
    sampling."""
    def write(path, x0, y0, offset_x=0.0, offset_y=0.0, elevation_a=0.0):
        root = ET.Element("OpenDRIVE")
        header = ET.SubElement(root, "header", revMajor="1", revMinor="6", name="t")
        ET.SubElement(header, "offset", x=str(offset_x), y=str(offset_y), z="0.0", hdg="0.0")
        road = ET.SubElement(root, "road", id="1", length="20.0", junction="-1")
        plan = ET.SubElement(road, "planView")
        geom = ET.SubElement(plan, "geometry", s="0.0", x=str(x0), y=str(y0), hdg="0.0", length="20.0")
        ET.SubElement(geom, "line")
        profile = ET.SubElement(road, "elevationProfile")
        ET.SubElement(profile, "elevation", s="0.0", a=str(elevation_a), b="0.0", c="0.0", d="0.0")
        ET.ElementTree(root).write(str(path), encoding="utf-8", xml_declaration=True)
        return str(path)

    manual = write(tmp_path / "manual.xodr", 1000.0, 2000.0, elevation_a=1.0)
    auto = write(tmp_path / "auto.xodr", 0.0, 0.0, offset_x=1000.0, offset_y=2000.0, elevation_a=2.0)

    result = ElevationGap.compute(manual, auto)

    assert result["disabled"] is False
    assert result["matched_count"] == 1
    assert result["mean_delta_m"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Issue 7: dem_provenance.py must verify declared CRS/bounds against the
# actual raster, not just record both side by side unchecked.
# ---------------------------------------------------------------------------

from ultimate_pipeline.dem.dem_provenance import (
    record_dem_provenance,
    verify_dem_provenance_against_raster,
)


def _real_dem_tif(tmp_path: Path, name: str = "real.tif"):
    import rasterio
    from rasterio.transform import from_origin
    import numpy as np
    from pyproj import CRS as _PyprojCRS

    path = tmp_path / name
    data = np.full((10, 10), 50.0, dtype="float32")
    transform = from_origin(500000, 5400000, 1, 1)  # UTM-like origin
    # NOTE: pass a WKT (resolved via pyproj) rather than the bare "EPSG:32632"
    # string -- this venv's rasterio/GDAL EPSG database lookup is broken
    # (documented: proj.db version mismatch between the GDAL/rasterio build
    # and the installed pyproj; pyproj's own lookups work fine and are what
    # dem_provenance.py's CRS comparison actually uses).
    wkt = _PyprojCRS.from_epsg(32632).to_wkt()
    with rasterio.open(
        str(path), "w", driver="GTiff", height=10, width=10, count=1,
        dtype="float32", crs=wkt, transform=transform, nodata=-9999.0,
    ) as dst:
        dst.write(data, 1)
    return str(path)


def test_record_dem_provenance_extra_field_does_not_crash(tmp_path: Path) -> None:
    """Regression: record_dem_provenance/DEMProvenance previously crashed
    with a TypeError (unexpected keyword argument 'extra') and separately
    had an IndentationError making the whole module unimportable."""
    dem = tmp_path / "dem.tif"
    dem.write_bytes(b"DEMDATA" * 64)

    rec = record_dem_provenance(str(dem), crs="EPSG:32632", extra={"note": "x"})

    assert rec.extra == {"note": "x"}
    d = rec.to_dict()
    assert d["extra"] == {"note": "x"}


def test_record_dem_provenance_verify_against_raster_detects_true_crs_bounds(tmp_path: Path) -> None:
    """When declared metadata matches the real raster, verify_against_raster
    must record an empty mismatch list (verified clean), not skip the check."""
    dem = _real_dem_tif(tmp_path)

    rec = record_dem_provenance(
        dem,
        crs="EPSG:32632",
        bounds={"left": 500000.0, "bottom": 5399990.0, "right": 500010.0, "top": 5400000.0},
        no_data=-9999.0,
        verify_against_raster=True,
    )

    assert rec._provenance_mismatches == []


def test_record_dem_provenance_verify_against_raster_flags_wrong_declared_crs(tmp_path: Path) -> None:
    """A declared CRS that disagrees with the actual raster CRS must be
    flagged as a mismatch, not silently accepted."""
    dem = _real_dem_tif(tmp_path)

    rec = record_dem_provenance(
        dem,
        crs="EPSG:4326",  # WRONG: the raster is actually EPSG:32632
        verify_against_raster=True,
    )

    assert rec._provenance_mismatches
    assert any("crs" in m for m in rec._provenance_mismatches)


def test_verify_dem_provenance_against_raster_standalone_detects_bounds_drift(tmp_path: Path) -> None:
    """Standalone post-hoc verification API: given a saved record whose
    declared bounds no longer match the file on disk, it must fail closed."""
    dem = _real_dem_tif(tmp_path)
    rec = record_dem_provenance(
        dem,
        crs="EPSG:32632",
        bounds={"left": 0.0, "bottom": 0.0, "right": 1.0, "top": 1.0},  # WRONG bounds
    )

    result = verify_dem_provenance_against_raster(rec)

    assert result["ok"] is False
    assert result["reason"] == "provenance_mismatch"
    assert any("bounds" in m for m in result["mismatches"])


def test_verify_dem_provenance_against_raster_rasterio_unavailable_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dem = tmp_path / "dem.tif"
    dem.write_bytes(b"DEMDATA")
    rec = record_dem_provenance(str(dem), crs="EPSG:32632")

    monkeypatch.setitem(sys.modules, "rasterio", None)

    result = verify_dem_provenance_against_raster(rec)

    assert result["ok"] is False
    assert result["reason"] == "rasterio_unavailable"


# ---------------------------------------------------------------------------
# Issue 8: vertical datum truth is honestly reported as unverified when it
# cannot actually be derived from the raster (the common case), rather than
# silently implying it was checked.
# ---------------------------------------------------------------------------


def test_record_dem_provenance_vertical_datum_source_reports_unverified_for_plain_crs(tmp_path: Path) -> None:
    """A plain (non-compound) CRS -- the overwhelmingly common case for real
    DEM sources -- cannot expose a vertical datum on its own. The record
    must say so explicitly (vertical_datum_source == 'declared_unverified')
    rather than silently treating the caller-declared string as verified
    ground truth."""
    dem = _real_dem_tif(tmp_path)

    rec = record_dem_provenance(
        dem,
        crs="EPSG:32632",
        vertical_datum="EGM2008 (Copernicus DEM geoid-referenced heights)",
        verify_against_raster=True,
    )

    assert rec._vertical_datum_source == "declared_unverified"
    assert rec.vertical_datum == "EGM2008 (Copernicus DEM geoid-referenced heights)"
