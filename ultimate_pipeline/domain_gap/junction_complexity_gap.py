#!/usr/bin/env python3
"""
Junction complexity gap:
Counts <connection> elements per <junction> and compares distributions.
Lightweight, deterministic, and OpenDRIVE-only.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from collections import Counter
from typing import Dict, List, Any


def _percentile(sorted_vals: List[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if q <= 0.0:
        return float(sorted_vals[0])
    if q >= 1.0:
        return float(sorted_vals[-1])
    pos = (len(sorted_vals) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_vals[lo])
    frac = pos - lo
    return float(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac)


def _stats(counts: List[int]) -> Dict[str, Any]:
    if not counts:
        return {"count": 0, "mean": 0.0, "median": 0.0, "p95": 0.0, "max": 0.0}
    vals = sorted(float(c) for c in counts)
    n = len(vals)
    mean = sum(vals) / n
    median = _percentile(vals, 0.5)
    p95 = _percentile(vals, 0.95)
    return {
        "count": n,
        "mean": mean,
        "median": median,
        "p95": p95,
        "max": vals[-1],
    }


def _hist(counts: List[int]) -> Dict[int, int]:
    raw = Counter(int(c) for c in counts)
    return {k: raw[k] for k in sorted(raw.keys())}


def _js_divergence(hist_a: Dict[int, int], hist_b: Dict[int, int], epsilon: float) -> float:
    keys = sorted(set(hist_a.keys()) | set(hist_b.keys()))
    if not keys:
        return 0.0
    k = len(keys)
    total_a = sum(hist_a.values()) + epsilon * k
    total_b = sum(hist_b.values()) + epsilon * k
    js = 0.0
    for key in keys:
        p = (hist_a.get(key, 0) + epsilon) / total_a
        q = (hist_b.get(key, 0) + epsilon) / total_b
        m = 0.5 * (p + q)
        js += 0.5 * (p * math.log(p / m) + q * math.log(q / m))
    return float(js)


class JunctionComplexityGap:
    """
    Compare junction connection-count distributions between two OpenDRIVE maps.
    """

    @staticmethod
    def _connection_counts(xodr_path: str) -> List[int]:
        root = ET.parse(xodr_path).getroot()
        counts: List[int] = []
        for j in root.findall(".//junction"):
            counts.append(len(j.findall("connection")))
        return counts

    @staticmethod
    def compute(manual_xodr: str, auto_xodr: str, *, epsilon: float = 1e-6) -> Dict[str, Any]:
        """
        Returns:
            {
                "manual": {"stats": {...}, "histogram": {...}},
                "auto": {...},
                "js_divergence": float,
                "epsilon": float,
                "disabled": False,
            }
        """
        try:
            manual_counts = JunctionComplexityGap._connection_counts(manual_xodr)
            auto_counts = JunctionComplexityGap._connection_counts(auto_xodr)

            hist_manual = _hist(manual_counts)
            hist_auto = _hist(auto_counts)

            return {
                "manual": {
                    "stats": _stats(manual_counts),
                    "histogram": hist_manual,
                },
                "auto": {
                    "stats": _stats(auto_counts),
                    "histogram": hist_auto,
                },
                "js_divergence": _js_divergence(hist_manual, hist_auto, epsilon),
                "epsilon": float(epsilon),
                "disabled": False,
            }
        except Exception as e:
            return {"disabled": False, "error": str(e)}

    @staticmethod
    def compare(manual_xodr: str, auto_xodr: str, *, epsilon: float = 1e-6) -> Dict[str, Any]:
        """Alias for compute() to match other gap modules."""
        return JunctionComplexityGap.compute(manual_xodr, auto_xodr, epsilon=epsilon)
