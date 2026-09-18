# ultimate_pipeline/domain_gap/cross_city.py

from __future__ import annotations
import json
import os
from typing import Dict, Any, List

from ultimate_pipeline.domain_gap.report_aggregator import ReportAggregator


class CrossCityGeneralization:
    """
    Analyze domain gap + perception metrics across multiple cities.

    Assumes experiments are named like:
      cityname_mode
    e.g.
      ingolstadt_real_only
      ingolstadt_synthetic_only
      munich_real_only
      munich_synthetic_only
    """

    @staticmethod
    def load_summary(summary_json: str) -> List[Dict[str, Any]]:
        with open(summary_json, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def group_by_city(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            exp = r.get("experiment", "")
            # assume "city_mode" naming
            parts = exp.split("_", 1)
            city = parts[0] if len(parts) > 1 else exp
            groups.setdefault(city, []).append(r)
        return groups

    @staticmethod
    def compute_city_level_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Simple example: for each city, average:
          - pg_mAP_absolute
          - dg_curvature_gap
        (Extend as needed.)
        """
        mAPs = []
        curv_gaps = []

        for r in rows:
            mAP = r.get("pg_mAP_absolute", None)
            if mAP is not None:
                mAPs.append(float(mAP))
            curv = r.get("dg_curvature_gap", None)
            if curv is not None:
                curv_gaps.append(float(curv))

        def _mean(xs):
            return sum(xs) / len(xs) if xs else 0.0

        return {
            "avg_mAP": _mean(mAPs),
            "avg_curvature_gap": _mean(curv_gaps),
        }

    @staticmethod
    def summarize_cross_city(exp_dir: str, out_json: str) -> Dict[str, Any]:
        rows = ReportAggregator.aggregate_experiments(
            exp_dir=exp_dir,
            out_json=os.path.join(exp_dir, "experiments_summary.json"),
        )
        groups = CrossCityGeneralization.group_by_city(rows)

        city_summary: Dict[str, Any] = {}
        for city, city_rows in groups.items():
            city_summary[city] = CrossCityGeneralization.compute_city_level_metrics(city_rows)

        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(city_summary, f, indent=2)

        return city_summary
