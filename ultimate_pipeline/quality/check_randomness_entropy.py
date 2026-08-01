# ultimate_pipeline/quality/check_randomness_entropy.py

from __future__ import annotations

import math
from collections import Counter
from typing import Dict
from xml.etree.ElementTree import Element


class RandomnessEntropyMetric:
    """
    Compute a naive entropy over road headings to detect "too regular" maps.

    This is NOT deep theory – it's a heuristic: if all headings are aligned
    on a grid (0/90deg), entropy will be low.
    """

    @staticmethod
    def compute(root: Element) -> float:
        headings = []

        for geo in root.findall(".//planView/geometry"):
            hdg = geo.get("hdg")
            if hdg is None:
                continue
            try:
                h = float(hdg)
            except Exception:
                continue
            headings.append(h)

        if not headings:
            return 0.0

        # Quantize into bins
        bin_size = math.pi / 12.0  # 15 degrees
        bins = [int(h / bin_size) for h in headings]
        counts = Counter(bins)
        total = float(sum(counts.values()))

        entropy = 0.0
        for c in counts.values():
            p = c / total
            entropy -= p * math.log2(p)

        # Normalize by max entropy for this number of bins
        n_bins = len(counts)
        if n_bins > 1:
            entropy /= math.log2(n_bins)

        return float(entropy)
