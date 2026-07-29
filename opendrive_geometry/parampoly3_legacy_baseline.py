"""Frozen adapters for the pre-migration production ParamPoly3 formulas.

Provenance:
  commit: 711580a3045be04fab606a6cb7d0a5c38b828440
  pose: ultimate_pipeline/quality/check_geometric_continuity.py
  curvature: ultimate_pipeline/domain_gap/curvature_gap.py

This module intentionally does not import the canonical evaluator.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

BASELINE_COMMIT = "711580a3045be04fab606a6cb7d0a5c38b828440"
BASELINE_POSE_SOURCE = "ultimate_pipeline/quality/check_geometric_continuity.py"
BASELINE_CURVATURE_SOURCE = "ultimate_pipeline/domain_gap/curvature_gap.py"


@dataclass(frozen=True)
class LegacyPose:
    x: float
    y: float
    hdg: float


def _norm_angle(angle: float) -> float:
    angle = (angle + math.pi) % (2.0 * math.pi) - math.pi
    if angle <= -math.pi:
        angle += 2.0 * math.pi
    return angle


def legacy_pose(record: dict, s_local: float) -> LegacyPose:
    """Exact pre-migration `_pose_param_poly3` behavior for valid records."""
    length = max(float(record["length"]), 1e-9)
    s_local = max(0.0, min(float(s_local), length))
    p_range = str(record.get("pRange") or "normalized").strip()
    p = s_local if p_range == "arcLength" else s_local / length

    u = (
        float(record["aU"])
        + float(record["bU"]) * p
        + float(record["cU"]) * p * p
        + float(record["dU"]) * p * p * p
    )
    v = (
        float(record["aV"])
        + float(record["bV"]) * p
        + float(record["cV"]) * p * p
        + float(record["dV"]) * p * p * p
    )
    du_dp = (
        float(record["bU"])
        + 2.0 * float(record["cU"]) * p
        + 3.0 * float(record["dU"]) * p * p
    )
    dv_dp = (
        float(record["bV"])
        + 2.0 * float(record["cV"]) * p
        + 3.0 * float(record["dV"]) * p * p
    )
    cos0 = math.cos(float(record["hdg0"]))
    sin0 = math.sin(float(record["hdg0"]))
    x = float(record["x0"]) + cos0 * u - sin0 * v
    y = float(record["y0"]) + sin0 * u + cos0 * v
    if abs(du_dp) < 1e-12 and abs(dv_dp) < 1e-12:
        heading = float(record["hdg0"])
    else:
        heading = _norm_angle(float(record["hdg0"]) + math.atan2(dv_dp, du_dp))
    return LegacyPose(x=x, y=y, hdg=heading)


def legacy_curvatures(record: dict, n_samples: int = 5) -> list[float]:
    """Exact pre-migration curvature formula and denominator policy."""
    p_max = (
        float(record["length"])
        if record.get("pRange", "arcLength") == "arcLength"
        else 1.0
    )
    if p_max <= 0.0 or n_samples <= 0:
        return []
    parameters = (
        [0.0]
        if n_samples == 1
        else [p_max * index / (n_samples - 1) for index in range(n_samples)]
    )
    result = []
    for p in parameters:
        du = record["bU"] + 2 * record["cU"] * p + 3 * record["dU"] * p**2
        dv = record["bV"] + 2 * record["cV"] * p + 3 * record["dV"] * p**2
        ddu = 2 * record["cU"] + 6 * record["dU"] * p
        ddv = 2 * record["cV"] + 6 * record["dV"] * p
        denominator = (du**2 + dv**2) ** 1.5
        if denominator < 1e-12:
            continue
        result.append(abs((du * ddv - dv * ddu) / denominator))
    return result
