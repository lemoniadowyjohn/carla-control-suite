# ultimate_pipeline/domain_gap/perception_gap.py

from __future__ import annotations

import json
import os

import numpy as np

from ultimate_pipeline.domain_gap.feature_gap import FeatureDomainGap
from typing import Dict, List, Any


# ---------------------------------------------------------------------------
# 1. Perception Metrics (PRESERVED + HARDENED)
# ---------------------------------------------------------------------------

class PerceptionMetrics:
    """
    Container for perception model performance.

    miou:
        Dict[class_name, IoU]
    mAP:
        Mean Average Precision for detection tasks
    """

    def __init__(
        self,
        miou: Dict[str, float] | None = None,
        map_score: float = 0.0,
        *,
        feature_mean: List[float] | None = None,
        feature_var_diag: List[float] | None = None,
        feature_samples: List[List[float]] | None = None,
        method: str | None = None,
    ):
        self.miou = dict(sorted((miou or {}).items()))
        self.mAP = float(map_score)
        self.feature_mean = feature_mean
        self.feature_var_diag = feature_var_diag
        self.feature_samples = feature_samples
        self.method = method

    @property
    def map_score(self) -> float:
        """Alias for mAP (legacy scripts expect `map_score`)."""
        return float(self.mAP)

    @map_score.setter
    def map_score(self, value: float) -> None:
        self.mAP = float(value)


    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "miou": self.miou,
            "mAP": self.mAP,
            "mean_miou": (sum(self.miou.values()) / len(self.miou)) if self.miou else 0.0,
        }
        # Optional feature-proxy metrics (for unlabeled domains)
        if self.feature_mean is not None:
            d["feature_mean"] = self.feature_mean
        if self.feature_var_diag is not None:
            d["feature_var_diag"] = self.feature_var_diag
        if self.feature_samples is not None:
            d["feature_samples"] = self.feature_samples
        if self.method is not None:
            d["method"] = self.method
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "PerceptionMetrics":
        return PerceptionMetrics(
            miou=d.get("miou", {}) or {},
            map_score=float(d.get("mAP", 0.0) or 0.0),
            feature_mean=d.get("feature_mean"),
            feature_var_diag=d.get("feature_var_diag"),
            feature_samples=d.get("feature_samples"),
            method=d.get("method"),
        )


# ---------------------------------------------------------------------------
# 2. Perception Gap (CORE DEFINITION)
# ---------------------------------------------------------------------------

class PerceptionGap:
    """
    Compute perception performance deltas between:
      (A) manual / reference dataset
      (B) auto-generated dataset

    Assumes:
      - same model
      - same training regime
      - only dataset differs
    """

    @staticmethod
    def compare(
        manual: PerceptionMetrics,
        auto: PerceptionMetrics,
    ) -> Dict[str, Any]:

        # Feature-proxy mode: if no class IoUs are provided, compute distributional gaps
        # using the stored feature samples (or means as fallback).
        if (not manual.miou) and (not auto.miou) and (manual.feature_samples or manual.feature_mean) and (auto.feature_samples or auto.feature_mean):
            fdg = FeatureDomainGap(output_dir=".")
            X = manual.feature_samples if manual.feature_samples else [manual.feature_mean]  # type: ignore[list-item]
            Y = auto.feature_samples if auto.feature_samples else [auto.feature_mean]  # type: ignore[list-item]
            feature_gap = fdg.compute(X, Y)
            return {
                "mode": "feature_proxy",
                "feature_gap": feature_gap,
                "method_manual": manual.method,
                "method_auto": auto.method,
            }

        classes = sorted(set(manual.miou) | set(auto.miou))
        iou_gap: Dict[str, float] = {}

        for cls in classes:
            m = manual.miou.get(cls, 0.0)
            a = auto.miou.get(cls, 0.0)
            iou_gap[cls] = m - a

        gap = {
            "iou_gap_per_class": iou_gap,
            "mean_iou_gap": (
                sum(iou_gap.values()) / len(iou_gap)
                if iou_gap else 0.0
            ),
            "mAP_gap": manual.mAP - auto.mAP,
        }

        return gap

    @staticmethod
    def save_json(gap: Dict[str, Any], out_path: str) -> None:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(gap, f, indent=2)


# ---------------------------------------------------------------------------
# 3. Perception Evaluator (ABSTRACTION LAYER)
# ---------------------------------------------------------------------------

class PerceptionEvaluator:
    """
    Abstract evaluation interface.

    HPC jobs plug real model evaluation here.
    Domain-gap pipeline stays ML-agnostic.
    """

    @staticmethod
    def from_predictions(
        predicted: Dict[str, List[Any]],
        ground_truth: Dict[str, List[Any]],
    ) -> PerceptionMetrics:
        """
        Placeholder evaluator.

        Replace with:
          - Detectron2
          - MMDetection
          - TorchMetrics
          - CARLA leaderboard tools
        """

        # Deterministic dummy output (pipeline continuity)
        classes = sorted(ground_truth.keys())

        miou = {cls: 0.0 for cls in classes}
        mAP = 0.0

        return PerceptionMetrics(miou=miou, map_score=mAP)

    @staticmethod
    def load_metrics(path: str) -> PerceptionMetrics:
        with open(path, "r", encoding="utf-8") as f:
            return PerceptionMetrics.from_dict(json.load(f))

    @staticmethod
    def save_metrics(metrics: PerceptionMetrics, out_path: str) -> None:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(metrics.to_dict(), f, indent=2)


# ---------------------------------------------------------------------------
# 4. Tile-Level Perception Gap
# ---------------------------------------------------------------------------

class PerTilePerceptionGap:
    """
    Compute perception gap per tile.

    Enables:
      - spatial correlation with geometry gap
      - tile heatmaps
      - failure localization
    """

    @staticmethod
    def compare_tile(
        tile_name: str,
        manual_metrics: PerceptionMetrics,
        auto_metrics: PerceptionMetrics,
    ) -> Dict[str, Any]:

        gap = PerceptionGap.compare(manual_metrics, auto_metrics)

        return {
            "tile": tile_name,
            "gap": gap,
        }

    @staticmethod
    def save_all(
        gaps: List[Dict[str, Any]],
        out_path: str,
    ) -> None:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(gaps, f, indent=2)


# ---------------------------------------------------------------------------
# 5. Unified Perception Gap Reporter
# ---------------------------------------------------------------------------

class PerceptionGapReporter:
    """
    Combine:
      - domain gap metrics
      - perception gap metrics
      - experiment metadata

    Used by:
      - HPC experiment logger
      - ablation runners
      - thesis figure generators
    """

    @staticmethod
    def combine(
        experiment_name: str,
        domain_gap: Dict[str, Any],
        perception_gap: Dict[str, Any],
        out_path: str,
    ) -> None:

        report = {
            "experiment": experiment_name,
            "domain_gap": domain_gap,
            "perception_gap": perception_gap,
        }

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        print(
            f"[PerceptionGapReporter] Full gap report saved → {out_path}"
        )
