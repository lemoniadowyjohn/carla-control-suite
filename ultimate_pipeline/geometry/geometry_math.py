import hashlib
import json

class GeometryHasher:
    @staticmethod
    def hash_geometry(geom: ET.Element) -> str:
        # Canonicalize and hash geometry
        # This is a simplified version, should be more robust
        data = ET.tostring(geom, encoding="unicode", method="xml")
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

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


def _validate_parampoly3_coefficients(geom: ET.Element) -> None:
    attrs = ["aU", "bU", "cU", "dU", "aV", "bV", "cV", "dV"]
    for attr in attrs:
        val = geom.get(attr)
        if val is not None:
            try:
                fval = float(val)
                if not math.isfinite(fval):
                    raise ValueError(f"Non-finite coefficient found: {attr}={val}")
            except ValueError as e:
                if "Non-finite coefficient found" in str(e):
                    raise
                pass


def _sample_parampoly3_impl(
    geom: ET.Element,
    x0: float,
    y0: float,
    hdg: float,
    length: float,
    t_values: Iterable[float],
) -> List[Tuple[float, float]]:
    if length <= 0:
        raise ValueError(f"Geometry length must be positive, got {length}")

    pp = geom.find("paramPoly3")
    if pp is None:
        return [(x0, y0)]

    _validate_parampoly3_coefficients(pp)

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
    
    # Ensure monotonic and unique sampling
    sorted_t = sorted(set(t_values))
    
    for t in sorted_t:
        if not (0.0 <= t <= 1.0):
            continue # Or raise error if strict validation is needed
        
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
        # Identify the geometry type
        for child in geometry_element:
            if child.tag == "arc":
                curv_raw = child.get("curvature", "0")
                try:
                    curvature = float(curv_raw)
                except Exception:
                    curvature = 0.0
                return GeometryCalculator._integrate_arc(x, y, hdg, length, curvature)
            elif child.tag == "line":
                return GeometryCalculator._integrate_line(x, y, hdg, length)
            elif child.tag == "spiral":
                # Implementation needed
                return GeometryCalculator._integrate_spiral(x, y, hdg, length, child)
            elif child.tag == "poly3" or child.tag == "paramPoly3":
                # Implementation needed
                return GeometryCalculator._integrate_parampoly3(x, y, hdg, length, child)
        
        # Default to line if no known type found? Or fail? The requirement says fail closed.
        raise ValueError(f"Unsupported geometry type: {geometry_element}")

    @staticmethod
    def _integrate_spiral(x, y, hdg, length, geom):
        # Placeholder for midpoint integration
        # Needs actual spiral implementation
        return x + length * math.cos(hdg), y + length * math.sin(hdg), hdg

    @staticmethod
    def _integrate_parampoly3(x, y, hdg, length, geom):
        # Placeholder for parampoly3 endpoint evaluation
        # Needs actual parampoly3 integration
        return x + length * math.cos(hdg), y + length * math.sin(hdg), hdg

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
