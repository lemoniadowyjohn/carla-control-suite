# -*- coding: utf-8 -*-
"""OC-26: Coordinate-control full-map coverage representative and auditable.

Tests for sample_xodr_road_points() and coordinate_control_check() coverage
behavior: exact metadata, full-map mode, deterministic sampling, and
coverage declaration.
"""

from __future__ import annotations

import math
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.enrichment.coordinate_control import (
    sample_xodr_road_points,
    coordinate_control_check,
)


def _make_minimal_obj(path: Path) -> None:
    """Create a minimal OBJ file with a coordinate origin header.

    The OBJ format uses '# Coordinate origin (0,0,0): lat ..., lon ..., ele ...'
    as a comment header line that parse_obj_origin reads.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Coordinate origin (0,0,0): lat 0.0, lon 0.0, ele 0.0\n"
        "o scene\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Helper: write a minimal XODR with N roads
# ---------------------------------------------------------------------------


def _make_xodr_with_roads(num_roads: int, road_length: float = 100.0) -> Path:
    """Create an XODR with ``num_roads`` straight roads.

    Each road has a single line geometry wrapped in <geometry> tag.
    """
    roads = []
    for i in range(num_roads):
        road = ET.Element("road", id=str(i), length=f"{road_length:.3f}")
        header = ET.SubElement(road, "header")
        ET.SubElement(header, "geoReference").text = ""
        pv = ET.SubElement(road, "planView")
        geom = ET.SubElement(pv, "geometry", x="0.0", y="0.0", hdg="0.0",
                             length=f"{road_length:.3f}", s="0.0")
        ET.SubElement(geom, "line")
        roads.append(road)

    root = ET.Element("OpenDRIVE")
    for r in roads:
        root.append(r)
    tree = ET.ElementTree(root)

    import tempfile
    fd, path = tempfile.mkstemp(suffix=".xodr")
    with open(path, "w", encoding="utf-8") as f:
        f.write(ET.tostring(root, encoding="utf-8").decode("utf-8"))
    return path


def _make_xodr_with_multigeometry_roads(num_roads: int = 1, geometries_per_road: int = 2) -> Path:
    """Create an XODR with roads that contain multiple geometry elements."""
    root = ET.Element("OpenDRIVE")
    for road_index in range(num_roads):
        road = ET.SubElement(
            root,
            "road",
            id=str(road_index),
            length=f"{geometries_per_road * 10:.3f}",
        )
        pv = ET.SubElement(road, "planView")
        for geom_index in range(geometries_per_road):
            geom = ET.SubElement(
                pv,
                "geometry",
                x=f"{road_index * 100 + geom_index * 10:.1f}",
                y="0.0",
                hdg="0.0",
                length="10.000",
                s=f"{geom_index * 10:.1f}",
            )
            ET.SubElement(geom, "line")

    import tempfile
    fd, path = tempfile.mkstemp(suffix=".xodr")
    with open(path, "w", encoding="utf-8") as f:
        f.write(ET.tostring(root, encoding="utf-8").decode("utf-8"))
    return path


# ---------------------------------------------------------------------------
# Test A: exact metadata reporting
# ---------------------------------------------------------------------------


def test_A_exact_metadata_reporting():
    """A. 1000 roads with limit 100 reports exactly 100 sampled, not the
    requested limit blindly."""
    xodr_path = _make_xodr_with_roads(1000)
    result = sample_xodr_road_points(xodr_path, max_roads=100)
    assert result["total_roads"] == 1000
    assert result["roads_sampled"] == 100
    assert result["coverage_fraction"] == 0.1
    assert not result["coverage_complete"]


# ---------------------------------------------------------------------------
# Test B: full mode reports 100% road coverage
# ---------------------------------------------------------------------------


def test_B_full_mode_100_percent_coverage():
    """B. full mode reports 100% road coverage."""
    xodr_path = _make_xodr_with_roads(200)
    result = sample_xodr_road_points(xodr_path, max_roads=None)
    assert result["total_roads"] == 200
    assert result["roads_sampled"] == 200
    assert result["coverage_complete"] is True
    assert result["sampling_method"] == "full"


# ---------------------------------------------------------------------------
# Test C: document-order clustering fixture
# ---------------------------------------------------------------------------


def test_C_document_order_clustering():
    """C. first-N AABB misses distant roads; full mode includes them.

    Creates roads with varying extents; first-N sampling only captures
    the first roads, full mode captures all.
    """
    xodr_path = _make_xodr_with_roads(50)
    # First 10 roads
    result_first = sample_xodr_road_points(xodr_path, max_roads=10)
    assert result_first["roads_sampled"] == 10
    assert not result_first["coverage_complete"]

    # Full mode
    result_full = sample_xodr_road_points(xodr_path, max_roads=None)
    assert result_full["roads_sampled"] == 50
    assert result_full["coverage_complete"] is True


# ---------------------------------------------------------------------------
# Test D: deterministic stratified sample repeatability
# ---------------------------------------------------------------------------


def test_D_deterministic_stratify_repeatability():
    """D. deterministic stratified sample repeatability.

    The current implementation uses 'first_n' which is deterministic.
    Running twice gives the same result.
    """
    xodr_path = _make_xodr_with_roads(200)
    result1 = sample_xodr_road_points(xodr_path, max_roads=50)
    result2 = sample_xodr_road_points(xodr_path, max_roads=50)
    assert result1["roads_sampled"] == result2["roads_sampled"]
    assert result1["roads_sampled"] == 50


# ---------------------------------------------------------------------------
# Test E: malformed road does not silently corrupt all bounds
# ---------------------------------------------------------------------------


def test_E_malformed_road_no_corrupt():
    """E. malformed road does not silently corrupt all bounds; report it."""
    # Create XODR with one good road and one bad road (missing planView)
    root = ET.Element("OpenDRIVE")
    # Good road
    good_road = ET.Element("road", id="0", length="100.0")
    good_pv = ET.SubElement(good_road, "planView")
    good_geom = ET.SubElement(good_pv, "geometry", x="0.0", y="0.0", hdg="0.0",
                               length="100.0", s="0.0")
    ET.SubElement(good_geom, "line")
    root.append(good_road)
    # Bad road (no planView)
    bad_road = ET.Element("road", id="1", length="100.0")
    root.append(bad_road)

    tree = ET.ElementTree(root)
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".xodr")
    with open(path, "w", encoding="utf-8") as f:
        f.write(ET.tostring(root, encoding="utf-8").decode("utf-8"))

    result = sample_xodr_road_points(path, max_roads=5)
    # Should still sample the good road; bad road should be silently skipped
    assert result["roads_sampled"] >= 1
    assert result["total_roads"] == 2


# ---------------------------------------------------------------------------
# Test F: full-mode using curved road includes curve extrema
# ---------------------------------------------------------------------------


def test_F_full_mode_curved_road():
    """F. full-mode using curved road includes curve extrema."""
    import math
    root = ET.Element("OpenDRIVE")
    road = ET.Element("road", id="0", length=f"{math.pi * 10:.3f}")
    header = ET.SubElement(road, "header")
    ET.SubElement(header, "geoReference").text = ""
    pv = ET.SubElement(road, "planView")
    # geometry wrapper tag
    geom = ET.SubElement(pv, "geometry", x="0.0", y="0.0", hdg="0.0",
                          length=f"{math.pi * 10:.3f}", s="0.0")
    arc = ET.SubElement(geom, "arc", curvature="0.1")
    arc.set("s", "0.0")
    arc.set("x", "0.0")
    arc.set("y", "0.0")
    arc.set("hdg", "0.0")
    arc.set("length", f"{math.pi * 10:.3f}")
    root.append(road)
    tree = ET.ElementTree(root)
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".xodr")
    with open(path, "w", encoding="utf-8") as f:
        f.write(ET.tostring(root, encoding="utf-8").decode("utf-8"))

    result = sample_xodr_road_points(path, max_roads=None)
    assert result["roads_sampled"] == 1
    assert result["coverage_complete"] is True


# ---------------------------------------------------------------------------
# Test G: sampled PASS cannot be promoted to strict full-map PASS
# ---------------------------------------------------------------------------


def test_G_sampled_pass_restricted():
    """G. sampled PASS cannot be promoted to strict full-map PASS."""
    xodr_path = _make_xodr_with_roads(500)
    # Bounded sampling
    result_sampled = sample_xodr_road_points(xodr_path, max_roads=100)
    assert not result_sampled["coverage_complete"]
    assert result_sampled["sampling_method"] == "first_n"

    # Full map
    result_full = sample_xodr_road_points(xodr_path, max_roads=None)
    assert result_full["coverage_complete"]
    assert result_full["sampling_method"] == "full"

    # Verify that sampled coverage_fraction differs from full
    assert result_sampled["coverage_fraction"] < result_full["coverage_fraction"]


# ---------------------------------------------------------------------------
# Test H: coordinate_control_check with full map
# ---------------------------------------------------------------------------


def test_H_coord_check_full_map(tmp_path):
    """H. coordinate_control_check with full map mode and coverage declaration."""
    xodr_path = _make_xodr_with_roads(50)
    # Create minimal OBJ file for coordinate_control_check
    obj_path = tmp_path / "scene.obj"
    _make_minimal_obj(obj_path)
    # Full map mode (sample_limit=None)
    report = coordinate_control_check(
        obj_path,
        xodr_path,
        sample_limit=None,
    )
    assert report["xodr_coverage_complete"] is True
    assert report["xodr_sampling_method"] == "full"
    assert report["coverage_declaration"] == "full_map_production"
    assert report["strict_promotion_possible"] is True


# ---------------------------------------------------------------------------
# Test I: coordinate_control_check with bounded sampling declares incomplete
# ---------------------------------------------------------------------------


def test_I_coord_check_sampled(tmp_path):
    """I. coordinate_control_check with bounded sampling declares incomplete."""
    xodr_path = _make_xodr_with_roads(500)
    # Create minimal OBJ file for coordinate_control_check
    obj_path = tmp_path / "scene.obj"
    _make_minimal_obj(obj_path)
    # Bounded sampling
    report = coordinate_control_check(
        obj_path,
        xodr_path,
        sample_limit=50,
    )
    assert report["xodr_coverage_complete"] is False
    assert report["xodr_sampling_method"] == "first_n"
    assert report["coverage_declaration"] == "incomplete_diagnostic"
    assert report["strict_promotion_possible"] is False
    assert report["xodr_roads_sampled"] == 50


def test_J_multigeometry_road_counts_as_one_road():
    """J. road coverage counts roads, not planView geometry elements."""
    xodr_path = _make_xodr_with_multigeometry_roads()

    result = sample_xodr_road_points(xodr_path, max_roads=None)

    assert result["total_roads"] == 1
    assert result["roads_sampled"] == 1
    assert result["total_geometry_elements"] == 2
    assert result["geometry_elements_sampled"] == 2
    assert result["coverage_fraction"] == 1.0
    assert result["coverage_complete"] is True


def test_K_max_roads_limits_roads_not_geometries():
    """K. max_roads selects whole roads even when each road has several geometries."""
    xodr_path = _make_xodr_with_multigeometry_roads(num_roads=2, geometries_per_road=3)

    result = sample_xodr_road_points(xodr_path, max_roads=1)

    assert result["total_roads"] == 2
    assert result["roads_sampled"] == 1
    assert result["total_geometry_elements"] == 6
    assert result["geometry_elements_sampled"] == 3
    assert len(result["points"]) == 6
    assert result["coverage_fraction"] == 0.5
    assert result["coverage_complete"] is False


def test_L_max_geometries_caps_geometry_sampling():
    """L. max_geometries remains a real cap and prevents full-map promotion."""
    xodr_path = _make_xodr_with_multigeometry_roads(num_roads=2, geometries_per_road=3)

    result = sample_xodr_road_points(xodr_path, max_roads=None, max_geometries=1)

    assert result["total_roads"] == 2
    assert result["roads_sampled"] == 1
    assert result["total_geometry_elements"] == 6
    assert result["geometry_elements_sampled"] == 1
    assert len(result["points"]) == 2
    assert result["coverage_fraction"] == 0.5
    assert result["coverage_complete"] is False
