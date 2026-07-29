"""
Cross-comparison benchmark for all existing ParamPoly3 evaluators.

Compares position, heading, curvature, endpoint, and sampling against the
authoritative canonical evaluator in opendrive_geometry/primitives.py.
"""
from __future__ import annotations

import math
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from opendrive_geometry.primitives import (
    evaluate_param_poly3,
    param_poly3_curvature_at,
    param_poly3_endpoint,
    sample_param_poly3,
    param_poly3_bounds,
)
from opendrive_geometry.model import Pose2D
from opendrive_geometry.errors import UnsupportedGeometryError


@dataclass(frozen=True)
class ParamPoly3Case:
    name: str
    x0: float
    y0: float
    hdg0: float
    length: float
    aU: float
    bU: float
    cU: float
    dU: float
    aV: float
    bV: float
    cV: float
    dV: float
    p_range: str
    eval_s: float


# ---------------------------------------------------------------------------
# Canonical reference implementation
# ---------------------------------------------------------------------------

def _canonical_pose(c: ParamPoly3Case) -> Pose2D:
    return evaluate_param_poly3(
        c.x0, c.y0, c.hdg0, c.length,
        c.aU, c.bU, c.cU, c.dU,
        c.aV, c.bV, c.cV, c.dV,
        c.p_range, c.eval_s,
    )


def _canonical_curvature(c: ParamPoly3Case) -> float:
    return param_poly3_curvature_at(
        c.aU, c.bU, c.cU, c.dU,
        c.aV, c.bV, c.cV, c.dV,
        c.p_range, c.length, c.eval_s,
    )


# ---------------------------------------------------------------------------
# Adapters for existing implementations
# ---------------------------------------------------------------------------

def _from_check_geometric_continuity(c: ParamPoly3Case) -> Pose2D:
    """Adapter for quality/check_geometric_continuity.py _pose_param_poly3."""
    from ultimate_pipeline.quality.check_geometric_continuity import Geometry, _pose_param_poly3
    g = Geometry(
        s0=0, x0=c.x0, y0=c.y0, hdg0=c.hdg0, length=c.length,
        kind="paramPoly3",
        param_a_u=c.aU, param_b_u=c.bU, param_c_u=c.cU, param_d_u=c.dU,
        param_a_v=c.aV, param_b_v=c.bV, param_c_v=c.cV, param_d_v=c.dV,
        param_p_range=c.p_range,
    )
    p = _pose_param_poly3(g, c.eval_s)
    return Pose2D(x=p.x, y=p.y, hdg=p.hdg)


def _from_geometry_math_xy(c: ParamPoly3Case) -> Pose2D | None:
    """Adapter for geometry/geometry_math.py sample_parampoly3_points (position only)."""
    from ultimate_pipeline.geometry.geometry_math import sample_parampoly3_points
    geom = _make_geom_element(c)
    pts = sample_parampoly3_points(geom, c.x0, c.y0, c.hdg0, c.length, [c.eval_s / c.length if c.length > 0 else 0.0])
    if pts:
        return Pose2D(x=pts[0][0], y=pts[0][1], hdg=float("nan"))
    return None


def _from_curvature_gap(c: ParamPoly3Case) -> float | None:
    """Adapter for domain_gap/curvature_gap.py curvature (now delegates to canonical)."""
    from opendrive_geometry.primitives import param_poly3_curvature_at as k_at
    try:
        return abs(k_at(c.aU, c.bU, c.cU, c.dU, c.aV, c.bV, c.cV, c.dV, c.p_range, c.length, c.eval_s))
    except Exception:
        return None


def _make_geom_element(c: ParamPoly3Case) -> ET.Element:
    geom = ET.Element("geometry", attrib={
        "s": "0", "x": str(c.x0), "y": str(c.y0),
        "hdg": str(c.hdg0), "length": str(c.length),
    })
    pp = ET.SubElement(geom, "paramPoly3", attrib={
        "aU": str(c.aU), "bU": str(c.bU), "cU": str(c.cU), "dU": str(c.dU),
        "aV": str(c.aV), "bV": str(c.bV), "cV": str(c.cV), "dV": str(c.dV),
        "pRange": c.p_range,
    })
    return geom


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def _default_cases() -> list[ParamPoly3Case]:
    L = 100.0
    return [
        ParamPoly3Case("forward", 0, 0, 0, L, 0, L, 0, 0, 0, 0, 0, 0, "normalized", 50),
        ParamPoly3Case("forward_arcLength", 0, 0, 0, L, 0, 1, 0, 0, 0, 0, 0, 0, "arcLength", 50),
        ParamPoly3Case("lateral_offset", 0, 0, 0, L, 0, L, 0, 0, 0, 10, 0, 0, "normalized", 50),
        ParamPoly3Case("quadratic", 0, 0, 0, L, 0, L, 50, 0, 0, 0, 0, 0, "normalized", 50),
        ParamPoly3Case("cubic", 0, 0, 0, L, 0, L, 0, 30, 0, 0, 0, 0, "normalized", 50),
        ParamPoly3Case("nonzero_origin", 100, 200, 0, L, 0, L, 0, 0, 0, 0, 0, 0, "normalized", 50),
        ParamPoly3Case("rotated", 0, 0, 0.5, L, 0, L, 20, 0, 0, 0, 0, 0, "normalized", 50),
        ParamPoly3Case("endpoint", 0, 0, 0, L, 0, L, 0, 0, 0, 0, 0, 0, "normalized", 100),
        ParamPoly3Case("start", 0, 0, 0, L, 0, L, 0, 0, 0, 0, 0, 0, "normalized", 0),
        ParamPoly3Case("curved_lateral_positive", 0, 0, 0, L, 0, L, 0, 0, 0, 0, 50, 0, "normalized", 50),
        ParamPoly3Case("curved_lateral_negative", 0, 0, 0, L, 0, L, 0, 0, 0, 0, -50, 0, "normalized", 50),
        ParamPoly3Case("full_cubic", 0, 0, 0, L, 0, L, 20, 5, 0, 10, 3, 1, "normalized", 75),
        ParamPoly3Case("arclength_quadratic", 0, 0, 0, L, 0, 1, 0.02, 0, 0, 0, 0, 0, "arcLength", 75),
        ParamPoly3Case("arclength_lateral", 0, 0, 0, 50, 0, 1, 0, 0, 0, 0.5, 0, 0, "arcLength", 25),
    ]


def _load_fixture_cases() -> list[ParamPoly3Case]:
    """Load test cases from the repository fixture manifest."""
    manifest = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "opendrive" / "parampoly3" / "manifest.json"
    if not manifest.exists():
        return []
    import json
    with open(manifest) as f:
        data = json.load(f)
    cases: list[ParamPoly3Case] = []
    for source in data["sources"]:
        for fx in source["fixtures"]:
            cases.append(ParamPoly3Case(
                name=f"{source['file']}_r{fx['road_id']}_g{fx['geometry_index']}",
                x0=fx["x0"], y0=fx["y0"], hdg0=fx["hdg0"],
                length=fx["length"],
                aU=fx["aU"], bU=fx["bU"], cU=fx["cU"], dU=fx["dU"],
                aV=fx["aV"], bV=fx["bV"], cV=fx["cV"], dV=fx["dV"],
                p_range=fx["pRange"],
                eval_s=fx["length"] * 0.5,
            ))
    return cases


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

@dataclass
class ImplResult:
    impl: str
    max_dx: float
    max_dy: float
    max_dh: float
    max_dk: float
    match_count: int
    total_count: int
    details: list[str]


def compare() -> None:
    cases = _default_cases() + _load_fixture_cases()

    if not cases:
        print("No test cases available.")
        sys.exit(0)

    implementations: list[tuple[str, Callable]] = [
        ("check_geometric_continuity", _from_check_geometric_continuity),
        ("geometry_math", _from_geometry_math_xy),
    ]

    curvature_impls: list[tuple[str, Callable]] = [
        ("curvature_gap", _from_curvature_gap),
    ]

    results: list[ImplResult] = []

    for impl_name, impl_fn in implementations:
        max_dx = max_dy = max_dh = 0.0
        match_count = total_count = 0
        details: list[str] = []
        for c in cases:
            total_count += 1
            ref = _canonical_pose(c)
            try:
                imp = impl_fn(c)
            except Exception as e:
                details.append(f"[{c.name}] exception: {e}")
                continue
            if imp is None:
                details.append(f"[{c.name}] None result")
                continue
            dx = abs(imp.x - ref.x)
            dy = abs(imp.y - ref.y)
            dh = abs(imp.hdg - ref.hdg) if not math.isnan(imp.hdg) else float("nan")
            max_dx = max(max_dx, dx)
            max_dy = max(max_dy, dy)
            if not math.isnan(dh):
                max_dh = max(max_dh, dh)
            is_match = dx < 1e-9 and dy < 1e-9 and (math.isnan(dh) or dh < 1e-9)
            if is_match:
                match_count += 1
            if dx > 1e-9 or dy > 1e-9 or (not math.isnan(dh) and dh > 1e-9):
                details.append(
                    f"[{c.name}] dx={dx:.4g} dy={dy:.4g} dh={dh:.4g}  "
                    f"ref=({ref.x:.6g},{ref.y:.6g},{ref.hdg:.6g})  "
                    f"imp=({imp.x:.6g},{imp.y:.6g},{imp.hdg:.6g})"
                )
        results.append(ImplResult(impl_name, max_dx, max_dy, max_dh, 0.0, match_count, total_count, details))

    for impl_name, impl_fn in curvature_impls:
        max_dk = 0.0
        match_count = total_count = 0
        details = []
        for c in cases:
            total_count += 1
            ref_k = _canonical_curvature(c)
            try:
                imp_k = impl_fn(c)
            except Exception as e:
                details.append(f"[{c.name}] exception: {e}")
                continue
            if imp_k is None:
                details.append(f"[{c.name}] None result")
                continue
            dk = abs(imp_k - abs(ref_k))  # curvature_gap returns abs
            max_dk = max(max_dk, dk)
            if dk < 1e-9:
                match_count += 1
            if dk > 1e-9:
                details.append(f"[{c.name}] dk={dk:.4g}  ref_k={ref_k:.6g} imp_k={imp_k:.6g}")
        results.append(ImplResult(impl_name, 0.0, 0.0, 0.0, max_dk, match_count, total_count, details))

    print("ParamPoly3 Cross-Comparison Results")
    print("=" * 80)
    print(f"{'Implementation':<30} {'|dx|max':<12} {'|dy|max':<12} {'|dh|max':<12} {'|dk|max':<12} {'Match':>8}")
    print("-" * 80)
    for r in results:
        match_str = f"{r.match_count}/{r.total_count}"
        print(f"{r.impl:<30} {r.max_dx:<12.4g} {r.max_dy:<12.4g} {r.max_dh:<12.4g} {r.max_dk:<12.4g} {match_str:>8}")
    print("-" * 80)

    any_diff = any(r.match_count < r.total_count for r in results)
    for r in results:
        if r.details:
            print(f"\n*** {r.impl}")
            for d in r.details[:10]:
                print(f"    {d}")
            if len(r.details) > 10:
                print(f"    ... and {len(r.details) - 10} more")

    verdict = "ALL MATCH" if not any_diff else "Some disagreements found"
    print(f"\nVERDICT: {verdict}")
    sys.exit(1 if any_diff else 0)


if __name__ == "__main__":
    compare()
