#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Intersection Domain Gap

Compares intersection-type distributions between:
    - manual reference map
    - automatically generated map

Classification is based on ROAD connectivity, not lane-level connections.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Dict, Set
from collections import Counter

# Word-boundary match for the roundabout markers: a raw substring check
# (e.g. "rb" in name_blob) would false-positive on any junction name/id
# that happens to contain that substring mid-word -- a real risk for
# German street names like "Silberburgstrasse".
_ROUNDABOUT_MARKER_RE = re.compile(r"\b(?:roundabout|rb)\b")


class IntersectionGap:
    """
    Intersection-type domain gap computation.
    """

    # Canonical intersection types (shared vocabulary)
    TYPES = (
        "dead_end",
        "three_way",
        "four_way",
        "complex",
        "roundabout",
        "other",
    )

    # ============================================================
    # Classification
    # ============================================================

    @staticmethod
    def classify_junction(junction: ET.Element) -> str:
        """
        Classify a single junction based on unique road connectivity.
        """

        roads: Set[str] = set()

        for conn in junction.findall("connection"):
            inc = conn.get("incomingRoad")
            con = conn.get("connectingRoad")
            if inc:
                roads.add(inc)
            if con:
                roads.add(con)

        n = len(roads)

        # --- Roundabout heuristic ---
        name_blob = (
            (junction.get("name") or "") + " " +
            (junction.get("id") or "")
        ).lower()

        if _ROUNDABOUT_MARKER_RE.search(name_blob):
            return "roundabout"

        # --- Structural classification ---
        if n <= 1:
            return "dead_end"
        if n == 3:
            return "three_way"
        if n == 4:
            return "four_way"
        if n > 4:
            return "complex"

        return "other"

    # ============================================================
    # Counting
    # ============================================================

    @staticmethod
    def count_types(root: ET.Element) -> Dict[str, int]:
        """
        Count intersection types in an OpenDRIVE root.
        """

        counts = Counter({k: 0 for k in IntersectionGap.TYPES})

        for j in root.findall(".//junction"):
            t = IntersectionGap.classify_junction(j)
            counts[t] += 1

        return dict(counts)

    # ============================================================
    # Comparison / Domain Gap
    # ============================================================

    @staticmethod
    def compute(manual_xodr: str, auto_xodr: str) -> Dict:
        """
        Compute intersection-type domain gap.

        Returns:
            {
                manual: {type → count},
                auto: {type → count},
                delta: {type → auto - manual},
                normalized_gap: float ∈ [0,1]
            }
        """

        rm = ET.parse(manual_xodr).getroot()
        ra = ET.parse(auto_xodr).getroot()

        cm = IntersectionGap.count_types(rm)
        ca = IntersectionGap.count_types(ra)

        # --- Raw deltas ---
        delta = {
            k: ca.get(k, 0) - cm.get(k, 0)
            for k in IntersectionGap.TYPES
        }

        # --- Normalized distribution gap (L1 / 2) ---
        total_m = sum(cm.values()) or 1
        total_a = sum(ca.values()) or 1

        norm_m = {k: cm[k] / total_m for k in IntersectionGap.TYPES}
        norm_a = {k: ca[k] / total_a for k in IntersectionGap.TYPES}

        l1 = sum(abs(norm_m[k] - norm_a[k]) for k in IntersectionGap.TYPES)
        normalized_gap = l1 / 2.0  # ∈ [0,1]

        return {
            "manual": cm,
            "auto": ca,
            "delta": delta,
            "normalized_gap": round(normalized_gap, 4),
        }
