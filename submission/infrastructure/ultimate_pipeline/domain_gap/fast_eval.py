# ultimate_pipeline/domain_gap/fast_eval.py

from __future__ import annotations

import json
import os
import time
from typing import Dict, Any, Optional

from ultimate_pipeline.domain_gap.map_stats_xodr import XODRMapStatsExtractor
from ultimate_pipeline.domain_gap.map_stats_osm import OSMMapStatsExtractor
from ultimate_pipeline.domain_gap.gap_analyzer import DomainGapAnalyzer
from ultimate_pipeline.domain_gap.osm_loader import OSMLoader
from ultimate_pipeline.domain_gap.manual_vs_auto_comparator import ManualAutoComparator


class FastEvaluator:
    """
    CPU-only structural domain-gap evaluator.

    Purpose
    -------
    Provides a fast, simulator-free comparison between:
        - OSM reference data
        - manually modeled OpenDRIVE map
        - automatically generated OpenDRIVE map

    This evaluator is intended for:
        - early validation
        - ablation studies
        - HPC sweeps
        - regression testing

    No CARLA dependency.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def run(
        *,
        manual_xodr: str,
        auto_xodr: str,
        osm_roads_json: str,
        out_json: str,
        strict: bool = True,
    ) -> Dict[str, Any]:
        """
        Execute the fast structural domain-gap evaluation.

        Parameters
        ----------
        manual_xodr:
            Path to manually created OpenDRIVE map

        auto_xodr:
            Path to automatically generated OpenDRIVE map

        osm_roads_json:
            Serialized OSM road graph (JSON)

        out_json:
            Output report path

        strict:
            If True, raise on missing inputs.
            If False, degrade gracefully and record errors.
        """

        t0 = time.perf_counter()

        # -----------------------------
        # Input validation
        # -----------------------------
        FastEvaluator._check_file(manual_xodr, "manual_xodr", strict)
        FastEvaluator._check_file(auto_xodr, "auto_xodr", strict)
        FastEvaluator._check_file(osm_roads_json, "osm_roads_json", strict)

        os.makedirs(os.path.dirname(out_json), exist_ok=True)

        errors = []

        # -----------------------------
        # Load OSM
        # -----------------------------
        try:
            osm_roads = OSMLoader.load_from_json(osm_roads_json)
            osm_stats = OSMMapStatsExtractor.from_osm_roads(osm_roads)
        except Exception as e:
            if strict:
                raise
            osm_stats = None
            errors.append(f"OSM load failed: {e}")

        # -----------------------------
        # Load OpenDRIVE maps
        # -----------------------------
        try:
            manual_stats = XODRMapStatsExtractor.from_file(manual_xodr)
        except Exception as e:
            if strict:
                raise
            manual_stats = None
            errors.append(f"Manual XODR load failed: {e}")

        try:
            auto_stats = XODRMapStatsExtractor.from_file(auto_xodr)
        except Exception as e:
            if strict:
                raise
            auto_stats = None
            errors.append(f"Auto XODR load failed: {e}")

        # -----------------------------
        # Gap computations
        # -----------------------------
        gap_osm_manual = None
        gap_osm_auto = None
        gap_manual_auto = None

        if osm_stats and manual_stats:
            gap_osm_manual = (
                DomainGapAnalyzer
                .compare(osm_stats, manual_stats)
                .to_dict()
            )

        if osm_stats and auto_stats:
            gap_osm_auto = (
                DomainGapAnalyzer
                .compare(osm_stats, auto_stats)
                .to_dict()
            )

        # Manual vs Auto comparison (geometry-aware)
        try:
            gap_manual_auto = (
                ManualAutoComparator
                .compare_maps(
                    manual_xodr=manual_xodr,
                    auto_xodr=auto_xodr,
                    out_json=os.path.splitext(out_json)[0] + "_manual_vs_auto.json",
                )
                .to_dict()
            )
        except Exception as e:
            if strict:
                raise
            errors.append(f"Manual vs Auto comparison failed: {e}")

        # -----------------------------
        # Report assembly
        # -----------------------------
        report: Dict[str, Any] = {
            "inputs": {
                "manual_xodr": manual_xodr,
                "auto_xodr": auto_xodr,
                "osm_roads_json": osm_roads_json,
            },
            "results": {
                "gap_osm_manual": gap_osm_manual,
                "gap_osm_auto": gap_osm_auto,
                "gap_manual_auto": gap_manual_auto,
            },
            "runtime_sec": round(time.perf_counter() - t0, 2),
            "errors": errors if errors else None,
        }

        report = FastEvaluator._prune_none(report)

        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        print(f"[FastEvaluator] Report written → {out_json}")

        return report

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _check_file(path: str, name: str, strict: bool) -> None:
        if not path or not os.path.exists(path):
            msg = f"{name} not found: {path}"
            if strict:
                raise FileNotFoundError(msg)
            print(f"[FastEvaluator] ⚠ {msg}")

    @staticmethod
    def _prune_none(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {
                k: FastEvaluator._prune_none(v)
                for k, v in obj.items()
                if v is not None
            }
        if isinstance(obj, list):
            return [FastEvaluator._prune_none(v) for v in obj]
        return obj
