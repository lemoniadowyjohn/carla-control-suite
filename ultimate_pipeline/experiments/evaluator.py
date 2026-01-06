# ultimate_pipeline/experiments/evaluator.py

from __future__ import annotations
import os
import json
from typing import Dict, Any

from ultimate_pipeline.domain_gap.map_stats_xodr import XODRMapStatsExtractor
from ultimate_pipeline.domain_gap.map_stats_osm import OSMMapStatsExtractor, OSMRoad
from ultimate_pipeline.domain_gap.gap_analyzer import DomainGapAnalyzer
from ultimate_pipeline.domain_gap.manual_vs_auto_comparator import ManualAutoComparator
from ultimate_pipeline.domain_gap.perception_gap import PerceptionMetrics, PerceptionGap


class Evaluator:
    """
    Evaluates a trained model (or fake one) and computes:

      1) perception metrics on a real test set (mIoU, mAP, etc.)
      2) domain gap metrics (structural)
      3) perception gap between manual vs auto maps

    For now, this is mostly a stub:
      - generate dummy perception numbers
      - compute domain gap via ManualAutoComparator
    Later:
      - plug in real prediction/GT evaluation logic
      - plug in per-tile evaluation
    """

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.exp_name = cfg["experiment"]["name"]
        self.exp_dir = os.path.join("logs", "experiments", self.exp_name)
        os.makedirs(self.exp_dir, exist_ok=True)

        # Paths to maps (you can override in config)
        self.manual_map_path = cfg["maps"].get("manual_xodr", "cities/ingolstadt/final_stable_map_manual.xodr")
        self.auto_map_path   = cfg["maps"].get("auto_xodr",   "cities/ingolstadt/final_stable_map_auto.xodr")

        # Optionally: path to OSM ground truth if you want map-vs-OSM gap here as well
        self.osm_roads_path = cfg["maps"].get("osm_roads_json", "")

        self._perception_metrics_manual: PerceptionMetrics | None = None
        self._perception_metrics_auto: PerceptionMetrics | None = None

    # ------------------------------------------------------
    # Perception eval stubs
    # ------------------------------------------------------
    def evaluate(self) -> Dict[str, Any]:
        """
        Evaluate the current experiment on a real test set.

        For now: produce dummy metrics but with realistic structure.
        Later: call your real evaluation pipeline here.
        """
        print(f"[Evaluator] Evaluating experiment: {self.exp_name}")

        # Dummy values that look realistic-ish
        # You can condition on exp_name (real_only / synthetic_only / mixed)
        base_map = {
            "real_only": 0.72,
            "synthetic_only": 0.64,
            "mixed": 0.78,
        }.get(self.exp_name, 0.70)

        base_miou_road = 0.80
        base_miou_building = 0.65
        base_miou_lane = 0.72

        # Build PerceptionMetrics for "auto" map
        self._perception_metrics_auto = PerceptionMetrics(
            miou={
                "road": base_miou_road,
                "building": base_miou_building,
                "lane": base_miou_lane,
            },
            map_score=base_map,
        )

        # For comparison we imagine a "manual map baseline" with slightly better performance
        self._perception_metrics_manual = PerceptionMetrics(
            miou={
                "road": base_miou_road + 0.02,
                "building": base_miou_building + 0.04,
                "lane": base_miou_lane + 0.03,
            },
            map_score=base_map + 0.03,
        )

        # Save raw metrics for debugging
        eval_out = {
            "manual": self._perception_metrics_manual.to_dict(),
            "auto": self._perception_metrics_auto.to_dict(),
        }
        eval_path = os.path.join(self.exp_dir, "perception_eval_fake.json")
        with open(eval_path, "w", encoding="utf-8") as f:
            json.dump(eval_out, f, indent=2)

        print(f"[Evaluator] Fake perception eval written → {eval_path}")
        return eval_out

    # ------------------------------------------------------
    # Domain gap: manual vs auto
    # ------------------------------------------------------
    def compute_domain_gap(self) -> Dict[str, Any]:
        """
        Compute structural domain gap between manual vs auto XODR.

        Uses ManualAutoComparator, which delegates to DomainGapAnalyzer.
        """
        print(f"[Evaluator] Computing structural domain gap (manual vs auto)...")

        out_json = os.path.join(self.exp_dir, "domain_gap_manual_vs_auto.json")
        scores = ManualAutoComparator.compare_maps(
            manual_xodr=self.manual_map_path,
            auto_xodr=self.auto_map_path,
            out_json=out_json,
        )

        print(f"[Evaluator] Domain gap saved → {out_json}")
        return scores.to_dict()

    # ------------------------------------------------------
    # Perception gap between manual vs auto
    # ------------------------------------------------------
    def compute_perception_gap(self) -> Dict[str, Any]:
        """
        Compare perception metrics between manual and auto maps.

        Uses PerceptionGap.compare(PerceptionMetrics_manual, PerceptionMetrics_auto).
        """
        print(f"[Evaluator] Computing perception gap (manual vs auto)...")

        if self._perception_metrics_manual is None or self._perception_metrics_auto is None:
            # Ensure evaluate() has been called
            self.evaluate()

        gap = PerceptionGap.compare(
            manual=self._perception_metrics_manual,
            auto=self._perception_metrics_auto,
        )

        # Also store absolute mAP of auto model (for plotting)
        gap["mAP_absolute"] = self._perception_metrics_auto.map_score

        out_path = os.path.join(self.exp_dir, "perception_gap_manual_vs_auto.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(gap, f, indent=2)

        print(f"[Evaluator] Perception gap saved → {out_path}")
        return gap
