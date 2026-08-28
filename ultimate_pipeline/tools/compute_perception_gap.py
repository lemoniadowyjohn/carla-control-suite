#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compute perceptual domain gap between two perception runs.

Reads the metrics JSON written by
`ultimate_pipeline.perception.perception_metrics_exporter.export_perception_metrics`
for each run. That JSON carries per-image feature vectors inline under the
"feature_samples" key (a subsample, capped at 256 rows, of the full embedding
set -- see export_perception_metrics). A "features_npz" key (an external .npz
of per-image embeddings) is also accepted if some future exporter mode writes
one, but nothing in this codebase currently produces it.

Outputs:
  - perception_gap.json
  - perception_gap.csv
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import numpy as np

from ultimate_pipeline.domain_gap.feature_gap import FeatureGap


def _load_metrics_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def _load_feats(metrics: Dict[str, Any], run_dir: Path) -> np.ndarray:
    # Preferred: an external .npz of per-image embeddings, if some exporter mode
    # ever writes one (currently nothing in this codebase does).
    npz = metrics.get("features_npz", None)
    if npz:
        npz_path = Path(npz)
        if not npz_path.is_absolute():
            npz_path = (run_dir / npz_path).resolve()
        if not npz_path.exists():
            raise FileNotFoundError(f"features_npz not found: {npz_path}")
        data = np.load(npz_path)
        feats = data["feats"]
        if feats.ndim != 2 or feats.shape[0] < 2:
            raise RuntimeError(f"unexpected feats shape: {feats.shape}")
        return feats.astype(np.float32)

    # Actual schema written by export_perception_metrics(): an inline
    # "feature_samples" list (subsampled, capped at 256 rows).
    samples = metrics.get("feature_samples", None)
    if samples:
        feats = np.asarray(samples, dtype=np.float32)
        if feats.ndim != 2 or feats.shape[0] < 2:
            raise RuntimeError(f"unexpected feature_samples shape: {feats.shape}")
        return feats

    raise RuntimeError(
        "metrics json does not contain 'features_npz' or 'feature_samples'. "
        "Run perception_metrics_exporter.export_perception_metrics() on this "
        "run's output directory first."
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manual_run", required=True, help="Run output folder for manual map recording")
    ap.add_argument("--auto_run", required=True, help="Run output folder for auto map recording")
    ap.add_argument("--manual_metrics", default="perception_metrics_manual.json")
    ap.add_argument("--auto_metrics", default="perception_metrics_auto.json")
    ap.add_argument("--out_dir", default="", help="Where to write outputs (default: auto_run)")
    args = ap.parse_args()

    manual_run = Path(args.manual_run)
    auto_run = Path(args.auto_run)

    m_json = manual_run / args.manual_metrics
    a_json = auto_run / args.auto_metrics
    if not m_json.exists():
        raise FileNotFoundError(f"manual metrics json not found: {m_json}")
    if not a_json.exists():
        raise FileNotFoundError(f"auto metrics json not found: {a_json}")

    m_metrics = _load_metrics_json(m_json)
    a_metrics = _load_metrics_json(a_json)

    m_feats = _load_feats(m_metrics, manual_run)
    a_feats = _load_feats(a_metrics, auto_run)

    fg = FeatureGap()
    gap = fg.compute(source=m_feats, target=a_feats)

    payload = {
        "manual_run": str(manual_run),
        "auto_run": str(auto_run),
        "manual_feats_n": int(m_feats.shape[0]),
        "auto_feats_n": int(a_feats.shape[0]),
        "feature_dim": int(m_feats.shape[1]),
        "gap": {k: float(v) for k, v in gap.items()},
    }

    out_dir = Path(args.out_dir) if args.out_dir else auto_run
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "perception_gap.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (out_dir / "perception_gap.csv").write_text(
        "metric,value\n" + "\n".join([f"{k},{payload['gap'][k]}" for k in sorted(payload["gap"].keys())]) + "\n",
        encoding="utf-8",
    )

    print(f"✅ wrote: {out_dir / 'perception_gap.json'}")
    print(f"✅ wrote: {out_dir / 'perception_gap.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
