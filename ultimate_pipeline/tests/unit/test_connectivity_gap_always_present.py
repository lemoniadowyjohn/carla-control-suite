import json
from pathlib import Path

import pytest

from ultimate_pipeline.run_full_domain_gap import (
    _finalize_smoke_results,
    _normalize_connectivity_gap_payload,
)


def test_normalize_connectivity_gap_marks_missing_manual_map_as_skipped():
    payload = _normalize_connectivity_gap_payload(
        None,
        run_meta={
            "manual_reference_status": "missing",
            "manual_xodr_resolved": "",
        },
    )

    assert payload["disabled"] is True
    assert payload["status"] == "skipped"
    assert payload["reason"] == "manual_map_missing"
    assert payload["definition"]
    assert payload["unit"] == "ratio [0,1]"


def test_finalize_smoke_results_writes_connectivity_gap(tmp_path: Path):
    manual = tmp_path / "manual.xodr"
    auto = tmp_path / "auto.xodr"
    manual.write_text("<OpenDRIVE />", encoding="utf-8")
    auto.write_text("<OpenDRIVE />", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    combined = _finalize_smoke_results(
        output_dir=str(out_dir),
        reference_xodr=str(manual),
        aligned_auto=str(auto),
        generated_xodr=str(auto),
        transform={},
        whole_geom_gap={"disabled": True, "reason": "smoke_mode"},
        tile_iou_gate_summary={},
        tile_map={},
        tile_pairing_source="none",
        corr_path=None,
        run_meta={
            "manual_reference_status": "missing",
            "manual_xodr_resolved": "",
            "manual_xodr_source": "env",
        },
        combined_repro_hash="test-hash",
        tile_pairing_provenance={},
    )

    full_report = json.loads((out_dir / "full_report.json").read_text(encoding="utf-8"))

    assert "connectivity_gap" in combined
    assert "connectivity_gap" in full_report
    assert combined["connectivity_gap"]["disabled"] is True
    assert combined["connectivity_gap"]["status"] == "skipped"
    assert combined["connectivity_gap"]["reason"] == "smoke_mode"


# ---------------------------------------------------------------------------
# Flat alias tests (Gemini audit finding A — added 2026-04-14)
# ---------------------------------------------------------------------------

def test_normalize_connectivity_gap_emits_flat_aliases_when_computed():
    """Flat top-level aliases must be present when status=computed."""
    payload = {
        "auto": {
            "road_link": {
                "predecessor_declared_rate": 0.0,
                "successor_declared_rate": 0.0,
            }
        },
        "manual": {
            "road_link": {
                "predecessor_declared_rate": 0.934,
                "successor_declared_rate": 0.967,
            }
        },
        "gap": {
            "road_link": {
                "predecessor_declared_rate": -0.934,
                "successor_declared_rate": -0.967,
            }
        },
    }
    result = _normalize_connectivity_gap_payload(payload)

    assert result["status"] == "computed"
    assert result["disabled"] is False
    # Manual-side flat aliases
    assert result["predecessor_rate"] == pytest.approx(0.934)
    assert result["successor_rate"] == pytest.approx(0.967)
    assert result["predecessor_declared_rate"] == pytest.approx(0.934)
    assert result["successor_declared_rate"] == pytest.approx(0.967)
    # Auto-side flat aliases
    assert result["auto_predecessor_declared_rate"] == pytest.approx(0.0)
    assert result["auto_successor_declared_rate"] == pytest.approx(0.0)


def test_normalize_connectivity_gap_no_flat_aliases_when_disabled():
    """Disabled payloads must not have flat alias keys set by the normalizer."""
    result = _normalize_connectivity_gap_payload(None)

    assert result["status"] == "skipped"
    assert result["disabled"] is True
    # Flat aliases should NOT be present for disabled payloads
    assert "predecessor_rate" not in result
    assert "auto_predecessor_declared_rate" not in result


def test_normalize_connectivity_gap_flat_aliases_do_not_overwrite_existing():
    """setdefault semantics: pre-existing top-level keys must not be overwritten."""
    payload = {
        "predecessor_rate": 0.999,  # already set by caller
        "auto": {"road_link": {"predecessor_declared_rate": 0.5}},
        "manual": {"road_link": {"predecessor_declared_rate": 0.8}},
    }
    result = _normalize_connectivity_gap_payload(payload)

    # Pre-existing value must be preserved
    assert result["predecessor_rate"] == pytest.approx(0.999)


# ---------------------------------------------------------------------------
# DG-001: Smoke report schema parity test
# ---------------------------------------------------------------------------

def test_smoke_report_has_all_required_schema_keys(tmp_path: Path):
    """DG-001: smoke full_report.json must contain the same top-level keys as a full report."""
    manual = tmp_path / "manual.xodr"
    auto = tmp_path / "auto.xodr"
    manual.write_text("<OpenDRIVE />", encoding="utf-8")
    auto.write_text("<OpenDRIVE />", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()

    combined = _finalize_smoke_results(
        output_dir=str(out),
        reference_xodr=str(manual),
        aligned_auto=str(auto),
        generated_xodr=str(auto),
        transform={},
        whole_geom_gap={"disabled": True, "reason": "smoke_mode"},
        tile_iou_gate_summary={},
        tile_map={},
        tile_pairing_source="none",
        corr_path=None,
        run_meta={
            "manual_reference_status": "missing",
            "manual_xodr_resolved": "",
            "manual_xodr_source": "env",
        },
        combined_repro_hash="test-hash",
        tile_pairing_provenance={},
    )

    required = {"summary", "parity_check", "elevation_qc", "dem_qc",
                "elevation_included", "sumo_repair", "connectivity_gap",
                "structural_domain_gap", "smoke"}
    missing = required - combined.keys()
    assert not missing, f"Smoke report missing keys: {missing}"

    full_report = json.loads((out / "full_report.json").read_text(encoding="utf-8"))
    missing_in_file = required - full_report.keys()
    assert not missing_in_file, f"full_report.json missing keys: {missing_in_file}"
    assert full_report["smoke"] is True
    assert full_report["elevation_included"] is False
    assert full_report["parity_check"]["disabled"] is True
