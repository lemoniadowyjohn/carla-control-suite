#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F2 — strict fallback policy for DEM elevation sampling.

Fallback chains that invent elevation values for a road are forbidden in
strict/release mode:

- flat (0.0) fallback sampler                                (flat)
- KD-tree nearest-neighbour extrapolation (default 2000 m)   (extrapolated)
- road-graph BFS propagation of a neighbour road's z         (propagated)
- global median of all sampled roads                         (median)
- hardcoded city constant (e.g. 375.0 m Ingolstadt)          (hardcoded)

A road whose elevation cannot be sampled directly from the DEM must fail the
run, never be assigned an invented value.  ``assert_no_fallback_violations``
implements the fail-closed gate; the QC record carries the evidence.

Policy modes (env ``UP_ELEVATION_FALLBACK_POLICY``):

- ``strict``  (default) — any invented value raises RuntimeError.
- ``lenient`` — legacy behaviour: log warnings only.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional


def elevation_fallback_policy() -> str:
    """'strict' by default; 'lenient' only via explicit opt-in."""
    mode = os.getenv("UP_ELEVATION_FALLBACK_POLICY", "").strip().lower()
    if mode in ("lenient", "legacy", "warn"):
        return "lenient"
    return "strict"


def fallback_kind_violations(
    *,
    extrapolated_road_ids: Optional[List[str]] = None,
    propagated_road_ids: Optional[List[str]] = None,
    unresolved_road_ids: Optional[List[str]] = None,
    flat_sampler_active: bool = False,
) -> Dict[str, List[str]]:
    """Classify forbidden fallback kinds by road id (deduplicated, sorted)."""
    ex = sorted(set(extrapolated_road_ids or []))
    pr = sorted(set(propagated_road_ids or []))
    un = sorted(set(unresolved_road_ids or []))
    flat = ["__flat_sampler__"] if flat_sampler_active else []
    return {
        "extrapolated": ex,
        "propagated": pr,
        "median_or_hardcoded": un,
        "flat_sampler": flat,
        "all_forbidden": sorted(set(ex + pr + un + flat)),
    }


def assert_no_fallback_violations(
    *,
    extrapolated_road_ids: Optional[List[str]] = None,
    propagated_road_ids: Optional[List[str]] = None,
    unresolved_road_ids: Optional[List[str]] = None,
    flat_sampler_active: bool = False,
    policy: Optional[str] = None,
) -> Dict[str, object]:
    """Fail closed when any road received invented elevation in strict mode.

    Returns the violation record (also when the run is lenient).
    """
    mode = policy or elevation_fallback_policy()
    violations = fallback_kind_violations(
        extrapolated_road_ids=extrapolated_road_ids,
        propagated_road_ids=propagated_road_ids,
        unresolved_road_ids=unresolved_road_ids,
        flat_sampler_active=flat_sampler_active,
    )
    forbidden = violations["all_forbidden"]
    if mode == "strict" and forbidden:
        detail = (
            f"extrapolated={violations['extrapolated']} "
            f"propagated={violations['propagated']} "
            f"median_or_hardcoded={violations['median_or_hardcoded']} "
            f"flat_sampler={violations['flat_sampler']}"
        )
        raise RuntimeError(
            "[ELEVATION][F2] Strict fallback policy: DEM elevation could not be "
            "established for roads that received invented values "
            f"(count={len(forbidden)}): {forbidden}. {detail}"
        )
    return {
        "policy": mode,
        "violations": violations,
        "violation_count": int(len(forbidden)),
        "passed": bool(not forbidden),
    }
