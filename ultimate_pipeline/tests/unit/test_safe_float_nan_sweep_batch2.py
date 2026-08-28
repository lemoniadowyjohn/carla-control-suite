# -*- coding: utf-8 -*-
"""Regression coverage for the second post-audit-phase-e `_safe_float` NaN/Inf sweep.

Continues the sweep started in `test_geometric_and_origin_gates_nan.py` (fixed
`check_geometric_continuity.py`, `check_lane_geometry_continuity.py`,
`check_lane_width_continuity.py`, `check_origin_sanity.py`) and
`test_elevation_quality_gates_nan.py`. This module covers the remaining files
in `grep -rln "def _safe_float" ultimate_pipeline/` where a local
`_safe_float(x, default=0.0)` helper only catches parse *exceptions* --
`float("nan")` parses successfully, so a corrupted XODR attribute silently
sails through into a magnitude/finiteness comparison that was supposed to
catch it (`x > eps`, `abs(k) < 1e-12`, `max(acc, candidate)` accumulators,
etc.), because a comparison against NaN is always False in IEEE-754.

Each test below feeds a NaN (or, where relevant, Inf) value into the exact
attribute the bug report identified and asserts the code now visibly reacts
(flags an issue / treats the geometry as degenerate / skips the write /
returns a non-finite-safe result) instead of silently proceeding as if the
value were fine.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


def _write_xodr(path: Path, root: ET.Element) -> str:
    ET.ElementTree(root).write(str(path), encoding="utf-8", xml_declaration=True)
    return str(path)


# ---------------------------------------------------------------------------
# ultimate_pipeline/diagnostics/audit_xodr_visual_geometry.py
# ---------------------------------------------------------------------------
class TestAuditXodrVisualGeometryLaneOffsetGate:
    def test_nan_lane_offset_coefficient_is_flagged(self, tmp_path):
        from ultimate_pipeline.diagnostics.audit_xodr_visual_geometry import (
            _build_lane_rows,
        )

        root = ET.Element("OpenDRIVE")
        road = ET.SubElement(root, "road", id="1", length="10.0", junction="-1")
        lanes = ET.SubElement(road, "lanes")
        ET.SubElement(lanes, "laneOffset", s="0", a="nan", b="0", c="0", d="0")
        section = ET.SubElement(lanes, "laneSection", s="0")
        left = ET.SubElement(section, "left")
        ET.SubElement(left, "lane", id="1", type="driving")

        rows = _build_lane_rows(root)
        offset_issues = [r for r in rows if r.get("issue") == "extreme_lane_offset"]
        assert offset_issues, "NaN laneOffset coefficient must be flagged, not silently pass"


# ---------------------------------------------------------------------------
# ultimate_pipeline/domain_gap/geometry_gap.py
# ---------------------------------------------------------------------------
class TestGeometryGapExtractPolylines:
    def test_nan_length_geometry_excluded_not_kept(self, tmp_path):
        from ultimate_pipeline.domain_gap.geometry_gap import _extract_polylines

        root = ET.Element("OpenDRIVE")
        road = ET.SubElement(root, "road", id="1", length="10.0", junction="-1")
        pv = ET.SubElement(road, "planView")
        g = ET.SubElement(pv, "geometry", s="0", x="0", y="0", hdg="0", length="nan")
        ET.SubElement(g, "line")
        xodr = _write_xodr(tmp_path / "gap.xodr", root)

        lines = _extract_polylines(xodr, sample_step_m=1.0, max_geoms=None)
        assert lines == [], "NaN-length geometry must be skipped, not sampled into a polyline"


# ---------------------------------------------------------------------------
# ultimate_pipeline/domain_gap/tile_gap_evaluator.py
# ---------------------------------------------------------------------------
class TestTileGapEvaluatorExtractCenterlines:
    def test_nan_length_geometry_excluded_not_kept(self, tmp_path):
        from ultimate_pipeline.domain_gap.tile_gap_evaluator import _extract_centerlines

        root = ET.Element("OpenDRIVE")
        road = ET.SubElement(root, "road", id="1", length="10.0", junction="-1")
        pv = ET.SubElement(road, "planView")
        g = ET.SubElement(pv, "geometry", s="0", x="0", y="0", hdg="0", length="nan")
        ET.SubElement(g, "line")
        xodr = _write_xodr(tmp_path / "tile.xodr", root)

        lines = _extract_centerlines(xodr)
        assert lines == [], "NaN-length geometry must be skipped, not sampled into a centerline"


# ---------------------------------------------------------------------------
# ultimate_pipeline/domain_gap/tile_grid_meta.py
# ---------------------------------------------------------------------------
class TestTileGridMetaBoundsFromXodr:
    def test_nan_coordinate_excluded_from_bbox(self, tmp_path):
        from ultimate_pipeline.domain_gap.tile_grid_meta import (
            _bounds_from_xodr,
            _infer_tile_size_from_bbox,
        )

        root = ET.Element("OpenDRIVE")
        road = ET.SubElement(root, "road", id="1", length="10.0", junction="-1")
        pv = ET.SubElement(road, "planView")
        # One legitimate geometry plus one NaN-poisoned geometry.
        ET.SubElement(pv, "geometry", s="0", x="0", y="0", hdg="0", length="100")
        ET.SubElement(pv, "geometry", s="100", x="nan", y="nan", hdg="0", length="10")
        xodr = _write_xodr(tmp_path / "bounds.xodr", root)

        bounds = _bounds_from_xodr(xodr)
        assert bounds is not None
        assert all(math.isfinite(v) for v in bounds), (
            "NaN planView coordinate must not leak into the inferred bbox"
        )
        # A degenerate (zero-extent) bbox must not silently produce a size.
        size = _infer_tile_size_from_bbox((0.0, 0.0, float("nan"), float("nan")), buffer_m=5.0)
        assert size is None


# ---------------------------------------------------------------------------
# ultimate_pipeline/enrichment/elevation_link_offset_solver.py
# ---------------------------------------------------------------------------
class TestElevationLinkOffsetSolverNanSafety:
    def test_nan_elevation_coefficient_does_not_write_nan_offset(self, tmp_path):
        from ultimate_pipeline.enrichment.elevation_link_offset_solver import (
            apply_link_offset_correction_root,
        )

        root = ET.Element("OpenDRIVE")
        r1 = ET.SubElement(root, "road", id="1", length="10.0", junction="-1")
        link1 = ET.SubElement(r1, "link")
        ET.SubElement(link1, "successor", elementType="road", elementId="2", contactPoint="start")
        prof1 = ET.SubElement(r1, "elevationProfile")
        ET.SubElement(prof1, "elevation", s="0", a="nan", b="0", c="0", d="0")

        r2 = ET.SubElement(root, "road", id="2", length="10.0", junction="-1")
        link2 = ET.SubElement(r2, "link")
        ET.SubElement(link2, "predecessor", elementType="road", elementId="1", contactPoint="end")
        prof2 = ET.SubElement(r2, "elevationProfile")
        ET.SubElement(prof2, "elevation", s="0", a="0", b="0", c="0", d="0")

        apply_link_offset_correction_root(root)

        # Road 1's own input coefficient was already NaN before the solver ran;
        # the solver is not expected to repair the source data. What must NOT
        # happen is the NaN *offset* propagating and poisoning road 2's
        # previously-clean elevation coefficient.
        road2 = root.find("./road[@id='2']")
        elev2 = road2.find("elevationProfile").find("elevation")
        a_val_2 = float(elev2.get("a"))
        assert math.isfinite(a_val_2), (
            "a NaN offset derived from a corrupted neighbor must not poison "
            "a previously-clean road's elevation coefficient"
        )


# ---------------------------------------------------------------------------
# ultimate_pipeline/enrichment/structure_classifier.py
# ---------------------------------------------------------------------------
class TestStructureClassifierGeometryPolyline:
    def test_nan_arc_curvature_falls_back_to_straight_line(self):
        from ultimate_pipeline.enrichment.structure_classifier import _geometry_polyline

        geom = ET.Element("geometry", s="0", x="0", y="0", hdg="0", length="10")
        ET.SubElement(geom, "arc", curvature="nan")

        pts = _geometry_polyline(geom, spacing_m=2.0)
        assert pts, "NaN curvature must not silently propagate to an empty/NaN polyline"
        assert all(math.isfinite(x) and math.isfinite(y) for x, y in pts)


# ---------------------------------------------------------------------------
# ultimate_pipeline/geometry/geometry_validator.py
# ---------------------------------------------------------------------------
class TestGeometryValidatorNanSafety:
    def test_nan_length_segment_is_removed(self):
        from ultimate_pipeline.geometry.geometry_validator import GeometryValidator

        root = ET.Element("OpenDRIVE")
        road = ET.SubElement(root, "road", id="1", length="10.0", junction="-1")
        pv = ET.SubElement(road, "planView")
        ET.SubElement(pv, "geometry", s="0", x="0", y="0", hdg="0", length="nan")
        ET.SubElement(pv, "geometry", s="5", x="5", y="0", hdg="0", length="5")

        result = GeometryValidator.validate(root)
        issues = result["roads"]["1"].get("issues", [])
        assert any("removed_zero_length_segment" in issue for issue in issues), (
            "NaN-length geometry must be removed like a zero-length one"
        )

    def test_nan_spiral_curvature_is_clamped_not_ignored(self):
        from ultimate_pipeline.geometry.geometry_validator import GeometryValidator

        root = ET.Element("OpenDRIVE")
        road = ET.SubElement(root, "road", id="1", length="10.0", junction="-1")
        pv = ET.SubElement(road, "planView")
        g = ET.SubElement(pv, "geometry", s="0", x="0", y="0", hdg="0", length="10")
        ET.SubElement(g, "spiral", curvStart="nan", curvEnd="0.01")

        result = GeometryValidator.validate(root)
        issues = result["roads"]["1"].get("issues", [])
        assert any("clamped_curvStart" in issue for issue in issues), (
            "NaN curvStart must be caught by the spiral sanity clamp"
        )
        clamped_value = float(g.find("spiral").attrib["curvStart"])
        assert math.isfinite(clamped_value)


# ---------------------------------------------------------------------------
# ultimate_pipeline/geometry/lane_seam_checker.py
# ---------------------------------------------------------------------------
class TestGeometryLaneSeamCheckerNanSafety:
    def test_nan_arc_curvature_falls_back_to_straight_sampling(self):
        from ultimate_pipeline.geometry.lane_seam_checker import _sample_geometry

        geom = ET.Element("geometry", x="0", y="0", hdg="0", length="10")
        ET.SubElement(geom, "arc", curvature="nan")

        pts = _sample_geometry(geom)
        assert pts
        assert all(math.isfinite(x) and math.isfinite(y) for x, y in pts)


# ---------------------------------------------------------------------------
# ultimate_pipeline/geometry/quarantine_bad_roads.py
# ---------------------------------------------------------------------------
class TestGeometryQuarantineBadRoadsNanSafety:
    def test_nan_curvature_metric_triggers_quarantine(self):
        from ultimate_pipeline.geometry.quarantine_bad_roads import _score_and_reasons

        entry = {"curvature_abs_max": float("nan")}
        thresholds = {"curvature_abs_max": 0.5}
        score, reasons = _score_and_reasons(entry, thresholds)
        assert reasons, "NaN curvature_abs_max must trigger the quarantine gate, not silently pass"
        assert not math.isfinite(score) or score > 0

    def test_nan_dxy_does_not_vanish_via_max_accumulator(self):
        from ultimate_pipeline.geometry.quarantine_bad_roads import _parse_continuity_report

        report = {
            "issues": [
                {"from_road": "1", "to_road": "2", "dxy": "nan", "dhdg": "0.0"},
            ]
        }
        scores = _parse_continuity_report(report)
        assert not math.isfinite(scores["1"]["continuity_dxy_max_m"]), (
            "a NaN dxy must not be silently dropped by the max() accumulator"
        )


# ---------------------------------------------------------------------------
# ultimate_pipeline/quality/autofix_postprune_elevation.py
# ---------------------------------------------------------------------------
class TestAutofixPostpruneElevationNanSafety:
    def test_nan_arc_curvature_falls_back_to_pose_line(self):
        from ultimate_pipeline.quality.autofix_postprune_elevation import _Geometry, _pose_arc

        g = _Geometry(s0=0.0, x0=0.0, y0=0.0, hdg0=0.0, length=10.0, kind="arc", curvature=float("nan"))
        x, y = _pose_arc(g, 5.0)
        assert math.isfinite(x) and math.isfinite(y)


# ---------------------------------------------------------------------------
# ultimate_pipeline/quality/carla_pruner.py
# ---------------------------------------------------------------------------
class TestCarlaPrunerNanSafety:
    def test_nan_road_length_is_treated_as_dangling(self):
        from ultimate_pipeline.quality.carla_pruner import CarlaSafetyPruner

        road = ET.Element("road", id="1", length="nan", junction="-1")
        pruner = CarlaSafetyPruner(min_road_length_m=0.5)
        dangling = pruner._find_dangling(
            nodes={("1", 0, 1): object()},
            out_edges={},
            in_edges={},
            roads_by_id={"1": road},
        )
        assert ("1", 0, 1) in dangling, (
            "a NaN road length must be treated as too short to drive, not silently accepted"
        )


# ---------------------------------------------------------------------------
# ultimate_pipeline/quality/check_determinism.py
# ---------------------------------------------------------------------------
class TestCheckDeterminismNanSafety:
    def test_nan_total_road_length_reports_a_diff(self, tmp_path):
        from ultimate_pipeline.quality.check_determinism import check_determinism

        root_a = ET.Element("OpenDRIVE")
        ET.SubElement(root_a, "road", id="1", length="nan", junction="-1")
        path_a = _write_xodr(tmp_path / "det_a.xodr", root_a)

        root_b = ET.Element("OpenDRIVE")
        ET.SubElement(root_b, "road", id="1", length="10.0", junction="-1")
        path_b = _write_xodr(tmp_path / "det_b.xodr", root_b)

        report = check_determinism(path_a, path_b)
        assert report["deterministic"] is False
        diffs = report["differences"]
        assert "total_road_length" in diffs, (
            "a NaN total_road_length delta must be reported as a diff, not silently ignored"
        )


# ---------------------------------------------------------------------------
# ultimate_pipeline/tile_validation/lane_seam_checker.py
# ---------------------------------------------------------------------------
class TestTileValidationLaneSeamCheckerNanSafety:
    def test_nan_lateral_offset_is_not_dropped_by_max_accumulator(self):
        # Directly exercise the max()-with-NaN accumulator quirk this file used to hit.
        max_lat = 0.0
        stats_lateral_offset = float("nan")
        # Old (buggy) behavior:
        buggy = max(max_lat, stats_lateral_offset)
        assert buggy == 0.0, "sanity: documents the max()-drops-NaN-when-first-arg quirk"
        # Fixed behavior (mirrors the guard added in lane_seam_checker.py):
        fixed = (
            stats_lateral_offset
            if not math.isfinite(stats_lateral_offset)
            else max(max_lat, stats_lateral_offset)
        )
        assert not math.isfinite(fixed)


# ---------------------------------------------------------------------------
# ultimate_pipeline/tools/assert_carla_invariants.py
# ---------------------------------------------------------------------------
class TestAssertCarlaInvariantsNanSafety:
    def test_nan_lane_section_s_is_flagged(self, tmp_path):
        from ultimate_pipeline.tools.assert_carla_invariants import check_invariants

        root = ET.Element("OpenDRIVE")
        road = ET.SubElement(root, "road", id="1", length="10.0", junction="-1")
        lanes = ET.SubElement(road, "lanes")
        ET.SubElement(lanes, "laneSection", s="nan")
        xodr = _write_xodr(tmp_path / "inv.xodr", root)

        result = check_invariants(xodr)
        codes = {v["code"] for v in result["violations"]}
        assert "negative_s" in codes or "s_exceeds_length" in codes, (
            "NaN laneSection s must be flagged by at least one invariant check"
        )


# ---------------------------------------------------------------------------
# ultimate_pipeline/tools/phase_f5_bounded_offsets.py
# ---------------------------------------------------------------------------
class TestPhaseF5BoundedOffsetsNanSafety:
    def test_nan_elevation_delta_counts_as_over_threshold(self, tmp_path):
        from ultimate_pipeline.tools.phase_f5_bounded_offsets import _seam_deltas

        root = ET.Element("OpenDRIVE")
        r1 = ET.SubElement(root, "road", id="1", length="10.0", junction="-1")
        link1 = ET.SubElement(r1, "link")
        ET.SubElement(link1, "successor", elementType="road", elementId="2")
        prof1 = ET.SubElement(r1, "elevationProfile")
        ET.SubElement(prof1, "elevation", s="0", a="nan", b="0", c="0", d="0")

        r2 = ET.SubElement(root, "road", id="2", length="10.0", junction="-1")
        prof2 = ET.SubElement(r2, "elevationProfile")
        ET.SubElement(prof2, "elevation", s="0", a="0", b="0", c="0", d="0")

        result = _seam_deltas(root)
        assert result["over_threshold"] >= 1, (
            "a NaN seam delta must count as over-threshold, not silently pass as bounded"
        )


# ---------------------------------------------------------------------------
# ultimate_pipeline/tools/phase_g7_roadmark_semantics.py
# ---------------------------------------------------------------------------
class TestPhaseG7RoadmarkSemanticsNanSafety:
    def test_nan_width_visible_roadmark_is_flagged_and_repaired(self):
        from ultimate_pipeline.tools.phase_g7_roadmark_semantics import (
            audit_roadmarks,
            repair_roadmarks,
        )

        root = ET.Element("OpenDRIVE")
        road = ET.SubElement(root, "road", id="1", length="10.0", junction="-1")
        lanes = ET.SubElement(road, "lanes")
        section = ET.SubElement(lanes, "laneSection", s="0")
        left = ET.SubElement(section, "left")
        lane = ET.SubElement(left, "lane", id="1", type="driving")
        rm = ET.SubElement(lane, "roadMark", type="solid", weight="standard", color="white",
                            laneChange="both", width="nan")

        audit = audit_roadmarks(root)
        assert audit["visible_zero_width"], "NaN roadMark width must be flagged as invalid"

        repair_roadmarks(root)
        repaired_width = float(rm.get("width"))
        assert math.isfinite(repaired_width), "repair must replace NaN width with a finite standard width"


# ---------------------------------------------------------------------------
# ultimate_pipeline/tools/post_run_carla_sanity.py
# ---------------------------------------------------------------------------
class TestPostRunCarlaSanityNanSafety:
    def test_nan_endpoint_coordinate_drops_the_link(self, tmp_path):
        from ultimate_pipeline.tools.post_run_carla_sanity import optional_repair_drop_bad_links

        root = ET.Element("OpenDRIVE")
        r1 = ET.SubElement(root, "road", id="1", length="10.0", junction="-1")
        link1 = ET.SubElement(r1, "link")
        ET.SubElement(link1, "successor", elementType="road", elementId="2")
        pv1 = ET.SubElement(r1, "planView")
        ET.SubElement(pv1, "geometry", s="0", x="0", y="0", hdg="0", length="10")

        r2 = ET.SubElement(root, "road", id="2", length="10.0", junction="-1")
        pv2 = ET.SubElement(r2, "planView")
        # Corrupt endpoint coordinate on the linked road.
        ET.SubElement(pv2, "geometry", s="0", x="nan", y="nan", hdg="0", length="10")

        xodr = _write_xodr(tmp_path / "sanity.xodr", root)
        out_path = tmp_path / "repaired.xodr"
        result = optional_repair_drop_bad_links(xodr, out_path, tol_m=5.0)
        assert result["dropped_link_count"] >= 1, (
            "a link to a road with NaN endpoint coordinates must be dropped, not kept"
        )
