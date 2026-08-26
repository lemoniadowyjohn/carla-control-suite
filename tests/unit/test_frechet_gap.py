"""Thesis future-work #14 (Fréchet / shape-sensitive distance metrics): the delivered
thesis computed discrete Fréchet distance once as a one-off supplement (median 126.80m,
mean 1,781.62m, p90 4,166.26m over 457 matched road pairs, 5m spacing, 50m correspondence
threshold, run_11 whole-network SE(2) alignment) -- see
submission/results/structural_gap_run11/frechet_distance_supplement.json. No script for it
was ever committed, and it was never revisited after delivery, using the OLD uncropped
whole-network methodology that C22/C23/C26 later found flawed.

This recomputes it against the CURRENT, correct methodology: local registration (crop auto
to the manual map's convex-hull footprint in the properly-transformed local CRS, via
ultimate_pipeline.domain_gap.local_registration -- no artificial SE(2) best-fit needed once
the CRS/offset handling is correct), road correspondence reused directly from
ultimate_pipeline.domain_gap.elevation_gap (_build_road_profiles / _match_roads, already
used and tested for the elevation-gap metric), and a fixed-arc-length resample + the
standard Eiter-Mannila discrete Fréchet DP recurrence.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.domain_gap.frechet_gap import (
    discrete_frechet_distance,
    resample_polyline_at_spacing,
    compute_frechet_gap,
)


# ---------------------------------------------------------------------------
# discrete_frechet_distance
# ---------------------------------------------------------------------------

def test_frechet_identical_curves_is_zero():
    curve = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 1.0)]
    assert discrete_frechet_distance(curve, curve) == pytest.approx(0.0, abs=1e-9)


def test_frechet_parallel_offset_lines_equals_the_offset():
    a = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)]
    b = [(0.0, 5.0), (1.0, 5.0), (2.0, 5.0), (3.0, 5.0)]
    assert discrete_frechet_distance(a, b) == pytest.approx(5.0, abs=1e-9)


def test_frechet_is_symmetric():
    a = [(0.0, 0.0), (2.0, 1.0), (4.0, 0.0)]
    b = [(0.0, 3.0), (2.0, 2.0), (4.0, 3.0)]
    assert discrete_frechet_distance(a, b) == pytest.approx(discrete_frechet_distance(b, a), abs=1e-9)


def test_frechet_detects_a_local_excursion_not_captured_by_endpoint_distance():
    # Endpoints coincide, but curve b bulges 10m away in the middle -- a metric that only
    # looked at endpoint/centroid distance would miss this; Fréchet must not.
    a = [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)]
    b = [(0.0, 0.0), (5.0, 10.0), (10.0, 0.0)]
    assert discrete_frechet_distance(a, b) == pytest.approx(10.0, abs=1e-9)


def test_frechet_single_point_curves_is_plain_distance():
    assert discrete_frechet_distance([(0.0, 0.0)], [(3.0, 4.0)]) == pytest.approx(5.0, abs=1e-9)


def test_frechet_raises_on_empty_curve():
    with pytest.raises(ValueError):
        discrete_frechet_distance([], [(0.0, 0.0)])


# ---------------------------------------------------------------------------
# resample_polyline_at_spacing
# ---------------------------------------------------------------------------

def test_resample_straight_line_at_fixed_spacing():
    points = [(0.0, 0.0), (10.0, 0.0)]
    resampled = resample_polyline_at_spacing(points, spacing_m=5.0)
    xs = [p[0] for p in resampled]
    assert xs[0] == pytest.approx(0.0, abs=1e-6)
    assert xs[-1] == pytest.approx(10.0, abs=1e-6)
    # consecutive spacing must be ~5m (last segment may be shorter, covering the remainder)
    for p, q in zip(resampled, resampled[1:-1]):
        pass
    diffs = [
        math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(resampled, resampled[1:])
    ]
    assert all(d <= 5.0 + 1e-6 for d in diffs)


def test_resample_preserves_total_length_on_a_straight_line():
    # A straight (single-segment) line has no interior corner, so fixed-spacing resampling
    # preserves its length exactly -- unlike a polyline with a kink (see the corner-cutting
    # test below), where resample points landing on either side of a corner instead of
    # exactly on it necessarily shorten the path (triangle inequality).
    points = [(0.0, 0.0), (15.0, 0.0)]
    resampled = resample_polyline_at_spacing(points, spacing_m=2.0)
    length = sum(
        math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(resampled, resampled[1:])
    )
    assert length == pytest.approx(15.0, abs=1e-9)


def test_resample_shortens_a_sharp_corner_by_at_most_the_spacing():
    # Documents the expected corner-cutting behavior: a fixed-spacing resample is not
    # required to land exactly on an original interior vertex, so a sharp corner's path
    # length can shrink slightly -- but never by more than roughly one spacing interval.
    points = [(0.0, 0.0), (3.0, 4.0), (3.0, 14.0)]  # original length = 5 + 10 = 15
    resampled = resample_polyline_at_spacing(points, spacing_m=2.0)
    length = sum(
        math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(resampled, resampled[1:])
    )
    assert length <= 15.0
    assert length == pytest.approx(15.0, abs=2.0)  # bounded, not unbounded, shrinkage


def test_resample_degenerate_zero_length_returns_single_point():
    resampled = resample_polyline_at_spacing([(1.0, 1.0), (1.0, 1.0)], spacing_m=5.0)
    assert resampled == [(1.0, 1.0)]


# ---------------------------------------------------------------------------
# compute_frechet_gap -- synthetic end-to-end
# ---------------------------------------------------------------------------

def _road(rid: str, x0: float, y0: float, length: float, hdg: float = 0.0) -> ET.Element:
    road = ET.Element("road", id=rid, length=str(length), junction="-1")
    plan = ET.SubElement(road, "planView")
    geom = ET.SubElement(plan, "geometry", s="0", x=str(x0), y=str(y0), hdg=str(hdg), length=str(length))
    ET.SubElement(geom, "line")
    return road


def _xodr(*roads: ET.Element) -> ET.Element:
    root = ET.Element("OpenDRIVE")
    header = ET.SubElement(root, "header")
    ET.SubElement(header, "offset", x="0.0", y="0.0", z="0.0", hdg="0.0")
    geo = ET.SubElement(header, "geoReference")
    geo.text = "+proj=tmerc +datum=WGS84 +units=m +no_defs"
    for road in roads:
        root.append(road)
    return root


def test_compute_frechet_gap_matches_a_single_road_pair_and_reports_offset(tmp_path):
    # Manual has the road under test (id=1, horizontal at y=0) plus a decoy anchor road
    # far away in y (id=2) purely so the manual footprint's bbox has real area (a
    # perfectly flat single road gives a zero-height bbox, which Shapely can't treat as a
    # containing polygon). The decoy has no auto counterpart within threshold, so it
    # contributes no match -- exactly 1 match is expected either way.
    manual_root = _xodr(
        _road("1", x0=0.0, y0=0.0, length=20.0),
        _road("2", x0=0.0, y0=100.0, length=20.0),
    )
    auto_root = _xodr(_road("101", x0=0.0, y0=3.0, length=20.0))

    manual_path = tmp_path / "manual.xodr"
    auto_path = tmp_path / "auto.xodr"
    ET.ElementTree(manual_root).write(str(manual_path), encoding="utf-8", xml_declaration=True)
    ET.ElementTree(auto_root).write(str(auto_path), encoding="utf-8", xml_declaration=True)

    result = compute_frechet_gap(
        str(auto_path), str(manual_path),
        spacing_m=5.0, match_threshold_m=50.0, footprint="bbox",
    )
    assert result["matched_pair_count"] == 1
    # Loose-ish tolerance: this now goes through a genuine CRS round-trip (local -> global ->
    # lon/lat -> manual CRS), not a pure Euclidean shortcut, so expect sub-mm/cm noise even
    # though auto and manual share the same proj4 string in this fixture.
    assert result["mean_m"] == pytest.approx(3.0, abs=1e-3)
    assert result["median_m"] == pytest.approx(3.0, abs=1e-3)


def test_compute_frechet_gap_reports_zero_matches_when_nothing_within_threshold(tmp_path):
    manual_root = _xodr(
        _road("1", x0=0.0, y0=0.0, length=20.0),
        _road("2", x0=0.0, y0=100.0, length=20.0),
    )
    auto_root = _xodr(_road("101", x0=0.0, y0=500.0, length=20.0))

    manual_path = tmp_path / "manual.xodr"
    auto_path = tmp_path / "auto.xodr"
    ET.ElementTree(manual_root).write(str(manual_path), encoding="utf-8", xml_declaration=True)
    ET.ElementTree(auto_root).write(str(auto_path), encoding="utf-8", xml_declaration=True)

    result = compute_frechet_gap(
        str(auto_path), str(manual_path),
        spacing_m=5.0, match_threshold_m=10.0, footprint="bbox",
    )
    assert result["matched_pair_count"] == 0
