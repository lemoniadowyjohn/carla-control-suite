"""Fail-closed consumer tests for feature-domain gap (FAL-A review)."""
from __future__ import annotations

import json
import sys

import numpy as np
import pytest

from ultimate_pipeline.domain_gap.feature_gap import FeatureDomainGap
from ultimate_pipeline.domain_gap.perception_gap import (
    PerceptionGap, PerceptionMetrics, PerTilePerceptionGap,
)
from ultimate_pipeline.tools.compute_perception_gap import main as compute_gap_main


def _metrics(samples=None, mean=None, *, status=None):
    return PerceptionMetrics(
        feature_samples=samples, feature_mean=mean, map_score=None,
        status=status or "MISSING_EVIDENCE",
        method="clip",
    )


def test_valid_feature_pairs_are_explicitly_diagnostic():
    gap = PerceptionGap.compare(
        _metrics([[0.0, 1.0], [1.0, 2.0]]),
        _metrics([[2.0, 3.0], [3.0, 4.0]]),
    )
    assert gap["status"] == "DIAGNOSTIC_ONLY"
    assert gap["mode"] == "feature_proxy"
    assert gap["manual_feature_count"] == 2
    assert gap["auto_feature_count"] == 2
    assert all(np.isfinite(v) for v in gap["feature_gap"].values())


@pytest.mark.parametrize("bad", [
    [[float("nan"), 1.0], [2.0, 3.0]],
    [[float("inf"), 1.0], [2.0, 3.0]],
    [[0.0, 1.0, 2.0], [3.0, 4.0, 5.0]],
    [[0.0, 1.0], [3.0]],
])
def test_invalid_feature_pairs_cannot_produce_numeric_gap(bad):
    valid = [[0.0, 1.0], [1.0, 2.0]]
    result = PerceptionGap.compare(_metrics(bad), _metrics(valid))
    assert result["status"] == "INVALID_MEASUREMENT"
    assert "feature_gap" not in result
    assert "gap" not in result


def test_one_missing_feature_arm_is_not_zero_gap():
    result = PerceptionGap.compare(
        _metrics([[0.0, 1.0], [1.0, 2.0]]),
        _metrics(None),
    )
    assert result["status"] == "MISSING_EVIDENCE"
    assert "feature_gap" not in result


def test_only_stored_means_are_not_distributions():
    result = PerceptionGap.compare(
        _metrics(mean=[1.0, 2.0]), _metrics(mean=[1.0, 2.0])
    )
    assert result["status"] == "INSUFFICIENT_SUPPORT"
    assert "feature_gap" not in result


def test_one_observation_per_arm_not_distributional_evidence():
    result = PerceptionGap.compare(
        _metrics([[1.0, 2.0]]), _metrics([[1.0, 2.0]])
    )
    assert result["status"] == "INSUFFICIENT_SUPPORT"


def test_core_compute_rejects_one_sample_even_if_means_match(tmp_path):
    gap = FeatureDomainGap(tmp_path)
    with pytest.raises(ValueError, match="insufficient feature observations"):
        gap.compute([[1.0, 2.0]], [[1.0, 2.0]])


def test_tile_gap_preserves_nonmeasured_status():
    result = PerTilePerceptionGap.compare_tile(
        "tile0", _metrics(mean=[1.0]), _metrics(mean=[1.0])
    )
    assert result["gap"]["status"] == "INSUFFICIENT_SUPPORT"
    assert "feature_gap" not in result["gap"]


def _invoke(monkeypatch, manual, auto, output):
    monkeypatch.setattr(sys, "argv", [
        "compute_perception_gap",
        "--manual_run", str(manual),
        "--auto_run", str(auto),
        "--out_dir", str(output),
    ])
    return compute_gap_main()


def _write_metrics(folder, name, samples):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(
        json.dumps({"feature_samples": samples}), encoding="utf-8"
    )


def test_cli_failure_quarantines_prior_success_not_leaving_stale_csv(tmp_path, monkeypatch):
    manual = tmp_path / "manual"
    auto = tmp_path / "auto"
    output = tmp_path / "out"
    output.mkdir()
    _write_metrics(manual, "perception_metrics_manual.json",
                   [[1.0, 2.0], [2.0, 3.0]])
    _write_metrics(auto, "perception_metrics_auto.json",
                   [[1.0, 2.0, 3.0], [2.0, 3.0, 4.0]])
    (output / "perception_gap.json").write_text('{"status":"PASS","gap":{"mmd":0}}')
    (output / "perception_gap.csv").write_text("metric,value\\nmmd,0\\n")

    assert _invoke(monkeypatch, manual, auto, output) != 0
    receipt = json.loads((output / "perception_gap.json").read_text())
    assert receipt["status"] == "INVALID_MEASUREMENT"
    assert receipt["gap"] is None
    assert not (output / "perception_gap.csv").exists()
    quarantine = list((output / "quarantine").glob("*/perception_gap.json"))
    assert len(quarantine) == 1
    assert json.loads(quarantine[0].read_text())["status"] == "PASS"
    assert len(list((output / "quarantine").glob("*/perception_gap.csv"))) == 1


def test_cli_missing_input_emits_non_success_receipt(tmp_path, monkeypatch):
    manual = tmp_path / "manual"
    auto = tmp_path / "auto"
    output = tmp_path / "out"
    auto.mkdir()
    assert _invoke(monkeypatch, manual, auto, output) != 0
    receipt = json.loads((output / "perception_gap.json").read_text())
    assert receipt["status"] == "MISSING_EVIDENCE"
    assert receipt["gap"] is None
    assert not (output / "perception_gap.csv").exists()


def test_cli_valid_run_is_diagnostic_not_rq3_accuracy(tmp_path, monkeypatch):
    manual = tmp_path / "manual"
    auto = tmp_path / "auto"
    output = tmp_path / "out"
    _write_metrics(manual, "perception_metrics_manual.json",
                   [[0.0, 1.0], [1.0, 2.0]])
    _write_metrics(auto, "perception_metrics_auto.json",
                   [[2.0, 3.0], [3.0, 4.0]])
    assert _invoke(monkeypatch, manual, auto, output) == 0
    receipt = json.loads((output / "perception_gap.json").read_text())
    assert receipt["status"] == "DIAGNOSTIC_ONLY"
    assert receipt["manual_feats_n"] == 2
    assert receipt["auto_feats_n"] == 2
    assert receipt["gap"]["mmd"] > 0
    assert (output / "perception_gap.csv").exists()
