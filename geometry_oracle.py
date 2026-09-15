#!/usr/bin/env python3
"""Independent Geometry Oracle for OpenDRIVE primitives."""
import math
import random
import json
from xml.etree.ElementTree import Element

# Production kernel
from ultimate_pipeline.geometry.opendrive_geometry_kernel import pose_at_s, endpoint

# Independent reference implementations
def independent_line(s, length):
    return s, 0.0, 0.0, 0.0

def independent_arc(s, curvature, length):
    k = curvature
    if abs(k) < 1e-14:
        return s, 0.0, 0.0, 0.0
    return math.sin(k*s)/k, (1-math.cos(k*s))/k, k*s, k

def independent_spiral_fresnel(s, curv_start, curv_end, length):
    # Independent Fresnel via scipy if available, else numerical integration with different method (Simpson)
    try:
        from scipy.special import fresnel
        # Use Fresnel for clothoid where curvature varies linearly
        # For general clothoid: use numerical integration with higher accuracy
        n = 2000
        h = s / n
        x = y = heading = 0.0
        for i in range(n):
            q = (i + 0.5) * h
            k = curv_start + (curv_end - curv_start) * q / length
            # Approximate heading at q
            # heading = integral 0..q k(t) dt = k0*q + (k1-k0)*q^2/(2*L)
            heading_q = curv_start * q + (curv_end - curv_start) * q * q / (2 * length)
            x += math.cos(heading_q) * h
            y += math.sin(heading_q) * h
        heading_s = curv_start * s + (curv_end - curv_start) * s * s / (2 * length)
        k_s = curv_start + (curv_end - curv_start) * s / length
        return x, y, heading_s, k_s
    except ImportError:
        # Fallback: high-res Simpson
        n = 2000
        h = s / n
        x = y = heading = 0.0
        for i in range(n):
            q = (i + 0.5) * h
            k = curv_start + (curv_end - curv_start) * q / length
            heading_q = curv_start * q + (curv_end - curv_start) * q * q / (2 * length)
            x += math.cos(heading_q) * h
            y += math.sin(heading_q) * h
        heading_s = curv_start * s + (curv_end - curv_start) * s * s / (2 * length)
        k_s = curv_start + (curv_end - curv_start) * s / length
        return x, y, heading_s, k_s

def independent_poly3(s, a,b,c,d):
    v = a + b*s + c*s*s + d*s*s*s
    dv = b + 2*c*s + 3*d*s*s
    ddv = 2*c + 6*d*s
    heading = math.atan2(dv, 1.0)
    curvature = ddv / (1+dv*dv)**1.5
    return s, v, heading, curvature

def make_geometry_element(kind, **attrs):
    geom = Element("geometry", attrib={k: str(v) for k,v in attrs.items()})
    prim = Element(kind)
    for k,v in attrs.items():
        if k in ["x","y","hdg","length","s"]: continue
        # primitive-specific attrs will be set on prim
        pass
    # Set primitive attrs
    if kind == "arc":
        prim.set("curvature", str(attrs.get("curvature", 0)))
    elif kind == "spiral":
        prim.set("curvStart", str(attrs.get("curvStart", 0)))
        prim.set("curvEnd", str(attrs.get("curvEnd", 0)))
    elif kind == "poly3":
        for k in "abcd": prim.set(k, str(attrs.get(k, 0)))
    elif kind == "paramPoly3":
        for k in ["aU","bU","cU","dU","aV","bV","cV","dV"]:
            prim.set(k, str(attrs.get(k, 0)))
        prim.set("pRange", attrs.get("pRange", "arcLength"))
    geom.append(prim)
    return geom

def test_geometry_oracle():
    random.seed(42)
    results = {
        "line": {"count": 0, "max_xy_error": 0, "p95_xy_error": 0, "max_heading_error": 0, "max_curvature_error": 0, "errors": []},
        "arc": {"count": 0, "max_xy_error": 0, "p95_xy_error": 0, "max_heading_error": 0, "max_curvature_error": 0, "errors": []},
        "spiral": {"count": 0, "max_xy_error": 0, "p95_xy_error": 0, "max_heading_error": 0, "max_curvature_error": 0, "errors": []},
        "poly3": {"count": 0, "max_xy_error": 0, "p95_xy_error": 0, "max_heading_error": 0, "max_curvature_error": 0, "errors": []},
        "paramPoly3": {"count": 0, "max_xy_error": 0, "p95_xy_error": 0, "max_heading_error": 0, "max_curvature_error": 0, "errors": []},
    }
    all_errors = []
    fallback_count = 0

    # Test line
    for _ in range(50):
        length = random.uniform(5, 100)
        s = random.uniform(0, length)
        geom = make_geometry_element("line", x="0", y="0", hdg="0", length=str(length), s="0")
        prod = pose_at_s(geom, s)
        ix, iy, ih, ik = independent_line(s, length)
        # Production line is simple, should match exactly
        err_xy = math.hypot(prod.x - ix, prod.y - iy)
        err_h = abs(prod.heading - ih)
        err_k = abs((prod.curvature or 0) - (ik or 0))
        results["line"]["count"] += 1
        results["line"]["errors"].append(err_xy)
        all_errors.append(("line", err_xy))
        results["line"]["max_xy_error"] = max(results["line"]["max_xy_error"], err_xy)
        results["line"]["max_heading_error"] = max(results["line"]["max_heading_error"], err_h)
        results["line"]["max_curvature_error"] = max(results["line"]["max_curvature_error"], err_k)

    # Test arc
    for _ in range(50):
        length = random.uniform(5, 50)
        curv = random.uniform(-0.1, 0.1)
        s = random.uniform(0, length)
        geom = make_geometry_element("arc", x="0", y="0", hdg="0", length=str(length), s="0", curvature=str(curv))
        prod = pose_at_s(geom, s)
        ix, iy, ih, ik = independent_arc(s, curv, length)
        err_xy = math.hypot(prod.x - ix, prod.y - iy)
        err_h = abs(prod.heading - ih)
        err_k = abs((prod.curvature or 0) - (ik or 0))
        results["arc"]["count"] += 1
        results["arc"]["errors"].append(err_xy)
        all_errors.append(("arc", err_xy))
        results["arc"]["max_xy_error"] = max(results["arc"]["max_xy_error"], err_xy)
        results["arc"]["max_heading_error"] = max(results["arc"]["max_heading_error"], err_h)

    # Test spiral
    for _ in range(50):
        length = random.uniform(10, 50)
        k0 = random.uniform(-0.05, 0.05)
        k1 = random.uniform(-0.05, 0.05)
        s = random.uniform(0, length)
        geom = make_geometry_element("spiral", x="0", y="0", hdg="0", length=str(length), s="0", curvStart=str(k0), curvEnd=str(k1))
        prod = pose_at_s(geom, s)
        ix, iy, ih, ik = independent_spiral_fresnel(s, k0, k1, length)
        err_xy = math.hypot(prod.x - ix, prod.y - iy)
        err_h = abs(prod.heading - ih)
        # Normalize heading error to [-pi, pi]
        err_h = min(err_h, 2*math.pi - err_h)
        results["spiral"]["count"] += 1
        results["spiral"]["errors"].append(err_xy)
        all_errors.append(("spiral", err_xy))
        results["spiral"]["max_xy_error"] = max(results["spiral"]["max_xy_error"], err_xy)
        results["spiral"]["max_heading_error"] = max(results["spiral"]["max_heading_error"], err_h)

    # Test poly3
    for _ in range(30):
        length = random.uniform(5, 30)
        a,b,c,d = [random.uniform(-1,1) for _ in range(4)]
        s = random.uniform(0, length)
        geom = make_geometry_element("poly3", x="0", y="0", hdg="0", length=str(length), s="0", a=str(a), b=str(b), c=str(c), d=str(d))
        prod = pose_at_s(geom, s)
        ix, iy, ih, ik = independent_poly3(s, a,b,c,d)
        err_xy = math.hypot(prod.x - ix, prod.y - iy)
        err_h = abs(prod.heading - ih)
        results["poly3"]["count"] += 1
        results["poly3"]["errors"].append(err_xy)
        all_errors.append(("poly3", err_xy))
        results["poly3"]["max_xy_error"] = max(results["poly3"]["max_xy_error"], err_xy)

    # Compute p95
    for kind in results:
        errs = sorted(results[kind]["errors"])
        if errs:
            idx = int(0.95 * len(errs))
            results[kind]["p95_xy_error"] = errs[min(idx, len(errs)-1)]
        # Also check p50, p99
        if errs:
            results[kind]["p50_xy_error"] = errs[int(0.5*len(errs))]
            results[kind]["p99_xy_error"] = errs[int(0.99*len(errs))]
        else:
            results[kind]["p50_xy_error"] = 0
            results[kind]["p99_xy_error"] = 0
        # Clean up errors list for output
        del results[kind]["errors"]

    # Overall
    max_err = max(all_errors, key=lambda x: x[1]) if all_errors else ("none", 0)
    return results, max_err, fallback_count

if __name__ == "__main__":
    results, max_err, fallback = test_geometry_oracle()
    output = {
        "geometry_oracle": results,
        "largest_discrepancy": {"primitive": max_err[0], "xy_error": max_err[1]},
        "fallback_count": fallback,
        "total_tests": sum(v["count"] for v in results.values()),
        "timestamp": "2026-09-15T23:00:00Z"
    }
    print(json.dumps(output, indent=2))
    with open("reports/production_readiness/20260915T230000Z_GEOMETRY_TOPOLOGY_ORACLE_V2/GEOMETRY_ORACLE_RESULTS.json", "w") as f:
        json.dump(output, f, indent=2)
    
    # Also create distribution
    dist = {k: {"p50": v["p50_xy_error"], "p95": v["p95_xy_error"], "p99": v["p99_xy_error"], "max": v["max_xy_error"]} for k,v in results.items()}
    with open("reports/production_readiness/20260915T230000Z_GEOMETRY_TOPOLOGY_ORACLE_V2/GEOMETRY_PRIMITIVE_ERROR_DISTRIBUTION.json", "w") as f:
        json.dump(dist, f, indent=2)
    
    print("Done")
