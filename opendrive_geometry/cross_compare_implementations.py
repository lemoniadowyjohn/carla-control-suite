"""
FOUNDATION-01A/G01 Deliverable: Cross-comparison benchmark against all existing
line/arc evaluators in the repository.

Distinguishes expected policy differences (e.g. different EPS thresholds)
from actual formula defects. Includes ParamPoly3 test coverage.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from typing import Callable

from opendrive_geometry.primitives import evaluate_line, evaluate_arc, evaluate_param_poly3, EPS

# Tolerances for declaring a difference a "defect" rather than a policy difference
POSITION_TOLERANCE = 1e-6  # 1 micron — any position difference below this is a policy/epsilon effect
HEADING_TOLERANCE = 1e-6   # ~0.000057 degrees


@dataclass(frozen=True)
class TestCase:
    name: str
    x0: float
    y0: float
    hdg0: float
    length: float
    curvature: float
    eval_s: float


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
    p_range: str | None
    eval_s: float


# ---------------------------------------------------------------------------
# Line/Arc test suite — 20 diverse cases
# ---------------------------------------------------------------------------
TEST_CASES: list[TestCase] = [
    TestCase("line_forward", 0.0, 0.0, 0.0, 100.0, 0.0, 50.0),
    TestCase("line_angled", 10.0, 20.0, math.pi / 6, 80.0, 0.0, 40.0),
    TestCase("line_backward", 5.0, 5.0, math.pi, 30.0, 0.0, 15.0),
    TestCase("line_negative_hdg", 0.0, 0.0, -0.5, 50.0, 0.0, 25.0),
    TestCase("line_start", 1.0, 2.0, 0.3, 100.0, 0.0, 0.0),
    TestCase("line_end", 1.0, 2.0, 0.3, 100.0, 0.0, 100.0),
    TestCase("arc_gentle_left", 0.0, 0.0, 0.0, 100.0, 0.005, 50.0),
    TestCase("arc_gentle_right", 0.0, 0.0, 0.0, 100.0, -0.005, 50.0),
    TestCase("arc_quarter_circle", 0.0, 0.0, 0.0, math.pi / 2 * 10.0, 0.1, math.pi / 2 * 10.0),
    TestCase("arc_half_circle", 0.0, 0.0, 0.0, math.pi * 5.0, 0.2, math.pi * 5.0),
    TestCase("arc_tight_left", 100.0, 200.0, 1.0, 30.0, 0.05, 15.0),
    TestCase("arc_tight_right", 100.0, 200.0, 1.0, 30.0, -0.05, 15.0),
    TestCase("arc_offset", 50.0, -30.0, 0.8, 60.0, 0.02, 30.0),
    TestCase("arc_start", 5.0, 5.0, 0.5, 100.0, 0.01, 0.0),
    TestCase("arc_end", 5.0, 5.0, 0.5, 100.0, 0.01, 100.0),
    TestCase("arc_almost_line_1e_8", 0.0, 0.0, 0.0, 100.0, 1e-8, 50.0),
    TestCase("arc_almost_line_1e_10", 0.0, 0.0, 0.0, 100.0, 1e-10, 50.0),
    TestCase("arc_almost_line_1e_12", 0.0, 0.0, 0.0, 100.0, 1e-12, 50.0),
    TestCase("arc_almost_line_neg_1e_9", 0.0, 0.0, 0.0, 100.0, -1e-9, 50.0),
    TestCase("arc_exact_zero", 0.0, 0.0, 0.0, 100.0, 0.0, 50.0),
]

# ---------------------------------------------------------------------------
# ParamPoly3 test cases
# ---------------------------------------------------------------------------
PARAMPOLY3_CASES: list[ParamPoly3Case] = [
    ParamPoly3Case("pp3_arcLength_mid", 0.0, 0.0, 0.0, 50.0,
                   0.0, 1.0, 0.0, 0.0,
                   0.0, 0.0, 0.001, 0.0,
                   "arcLength", 25.0),
    ParamPoly3Case("pp3_arcLength_end", 0.0, 0.0, 0.0, 50.0,
                   0.0, 1.0, 0.0, 0.0,
                   0.0, 0.0, 0.001, 0.0,
                   "arcLength", 50.0),
    ParamPoly3Case("pp3_normalized_mid", 0.0, 0.0, 0.0, 100.0,
                   0.0, 100.0, 0.0, 0.0,
                   0.0, 0.0, 100.0, 0.0,
                   "normalized", 50.0),
    ParamPoly3Case("pp3_normalized_end", 0.0, 0.0, 0.0, 100.0,
                   0.0, 100.0, 0.0, 0.0,
                   0.0, 0.0, 100.0, 0.0,
                   "normalized", 100.0),
    ParamPoly3Case("pp3_offset_origin", 100.0, 200.0, 0.5, 75.0,
                   0.0, 1.0, 0.01, -0.0001,
                   0.0, 0.5, 0.005, 0.0001,
                   "arcLength", 37.5),
]


# ---------------------------------------------------------------------------
# Reference: the authoritative evaluator (canonical)
# ---------------------------------------------------------------------------
def reference_eval(tc: TestCase) -> tuple[float, float, float]:
    if abs(tc.curvature) < EPS:
        p = evaluate_line(tc.x0, tc.y0, tc.hdg0, tc.length, tc.eval_s)
    else:
        p = evaluate_arc(tc.x0, tc.y0, tc.hdg0, tc.length, tc.curvature, tc.eval_s)
    return (p.x, p.y, p.hdg)


def reference_pp3_eval(tc: ParamPoly3Case) -> tuple[float, float, float]:
    p = evaluate_param_poly3(
        tc.x0, tc.y0, tc.hdg0, tc.length,
        tc.aU, tc.bU, tc.cU, tc.dU,
        tc.aV, tc.bV, tc.cV, tc.dV,
        tc.p_range, tc.eval_s,
    )
    return (p.x, p.y, p.hdg)


# ---------------------------------------------------------------------------
# Existing implementation wrappers
# Each takes x0, y0, hdg0, length, curvature, s and returns (x, y, hdg)
# ---------------------------------------------------------------------------

def impl_geometry_calculator(x0, y0, h0, L, k, s):
    """geometry_math.py GeometryCalculator._integrate_arc / _integrate_line"""
    if abs(k) < 1e-9:
        return (x0 + s * math.cos(h0), y0 + s * math.sin(h0), h0)
    h = h0 + s * k
    return (
        x0 + (math.sin(h) - math.sin(h0)) / k,
        y0 + (math.cos(h0) - math.cos(h)) / k,
        h,
    )


def impl_geometry_seam_checker(x0, y0, h0, L, k, s):
    """tile_validation/geometry_seam_checker.py R-based formula"""
    if abs(k) < 1e-12:
        return (x0 + s * math.cos(h0), y0 + s * math.sin(h0), h0)
    R = 1.0 / k
    theta = s * k
    return (
        x0 + R * (math.sin(h0 + theta) - math.sin(h0)),
        y0 - R * (math.cos(h0 + theta) - math.cos(h0)),
        h0 + theta,
    )


def impl_local_frame(x0, y0, h0, L, k, s):
    """check_geometric_continuity.py local-frame formula (EPS=1e-12)"""
    if abs(k) < 1e-12:
        return (x0 + s * math.cos(h0), y0 + s * math.sin(h0), h0)
    h = h0 + k * s
    dx_local = math.sin(k * s) / k
    dy_local = (1.0 - math.cos(k * s)) / k
    cos0 = math.cos(h0)
    sin0 = math.sin(h0)
    return (
        x0 + cos0 * dx_local - sin0 * dy_local,
        y0 + sin0 * dx_local + cos0 * dy_local,
        h,
    )


def impl_lane_seam_checker(x0, y0, h0, L, k, s):
    """geometry/lane_seam_checker.py R-based formula (EPS=1e-9)"""
    if abs(k) < 1e-9:
        return (x0 + s * math.cos(h0), y0 + s * math.sin(h0), h0)
    R = 1.0 / k
    theta = s * k
    return (
        x0 + R * (math.sin(h0 + theta) - math.sin(h0)),
        y0 - R * (math.cos(h0 + theta) - math.cos(h0)),
        h0 + theta,
    )


def impl_elevation_gap(x0, y0, h0, L, k, s):
    """domain_gap/elevation_gap.py canonical formula (EPS=1e-12)"""
    if abs(k) <= 1e-12:
        return (x0 + s * math.cos(h0), y0 + s * math.sin(h0), h0)
    theta = h0 + k * s
    return (
        x0 + (math.sin(theta) - math.sin(h0)) / k,
        y0 - (math.cos(theta) - math.cos(h0)) / k,
        theta,
    )


def impl_geo_alignment(x0, y0, h0, L, k, s):
    """domain_gap/geo_alignment.py canonical formula (EPS=1e-12)"""
    if abs(k) <= 1e-12:
        return (x0 + s * math.cos(h0), y0 + s * math.sin(h0), h0)
    theta = h0 + k * s
    return (
        x0 + (math.sin(theta) - math.sin(h0)) / k,
        y0 - (math.cos(theta) - math.cos(h0)) / k,
        theta,
    )


def impl_map_plotter(x0, y0, h0, L, k, s):
    """visualization/map_plotter.py _sample_geometry (line branch + arc with line fallback at 1e-12)"""
    if abs(k) < 1e-12:
        return (x0 + s * math.cos(h0), y0 + s * math.sin(h0), h0)
    inv_c = 1.0 / k
    heading = h0 + s * k
    return (
        x0 + (math.sin(heading) - math.sin(h0)) * inv_c,
        y0 + (math.cos(h0) - math.cos(heading)) * inv_c,
        heading,
    )


def impl_map_diff(x0, y0, h0, L, k, s):
    """visualization/map_diff.py _sample_geometry (line + arc with line fallback at 1e-12)"""
    if abs(k) < 1e-12:
        return (x0 + s * math.cos(h0), y0 + s * math.sin(h0), h0)
    inv_c = 1.0 / k
    heading = h0 + s * k
    return (
        x0 + (math.sin(heading) - math.sin(h0)) * inv_c,
        y0 + (math.cos(h0) - math.cos(heading)) * inv_c,
        heading,
    )


def impl_dem_coverage(x0, y0, h0, L, k, s):
    """quality/check_dem_full_coverage.py (EPS=1e-9)"""
    if abs(k) < 1e-9:
        return (x0 + s * math.cos(h0), y0 + s * math.sin(h0), h0)
    theta = h0 + k * s
    return (
        x0 + (math.sin(theta) - math.sin(h0)) / k,
        y0 + (math.cos(h0) - math.cos(theta)) / k,
        theta,
    )


def impl_lane_overlay(x0, y0, h0, L, k, s):
    """visualization/lane_overlay.py endpoint helper (EPS=1e-9)"""
    if abs(k) < 1e-9:
        return (x0 + s * math.cos(h0), y0 + s * math.sin(h0), h0)
    h2 = h0 + k * s
    return (
        x0 + (math.sin(h2) - math.sin(h0)) / k,
        y0 - (math.cos(h2) - math.cos(h0)) / k,
        h2,
    )


def impl_heatmap_generator(x0, y0, h0, L, k, s):
    """visualization/heatmap_generator.py endpoint helper (EPS=1e-9)"""
    if abs(k) < 1e-9:
        return (x0 + s * math.cos(h0), y0 + s * math.sin(h0), h0)
    h2 = h0 + k * s
    return (
        x0 + (math.sin(h2) - math.sin(h0)) / k,
        y0 - (math.cos(h2) - math.cos(h0)) / k,
        h2,
    )


def impl_junction_connector_rebuild(x0, y0, h0, L, k, s):
    """topology/junction_connector_rebuild.py local-frame (EPS=1e-12)"""
    if abs(k) < 1e-12:
        return (x0 + s * math.cos(h0), y0 + s * math.sin(h0), h0)
    h = h0 + k * s
    dx_local = math.sin(k * s) / k
    dy_local = (1.0 - math.cos(k * s)) / k
    cos0 = math.cos(h0)
    sin0 = math.sin(h0)
    return (
        x0 + cos0 * dx_local - sin0 * dy_local,
        y0 + sin0 * dx_local + cos0 * dy_local,
        h,
    )


def impl_canonical(x0, y0, h0, L, k, s):
    """opendrive_geometry/primitives.py authoritative evaluator (EPS=1e-12)"""
    if abs(k) < EPS:
        p = evaluate_line(x0, y0, h0, L, s)
    else:
        p = evaluate_arc(x0, y0, h0, L, k, s)
    return (p.x, p.y, p.hdg)


# ---------------------------------------------------------------------------
# Registry of implementations to compare
# Each entry: (name, source, fn, eps, is_read_only, is_active)
# ---------------------------------------------------------------------------
@dataclass
class ImplEntry:
    name: str
    source: str
    fn: Callable
    eps: float
    is_read_only: bool
    is_active: bool  # True if code is in active call path (not stale mirror)


IMPLEMENTATIONS: list[ImplEntry] = [
    ImplEntry("geometry_calculator", "geometry/geometry_math.py:80-116 (EPS=1e-9)", impl_geometry_calculator, 1e-9, False, True),
    ImplEntry("geometry_seam_checker", "tile_validation/geometry_seam_checker.py (EPS=1e-12)", impl_geometry_seam_checker, 1e-12, True, False),
    ImplEntry("local_frame", "quality/check_geometric_continuity.py:98-117 (EPS=1e-12)", impl_local_frame, 1e-12, False, True),
    ImplEntry("lane_seam_checker", "geometry/lane_seam_checker.py (EPS=1e-9)", impl_lane_seam_checker, 1e-9, True, False),
    ImplEntry("elevation_gap", "domain_gap/elevation_gap.py (EPS=1e-12)", impl_elevation_gap, 1e-12, True, True),
    ImplEntry("geo_alignment", "domain_gap/geo_alignment.py (EPS=1e-12)", impl_geo_alignment, 1e-12, True, True),
    ImplEntry("dem_coverage", "quality/check_dem_full_coverage.py (EPS=1e-9)", impl_dem_coverage, 1e-9, True, False),
    ImplEntry("lane_overlay", "visualization/lane_overlay.py (EPS=1e-9)", impl_lane_overlay, 1e-9, True, True),
    ImplEntry("heatmap_generator", "visualization/heatmap_generator.py (EPS=1e-9)", impl_heatmap_generator, 1e-9, True, True),
    ImplEntry("junction_connector_rebuild", "topology/junction_connector_rebuild.py (EPS=1e-12)", impl_junction_connector_rebuild, 1e-12, False, True),
    ImplEntry("map_plotter", "visualization/map_plotter.py (line+arc, delegates to canonical)", impl_map_plotter, 1e-12, True, True),
    ImplEntry("map_diff", "visualization/map_diff.py (line+arc, delegates to canonical)", impl_map_diff, 1e-12, True, True),
    ImplEntry("canonical", "opendrive_geometry/primitives.py (EPS=1e-12)", impl_canonical, EPS, True, True),
]


# Active read-only consumers (must agree within declared contracts)
ACTIVE_READ_ONLY_CONSUMERS = [e for e in IMPLEMENTATIONS if e.is_read_only and e.is_active]


# ---------------------------------------------------------------------------
# Classify a difference
# ---------------------------------------------------------------------------
def classify_diff(dx: float, dy: float, dh: float, impl_eps: float) -> str:
    """Classify a difference as expected policy difference or formula defect."""
    if dx > POSITION_TOLERANCE or dy > POSITION_TOLERANCE:
        return "FORMULA_DEFECT"
    if dh > HEADING_TOLERANCE:
        return "FORMULA_DEFECT"
    # All remaining differences are below tolerance — expected policy/epsilon effects
    return "EXPECTED_POLICY"


# ---------------------------------------------------------------------------
# Run line/arc comparison
# ---------------------------------------------------------------------------
def run_comparison() -> list[dict]:
    results: list[dict] = []
    for entry in IMPLEMENTATIONS:
        max_dx = max_dy = max_dh = 0.0
        worst_x = worst_y = worst_h = ""
        total_cases = len(TEST_CASES)
        diffs: list[dict] = []
        defect_cases = 0
        policy_cases = 0

        for tc in TEST_CASES:
            ref = reference_eval(tc)
            imp = entry.fn(tc.x0, tc.y0, tc.hdg0, tc.length, tc.curvature, tc.eval_s)
            dx = abs(ref[0] - imp[0])
            dy = abs(ref[1] - imp[1])
            dh = abs(ref[2] - imp[2])
            if dx > max_dx:
                max_dx = dx
                worst_x = tc.name
            if dy > max_dy:
                max_dy = dy
                worst_y = tc.name
            if dh > max_dh:
                max_dh = dh
                worst_h = tc.name
            if dx > 0 or dy > 0 or dh > 0:
                classification = classify_diff(dx, dy, dh, entry.eps)
                if classification == "FORMULA_DEFECT":
                    defect_cases += 1
                else:
                    policy_cases += 1
                diffs.append({
                    "case": tc.name,
                    "dx": dx, "dy": dy, "dh": dh,
                    "ref": {"x": ref[0], "y": ref[1], "h": ref[2]},
                    "imp": {"x": imp[0], "y": imp[1], "h": imp[2]},
                    "classification": classification,
                })

        matching = total_cases - len(diffs)
        results.append({
            "name": entry.name,
            "source": entry.source,
            "eps": entry.eps,
            "is_read_only": entry.is_read_only,
            "is_active": entry.is_active,
            "max_dx": max_dx,
            "max_dy": max_dy,
            "max_dh": max_dh,
            "worst_x": worst_x,
            "worst_y": worst_y,
            "worst_h": worst_h,
            "diffs": diffs,
            "matching": matching,
            "total": total_cases,
            "all_match": matching == total_cases,
            "defect_cases": defect_cases,
            "policy_cases": policy_cases,
        })
    return results


# ---------------------------------------------------------------------------
# Run ParamPoly3 comparison (canonical self-test only)
# ---------------------------------------------------------------------------
def run_parampoly3_self_test() -> list[dict]:
    results: list[dict] = []
    for tc in PARAMPOLY3_CASES:
        ref = reference_pp3_eval(tc)
        results.append({
            "case": tc.name,
            "x": ref[0], "y": ref[1], "h": ref[2],
        })
    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def print_results(results: list[dict]) -> None:
    max_name = max(len(r["name"]) for r in results)
    print("=" * 120)
    print(f"{'Implementation':<{max_name}}  {'Max |dx|':>12}  {'Max |dy|':>12}  {'Max |dh|':>12}  {'Match':>8}  {'Defects':>8}  {'Policy':>8}")
    print("-" * 120)
    for r in results:
        name = r["name"]
        if not r["all_match"]:
            name += "*"
        tag = "ALL OK" if r["all_match"] else f"{r['matching']}/{r['total']}"
        print(
            f"{name:<{max_name}}  {r['max_dx']:12.2e}  {r['max_dy']:12.2e}  {r['max_dh']:12.2e}  {tag:>8}  {r['defect_cases']:>8}  {r['policy_cases']:>8}"
        )
    print("-" * 120)
    print()

    any_formula_defect = False
    for r in results:
        if r["defect_cases"] > 0:
            any_formula_defect = True
            print(f"\n!!! FORMULA DEFECT: {r['name']} ({r['source']})")
            print(f"    max Δx={r['max_dx']:.2e} (case: {r['worst_x']})")
            print(f"    max Δy={r['max_dy']:.2e} (case: {r['worst_y']})")
            print(f"    max Δh={r['max_dh']:.2e} (case: {r['worst_h']})")
            for d in r['diffs']:
                if d['classification'] == 'FORMULA_DEFECT':
                    print(f"      [{d['case']}] dx={d['dx']:.2e} dy={d['dy']:.2e} dh={d['dh']:.2e} **DEFECT**")
                    print(f"        ref=({d['ref']['x']:.12g},{d['ref']['y']:.12g},{d['ref']['h']:.12g})")
                    print(f"        imp=({d['imp']['x']:.12g},{d['imp']['y']:.12g},{d['imp']['h']:.12g})")

    # Report expected policy differences only if no formula defects
    if not any_formula_defect:
        for r in results:
            if r["policy_cases"] > 0:
                print(f"\n--- EXPECTED POLICY: {r['name']} ({r['source']})")
                print(f"    max Δx={r['max_dx']:.2e} (case: {r['worst_x']})")
                print(f"    max Δy={r['max_dy']:.2e} (case: {r['worst_y']})")
                print(f"    max Δh={r['max_dh']:.2e} (case: {r['worst_h']})")
                print(f"    Reason: EPS={r['eps']:.0e} vs canonical EPS={EPS:.0e}")
                for d in r['diffs'][:2]:
                    print(f"      [{d['case']}] dx={d['dx']:.2e} dy={d['dy']:.2e} dh={d['dh']:.2e} (policy: EPS {r['eps']:.0e})")

    return any_formula_defect


if __name__ == "__main__":
    print(f"Authoritative evaluator epsilon: {EPS}")
    print(f"Line/Arc test cases: {len(TEST_CASES)}")
    print(f"ParamPoly3 test cases: {len(PARAMPOLY3_CASES)}")
    print(f"Position tolerance: {POSITION_TOLERANCE}")
    print(f"Heading tolerance: {HEADING_TOLERANCE}")
    print()
    results = run_comparison()
    has_formula_defect = print_results(results)

    # ParamPoly3 self-test
    print("\n" + "=" * 60)
    print("ParamPoly3 self-test (canonical reference)")
    print("=" * 60)
    pp3_results = run_parampoly3_self_test()
    for r in pp3_results:
        print(f"  {r['case']:30s}  x={r['x']:16.12g}  y={r['y']:16.12g}  h={r['h']:12.10g}")
    print(f"\n  {len(pp3_results)} ParamPoly3 cases evaluated.")

    # Summary
    any_read_only_defect = any(
        r["defect_cases"] > 0 for r in results if r["is_read_only"] and r["is_active"]
    )
    any_formula_defect_overall = any(
        r["defect_cases"] > 0 for r in results
    )

    print("\n" + "=" * 60)
    print("VERDICT")
    print("=" * 60)
    if any_read_only_defect:
        print("FAIL: Active read-only consumers contain formula defects.")
        print("      These must be investigated and repaired.")
        sys.exit(1)
    elif any_formula_defect_overall:
        print("FAIL: Some implementations contain formula defects (inactive or mutator code).")
        print("      Active read-only consumers are clean.")
        sys.exit(1)
    else:
        print("PASS: All differences are expected policy (EPS threshold) effects.")
        print("      No formula defects detected in active read-only consumers.")
        print(f"      {sum(r['policy_cases'] for r in results)} expected policy differences documented.")
        sys.exit(0)
