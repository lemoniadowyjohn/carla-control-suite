from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass(frozen=True)
class EvalResult:
    x: float
    y: float
    hdg: float


class GeometryAdapter(Protocol):
    name: str
    source: str

    def evaluate(
        self, x0: float, y0: float, hdg0: float, length: float, curvature: float, s: float
    ) -> EvalResult:
        ...

    def can_evaluate(self, curvature: float) -> bool:
        ...


@dataclass(frozen=True)
class Adapter:
    name: str
    source: str
    _fn: Callable[[float, float, float, float, float, float], tuple[float, float, float]]
    eps: float | None = None
    _supports_curvature: bool = True

    def evaluate(
        self, x0: float, y0: float, hdg0: float, length: float, curvature: float, s: float
    ) -> EvalResult:
        x, y, h = self._fn(x0, y0, hdg0, length, curvature, s)
        return EvalResult(x=x, y=y, hdg=h)

    def can_evaluate(self, curvature: float) -> bool:
        if not self._supports_curvature:
            return False
        if self.eps is not None and abs(curvature) < self.eps:
            return True
        return True

    def __repr__(self) -> str:
        return f"Adapter({self.name}, {self.source})"


# ---------------------------------------------------------------------------
# Implementation: opendrive_geometry/primitives.py (canonical)
# ---------------------------------------------------------------------------
from opendrive_geometry.primitives import evaluate_line, evaluate_arc, EPS as CANONICAL_EPS


def _canonical(x0, y0, h0, L, k, s):
    if abs(k) < CANONICAL_EPS:
        p = evaluate_line(x0, y0, h0, L, s)
    else:
        p = evaluate_arc(x0, y0, h0, L, k, s)
    return (p.x, p.y, p.hdg)


ADAPTER_CANONICAL = Adapter(
    name="canonical",
    source="opendrive_geometry/primitives.py",
    _fn=_canonical,
    eps=CANONICAL_EPS,
)

# ---------------------------------------------------------------------------
# Implementation: geometry/geometry_math.py GeometryCalculator (EPS=1e-9)
# ---------------------------------------------------------------------------
_GC_EPS = 1e-9


def _geometry_calculator(x0, y0, h0, L, k, s):
    if abs(k) < _GC_EPS:
        return (x0 + s * math.cos(h0), y0 + s * math.sin(h0), h0)
    h = h0 + s * k
    return (
        x0 + (math.sin(h) - math.sin(h0)) / k,
        y0 + (math.cos(h0) - math.cos(h)) / k,
        h,
    )


ADAPTER_GEOMETRY_CALCULATOR = Adapter(
    name="geometry_calculator",
    source="geometry/geometry_math.py:80-116",
    _fn=_geometry_calculator,
    eps=_GC_EPS,
)

# ---------------------------------------------------------------------------
# Implementation: quality/check_geometric_continuity.py (local-frame, EPS=1e-12)
# ---------------------------------------------------------------------------
_CL_EPS = 1e-12


def _local_frame(x0, y0, h0, L, k, s):
    if abs(k) < _CL_EPS:
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


ADAPTER_LOCAL_FRAME = Adapter(
    name="local_frame",
    source="quality/check_geometric_continuity.py:98-117",
    _fn=_local_frame,
    eps=_CL_EPS,
)

# ---------------------------------------------------------------------------
# Implementation: tile_validation/geometry_seam_checker.py (R-based, EPS=1e-12)
# ---------------------------------------------------------------------------
_GSC_EPS = 1e-12


def _geometry_seam_checker(x0, y0, h0, L, k, s):
    if abs(k) < _GSC_EPS:
        return (x0 + s * math.cos(h0), y0 + s * math.sin(h0), h0)
    R = 1.0 / k
    theta = s * k
    return (
        x0 + R * (math.sin(h0 + theta) - math.sin(h0)),
        y0 - R * (math.cos(h0 + theta) - math.cos(h0)),
        h0 + theta,
    )


ADAPTER_GEOMETRY_SEAM_CHECKER = Adapter(
    name="geometry_seam_checker",
    source="tile_validation/geometry_seam_checker.py:28-55",
    _fn=_geometry_seam_checker,
    eps=_GSC_EPS,
)

# ---------------------------------------------------------------------------
# Implementation: geometry/lane_seam_checker.py (R-based, EPS=1e-9)
# ---------------------------------------------------------------------------
_LSC_EPS = 1e-9


def _lane_seam_checker(x0, y0, h0, L, k, s):
    if abs(k) < _LSC_EPS:
        return (x0 + s * math.cos(h0), y0 + s * math.sin(h0), h0)
    R = 1.0 / k
    theta = s * k
    return (
        x0 + R * (math.sin(h0 + theta) - math.sin(h0)),
        y0 - R * (math.cos(h0 + theta) - math.cos(h0)),
        h0 + theta,
    )


ADAPTER_LANE_SEAM_CHECKER = Adapter(
    name="lane_seam_checker",
    source="geometry/lane_seam_checker.py:25-61",
    _fn=_lane_seam_checker,
    eps=_LSC_EPS,
)

# ---------------------------------------------------------------------------
# Implementation: domain_gap/elevation_gap.py (canonical, EPS=1e-12, <=)
# ---------------------------------------------------------------------------
_EG_EPS = 1e-12


def _elevation_gap(x0, y0, h0, L, k, s):
    if abs(k) <= _EG_EPS:
        return (x0 + s * math.cos(h0), y0 + s * math.sin(h0), h0)
    theta = h0 + k * s
    return (
        x0 + (math.sin(theta) - math.sin(h0)) / k,
        y0 - (math.cos(theta) - math.cos(h0)) / k,
        theta,
    )


ADAPTER_ELEVATION_GAP = Adapter(
    name="elevation_gap",
    source="domain_gap/elevation_gap.py:133-161",
    _fn=_elevation_gap,
    eps=_EG_EPS,
)

# ---------------------------------------------------------------------------
# Implementation: domain_gap/geo_alignment.py (canonical, EPS=1e-12, <=)
# ---------------------------------------------------------------------------
_GA_EPS = 1e-12


def _geo_alignment(x0, y0, h0, L, k, s):
    if abs(k) <= _GA_EPS:
        return (x0 + s * math.cos(h0), y0 + s * math.sin(h0), h0)
    theta = h0 + k * s
    return (
        x0 + (math.sin(theta) - math.sin(h0)) / k,
        y0 - (math.cos(theta) - math.cos(h0)) / k,
        theta,
    )


ADAPTER_GEO_ALIGNMENT = Adapter(
    name="geo_alignment",
    source="domain_gap/geo_alignment.py:37-66",
    _fn=_geo_alignment,
    eps=_GA_EPS,
)

# ---------------------------------------------------------------------------
# Implementation: quality/check_dem_full_coverage.py (EPS=1e-9)
# ---------------------------------------------------------------------------
_DEM_EPS = 1e-9


def _dem_coverage(x0, y0, h0, L, k, s):
    if abs(k) < _DEM_EPS:
        return (x0 + s * math.cos(h0), y0 + s * math.sin(h0), h0)
    theta = h0 + k * s
    return (
        x0 + (math.sin(theta) - math.sin(h0)) / k,
        y0 + (-math.cos(theta) + math.cos(h0)) / k,
        theta,
    )


ADAPTER_DEM_COVERAGE = Adapter(
    name="dem_coverage",
    source="quality/check_dem_full_coverage.py:13-34",
    _fn=_dem_coverage,
    eps=_DEM_EPS,
)

# ---------------------------------------------------------------------------
# Implementation: visualization/map_diff.py (correct)
# Line + Arc with line fallback at 1e-12, standard arc formula
# ---------------------------------------------------------------------------
def _map_diff(x0, y0, h0, L, k, s):
    if abs(k) < 1e-12:
        return (x0 + s * math.cos(h0), y0 + s * math.sin(h0), h0)
    inv_c = 1.0 / k
    heading = h0 + s * k
    return (
        x0 + (math.sin(heading) - math.sin(h0)) * inv_c,
        y0 + (math.cos(h0) - math.cos(heading)) * inv_c,
        heading,
    )


ADAPTER_MAP_DIFF = Adapter(
    name="map_diff",
    source="visualization/map_diff.py:38-67 (line+arc, line fallback 1e-12)",
    _fn=_map_diff,
    eps=1e-12,
)

# ---------------------------------------------------------------------------
# Implementation: visualization/map_plotter.py (correct)
# Line branch + Arc with line fallback at 1e-12, standard arc formula
# ---------------------------------------------------------------------------
def _map_plotter(x0, y0, h0, L, k, s):
    if abs(k) < 1e-12:
        return (x0 + s * math.cos(h0), y0 + s * math.sin(h0), h0)
    inv_c = 1.0 / k
    heading = h0 + s * k
    return (
        x0 + (math.sin(heading) - math.sin(h0)) * inv_c,
        y0 + (math.cos(h0) - math.cos(heading)) * inv_c,
        heading,
    )


ADAPTER_MAP_PLOTTER = Adapter(
    name="map_plotter",
    source="visualization/map_plotter.py:32-61 (line+arc, line fallback 1e-12)",
    _fn=_map_plotter,
    eps=1e-12,
)

# ---------------------------------------------------------------------------
# Implementation: topology/junction_connector_rebuild.py (local-frame, EPS=1e-12)
# ---------------------------------------------------------------------------
_JCR_EPS = 1e-12


def _junction_connector_rebuild(x0, y0, h0, L, k, s):
    if abs(k) < _JCR_EPS:
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


ADAPTER_JUNCTION_CONNECTOR_REBUILD = Adapter(
    name="junction_connector_rebuild",
    source="topology/junction_connector_rebuild.py:225-239",
    _fn=_junction_connector_rebuild,
    eps=_JCR_EPS,
)

# ---------------------------------------------------------------------------
# Implementation: visualization/lane_overlay.py (endpoint only, implicit EPS)
# ---------------------------------------------------------------------------
_LO_EPS = 1e-9


def _lane_overlay(x0, y0, h0, L, k, s):
    if abs(k) < _LO_EPS:
        return (x0 + s * math.cos(h0), y0 + s * math.sin(h0), h0)
    h2 = h0 + k * s
    return (
        x0 + (math.sin(h2) - math.sin(h0)) / k,
        y0 - (math.cos(h2) - math.cos(h0)) / k,
        h2,
    )


ADAPTER_LANE_OVERLAY = Adapter(
    name="lane_overlay",
    source="visualization/lane_overlay.py:58-83",
    _fn=_lane_overlay,
    eps=_LO_EPS,
)

# ---------------------------------------------------------------------------
# Implementation: visualization/heatmap_generator.py (endpoint only, implicit EPS)
# ---------------------------------------------------------------------------
_HG_EPS = 1e-9


def _heatmap_generator(x0, y0, h0, L, k, s):
    if abs(k) < _HG_EPS:
        return (x0 + s * math.cos(h0), y0 + s * math.sin(h0), h0)
    h2 = h0 + k * s
    return (
        x0 + (math.sin(h2) - math.sin(h0)) / k,
        y0 - (math.cos(h2) - math.cos(h0)) / k,
        h2,
    )


ADAPTER_HEATMAP_GENERATOR = Adapter(
    name="heatmap_generator",
    source="visualization/heatmap_generator.py:55-84",
    _fn=_heatmap_generator,
    eps=_HG_EPS,
)


# ---------------------------------------------------------------------------
# Registry of all adapters (production-relevant subset)
# ---------------------------------------------------------------------------
ALL_ADAPTERS: list[Adapter] = [
    ADAPTER_CANONICAL,
    ADAPTER_GEOMETRY_CALCULATOR,
    ADAPTER_LOCAL_FRAME,
    ADAPTER_GEOMETRY_SEAM_CHECKER,
    ADAPTER_LANE_SEAM_CHECKER,
    ADAPTER_ELEVATION_GAP,
    ADAPTER_GEO_ALIGNMENT,
    ADAPTER_DEM_COVERAGE,
    ADAPTER_LANE_OVERLAY,
    ADAPTER_HEATMAP_GENERATOR,
    ADAPTER_JUNCTION_CONNECTOR_REBUILD,
    ADAPTER_MAP_DIFF,
    ADAPTER_MAP_PLOTTER,
]

NON_BUGGY_ADAPTERS: list[Adapter] = [
    a for a in ALL_ADAPTERS
]
