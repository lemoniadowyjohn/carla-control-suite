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

    CD-2 remediation: a metrics payload that was never measured carries
    ``status`` in {"NOT_IMPLEMENTED", "NOT_RUN", "MISSING_EVIDENCE"} and
    ``miou=None``/``mAP=None``. It must never be confused with a real
    measurement via numeric zeros.
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
        status: str | None = None,
    ):
        self.miou = dict(sorted((miou or {}).items()))
        self.mAP = None if map_score is None else float(map_score)
        self.feature_mean = feature_mean
        self.feature_var_diag = feature_var_diag
        self.feature_samples = feature_samples
        self.method = method
        self.status = status or ("measured" if self.miou or self.mAP is not None else "MISSING_EVIDENCE")

    @property
    def map_score(self) -> Any:
        """Alias for mAP (legacy scripts expect `map_score`)."""
        return self.mAP

    @map_score.setter
    def map_score(self, value: Any) -> None:
        self.mAP = None if value is None else float(value)


    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "miou": self.miou,
            "mAP": self.mAP,
            "mean_miou": (sum(self.miou.values()) / len(self.miou)) if self.miou else None,
        }
        # CD-2: record non-measured states explicitly; never fabricate zeros.
        if self.status and self.status != "measured":
            d["status"] = self.status
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
            map_score=d.get("mAP", 0.0) if d.get("mAP") is not None else None,
            feature_mean=d.get("feature_mean"),
            feature_var_diag=d.get("feature_var_diag"),
            feature_samples=d.get("feature_samples"),
            method=d.get("method"),
            status=d.get("status"),
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

        # CD-2: refuse to fabricate a gap from non-measured metrics.
        not_measured = [
            m for m in (manual, auto)
            if (getattr(m, "status", "measured") != "measured")
        ]
        if not_measured and not (
            (manual.feature_samples or manual.feature_mean)
            and (auto.feature_samples or auto.feature_mean)
        ):
            return {
                "status": "MISSING_EVIDENCE" if all(
                    getattr(m, "status", "measured") in ("NOT_RUN", "MISSING_EVIDENCE")
                    for m in not_measured
                ) else "NOT_IMPLEMENTED",
                "reason": (
                    "perception metrics were never actually computed; "
                    "no zero-gap value was fabricated"
                ),
                "statuses": {
                    "manual": getattr(manual, "status", "measured"),
                    "auto": getattr(auto, "status", "measured"),
                },
            }

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
    ) -> "PerceptionMetrics":
        """
        NOT IMPLEMENTED evaluator (CD-2 remediation).

        No real metric engine is wired into this pipeline layer (Detectron2 /
        MMDetection / TorchMetrics / CARLA leaderboard tools are not bound
        here). The predecessor stub returned deterministic dummy zeros, which
        downstream consumers could mistake for measured performance. It now
        returns an explicit NOT_IMPLEMENTED metrics payload with ``miou=None``
        and ``mAP=None``: missing evidence is a *status*, never a number.
        """
        classes = sorted(ground_truth.keys())
        return NotImplementedMetrics(expected_classes=classes)

    @staticmethod
    def load_metrics(path: str) -> "PerceptionMetrics":
        with open(path, "r", encoding="utf-8") as f:
            return PerceptionMetrics.from_dict(json.load(f))

    @staticmethod
    def save_metrics(metrics: "PerceptionMetrics", out_path: str) -> None:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(metrics.to_dict(), f, indent=2)


class NotImplementedMetrics(PerceptionMetrics):
    """Sentinel result for an evaluator that was never actually executed."""

    def __init__(self, expected_classes: List[str] | None = None, *, status: str = "NOT_IMPLEMENTED"):
        super().__init__(miou=None, map_score=None, status=status)
        self.expected_classes = list(expected_classes or [])

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["expected_classes"] = self.expected_classes
        d["note"] = (
            "evaluator not implemented/executed in this pipeline layer; "
            "no numeric metrics were fabricated"
        )
        return d


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
