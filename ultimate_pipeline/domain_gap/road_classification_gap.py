#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
RoadClassificationGap
---------------------
Compares road categories between manual and auto OpenDRIVE maps.

Improvements over naive version:
- Length-weighted distributions (not just road counts)
- Numerically stable KL divergence
- Symmetric JS divergence (recommended for reporting)
- Explicit misclassification mass
- JSON-safe outputs

This is a STRUCTURAL / SEMANTIC domain-gap metric,
not a routing or geometry metric.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Dict, Tuple


EPS = 1e-9


class RoadClassificationGap:
    # ------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------

    @staticmethod
    def _extract_length_weighted_classes(xodr_path: str) -> Dict[str, float]:
        """
        Extract road-type distribution weighted by road length.

        Returns:
            { road_type: total_length_m }
        """
        tree = ET.parse(xodr_path)
        root = tree.getroot()

        lengths: Dict[str, float] = {}

        for road in root.findall("./road"):
            length = float(road.get("length", "0") or 0.0)

            typ = road.find("./type")
            if typ is not None:
                cls = typ.get("type", "unknown")
            else:
                cls = "unknown"

            lengths[cls] = lengths.get(cls, 0.0) + length

        return lengths

    # ------------------------------------------------------------
    # Divergences
    # ------------------------------------------------------------

    @staticmethod
    def _normalize(dist: Dict[str, float]) -> Dict[str, float]:
        total = sum(dist.values())
        if total <= 0:
            return {k: 0.0 for k in dist}
        return {k: v / total for k, v in dist.items()}

    @staticmethod
    def _kl_divergence(p: Dict[str, float], q: Dict[str, float]) -> float:
        """
        KL(p || q) with smoothing.
        """
        kl = 0.0
        for k in p:
            pk = max(p.get(k, 0.0), EPS)
            qk = max(q.get(k, 0.0), EPS)
            kl += pk * math.log(pk / qk)
        return float(kl)

    @staticmethod
    def _js_divergence(p: Dict[str, float], q: Dict[str, float]) -> float:
        """
        Jensen–Shannon divergence (symmetric, bounded, thesis-safe).
        """
        m = {k: 0.5 * (p.get(k, 0.0) + q.get(k, 0.0)) for k in set(p) | set(q)}
        return 0.5 * (
            RoadClassificationGap._kl_divergence(p, m) +
            RoadClassificationGap._kl_divergence(q, m)
        )

    # ------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------

    @staticmethod
    def compute(manual_xodr: str, auto_xodr: str) -> Dict:
        """
        Compute road-classification domain gap.

        Returns a JSON-safe dictionary with:
        - length-weighted distributions
        - KL divergence
        - JS divergence (recommended metric)
        - misclassified length ratio
        """

        # Length-weighted class distributions
        dist_m = RoadClassificationGap._extract_length_weighted_classes(manual_xodr)
        dist_a = RoadClassificationGap._extract_length_weighted_classes(auto_xodr)

        # Normalize
        pm = RoadClassificationGap._normalize(dist_m)
        pa = RoadClassificationGap._normalize(dist_a)

        # Divergences
        kl_ma = RoadClassificationGap._kl_divergence(pm, pa)
        kl_am = RoadClassificationGap._kl_divergence(pa, pm)
        js = RoadClassificationGap._js_divergence(pm, pa)

        # Misclassified mass:
        # how much length belongs to classes present in one map but not the other
        classes = set(pm) | set(pa)
        misclassified = sum(abs(pm.get(c, 0.0) - pa.get(c, 0.0)) for c in classes) / 2.0

        return {
            "manual_distribution": pm,
            "auto_distribution": pa,

            # Divergences
            "kl_manual_to_auto": kl_ma,
            "kl_auto_to_manual": kl_am,
            "js_divergence": js,

            # Intuitive scalar
            "misclassified_length_ratio": misclassified,

            # Metadata
            "classes": sorted(classes),
            "note": "Distributions are length-weighted, not count-based",
        }
