"""ultimate_pipeline/tools/compute_perception_gap.py vs. perception_metrics_exporter.py.

This CLI tool is the RQ2 perceptual-gap script a human would actually run against
real captured manual/auto perception runs once live CARLA is available. Its own
docstring says it "Requires that perception_metrics_exporter.py was run with
--dump_features, so each run has a *_features.npz with per-image embeddings" and
looks for a top-level "features_npz" key in the metrics JSON.

But perception_metrics_exporter.py (the only producer of these metrics JSON files
in this codebase) has no --dump_features flag and never writes a "features_npz"
key -- it writes features inline as a "feature_samples" list (see
export_perception_metrics in perception_metrics_exporter.py). grepping the whole
repo (excluding frozen submission/infrastructure mirrors and old worktrees) turns
up zero producers of "features_npz" or "--dump_features" anywhere.

So this tool is a "reads as done but isn't wired" dead end: it has real, correct
FeatureGap math behind it (verified independently in test_feature_gap.py-style
usage via ultimate_pipeline/domain_gap/feature_gap.py), but the CLI glue can never
succeed against real exporter output -- it always raises RuntimeError on the very
first call. This test file characterizes the bug (RED) and the fix that makes the
tool accept the exporter's actual "feature_samples" schema as a fallback (GREEN).
"""
from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image

from ultimate_pipeline.perception.perception_metrics_exporter import export_perception_metrics
from ultimate_pipeline.tools.compute_perception_gap import _load_feats, main


def _write_tiny_images(folder, n=5, seed=0):
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    for i in range(n):
        arr = rng.integers(0, 255, size=(16, 16, 3), dtype=np.uint8)
        Image.fromarray(arr, mode="RGB").save(folder / f"{i:03d}.png")


def test_load_feats_raises_a_clear_error_when_features_npz_is_absent(tmp_path):
    # A metrics JSON with neither "features_npz" nor "feature_samples" -- genuinely
    # nothing to load from. Should still raise, but doesn't need "--dump_features"
    # in the message since that flag doesn't exist anywhere in this codebase.
    metrics = {"n_images_used": 0}
    with pytest.raises(RuntimeError):
        _load_feats(metrics, tmp_path)


def test_load_feats_accepts_real_exporter_output_via_feature_samples(tmp_path):
    """RED (pre-fix): exporter output has 'feature_samples', not 'features_npz',
    so _load_feats used to raise RuntimeError against every real run.
    GREEN (post-fix): _load_feats falls back to the inline 'feature_samples' list
    that export_perception_metrics actually produces.
    """
    run_dir = tmp_path / "run_manual"
    _write_tiny_images(run_dir / "perception", n=5)
    metrics_path = export_perception_metrics(str(run_dir), out_name="perception_metrics_manual.json", max_images=100)
    metrics = json.loads(open(metrics_path, encoding="utf-8").read())

    assert "features_npz" not in metrics  # confirms the exporter never writes this key
    assert isinstance(metrics.get("feature_samples"), list) and len(metrics["feature_samples"]) > 0

    feats = _load_feats(metrics, run_dir)
    assert feats.ndim == 2
    assert feats.shape[0] == len(metrics["feature_samples"])
    assert feats.shape[1] == metrics["feature_dim"]


def test_compute_perception_gap_end_to_end_against_real_exporter_output(tmp_path, monkeypatch, capsys):
    """Full CLI path: two real exporter runs -> compute_perception_gap.main() must
    succeed and write a real, non-degenerate gap report -- not raise RuntimeError.
    """
    manual_run = tmp_path / "run_manual"
    auto_run = tmp_path / "run_auto"
    _write_tiny_images(manual_run / "perception", n=5, seed=0)
    _write_tiny_images(auto_run / "perception", n=5, seed=1)

    export_perception_metrics(str(manual_run), out_name="perception_metrics_manual.json", max_images=100)
    export_perception_metrics(str(auto_run), out_name="perception_metrics_auto.json", max_images=100)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "compute_perception_gap.py",
            "--manual_run", str(manual_run),
            "--auto_run", str(auto_run),
        ],
    )

    rc = main()
    assert rc == 0

    out_json = auto_run / "perception_gap.json"
    assert out_json.exists()
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["manual_feats_n"] == 5
    assert payload["auto_feats_n"] == 5
    assert set(payload["gap"]) == {"mmd", "wasserstein", "mean_gap"}
    assert all(np.isfinite(v) for v in payload["gap"].values())
