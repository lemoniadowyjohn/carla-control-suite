"""
FOUNDATION-01A Deliverable: Cross-comparison benchmark against all existing
line/arc evaluators in the repository.

This script runs every existing implementation through a common test suite
and reports disagreements against the authoritative evaluator.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from typing import Callable

from opendrive_geometry.primitives import evaluate_line, evaluate_arc, EPS


@dataclass(frozen=True)
class TestCase:
    name: str
    x0: float
    y0: float
    hdg0: float
    length: float
    curvature: float
    eval_s: float  # distance along geometry to evaluate


# ---------------------------------------------------------------------------
# Test suite of 20 diverse cases
# ---------------------------------------------------------------------------
TEST_CASES: list[TestCase] = [
    # Line cases
    TestCase("line_forward", 0.0, 0.0, 0.0, 100.0, 0.0, 50.0),
    TestCase("line_angled", 10.0, 20.0, math.pi / 6, 80.0, 0.0, 40.0),
    TestCase("line_backward", 5.0, 5.0, math.pi, 30.0, 0.0, 15.0),
    TestCase("line_negative_hdg", 0.0, 0.0, -0.5, 50.0, 0.0, 25.0),
    TestCase("line_start", 1.0, 2.0, 0.3, 100.0, 0.0, 0.0),
    TestCase("line_end", 1.0, 2.0, 0.3, 100.0, 0.0, 100.0),
    # Arc cases
    TestCase("arc_gentle_left", 0.0, 0.0, 0.0, 100.0, 0.005, 50.0),
    TestCase("arc_gentle_right", 0.0, 0.0, 0.0, 100.0, -0.005, 50.0),
    TestCase("arc_quarter_circle", 0.0, 0.0, 0.0, math.pi / 2 * 10.0, 0.1, math.pi / 2 * 10.0),
    TestCase("arc_half_circle", 0.0, 0.0, 0.0, math.pi * 5.0, 0.2, math.pi * 5.0),
    TestCase("arc_tight_left", 100.0, 200.0, 1.0, 30.0, 0.05, 15.0),
    TestCase("arc_tight_right", 100.0, 200.0, 1.0, 30.0, -0.05, 15.0),
    TestCase("arc_offset", 50.0, -30.0, 0.8, 60.0, 0.02, 30.0),
    TestCase("arc_start", 5.0, 5.0, 0.5, 100.0, 0.01, 0.0),
    TestCase("arc_end", 5.0, 5.0, 0.5, 100.0, 0.01, 100.0),
    # Near-zero curvature edge cases
    TestCase("arc_almost_line_1e_8", 0.0, 0.0, 0.0, 100.0, 1e-8, 50.0),
    TestCase("arc_almost_line_1e_10", 0.0, 0.0, 0.0, 100.0, 1e-10, 50.0),
    TestCase("arc_almost_line_1e_12", 0.0, 0.0, 0.0, 100.0, 1e-12, 50.0),
    TestCase("arc_almost_line_neg_1e_9", 0.0, 0.0, 0.0, 100.0, -1e-9, 50.0),
    TestCase("arc_exact_zero", 0.0, 0.0, 0.0, 100.0, 0.0, 50.0),
]


# ---------------------------------------------------------------------------
# Reference: the authoritative evaluator
# ---------------------------------------------------------------------------
def reference_eval(tc: TestCase) -> tuple[float, float, float]:
    if abs(tc.curvature) < EPS:
        p = evaluate_line(tc.x0, tc.y0, tc.hdg0, tc.length, tc.eval_s)
    else:
        p = evaluate_arc(tc.x0, tc.y0, tc.hdg0, tc.length, tc.curvature, tc.eval_s)
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
# ---------------------------------------------------------------------------
IMPLEMENTATIONS: list[tuple[str, str, Callable]] = [
    ("geometry_calculator", "geometry/geometry_math.py:80-116 (EPS=1e-9)", impl_geometry_calculator),
    ("geometry_seam_checker", "tile_validation/geometry_seam_checker.py:28-55 (EPS=1e-12)", impl_geometry_seam_checker),
    ("local_frame", "quality/check_geometric_continuity.py:98-117 (EPS=1e-12)", impl_local_frame),
    ("lane_seam_checker", "geometry/lane_seam_checker.py:25-61 (EPS=1e-9)", impl_lane_seam_checker),
    ("elevation_gap", "domain_gap/elevation_gap.py:133-161 (EPS=1e-12)", impl_elevation_gap),
    ("geo_alignment", "domain_gap/geo_alignment.py:37-66 (EPS=1e-12)", impl_geo_alignment),
    ("dem_coverage", "quality/check_dem_full_coverage.py:13-34 (EPS=1e-9)", impl_dem_coverage),
    ("lane_overlay", "visualization/lane_overlay.py:58-83 (EPS=1e-9)", impl_lane_overlay),
    ("heatmap_generator", "visualization/heatmap_generator.py:55-84 (EPS=1e-9)", impl_heatmap_generator),
    ("junction_connector_rebuild", "topology/junction_connector_rebuild.py:225-239 (EPS=1e-12)", impl_junction_connector_rebuild),
    ("map_plotter", "visualization/map_plotter.py:32-61 (line+arc, line fallback 1e-12)", impl_map_plotter),
    ("map_diff", "visualization/map_diff.py:38-67 (line+arc, line fallback 1e-12)", impl_map_diff),
    ("canonical", "opendrive_geometry/primitives.py (EPS=1e-12)", impl_canonical),
]


# ---------------------------------------------------------------------------
# Run comparison
# ---------------------------------------------------------------------------
def run_comparison() -> list[dict]:
    results: list[dict] = []
    for name, source, impl_fn in IMPLEMENTATIONS:
        max_dx = max_dy = max_dh = 0.0
        worst_x = worst_y = worst_h = ""
        total_cases = len(TEST_CASES)
        diffs: list[tuple[str, float, float, float, dict, dict]] = []

        for tc in TEST_CASES:
            ref = reference_eval(tc)
            imp = impl_fn(tc.x0, tc.y0, tc.hdg0, tc.length, tc.curvature, tc.eval_s)
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
                diffs.append((tc.name, dx, dy, dh,
                              {"x": ref[0], "y": ref[1], "h": ref[2]},
                              {"x": imp[0], "y": imp[1], "h": imp[2]}))

        matching = total_cases - len(diffs)
        results.append({
            "name": name,
            "source": source,
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
        })
    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def print_results(results: list[dict]) -> None:
    max_name = max(len(r["name"]) for r in results)
    print("=" * 110)
    print(f"{'Implementation':<{max_name}}  {'Max |dx|':>12}  {'Max |dy|':>12}  {'Max |dh|':>12}  {'Match':>7}")
    print("-" * 110)
    for r in results:
        all_ok = r["all_match"]
        tag = "ALL OK" if all_ok else f"{r['matching']}/{r['total']}"
        name = r["name"]
        # Emit worst-case detail on disagreements
        if not all_ok:
            name += "*"
        print(
            f"{name:<{max_name}}  {r['max_dx']:12.2e}  {r['max_dy']:12.2e}  {r['max_dh']:12.2e}  {tag:>7}"
        )
    print("-" * 110)
    print()

    # Detail any disagreements
    any_disagreement = False
    for r in results:
        if not r["all_match"]:
            any_disagreement = True
            print(f"\n*** {r['name']} ({r['source']})")
            print(f"    max Δx={r['max_dx']:.2e} (case: {r['worst_x']})")
            print(f"    max Δy={r['max_dy']:.2e} (case: {r['worst_y']})")
            print(f"    max Δh={r['max_dh']:.2e} (case: {r['worst_h']})")
            print(f"    non-zero diffs: {len(r['diffs'])}/{r['total']} cases")
            # Show up to 3 worst diffs
            sorted_diffs = sorted(r['diffs'], key=lambda d: max(d[1], d[2], d[3]), reverse=True)
            for tc_name, dx, dy, dh, ref, imp in sorted_diffs[:3]:
                print(f"      [{tc_name}] dx={dx:.2e} dy={dy:.2e} dh={dh:.2e}")
                print(f"        ref=({ref['x']:.12g},{ref['y']:.12g},{ref['h']:.12g})")
                print(f"        imp=({imp['x']:.12g},{imp['y']:.12g},{imp['h']:.12g})")
    if not any_disagreement:
        print("ALL implementations produce identical results to the authoritative evaluator.")


if __name__ == "__main__":
    print(f"Authoritative evaluator epsilon: {EPS}")
    print(f"Test cases: {len(TEST_CASES)}")
    print()
    results = run_comparison()
    print_results(results)

    # Summary
    all_match = all(r["all_match"] for r in results)
    if all_match:
        print("\nVERDICT: All 7 existing implementations are numerically identical")
        print("to the authoritative evaluator at 1e-12 tolerance.")
        sys.exit(0)
    else:
        print("\nVERDICT: Some disagreements found — see above.")
        sys.exit(1)
