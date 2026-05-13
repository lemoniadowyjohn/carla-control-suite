from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.domain_gap.domain_gap_aggregator import DomainGapAggregator
from ultimate_pipeline.domain_gap.elevation_gap import ElevationGap, _effective_header_offset_xy
from ultimate_pipeline.run_full_domain_gap import (
    _compute_supplementary_elevation_gap,
    _disabled_elevation_gap,
    _discover_elevation_dem_qc_path,
    _finalize_results,
)


def _write_line_elevation_xodr(
    path: Path,
    *,
    x0: float,
    y0: float,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    length: float = 20.0,
    elevation_a: float = 0.0,
) -> str:
    root = ET.Element("OpenDRIVE")
    header = ET.SubElement(root, "header", revMajor="1", revMinor="6", name="test")
    ET.SubElement(
        header,
        "offset",
        x=str(offset_x),
        y=str(offset_y),
        z="0.0",
        hdg="0.0",
    )
    road = ET.SubElement(root, "road", id="1", length=str(length), junction="-1")
    plan = ET.SubElement(road, "planView")
    geom = ET.SubElement(
        plan,
        "geometry",
        s="0.0",
        x=str(x0),
        y=str(y0),
        hdg="0.0",
        length=str(length),
    )
    ET.SubElement(geom, "line")
    profile = ET.SubElement(road, "elevationProfile")
    ET.SubElement(
        profile,
        "elevation",
        s="0.0",
        a=str(elevation_a),
        b="0.0",
        c="0.0",
        d="0.0",
    )
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return str(path)


def test_elevation_gap_matches_with_header_offset(tmp_path: Path) -> None:
    manual = _write_line_elevation_xodr(
        tmp_path / "manual.xodr",
        x0=1000.0,
        y0=2000.0,
        elevation_a=1.0,
    )
    auto = _write_line_elevation_xodr(
        tmp_path / "auto.xodr",
        x0=0.0,
        y0=0.0,
        offset_x=1000.0,
        offset_y=2000.0,
        elevation_a=2.0,
    )

    result = ElevationGap.compute(manual, auto)

    assert result["disabled"] is False
    assert result["supplementary"] is True
    assert result["primary_artifact_is_planar"] is True
    assert result["matched_count"] == 1
    assert result["mean_delta_m"] == 1.0
    assert result["std_delta_m"] == 0.0
    assert result["rmse_m"] == 1.0
    assert result["pct_roads_flat_manual"] == 1.0
    assert result["pct_roads_flat_auto"] == 1.0


def test_elevation_gap_matches_overlapping_roads_with_different_segmentation(tmp_path: Path) -> None:
    manual = _write_line_elevation_xodr(
        tmp_path / "manual_long.xodr",
        x0=0.0,
        y0=0.0,
        length=200.0,
        elevation_a=10.0,
    )
    auto = _write_line_elevation_xodr(
        tmp_path / "auto_short.xodr",
        x0=0.0,
        y0=0.0,
        length=50.0,
        elevation_a=20.0,
    )

    result = ElevationGap.compute(manual, auto)

    assert result["disabled"] is False
    assert result["matched_count"] == 1
    assert result["matched_road_pairs"] == 1
    assert result["match_distance_method"] == "sampled_polyline_min_distance"
    assert result["max_match_distance_m"] == 100.0
    assert result["candidate_centroid_distance_m"] == 200.0


def test_elevation_gap_ignores_offset_when_geometry_is_already_global(tmp_path: Path) -> None:
    manual = _write_line_elevation_xodr(
        tmp_path / "manual_global.xodr",
        x0=678000.0,
        y0=5402000.0,
        elevation_a=371.0,
    )
    auto = _write_line_elevation_xodr(
        tmp_path / "auto_global_aligned.xodr",
        x0=678000.0,
        y0=5402000.0,
        offset_x=677577.43,
        offset_y=5401899.77,
        elevation_a=372.0,
    )

    result = ElevationGap.compute(manual, auto)

    assert result["disabled"] is False
    assert result["matched_count"] == 1
    assert result["matched_road_pairs"] == 1
    assert result["mean_delta_m"] == 1.0


def test_finalize_results_writes_disabled_elevation_gap(tmp_path: Path) -> None:
    manual = _write_line_elevation_xodr(tmp_path / "manual.xodr", x0=0.0, y0=0.0)
    auto = _write_line_elevation_xodr(tmp_path / "auto.xodr", x0=0.0, y0=0.0)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    whole_elev_gap = _disabled_elevation_gap("dem_qc_failed")

    result = _finalize_results(
        output_dir=str(out_dir),
        reference_xodr=manual,
        aligned_auto=auto,
        generated_xodr=auto,
        transform={},
        whole_geom_gap={"disabled": True, "reason": "test"},
        whole_curv_gap={"disabled": True, "reason": "test"},
        whole_elev_gap=whole_elev_gap,
        whole_inter_gap={"disabled": True, "reason": "test"},
        whole_sem_gap={"disabled": True, "reason": "test"},
        whole_class_gap={"disabled": True, "reason": "test"},
        whole_conn_gap={"disabled": True, "reason": "test"},
        tile_geom_gaps={},
        tile_curv_gaps={},
        tile_gap_vector={},
        tile_map={},
        perception_gap=None,
        latent_whole=None,
        latent_per_tile=None,
        aggregated=None,
        run_meta={
            "manual_map_choice": None,
            "manual_xodr_resolved": manual,
            "manual_xodr_source": "test_fixture",
        },
        combined_repro_hash="test-hash",
        tile_pairing_provenance={},
    )

    full_report = json.loads((out_dir / "full_report.json").read_text(encoding="utf-8"))

    assert result["elevation"]["reason"] == "dem_qc_failed"
    assert result["elevation"]["disabled_reason"] == "DEM fallback used - excluded from composite per policy"
    assert full_report["elevation"]["reason"] == "dem_qc_failed"
    assert full_report["elevation"]["disabled_reason"] == "DEM fallback used - excluded from composite per policy"
    assert full_report["structural_domain_gap"]["elevation"] == full_report["elevation"]


def test_discover_elevation_dem_qc_path_uses_run_root(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    run_root = tmp_path / "auto_run"
    run_root.mkdir()
    qc_path = run_root / "elevation_dem_qc.json"
    qc_path.write_text('{"ok": true}\n', encoding="utf-8")

    discovered = _discover_elevation_dem_qc_path(
        str(out_dir),
        run_root=str(run_root),
    )

    assert discovered == qc_path


def test_finalize_results_embeds_summary_parity_and_elevation_qc(tmp_path: Path) -> None:
    manual = _write_line_elevation_xodr(
        tmp_path / "manual_nonflat.xodr",
        x0=0.0,
        y0=0.0,
        elevation_a=371.0,
    )
    auto = _write_line_elevation_xodr(
        tmp_path / "auto_nonflat.xodr",
        x0=0.0,
        y0=0.0,
        elevation_a=372.0,
    )
    out_dir = tmp_path / "out_full"
    out_dir.mkdir()
    run_root = tmp_path / "supplementary_run"
    run_root.mkdir()
    (run_root / "elevation_dem_qc.json").write_text(
        json.dumps(
            {
                "ok": True,
                "dem_path": str(run_root / "dem_ing_expanded.tif"),
                "dem_nodata_ratio": 0.0,
            }
        ),
        encoding="utf-8",
    )

    result = _finalize_results(
        output_dir=str(out_dir),
        reference_xodr=manual,
        aligned_auto=auto,
        generated_xodr=auto,
        transform={},
        whole_geom_gap={
            "disabled": False,
            "rmse": 54.84,
            "hausdorff": 1663.0,
            "hausdorff_norm": 0.5,
        },
        whole_curv_gap={"disabled": False, "kl_divergence": 0.1},
        whole_elev_gap={"disabled": False, "rmse_m": 1.5},
        whole_inter_gap={"disabled": False, "normalized_gap": 0.1},
        whole_sem_gap={"disabled": False, "gap": 0.2},
        whole_class_gap={"disabled": False, "gap": 0.3},
        whole_conn_gap={"disabled": True, "reason": "test_fixture"},
        tile_geom_gaps={},
        tile_curv_gaps={},
        tile_gap_vector={},
        tile_map={},
        perception_gap=None,
        latent_whole=None,
        latent_per_tile=None,
        aggregated=None,
        run_meta={
            "auto_run_root": str(run_root),
            "manual_map_choice": None,
            "manual_xodr_resolved": manual,
            "manual_xodr_source": "test_fixture",
        },
        combined_repro_hash="test-hash",
        tile_pairing_provenance={},
    )

    full_report = json.loads((out_dir / "full_report.json").read_text(encoding="utf-8"))

    assert result["summary"]["geometry_rmse"] == 54.84
    assert full_report["summary"]["geometry_rmse"] == 54.84
    assert full_report["parity_check"]["ok"] is True
    assert full_report["parity_check"]["n_divergences"] == 0
    # DG-004: parity check must now cover curvature_kl_divergence and connectivity
    parity_results = full_report["parity_check"].get("results", {})
    assert "curvature_kl_divergence" in parity_results, "DG-004: curvature_kl_divergence must be in parity check"
    assert "connectivity_predecessor_rate" in parity_results, "DG-004: connectivity must be in parity check"
    assert full_report["elevation_qc"]["dem_nodata_ratio"] == 0.0
    assert full_report["elevation_qc"]["dem_expanded_used"] is True
    assert full_report["dem_qc"]["dem_path"].endswith("dem_ing_expanded.tif")
    assert full_report["elevation_included"] is True


def test_compute_supplementary_elevation_gap_keeps_no_matched_roads_reason(tmp_path: Path, monkeypatch) -> None:
    manual = _write_line_elevation_xodr(
        tmp_path / "manual_nonflat_gap.xodr",
        x0=0.0,
        y0=0.0,
        elevation_a=371.0,
    )
    auto = _write_line_elevation_xodr(
        tmp_path / "auto_nonflat_gap.xodr",
        x0=0.0,
        y0=0.0,
        elevation_a=372.0,
    )
    out_dir = tmp_path / "gap_out"
    out_dir.mkdir()
    run_root = tmp_path / "auto_run"
    run_root.mkdir()
    (run_root / "elevation_dem_qc.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

    def _fake_compute(*_args, **_kwargs):
        return {
            "disabled": True,
            "reason": "no_matched_roads",
            "supplementary": True,
            "primary_artifact_is_planar": True,
        }

    monkeypatch.setattr(ElevationGap, "compute", staticmethod(_fake_compute))

    result = _compute_supplementary_elevation_gap(
        reference_xodr=manual,
        aligned_auto=auto,
        output_dir=str(out_dir),
        log=logging.getLogger("test_elevation_gap"),
        generated_xodr=auto,
        run_root=str(run_root),
    )

    assert result["disabled"] is True
    assert result["reason"] == "no_matched_roads"
    assert result["disabled_reason"] == "no matched roads - excluded from composite per policy"
    assert result.get("warning") != "auto_xodr_is_planar"


def test_compute_supplementary_elevation_gap_sets_disabled_reason_for_planar_auto(tmp_path: Path, monkeypatch) -> None:
    manual = _write_line_elevation_xodr(
        tmp_path / "manual_planar_reason.xodr",
        x0=0.0,
        y0=0.0,
        elevation_a=371.0,
    )
    auto = _write_line_elevation_xodr(
        tmp_path / "auto_planar_reason.xodr",
        x0=0.0,
        y0=0.0,
        elevation_a=0.0,
    )
    out_dir = tmp_path / "planar_reason_out"
    out_dir.mkdir()
    run_root = tmp_path / "planar_reason_run"
    run_root.mkdir()
    (run_root / "elevation_dem_qc.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

    def _fake_compute(*_args, **_kwargs):
        return {
            "disabled": False,
            "reason": "",
            "supplementary": True,
            "primary_artifact_is_planar": True,
            "pct_roads_flat_auto": 1.0,
            "rmse_m": 369.1514853955128,
        }

    monkeypatch.setattr(ElevationGap, "compute", staticmethod(_fake_compute))

    result = _compute_supplementary_elevation_gap(
        reference_xodr=manual,
        aligned_auto=auto,
        output_dir=str(out_dir),
        log=logging.getLogger("test_elevation_gap"),
        generated_xodr=auto,
        run_root=str(run_root),
    )

    assert result["disabled"] is True
    assert result["reason"] == "auto_xodr_is_planar"
    assert result["disabled_reason"] == "auto XODR is planar - excluded from composite per policy"
    assert result["rmse_m"] == 369.1514853955128


def test_domain_gap_aggregator_reports_but_excludes_elevation() -> None:
    aggregated = DomainGapAggregator.aggregate(
        gap_geometry={"disabled": False, "rmse": 1.0, "hausdorff": 2.0},
        gap_curvature={"disabled": False, "kl_divergence": 0.1, "delta_mean": 0.0},
        gap_elevation={"disabled": False, "rmse_m": 1.5, "supplementary": True},
        compute_composite=True,
    )

    assert aggregated["components"]["elevation"]["rmse_m"] == 1.5
    assert "elevation" in aggregated["composite_metadata"]["excluded_components"]


# ---------------------------------------------------------------------------
# _effective_header_offset_xy edge-case tests
# ---------------------------------------------------------------------------

def _make_root(*, offset_x: float = 0.0, offset_y: float = 0.0, geom_x: float = 0.0, geom_y: float = 0.0, has_header: bool = True, has_offset: bool = True) -> "ET.Element":
    import xml.etree.ElementTree as ET
    root = ET.Element("OpenDRIVE")
    if has_header:
        header = ET.SubElement(root, "header")
        if has_offset:
            ET.SubElement(header, "offset", x=str(offset_x), y=str(offset_y), z="0.0", hdg="0.0")
    road = ET.SubElement(root, "road", id="1", length="20.0", junction="-1")
    plan = ET.SubElement(road, "planView")
    geom = ET.SubElement(plan, "geometry", s="0.0", x=str(geom_x), y=str(geom_y), hdg="0.0", length="20.0")
    ET.SubElement(geom, "line")
    return root


def test_effective_header_offset_no_header() -> None:
    """Missing header element → returns (0.0, 0.0)."""
    import xml.etree.ElementTree as ET
    root = ET.Element("OpenDRIVE")
    assert _effective_header_offset_xy(root) == (0.0, 0.0)


def test_effective_header_offset_zero_offset() -> None:
    """Zero offset → returns (0.0, 0.0) immediately without examining geometry."""
    root = _make_root(offset_x=0.0, offset_y=0.0, geom_x=50.0, geom_y=50.0)
    assert _effective_header_offset_xy(root) == (0.0, 0.0)


def test_effective_header_offset_global_geom_suppresses_offset() -> None:
    """Global geometry (x > 100000) with large offset → offset suppressed → (0.0, 0.0)."""
    root = _make_root(offset_x=677577.43, offset_y=5401899.77, geom_x=678000.0, geom_y=5402000.0)
    assert _effective_header_offset_xy(root) == (0.0, 0.0)


def test_effective_header_offset_local_geom_returns_offset() -> None:
    """Local geometry (x < 100000) with small offset → returns (offset_x, offset_y)."""
    root = _make_root(offset_x=1000.0, offset_y=2000.0, geom_x=0.0, geom_y=0.0)
    assert _effective_header_offset_xy(root) == (1000.0, 2000.0)


def test_effective_header_offset_large_offset_small_geom_passes_through() -> None:
    """Large offset but small geometry coordinates → offset NOT suppressed (boundary check)."""
    # geom_x=50000 < 100000 threshold, so suppression does NOT trigger
    root = _make_root(offset_x=50000.0, offset_y=60000.0, geom_x=50000.0, geom_y=60000.0)
    # max_abs_geom = 60000 < 100000 → offset is returned as-is
    assert _effective_header_offset_xy(root) == (50000.0, 60000.0)


def test_effective_header_offset_no_geometry_suppresses_offset() -> None:
    """EG-001: No planView geometry → offset suppressed to avoid phantom double-shift."""
    import xml.etree.ElementTree as ET
    root = ET.Element("OpenDRIVE")
    header = ET.SubElement(root, "header")
    ET.SubElement(header, "offset", x="677577.43", y="5401899.77", z="0.0", hdg="0.0")
    road = ET.SubElement(root, "road", id="1", length="20.0", junction="-1")
    ET.SubElement(road, "planView")  # empty — no geometry children
    assert _effective_header_offset_xy(root) == (0.0, 0.0)


def test_match_roads_single_candidate_bypasses_centroid_filter(tmp_path: Path) -> None:
    """EG-002: Centroid pre-filter must be bypassed when there is only one candidate.

    Setup: manual road 0→500m, auto road 400→900m. Centroids are 250 and 650
    (centroid_dist=400 > 200m threshold → pre-filter would drop it). But the
    roads OVERLAP at 400–500m so polyline min-distance ≈ 0 < max_match_distance.
    Without EG-002 fix the pair is silently dropped; with the fix it is matched.
    """
    manual = _write_line_elevation_xodr(
        tmp_path / "manual_long.xodr",
        x0=0.0, y0=0.0, length=500.0, elevation_a=5.0,
    )
    auto = _write_line_elevation_xodr(
        tmp_path / "auto_offset.xodr",
        x0=400.0, y0=0.0, length=500.0, elevation_a=6.0,
    )
    result = ElevationGap.compute(manual, auto)
    assert result.get("matched_count", 0) >= 1, (
        "EG-002: single-candidate centroid bypass must produce a match for overlapping roads"
    )
