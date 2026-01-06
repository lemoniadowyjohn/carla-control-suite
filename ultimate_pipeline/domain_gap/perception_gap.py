# ultimate_pipeline/domain_gap/perception_gap.py

from __future__ import annotations

import json
import os
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

    def __init__(self, miou: Dict[str, float], map_score: float):
        self.miou = dict(sorted(miou.items()))
        self.mAP = float(map_score)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "miou": self.miou,
            "mAP": self.mAP,
            "mean_miou": (
                sum(self.miou.values()) / len(self.miou)
                if self.miou else 0.0
            ),
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "PerceptionMetrics":
        return PerceptionMetrics(
            miou=d.get("miou", {}),
            map_score=d.get("mAP", 0.0),
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
