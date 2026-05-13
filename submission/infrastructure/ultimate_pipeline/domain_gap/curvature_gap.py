from __future__ import annotations

"""
Curvature domain-gap metric.

Complexity notes:
- Extraction: O(n) geometries
- Histogramming: O(n)
- KL divergence: O(bins)

This metric is scale-invariant and complementary to geometry RMSE.
"""

import time
import xml.etree.ElementTree as ET
import numpy as np
from typing import Dict, List, Optional

from ultimate_pipeline.config.settings import SETTINGS


# ==============================
# Helpers
# ==============================

def _sample_parampoly3_curvatures(
    geom: ET.Element,
    length: float,
    n_samples: int = 5,
) -> List[float]:
    """
    Sample absolute curvature at n_samples evenly-spaced parameter values
    along a paramPoly3 geometry segment.
    Returns [] if the element is missing required attributes or the
    denominator is numerically zero at all sampled points.
    """
    pp = geom.find("paramPoly3")
    if pp is None:
        return []
    try:
        bU = float(pp.get("bU", 0))
        cU = float(pp.get("cU", 0))
        dU = float(pp.get("dU", 0))
        bV = float(pp.get("bV", 0))
        cV = float(pp.get("cV", 0))
        dV = float(pp.get("dV", 0))
    except (TypeError, ValueError):
        return []
    p_range = pp.get("pRange", "arcLength")
    p_max = float(length) if p_range == "arcLength" else 1.0
    if p_max <= 0:
        return []
    result: List[float] = []
    for p in np.linspace(0.0, p_max, n_samples):
        du = bU + 2 * cU * p + 3 * dU * p**2
        dv = bV + 2 * cV * p + 3 * dV * p**2
        ddu = 2 * cU + 6 * dU * p
        ddv = 2 * cV + 6 * dV * p
        denom = (du**2 + dv**2) ** 1.5
        if denom < 1e-12:
            continue
        k = abs((du * ddv - dv * ddu) / denom)
        result.append(float(k))
    return result


def _extract_curvatures(
    root: ET.Element,
    *,
    include_lines: bool = False,
    max_geoms: Optional[int] = None,
) -> List[float]:
    """
    Extract absolute curvature values.

    include_lines:
        if True, straight segments are included as curvature=0

    max_geoms:
        hard cap for safety (laptop / debug)
    """
    values: List[float] = []
    geoms = root.findall(".//geometry")

    if max_geoms:
        geoms = geoms[:max_geoms]

    for geom in geoms:
        arc = geom.find("arc")
        if arc is not None:
            try:
                k = float(arc.get("curvature", "0"))
                values.append(abs(k))
            except Exception:
                continue
        elif geom.find("paramPoly3") is not None:
            try:
                length = float(geom.get("length", 0) or 0)
            except (TypeError, ValueError):
                length = 0.0
            sampled = _sample_parampoly3_curvatures(geom, length)
            values.extend(sampled)
            if include_lines and not sampled:
                values.append(0.0)
        elif include_lines:
            # straight geometry → zero curvature
            values.append(0.0)

    return values


def _compute_kl_div(p: np.ndarray, q: np.ndarray) -> float:
    """
    KL divergence with numerical stabilization.
    """
    eps = 1e-12
    p = p + eps
    q = q + eps
    return float(np.sum(p * np.log(p / q)))


# ==============================
# Curvature Gap
# ==============================

class CurvatureGap:
    """
    Curvature distribution gap between two OpenDRIVE maps.

    Measures:
        - mean curvature
        - std curvature
        - delta mean
        - KL divergence (raw + normalized)
        - runtime

    Controlled via SETTINGS:
        CURVATURE_BINS
        CURVATURE_INCLUDE_LINES
        CURVATURE_MAX_GEOMS
    """

    @staticmethod
    def compute(
        manual_xodr: str,
        auto_xodr: str,
    ) -> Dict:

        t0 = time.perf_counter()

        # ------------------------------
        # Settings
        # ------------------------------
        bins = getattr(SETTINGS, "CURVATURE_BINS", 60)
        include_lines = getattr(SETTINGS, "CURVATURE_INCLUDE_LINES", False)
        max_geoms = getattr(SETTINGS, "CURVATURE_MAX_GEOMS", None)

        # ------------------------------
        # Parse XODR
        # ------------------------------
        rm = ET.parse(manual_xodr).getroot()
        ra = ET.parse(auto_xodr).getroot()

        # ------------------------------
        # Extract curvature values
        # ------------------------------
        m_vals = _extract_curvatures(
            rm,
            include_lines=include_lines,
            max_geoms=max_geoms,
        )
        a_vals = _extract_curvatures(
            ra,
            include_lines=include_lines,
            max_geoms=max_geoms,
        )

        if not m_vals or not a_vals:
            return {
                "disabled": True,
                "reason": "no curvature data",
            }

        m_vals = np.asarray(m_vals, dtype=float)
        a_vals = np.asarray(a_vals, dtype=float)

        # ------------------------------
        # Summary statistics
        # ------------------------------
        mean_m = float(np.mean(m_vals))
        mean_a = float(np.mean(a_vals))
        std_m = float(np.std(m_vals))
        std_a = float(np.std(a_vals))

        # ------------------------------
        # Histogram domain
        # ------------------------------
        max_val = max(m_vals.max(), a_vals.max(), 1e-6)

        hist_m, bin_edges = np.histogram(
            m_vals,
            bins=bins,
            range=(0.0, max_val),
            density=True,
        )
        hist_a, _ = np.histogram(
            a_vals,
            bins=bin_edges,
            density=True,
        )

        kl = _compute_kl_div(hist_m, hist_a)

        # Normalize KL by bin count (comparability across configs)
        kl_norm = kl / np.log(bins)

        runtime = time.perf_counter() - t0

        return {
            "mean_manual": mean_m,
            "mean_auto": mean_a,
            "std_manual": std_m,
            "std_auto": std_a,
            "delta_mean": mean_a - mean_m,
            "kl_divergence": kl,
            "kl_divergence_norm": kl_norm,
            "bins": bins,
            "include_lines": include_lines,
            "samples_manual": int(len(m_vals)),
            "samples_auto": int(len(a_vals)),
            "runtime_sec": round(runtime, 3),
        }
