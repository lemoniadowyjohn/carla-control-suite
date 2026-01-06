# ultimate_pipeline/tiling/tile_matcher.py

import os
import re
from typing import Dict, Tuple
import math


class TileMatcher:
    """
    Minimal deterministic tile matcher.
    Maps manual tile_i_j.xodr → closest auto tile based on (i,j) index.
    """

    TILE_RE = re.compile(r".*tile_(-?\d+)_(-?\d+)\.xodr$")

    @staticmethod
    def _idx_of(path):
        m = TileMatcher.TILE_RE.match(os.path.basename(path))
        if not m:
            return None
        return int(m.group(1)), int(m.group(2))

    @staticmethod
    def match(manual_dir: str, auto_dir: str) -> Dict[str, str]:
        """
        Returns {manual_tile_name: auto_tile_name}
        """

        manual_tiles = [f for f in os.listdir(manual_dir) if f.endswith(".xodr")]
        auto_tiles   = [f for f in os.listdir(auto_dir) if f.endswith(".xodr")]

        manual_idx = {t: TileMatcher._idx_of(t) for t in manual_tiles}
        auto_idx   = {t: TileMatcher._idx_of(t) for t in auto_tiles}

        out = {}

        for m_name, m_idx in manual_idx.items():
            if m_idx is None:
                continue

            # find nearest auto tile by Euclidean index distance
            best = None
            best_dist = 1e9

            for a_name, a_idx in auto_idx.items():
                if a_idx is None:
                    continue
                d = math.dist(m_idx, a_idx)
                if d < best_dist:
                    best = a_name
                    best_dist = d

            if best:
                out[m_name] = best

        return out
