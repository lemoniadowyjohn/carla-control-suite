import math
import xml.etree.ElementTree as ET
from typing import Iterable, List, Tuple

# ------------------------------------------------------------
# 1. Shared paramPoly3 sampling utility
# ------------------------------------------------------------

def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except Exception:
        return float(default)
    if not math.isfinite(parsed):
        return float(default)
    return float(parsed)


def _sample_parampoly3_impl(
    geom: ET.Element,
    x0: float,
    y0: float,
    hdg: float,
    length: float,
    t_values: Iterable[float],
) -> List[Tuple[float, float]]:
    pp = geom.find("paramPoly3")
    if pp is None:
        return [(x0, y0)]
    p_range = str(pp.get("pRange", "arcLength") or "arcLength")
    p_max = float(length) if p_range == "arcLength" else 1.0
    a_u = _safe_float(pp.get("aU"), 0.0)
    b_u = _safe_float(pp.get("bU"), 0.0)
    c_u = _safe_float(pp.get("cU"), 0.0)
    d_u = _safe_float(pp.get("dU"), 0.0)
    a_v = _safe_float(pp.get("aV"), 0.0)
    b_v = _safe_float(pp.get("bV"), 0.0)
    c_v = _safe_float(pp.get("cV"), 0.0)
    d_v = _safe_float(pp.get("dV"), 0.0)
    cos_h = math.cos(hdg)
    sin_h = math.sin(hdg)
    points: List[Tuple[float, float]] = []
    for t in t_values:
        p = p_max * float(t)
        u = a_u + b_u * p + c_u * p * p + d_u * p * p * p
        v = a_v + b_v * p + c_v * p * p + d_v * p * p * p
        xx = x0 + (u * cos_h) - (v * sin_h)
        yy = y0 + (u * sin_h) + (v * cos_h)
        points.append((xx, yy))
    return points


def sample_parampoly3_points(
    geom: ET.Element,
    x0: float,
    y0: float,
    hdg: float,
    length: float,
    t_values: Iterable[float],
) -> List[Tuple[float, float]]:
    """Sample XY positions along a paramPoly3 geometry element.

    Authoritative location for paramPoly3 sampling shared between
    the domain-gap elevation metric and the XODR cropper.
    """
    return _sample_parampoly3_impl(
        geom=geom,
        x0=x0,
        y0=y0,
        hdg=hdg,
        length=length,
        t_values=t_values,
    )


# ------------------------------------------------------------
# 2. Geometry math: robust line/arc integration
# ------------------------------------------------------------

class GeometryCalculator:
    """
    Robust integration for OpenDRIVE geometries.
    Handles Lines and Arcs; spirals/poly3 approximated as lines for endpoints.
    """

    @staticmethod
    def get_endpoint(x: float, y: float, hdg: float,
                     length: float, geometry_element: ET.Element):
        arc_elem = geometry_element.find("arc")
        if arc_elem is not None:
            curv_raw = arc_elem.get("curvature", "0")
            try:
                curvature = float(curv_raw)
            except Exception:
                curvature = 0.0
            return GeometryCalculator._integrate_arc(x, y, hdg, length, curvature)
        else:
            # Default to line (spirals/poly3 treated as line here)
            return GeometryCalculator._integrate_line(x, y, hdg, length)

    @staticmethod
    def _integrate_line(x, y, hdg, length):
        x_new = x + length * math.cos(hdg)
        y_new = y + length * math.sin(hdg)
        return x_new, y_new, hdg

    @staticmethod
    def _integrate_arc(x, y, hdg, length, curvature):
        if abs(curvature) < 1e-9:
            return GeometryCalculator._integrate_line(x, y, hdg, length)

        hdg_new = hdg + length * curvature
        # Standard OpenDRIVE arc integration:
        x_new = x + (math.sin(hdg_new) - math.sin(hdg)) / curvature
        y_new = y + (math.cos(hdg) - math.cos(hdg_new)) / curvature
        return x_new, y_new, hdg_new
