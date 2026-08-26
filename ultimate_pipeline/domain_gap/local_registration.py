"""RQ1 local registration.

The whole-map structural gap (map_stats_xodr + gap_analyzer) is dominated by *scope*
artifacts: the auto map is the full OSM extraction (32k roads over ~13x14 km) while the
manual Grid0828 is a curated ~4.4x2.9 km patch. To measure a *local* structural domain gap
we crop the auto map to the manual map's geographic footprint, then compare.

Frames:
  - auto (Osm2Odr): geometry in a LOCAL frame; a bare `+proj=tmerc` geoReference (defaults
    lat_0=0/lon_0=0/k=1/x_0=0) plus a header <offset x y> that restores the global frame.
  - manual (Grid0828): UTM-32N (`+proj=tmerc +lon_0=9 +k=0.9996 +x_0=500000 ...`).

Registration = manual footprint -> lat/lon -> auto bare-tmerc (global) -> minus auto offset
-> auto-local, giving a polygon we crop the auto roads to (verified: Grid0828 lands at
auto-local x[~6155..10922] y[~6424..9876], inside the auto extent [0..13267]x[0..14073]).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

from pyproj import CRS, Transformer
from shapely.geometry import Point, Polygon
from shapely.prepared import prep

from ultimate_pipeline.core.xodr_sanitizer import _safe_float

BARE_TMERC_DEFAULT = "+proj=tmerc +datum=WGS84 +units=m +no_defs"


# ------------------------------------------------------------------ header I/O
def read_offset(root: ET.Element) -> Tuple[float, float]:
    """Header <offset x y> (auto local->global shift); (0,0) if absent."""
    hdr = root.find(".//header")
    off = hdr.find("offset") if hdr is not None else None
    if off is None:
        return 0.0, 0.0
    return _safe_float(off.get("x", "0"), 0.0), _safe_float(off.get("y", "0"), 0.0)


def read_georef_proj4(root: ET.Element, *, bare_default: str = BARE_TMERC_DEFAULT) -> str:
    """proj4 from <geoReference>; a bare `+proj=tmerc` (Osm2Odr) is expanded to usable defaults."""
    hdr = root.find(".//header")
    geo = hdr.find("geoReference") if hdr is not None else None
    txt = (geo.text or "").strip() if geo is not None else ""
    if not txt:
        raise ValueError("missing/empty geoReference")
    if txt.replace(" ", "") == "+proj=tmerc":
        return bare_default
    return txt


# ------------------------------------------------------------------ geometry
def road_geometry_points(road: ET.Element) -> List[Tuple[float, float]]:
    return [
        (_safe_float(g.get("x", "0"), 0.0), _safe_float(g.get("y", "0"), 0.0))
        for g in road.findall("./planView/geometry")
    ]


def road_centroid(road: ET.Element) -> Optional[Tuple[float, float]]:
    pts = road_geometry_points(road)
    if not pts:
        return None
    n = len(pts)
    return sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n


def crop_roads_to_polygon(roads: Sequence[ET.Element], polygon: Polygon) -> List[ET.Element]:
    """Keep roads whose geometry centroid lies inside `polygon` (auto-local frame)."""
    pp = prep(polygon)
    return [r for r in roads if (c := road_centroid(r)) is not None and pp.contains(Point(c))]


def kept_junction_ids(roads: Sequence[ET.Element]) -> Set[str]:
    ids: Set[str] = set()
    for r in roads:
        j = r.get("junction", "-1")
        if j not in (None, "-1", ""):
            ids.add(j)
    return ids


# ------------------------------------------------------------------ registration
def transform_manual_bbox_to_auto_local(
    manual_bbox: Tuple[float, float, float, float],
    manual_proj4: str,
    auto_proj4: str,
    auto_offset: Tuple[float, float],
) -> Polygon:
    """Manual (west,south,east,north) -> lat/lon -> auto bare-tmerc -> minus offset -> polygon."""
    w, s, e, n = manual_bbox
    ox, oy = auto_offset
    to_ll = Transformer.from_crs(CRS.from_proj4(manual_proj4), "EPSG:4326", always_xy=True)
    to_auto = Transformer.from_crs("EPSG:4326", CRS.from_proj4(auto_proj4), always_xy=True)
    local: List[Tuple[float, float]] = []
    for (x, y) in [(w, s), (e, s), (e, n), (w, n)]:
        lon, lat = to_ll.transform(x, y)
        gx, gy = to_auto.transform(lon, lat)
        local.append((gx - ox, gy - oy))
    return Polygon(local)


def manual_geometry_bbox(manual_root: ET.Element) -> Tuple[float, float, float, float]:
    xs: List[float] = []
    ys: List[float] = []
    for r in manual_root.findall("road"):
        for (x, y) in road_geometry_points(r):
            xs.append(x)
            ys.append(y)
    if not xs:
        raise ValueError("manual map has no planView geometry points")
    return (min(xs), min(ys), max(xs), max(ys))


@dataclass
class LocalRegistrationResult:
    local_gap: object              # DomainGapScores
    manual_stats: object           # XODRMapStats
    cropped_auto_stats: object     # XODRMapStats
    full_auto_road_count: int
    cropped_auto_road_count: int
    footprint_local_bounds: Tuple[float, float, float, float]
    provenance: Dict


def local_structural_summary(result: LocalRegistrationResult) -> Dict:
    """Interpretable LOCAL structural comparison: road-network ratios + croppable gaps,
    with non-croppable construction differences (buildings/traffic-lights) separated out.

    road_length_gap/traffic_light/building gaps in the raw DomainGapScores cap at 1.0 and
    mix construction choices with structure; the ratios below are the interpretable signal.
    """
    m, ca = result.manual_stats, result.cropped_auto_stats

    def _ratio(a: float, b: float) -> Optional[float]:
        return round(a / b, 3) if b else None

    return {
        "road_network_structural": {
            "lane_width_gap": round(result.local_gap.lane_width_gap, 4),
            "curvature_gap": round(result.local_gap.curvature_gap, 4),
            "curvature_wasserstein_gap": round(
                getattr(result.local_gap, "curvature_wasserstein_gap", 0.0),
                4,
            ),
            "road_length_ratio_auto_over_manual": _ratio(ca.total_road_length, m.total_road_length),
            "junction_ratio_auto_over_manual": _ratio(ca.num_junctions, m.num_junctions),
            "road_count_ratio_auto_over_manual": _ratio(ca.num_roads, m.num_roads),
        },
        "construction_differences_excluded": {
            "reason": (
                "buildings + traffic lights are construction layers, not road-network structure. "
                "Excluded from the LOCAL structural gap because the auto map's buildings are all "
                "attached to a single container road (not spatially distributed), so they cannot be "
                "cropped to the footprint. Note both maps DO model buildings (Grid0828 spatially; "
                "auto on a container road); traffic-lights are modeled by the auto map but not "
                "Grid0828. Reported at whole-map level as construction artifacts."
            ),
            "cropped_auto_buildings": ca.num_buildings,
            "cropped_auto_traffic_lights": ca.num_traffic_lights,
            "manual_buildings": m.num_buildings,
            "manual_traffic_lights": m.num_traffic_lights,
        },
        "footprint": {
            "auto_roads_kept": result.cropped_auto_road_count,
            "auto_roads_total": result.full_auto_road_count,
            "kept_fraction": round(result.cropped_auto_road_count / result.full_auto_road_count, 4)
            if result.full_auto_road_count else None,
        },
    }


def compute_local_registration(auto_xodr: str, manual_xodr: str) -> LocalRegistrationResult:
    """Crop auto -> manual footprint, then compute the LOCAL structural gap (ref=manual)."""
    from ultimate_pipeline.domain_gap.map_stats_xodr import XODRMapStatsExtractor
    from ultimate_pipeline.domain_gap.gap_analyzer import DomainGapAnalyzer

    auto_root = ET.parse(auto_xodr).getroot()
    manual_root = ET.parse(manual_xodr).getroot()

    auto_off = read_offset(auto_root)
    auto_proj = read_georef_proj4(auto_root)
    manual_proj = read_georef_proj4(manual_root)
    manual_bbox = manual_geometry_bbox(manual_root)
    poly = transform_manual_bbox_to_auto_local(manual_bbox, manual_proj, auto_proj, auto_off)

    auto_roads = auto_root.findall("road")
    kept_roads = crop_roads_to_polygon(auto_roads, poly)
    keep_j = kept_junction_ids(kept_roads)

    cropped = ET.Element("OpenDRIVE")
    for r in kept_roads:
        cropped.append(r)
    for j in auto_root.findall("junction"):
        if j.get("id") in keep_j:
            cropped.append(j)

    cropped_stats = XODRMapStatsExtractor.from_root(cropped)
    manual_stats = XODRMapStatsExtractor.from_root(manual_root)
    local_gap = DomainGapAnalyzer.compare_xodr_to_xodr(manual_stats, cropped_stats)

    return LocalRegistrationResult(
        local_gap=local_gap,
        manual_stats=manual_stats,
        cropped_auto_stats=cropped_stats,
        full_auto_road_count=len(auto_roads),
        cropped_auto_road_count=len(kept_roads),
        footprint_local_bounds=poly.bounds,
        provenance={
            "auto_offset": auto_off,
            "auto_proj4": auto_proj,
            "manual_proj4": manual_proj,
            "manual_bbox_native": manual_bbox,
            "footprint_local_bounds": poly.bounds,
            "crop_rule": "road kept if planView-geometry centroid inside manual footprint polygon",
        },
    )
