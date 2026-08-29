# -*- coding: utf-8 -*-
"""Tests for PerceptionGap/PerceptionMetrics (ultimate_pipeline/domain_gap/perception_gap.py).

Live: imported by run_full_domain_gap.py -- feeds the RQ2/RQ3 perceptual
domain-gap metric. Zero prior test coverage.
"""
from __future__ import annotations

import json

import pytest

from ultimate_pipeline.domain_gap.perception_gap import (
    PerceptionEvaluator,
    PerceptionGap,
    PerceptionMetrics,
    PerTilePerceptionGap,
)


def test_metrics_round_trip_to_from_dict():
    m = PerceptionMetrics(miou={"road": 0.8, "car": 0.6}, map_score=0.7)
    d = m.to_dict()
    assert d["mean_miou"] == (0.8 + 0.6) / 2
    restored = PerceptionMetrics.from_dict(d)
    assert restored.miou == m.miou
    assert restored.mAP == m.mAP


def test_map_score_alias_is_settable():
    m = PerceptionMetrics()
    m.map_score = 0.42
    assert m.mAP == 0.42
    assert m.map_score == 0.42


def test_miou_mode_computes_per_class_and_mean_gap():
    manual = PerceptionMetrics(miou={"road": 0.9, "car": 0.7}, map_score=0.5)
    auto = PerceptionMetrics(miou={"road": 0.8, "car": 0.5}, map_score=0.3)
    gap = PerceptionGap.compare(manual, auto)
    assert gap["iou_gap_per_class"]["road"] == pytest.approx(0.1)
    assert gap["iou_gap_per_class"]["car"] == pytest.approx(0.2)
    assert gap["mean_iou_gap"] == pytest.approx(0.15)
    assert gap["mAP_gap"] == pytest.approx(0.2)


def test_miou_mode_handles_class_only_in_one_side():
    # A class present only in `auto` (or only `manual`) should still appear
    # in the gap with the missing side defaulting to 0.0, not KeyError.
    manual = PerceptionMetrics(miou={"road": 0.9})
    auto = PerceptionMetrics(miou={"road": 0.8, "sidewalk": 0.4})
    gap = PerceptionGap.compare(manual, auto)
    assert gap["iou_gap_per_class"]["sidewalk"] == pytest.approx(0.0 - 0.4)


def test_feature_proxy_mode_used_when_no_miou():
    manual = PerceptionMetrics(feature_samples=[[1.0, 0.0], [1.0, 0.2]], method="clip")
    auto = PerceptionMetrics(feature_samples=[[0.0, 1.0], [0.1, 1.0]], method="clip")
    gap = PerceptionGap.compare(manual, auto)
    assert gap["mode"] == "feature_proxy"
    assert "feature_gap" in gap
    assert gap["method_manual"] == "clip"
    assert gap["method_auto"] == "clip"


def test_dummy_evaluator_is_deterministic_placeholder():
    metrics = PerceptionEvaluator.from_predictions(
        predicted={}, ground_truth={"road": [], "car": []}
    )
    assert metrics.miou == {"road": 0.0, "car": 0.0}
    assert metrics.mAP == 0.0


def test_save_and_load_metrics_round_trip(tmp_path):
    m = PerceptionMetrics(miou={"road": 0.5}, map_score=0.25)
    out = tmp_path / "metrics.json"
    PerceptionEvaluator.save_metrics(m, str(out))
    loaded = PerceptionEvaluator.load_metrics(str(out))
    assert loaded.miou == m.miou
    assert loaded.mAP == m.mAP
    assert json.loads(out.read_text())["mAP"] == 0.25


def test_per_tile_gap_wraps_compare_with_tile_name():
    manual = PerceptionMetrics(miou={"road": 0.9})
    auto = PerceptionMetrics(miou={"road": 0.8})
    result = PerTilePerceptionGap.compare_tile("tile_0_0", manual, auto)
    assert result["tile"] == "tile_0_0"
    assert result["gap"]["iou_gap_per_class"]["road"] == pytest.approx(0.1)
