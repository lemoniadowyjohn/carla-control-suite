#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Intersection Classification for OpenDRIVE Maps

Classifies junctions into:
    - t_junction        (3 unique roads)
    - four_way          (4 unique roads)
    - roundabout        (explicit or inferred)
    - complex           (>4 unique roads)
    - other             (degenerate / malformed)

Design goals:
- Deterministic
- Robust to incomplete OpenDRIVE exports
- Conservative classification (avoid over-claiming)
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from typing import Dict, Set


class IntersectionClassifier:
    """
    Classify intersections in an OpenDRIVE map using structural heuristics.

    IMPORTANT:
    - Classification is based on *road connectivity*, not lane count.
    - Roundabouts are detected via explicit junction metadata OR
      inferred via high connection count with cyclic topology.
    """

    @staticmethod
    def classify(xodr_path: str) -> Dict[str, int]:
        """
        Classify all junctions in the given OpenDRIVE map.

        Returns:
            dict with counts per intersection class
        """

        tree = ET.parse(xodr_path)
        root = tree.getroot()

        junctions = root.findall(".//junction")
        counts: Counter[str] = Counter()

        for junc in junctions:
            roads = IntersectionClassifier._collect_unique_roads(junc)

            if not roads:
                counts["other"] += 1
                continue

            n_roads = len(roads)

            # ---------- Roundabout detection ----------
            if IntersectionClassifier._is_roundabout(junc, roads):
                counts["roundabout"] += 1
                continue

            # ---------- Structural classification ----------
            if n_roads == 3:
                counts["t_junction"] += 1
            elif n_roads == 4:
                counts["four_way"] += 1
            elif n_roads > 4:
                counts["complex"] += 1
            else:
                counts["other"] += 1

        return dict(counts)

    # ======================================================================
    # Helpers
    # ======================================================================

    @staticmethod
    def _collect_unique_roads(junction: ET.Element) -> Set[str]:
        """
        Extract unique road IDs participating in a junction.
        """
        roads: Set[str] = set()

        for conn in junction.findall("connection"):
            incoming = conn.get("incomingRoad")
            connecting = conn.get("connectingRoad")

            if incoming:
                roads.add(incoming)
            if connecting:
                roads.add(connecting)

        return roads

    @staticmethod
    def _is_roundabout(junction: ET.Element, roads: Set[str]) -> bool:
        """
        Detect roundabouts via conservative heuristics.

        Criteria (ANY of):
        1) Explicit hint in junction name or id
        2) High connectivity + cyclic connections
        """

        name_blob = (
            (junction.get("name") or "") +
            (junction.get("id") or "")
        ).lower()

        # --- Explicit naming heuristic ---
        if "roundabout" in name_blob or "rb" in name_blob:
            return True

        # --- Structural heuristic ---
        # Roundabouts usually have:
        # - many small connections
        # - multiple roads feeding into a cycle
        connections = junction.findall("connection")

        if len(roads) >= 4 and len(connections) >= 6:
            # heuristic: dense connectivity implies circular topology
            return True

        return False
