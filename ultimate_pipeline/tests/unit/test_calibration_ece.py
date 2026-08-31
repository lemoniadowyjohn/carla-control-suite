# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/perception/calibration.py's compute_ece().

Live via tools/run_perception_safe.py. Zero prior test coverage.

The bug: bin membership used `confidences < bins[i + 1]` for EVERY bin,
including the last one, whose upper edge is exactly 1.0. Since no
confidence value can ever be strictly less than 1.0 while also being
exactly 1.0, any sample with confidence==1.0 matched NO bin at all and
was silently excluded from the ECE sum entirely (np.sum(mask) == 0 for
whichever bin it would have belonged to). Reproduced the worst possible
case: 10 samples, all confidence=1.0, all WRONG (accuracy=0) -- the
maximally miscalibrated scenario -- reported ECE=0.0 (perfectly
calibrated), a complete inversion of the metric.
"""
from __future__ import annotations

from ultimate_pipeline.perception.calibration import compute_ece


def test_ece_zero_for_perfectly_calibrated_predictions():
    # confidence matches accuracy exactly within each bin -> ECE ~ 0.
    confidences = [0.9] * 10
    labels = [1] * 9 + [0] * 1  # 90% accuracy at 90% confidence
    ece = compute_ece(confidences, labels, n_bins=10)
    assert ece < 0.05


def test_ece_high_for_overconfident_wrong_predictions_at_max_confidence():
    # The maximally miscalibrated case: confidence=1.0 (100% sure), but
    # every single prediction is wrong (0% accuracy). ECE must reflect
    # this as close to 1.0, not silently exclude these samples from the
    # bin sum and report 0.0.
    confidences = [1.0] * 10
    labels = [0] * 10
    ece = compute_ece(confidences, labels, n_bins=15)
    assert ece > 0.9, f"expected near-maximal ECE for max-confidence-always-wrong, got {ece}"


def test_ece_confidence_exactly_one_is_not_silently_dropped():
    # A single confidence=1.0 sample mixed with well-calibrated ones must
    # still be counted -- confirms it lands in a bin rather than
    # vanishing from the weighted sum (which would show up as the total
    # weighted mass being less than expected).
    confidences = [0.5, 0.5, 1.0]
    labels = [1, 0, 0]  # the confidence=1.0 sample is wrong
    ece = compute_ece(confidences, labels, n_bins=10)
    # If the confidence=1.0 sample were dropped, only the two 0.5-confidence
    # samples (perfectly calibrated: 50% confidence, 50% accuracy) would
    # contribute, giving ECE=0.0. With it correctly included, ECE must be
    # meaningfully nonzero (that sample contributes |0 - 1.0| weighted by 1/3).
    assert ece > 0.2


def test_ece_empty_input_returns_zero():
    assert compute_ece([], [], n_bins=15) == 0.0


def test_ece_mismatched_lengths_returns_zero():
    assert compute_ece([0.5, 0.6], [1], n_bins=15) == 0.0
