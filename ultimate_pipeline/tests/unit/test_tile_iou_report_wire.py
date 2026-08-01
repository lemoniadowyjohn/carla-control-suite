from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.run_full_domain_gap import (
    _build_tile_iou_gate_summary,
    _combine_per_tile_structural_gap,
    _collect_unique_tile_pairs,
    _finalize_results,
    _finalize_smoke_results,
    _print_tile_iou_gate_rejection,
    _print_tile_iou_gate_summary,
    _write_tile_iou_report,
)


def test_tile_iou_report_summary_contains_all_required_fields(tmp_path: Path) -> None:
    rows = [
        {
            "manual_tile": "tile_0_0.xodr",
            "auto_tile": "tile_1_1.xodr",
            "iou": 0.1166,
            "match_quality": "good",
            "match_method": "centroid_spatial",
        }
    ]
    summary = _build_tile_iou_gate_summary(
        rows,
        iou_gate_threshold=0.5,
        tiles_passed_gate_count=0,
        tiles_gated_count=1,
        match_method="centroid_spatial",
    )
    path = _write_tile_iou_report(str(tmp_path), rows=rows, summary=summary)
    payload = json.loads(Path(path).read_text(encoding="utf-8"))

    assert summary["total_tile_pairs"] == 1
    assert summary["tiles_passed_gate_count"] == 0
    assert summary["tiles_gated_count"] == 1
    assert summary["max_tile_iou_observed"] == 0.1166
    assert summary["mean_tile_iou_observed"] == 0.1166
    assert summary["iou_gate_threshold"] == 0.5
    assert summary["match_method"] == "centroid_spatial"
    assert payload["summary"] == summary
    assert payload["rows"] == rows


def test_finalize_smoke_results_writes_full_report_with_tile_iou_gate_summary(tmp_path: Path) -> None:
    manual_xodr = tmp_path / "manual.xodr"
    auto_xodr = tmp_path / "auto.xodr"
    manual_xodr.write_text("<OpenDRIVE />", encoding="utf-8")
    auto_xodr.write_text("<OpenDRIVE />", encoding="utf-8")

    rows = [
        {
            "manual_tile": "tile_0_0.xodr",
            "auto_tile": "tile_1_1.xodr",
            "iou": 0.1166,
            "match_quality": "good",
            "match_method": "centroid_spatial",
        }
    ]
    summary = _build_tile_iou_gate_summary(
        rows,
        iou_gate_threshold=0.5,
        tiles_passed_gate_count=0,
        tiles_gated_count=1,
        match_method="centroid_spatial",
    )

    payload = _finalize_smoke_results(
        output_dir=str(tmp_path),
        reference_xodr=str(manual_xodr),
        aligned_auto=str(auto_xodr),
        generated_xodr=str(auto_xodr),
        transform={
            "crs_reprojection": {"applied": True},
            "transform": {"scale": 1.0},
            "diagnostics": {"fit_metric": "planView geometry start-point correspondence RMSE"},
        },
        whole_geom_gap={"disabled": False, "rmse": 54.84, "hausdorff": 1663.0},
        tile_iou_gate_summary=summary,
        tile_map={"tile_0_0.xodr": {"match": "tile_1_1.xodr", "iou": 0.1166}},
        tile_pairing_source="centroid_spatial",
        corr_path=tmp_path / "tile_correspondence.csv",
        run_meta={"manual_map_choice": "Grid0828", "manual_xodr_source": "cli"},
        combined_repro_hash="abc123",
        tile_pairing_provenance={"frame_method": "native_aligned"},
    )

    full_report = json.loads((tmp_path / "full_report.json").read_text(encoding="utf-8"))

    assert payload["tile_iou_gate_summary"] == summary
    assert full_report["tile_iou_gate_summary"] == summary
    assert full_report["alignment"]["transform"]["scale"] == 1.0
    assert (
        full_report["alignment"]["diagnostics"]["fit_metric_note"]
        == "Diagnostic metric (planView start-point RMSE); not proven equivalent to ICP optimization objective. Monotonic increase does not imply ICP failure - see chap7 alignment interpretation."
    )
    assert full_report["structural_domain_gap"]["geometry"]["disabled"] is False
    assert full_report["structural_domain_gap"]["geometry"]["rmse"] == 54.84
    assert full_report["smoke"] is True


def test_collect_unique_tile_pairs_dedupes_matches_and_candidates() -> None:
    row = {
        "manual": "tile_0_0.xodr",
        "auto": "tile_1_1.xodr",
        "iou": 1.0,
        "match_quality": "good",
        "status": "matched_ok",
    }
    report = {
        "matches": [dict(row)],
        "candidates": [dict(row)],
    }

    pairs = _collect_unique_tile_pairs(report, {})

    assert len(pairs) == 1
    assert pairs[0]["manual"] == "tile_0_0.xodr"
    assert pairs[0]["auto"] == "tile_1_1.xodr"


def _write_stub_xodr(path: Path) -> str:
    root = ET.Element("OpenDRIVE")
    ET.SubElement(root, "header", revMajor="1", revMinor="6", name="stub")
    road = ET.SubElement(root, "road", id="1", length="10.0", junction="-1")
    plan = ET.SubElement(road, "planView")
    geom = ET.SubElement(plan, "geometry", s="0.0", x="0.0", y="0.0", hdg="0.0", length="10.0")
    ET.SubElement(geom, "line")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return str(path)


def test_combine_per_tile_structural_gap_is_tile_keyed() -> None:
    combined = _combine_per_tile_structural_gap(
        {
            "tile_0_0.xodr": {"rmse": 12.0, "auto_tile": "auto_0_0.xodr"},
            "tile_0_1.xodr": {"rmse": 8.0, "auto_tile": "auto_0_1.xodr"},
        },
        {
            "tile_0_0.xodr": {"kl_divergence": 0.2, "auto_tile": "auto_0_0.xodr"},
            "tile_0_1.xodr": {"kl_divergence": 0.1, "auto_tile": "auto_0_1.xodr"},
        },
    )

    assert sorted(combined.keys()) == ["tile_0_0.xodr", "tile_0_1.xodr"]
    assert combined["tile_0_0.xodr"]["geometry"]["rmse"] == 12.0
    assert combined["tile_0_0.xodr"]["curvature"]["kl_divergence"] == 0.2
    assert len(combined) == 2


def test_finalize_results_embeds_all_per_tile_entries(tmp_path: Path) -> None:
    manual = _write_stub_xodr(tmp_path / "manual.xodr")
    auto = _write_stub_xodr(tmp_path / "auto.xodr")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    payload = _finalize_results(
        output_dir=str(out_dir),
        reference_xodr=manual,
        aligned_auto=auto,
        generated_xodr=auto,
        transform={},
        whole_geom_gap={"disabled": False, "rmse": 1.0, "hausdorff": 2.0},
        whole_curv_gap={"disabled": False, "kl_divergence": 0.1},
        whole_elev_gap={"disabled": True, "reason": "test"},
        whole_inter_gap={"disabled": True, "reason": "test"},
        whole_sem_gap={"disabled": True, "reason": "test"},
        whole_class_gap={"disabled": True, "reason": "test"},
        whole_conn_gap={"disabled": True, "reason": "test"},
        tile_geom_gaps={
            "tile_0_0.xodr": {"rmse": 10.0, "auto_tile": "auto_0_0.xodr"},
            "tile_0_1.xodr": {"rmse": 11.0, "auto_tile": "auto_0_1.xodr"},
        },
        tile_curv_gaps={
            "tile_0_0.xodr": {"kl_divergence": 0.2, "auto_tile": "auto_0_0.xodr"},
            "tile_0_1.xodr": {"kl_divergence": 0.3, "auto_tile": "auto_0_1.xodr"},
        },
        tile_gap_vector={},
        tile_map={
            "tile_0_0.xodr": {"match": "auto_0_0.xodr", "iou": 0.8},
            "tile_0_1.xodr": {"match": "auto_0_1.xodr", "iou": 0.7},
        },
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

    report = json.loads((out_dir / "full_report.json").read_text(encoding="utf-8"))

    assert len(payload["per_tile_structural_gap"]) == 2
    assert len(report["per_tile_structural_gap"]) == 2
    assert report["per_tile_structural_gap"]["tile_0_0.xodr"]["geometry"]["rmse"] == 10.0
    assert report["per_tile_structural_gap"]["tile_0_1.xodr"]["curvature"]["kl_divergence"] == 0.3


def test_print_tile_iou_gate_rejection_emits_console_line(capsys) -> None:
    _print_tile_iou_gate_rejection(
        pair_name="tile_0_0.xodr->tile_1_1.xodr",
        iou=0.1166,
        threshold=0.5,
    )

    captured = capsys.readouterr()
    assert (
        "[TILE-GATE] Rejected tile pair tile_0_0.xodr->tile_1_1.xodr: IoU=0.117 < 0.500"
        in captured.out
    )


def test_print_tile_iou_gate_summary_emits_console_line(capsys) -> None:
    _print_tile_iou_gate_summary(n_rejected=27, n_total=39, threshold=0.5)

    captured = capsys.readouterr()
    assert "[TILE-GATE] 27 of 39 tile pairs rejected (IoU < 0.500); 12 passed" in captured.out
