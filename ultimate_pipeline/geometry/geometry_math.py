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
