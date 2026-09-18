#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Manual vs Auto Map Comparator

Compares a manually authored OpenDRIVE map against an
automatically generated OpenDRIVE map using the SAME
feature space, without assuming OSM-specific priors.
"""

from __future__ import annotations

import json
from typing import Dict, Optional

from .map_stats_xodr import XODRMapStatsExtractor
from .gap_analyzer import DomainGapAnalyzer, DomainGapScores


class ManualAutoComparator:
    """
    Compare manual reference map vs auto-generated map.

    Key principle:
        - manual map is treated as ground truth
        - no OSM assumptions are applied
        - only XODR↔XODR comparable features are used
    """

    @staticmethod
    def compare_maps(
        manual_xodr: str,
        auto_xodr: str,
        out_json: Optional[str] = None,
    ) -> DomainGapScores:
        """
        Perform manual-vs-auto comparison.

        Returns:
            DomainGapScores
        """

        # -----------------------------
        # Extract comparable stats
        # -----------------------------
        manual_stats = XODRMapStatsExtractor.from_file(manual_xodr)
        auto_stats = XODRMapStatsExtractor.from_file(auto_xodr)

        # -----------------------------
        # Compare using XODR-only logic
        # -----------------------------
        scores = DomainGapAnalyzer.compare_xodr_to_xodr(
            reference_stats=manual_stats,
            generated_stats=auto_stats,
        )

        # -----------------------------
        # Optional persistence
        # -----------------------------
        if out_json:
            payload = {
                "comparison": "manual_vs_auto",
                "reference_map": manual_xodr,
                "generated_map": auto_xodr,
                "assumptions": [
                    "manual map treated as ground truth",
                    "only XODR-comparable features evaluated",
                    "no OSM priors applied",
                ],
                "scores": scores.to_dict(),
            }

            with open(out_json, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)

        return scores
