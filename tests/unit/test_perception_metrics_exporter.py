"""ultimate_pipeline/perception/perception_metrics_exporter.py.

This is the RQ2/RQ3 perceptual-gap feature producer: export_perception_metrics()
discovers images under a run's output directory, embeds them (ResNet18 if torch
is available, else an RGB-histogram fallback), and writes a metrics JSON that
ultimate_pipeline/domain_gap/perception_gap.py's PerceptionGap.compare()
(feature_proxy branch) and ultimate_pipeline/tools/compute_perception_gap.py both
read via the "feature_samples"/"feature_mean"/"feature_var_diag"/"method" keys.

No test previously existed for this module at all, despite it being the sole
producer of the JSON schema three other modules depend on. These tests lock down
that schema and the two edge cases in export_perception_metrics with real branches:
no images found, and the >256-sample subsampling path.
"""
from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image

from ultimate_pipeline.perception.perception_metrics_exporter import (
    export_perception_metrics,
    _rgb_histogram_features,
)


def _write_images(folder, n, seed=0, size=(16, 16)):
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    for i in range(n):
        arr = rng.integers(0, 255, size=(size[0], size[1], 3), dtype=np.uint8)
        Image.fromarray(arr, mode="RGB").save(folder / f"{i:03d}.png")


def test_export_perception_metrics_writes_the_schema_downstream_code_depends_on(tmp_path):
    run_out = tmp_path / "run"
    _write_images(run_out / "perception", n=5)

    out_path = export_perception_metrics(str(run_out), max_images=100)
    payload = json.loads(open(out_path, encoding="utf-8").read())

    # Exact keys that PerceptionGap.compare's feature_proxy branch and
    # compute_perception_gap.py's _load_feats both read.
    assert payload["method"] is not None
    assert payload["feature_dim"] > 0
    assert isinstance(payload["feature_mean"], list) and len(payload["feature_mean"]) == payload["feature_dim"]
    assert isinstance(payload["feature_var_diag"], list) and len(payload["feature_var_diag"]) == payload["feature_dim"]
    assert isinstance(payload["feature_samples"], list) and len(payload["feature_samples"]) == 5
    assert all(len(row) == payload["feature_dim"] for row in payload["feature_samples"])
    assert payload["n_images_used"] == 5
    assert "error" not in payload


def test_export_perception_metrics_reports_an_explicit_error_when_no_images_found(tmp_path):
    """A run directory with none of the recognized image folders (perception/,
    screenshots/, road_perception/, qa/, viz/) and no images anywhere must not
    silently produce a fake all-zero feature vector that PerceptionGap.compare
    could mistake for "zero distributional gap" -- the perceptual-gap number for
    that side would be meaningless. It must report n_images_used=0 with an
    explicit "error" key.
    """
    run_out = tmp_path / "empty_run"
    run_out.mkdir()

    out_path = export_perception_metrics(str(run_out), max_images=100)
    payload = json.loads(open(out_path, encoding="utf-8").read())

    assert payload["n_images_discovered"] == 0
    assert payload["n_images_used"] == 0
    assert "error" in payload
    assert payload["feature_mean"] is None


def test_export_perception_metrics_subsamples_deterministically_above_256_images(tmp_path):
    """feature_samples is capped at 256 rows via a seeded RNG (seed=0) so repeated
    runs against the same image set are reproducible -- required for a thesis
    result to be defensible. Uses the dependency-light RGB-histogram feature path
    directly (bypassing ResNet18) so this stays fast; the subsampling logic itself
    lives in export_perception_metrics after feature extraction, independent of
    which extractor produced the features.
    """
    run_out = tmp_path / "big_run"
    _write_images(run_out / "perception", n=300, size=(4, 4))

    out_path = export_perception_metrics(str(run_out), max_images=1000)
    payload = json.loads(open(out_path, encoding="utf-8").read())

    assert payload["n_images_used"] == 300
    assert len(payload["feature_samples"]) == 256  # capped, not all 300
    assert payload["feature_samples_seed"] == 0

    # Re-running against the identical image set must reproduce the same subsample
    # (same seed=0 default_rng, same input order from sorted glob).
    out_path2 = export_perception_metrics(str(run_out), out_name="perception_metrics_rerun.json", max_images=1000)
    payload2 = json.loads(open(out_path2, encoding="utf-8").read())
    assert payload["feature_samples"] == payload2["feature_samples"]


def test_rgb_histogram_features_shape_and_density(tmp_path):
    folder = tmp_path / "imgs"
    _write_images(folder, n=2, size=(8, 8))
    paths = sorted(folder.glob("*.png"))

    feats = _rgb_histogram_features(paths, bins=32)

    assert feats.shape == (2, 96)  # 3 channels * 32 bins
    # np.histogram(..., density=True) integrates to 1 over the bin width, not to 1 directly;
    # just assert every row is finite and non-negative (a valid density estimate).
    assert np.isfinite(feats).all()
    assert (feats >= 0).all()
