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
from typing import Dict, List, Optional, Sequence, Set, Tuple, Union

from pyproj import CRS, Transformer
from shapely.geometry import MultiPoint, Point, Polygon
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


# ------------------------------------------------------------------ buildings
def building_global_centroid(
    obj: ET.Element, *, shift: Tuple[float, float] = (0.0, 0.0)
) -> Optional[Tuple[float, float]]:
    """Centroid of a building `<object>`'s `<outline><cornerGlobal .../></outline>` points,
    optionally translated by `shift` (dx, dy) to align into a different local frame.

    `cornerGlobal` gives absolute positions, but -- on the real Ingolstadt pair -- in a
    DIFFERENT local tmerc frame than the road network's planView geometry: the building
    enrichment step (`osm_polygon_loader.py`) projects OSM lon/lat via
    `+proj=tmerc +lat_0=<osm_bbox lat_min> +lon_0=<osm_bbox lon_min> +x_0=0 +y_0=0`, while
    roads use the bare `+proj=tmerc` (lat_0=lon_0=0) global frame minus the header
    `<offset>`. These are two different origins (~6.5km/6.4km apart on the pinned pair) —
    `shift` is the correction, computed by `building_frame_shift_to_auto_local`. This is
    independent of the object's (non-representative) `s`/`t` road-relative attachment, so
    it lets buildings be cropped to a footprint even when they are all attached to a single
    container road.

    Returns None if no `<outline>` with `<cornerGlobal>` points is present (e.g. the
    road-relative `<cornerLocal>`/`<cornerRoad>` forms used by some OpenDRIVE writers,
    which would require the object's own s/t + road geometry to resolve to an absolute
    position — not attempted here since it is unnecessary for this dataset).
    """
    outline = obj.find("outline")
    if outline is None:
        return None
    corners = outline.findall("cornerGlobal")
    if not corners:
        return None
    dx, dy = shift
    xs = [_safe_float(c.get("x", "0"), 0.0) for c in corners]
    ys = [_safe_float(c.get("y", "0"), 0.0) for c in corners]
    return sum(xs) / len(xs) + dx, sum(ys) / len(ys) + dy


def collect_building_objects(root: ET.Element) -> List[ET.Element]:
    """All `type="building"` `<object>` elements, map-wide (not scoped to a specific road).

    Buildings are collected independently of which road they are attached to, since a
    single non-representative "container" road with s=0/t=0 attachments (as in the auto
    map) would otherwise make every building live-or-die with that one road's crop status.
    """
    return [
        obj
        for road in root.findall("road")
        for obj in road.findall(".//object")
        if (obj.get("type") or "").lower() == "building"
    ]


def crop_buildings_to_polygon(
    buildings: Sequence[ET.Element], polygon: Polygon, *, shift: Tuple[float, float] = (0.0, 0.0)
) -> List[ET.Element]:
    """Keep buildings whose (optionally frame-shifted) `cornerGlobal` outline centroid lies
    inside `polygon`. See `building_global_centroid` for why `shift` is needed.

    Buildings without a recoverable `cornerGlobal` centroid are dropped (conservative: we
    cannot claim they're in-footprint without a position).
    """
    pp = prep(polygon)
    kept = []
    for b in buildings:
        c = building_global_centroid(b, shift=shift)
        if c is not None and pp.contains(Point(c)):
            kept.append(b)
    return kept


def building_frame_shift_to_auto_local(
    osm_lat_min: float,
    osm_lon_min: float,
    auto_proj4: str,
    auto_offset: Tuple[float, float],
) -> Tuple[float, float]:
    """(dx, dy) to translate building `cornerGlobal` points into the auto map's local frame.

    The building enrichment step projects OSM lon/lat with
    `+proj=tmerc +lat_0=<osm_lat_min> +lon_0=<osm_lon_min> +x_0=0 +y_0=0` (see
    `osm_polygon_loader.py`), i.e. building-local (0,0) = (osm_lon_min, osm_lat_min). The
    shift is simply that origin's position in auto-local space: project it through the
    auto map's own bare-tmerc CRS, then subtract the auto header `<offset>` — the same
    "global minus offset" step used to register the manual map's footprint.
    """
    ox, oy = auto_offset
    to_auto_global = Transformer.from_crs("EPSG:4326", CRS.from_proj4(auto_proj4), always_xy=True)
    gx, gy = to_auto_global.transform(osm_lon_min, osm_lat_min)
    return gx - ox, gy - oy


# ------------------------------------------------------------------ registration
def transform_manual_points_to_auto_local(
    manual_points: Sequence[Tuple[float, float]],
    manual_proj4: str,
    auto_proj4: str,
    auto_offset: Tuple[float, float],
) -> Polygon:
    """Manual (x,y)* -> lat/lon -> auto bare-tmerc -> minus offset -> convex-hull polygon.

    Generalization of the bbox transform to an arbitrary point set. The returned polygon is
    always the convex hull of the transformed points (a polygon built from >=3 non-collinear
    points is convex by construction when the input is a bbox's 4 corners; for a hull point
    set this yields the tightened footprint).
    """
    ox, oy = auto_offset
    to_ll = Transformer.from_crs(CRS.from_proj4(manual_proj4), "EPSG:4326", always_xy=True)
    to_auto = Transformer.from_crs("EPSG:4326", CRS.from_proj4(auto_proj4), always_xy=True)
    local: List[Tuple[float, float]] = []
    for (x, y) in manual_points:
        lon, lat = to_ll.transform(x, y)
        gx, gy = to_auto.transform(lon, lat)
        local.append((gx - ox, gy - oy))
    return MultiPoint(local).convex_hull


def transform_auto_points_to_manual_local(
    auto_points: Sequence[Tuple[float, float]],
    auto_proj4: str,
    auto_offset: Tuple[float, float],
    manual_proj4: str,
) -> List[Tuple[float, float]]:
    """Mirror of `transform_manual_points_to_auto_local`: auto-local (x,y)* -> plus offset
    -> auto global bare-tmerc -> lat/lon -> manual's own native CRS.

    `compute_local_registration` only ever needs manual's footprint expressed in auto's
    frame (to crop auto roads by centroid). Metrics that need genuine POINT-LEVEL
    correspondence between the two maps -- e.g. a curve-similarity metric like discrete
    Fréchet distance, where "does this auto road's shape match this manual road's shape"
    requires both centerlines in one common frame -- need the opposite direction. Vectorized
    (list in, list out) since callers typically reproject many points per road across many
    roads.
    """
    ox, oy = auto_offset
    to_ll = Transformer.from_crs(CRS.from_proj4(auto_proj4), "EPSG:4326", always_xy=True)
    to_manual = Transformer.from_crs("EPSG:4326", CRS.from_proj4(manual_proj4), always_xy=True)
    xs = [float(x) + ox for x, _ in auto_points]
    ys = [float(y) + oy for _, y in auto_points]
    lons, lats = to_ll.transform(xs, ys)
    mxs, mys = to_manual.transform(lons, lats)
    return list(zip(mxs, mys))


def transform_manual_bbox_to_auto_local(
    manual_bbox: Tuple[float, float, float, float],
    manual_proj4: str,
    auto_proj4: str,
    auto_offset: Tuple[float, float],
) -> Polygon:
    """Manual (west,south,east,north) -> lat/lon -> auto bare-tmerc -> minus offset -> polygon."""
    w, s, e, n = manual_bbox
    corners = [(w, s), (e, s), (e, n), (w, n)]
    return transform_manual_points_to_auto_local(corners, manual_proj4, auto_proj4, auto_offset)


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


def manual_geometry_convex_hull(manual_root: ET.Element) -> List[Tuple[float, float]]:
    """Vertices of the convex hull of the manual map's planView geometry points (native CRS).

    Tighter than `manual_geometry_bbox`: a convex hull is always <= the bbox in area, so
    cropping the auto map to the hull-derived footprint can only shrink (or keep-equal) the
    kept-road set versus the bbox footprint.
    """
    pts: List[Tuple[float, float]] = []
    for r in manual_root.findall("road"):
        pts.extend(road_geometry_points(r))
    if not pts:
        raise ValueError("manual map has no planView geometry points")
    hull = MultiPoint(pts).convex_hull
    # convex_hull of a point set may degenerate to a Point/LineString for <3 non-collinear
    # points; exterior.coords is only defined for a Polygon.
    if hull.geom_type != "Polygon":
        return pts
    return list(hull.exterior.coords)


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
    with non-croppable construction differences (traffic-lights) separated out.

    road_length_gap/traffic_light/building gaps in the raw DomainGapScores cap at 1.0 and
    mix construction choices with structure; the ratios below are the interpretable signal.

    Buildings are now cropped in-footprint (via `<outline><cornerGlobal>` absolute
    positions recovered independently of the objects' road-relative s/t attachment), so
    `building_density_comparison` is a real in-footprint density comparison, not an
    excluded construction artifact.
    """
    m, ca = result.manual_stats, result.cropped_auto_stats

    def _ratio(a: float, b: float) -> Optional[float]:
        return round(a / b, 3) if b else None

    def _density(n: int, length_m: float) -> Optional[float]:
        return round(n / (length_m / 1000.0), 4) if length_m else None

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
        "building_density_comparison": {
            "note": (
                "buildings recovered via <outline><cornerGlobal> absolute positions (same local "
                "frame as road planView geometry), independent of their road-relative s=0/t=0 "
                "attachment, and cropped to the same footprint polygon as roads. See "
                "local_registration.py:building_global_centroid / crop_buildings_to_polygon."
            ),
            "building_density_gap": round(result.local_gap.building_density_gap, 4),
            "cropped_auto_buildings": ca.num_buildings,
            "manual_buildings": m.num_buildings,
            "cropped_auto_buildings_per_km": _density(ca.num_buildings, ca.total_road_length),
            "manual_buildings_per_km": _density(m.num_buildings, m.total_road_length),
        },
        "construction_differences_excluded": {
            "reason": (
                "traffic lights are a construction layer, not road-network structure, and are "
                "excluded from the LOCAL structural gap because Grid0828 does not model traffic "
                "lights at all (0 in the manual map) -- there is nothing in-footprint to compare "
                "against, independent of croppability. Reported at whole-map level as a "
                "construction/modeling-choice artifact."
            ),
            "cropped_auto_traffic_lights": ca.num_traffic_lights,
            "manual_traffic_lights": m.num_traffic_lights,
        },
        "footprint": {
            "auto_roads_kept": result.cropped_auto_road_count,
            "auto_roads_total": result.full_auto_road_count,
            "kept_fraction": round(result.cropped_auto_road_count / result.full_auto_road_count, 4)
            if result.full_auto_road_count else None,
        },
    }


def compute_local_registration(
    auto_xodr: str,
    manual_xodr: str,
    *,
    footprint: str = "hull",
    building_frame_shift: Union[Tuple[float, float], str] = "auto",
) -> LocalRegistrationResult:
    """Crop auto -> manual footprint, then compute the LOCAL structural gap (ref=manual).

    `footprint`:
      - "hull" (default): convex hull of the manual map's planView geometry. Tighter than
        the bbox (hull area <= bbox area for any point set), so it never grows the kept-road
        set vs. "bbox" -- it only shrinks it or keeps it equal.
      - "bbox": axis-aligned bounding box (legacy/wider footprint), kept for side-by-side
        comparison against the hull result.

    Buildings are cropped independently of roads (map-wide, via `<outline><cornerGlobal>`
    absolute positions) and injected into the cropped tree so `cropped_auto_stats.num_buildings`
    reflects the in-footprint count rather than 0 (the auto map's buildings all sit on a
    single non-representative container road, so a road-centroid crop alone always zeroes
    them out).

    `building_frame_shift`: buildings' `cornerGlobal` points are written by the OSM
    enrichment step in a DIFFERENT local tmerc frame than the road network (see
    `building_frame_shift_to_auto_local`'s docstring for why). Pass an explicit (dx, dy) to
    correct for it, `(0.0, 0.0)` to disable the correction, or the default `"auto"` to
    resolve it from `ultimate_pipeline.config.settings.SETTINGS.load_gps_bounds()` (falls
    back to no shift if settings/gps-bounds are unavailable, e.g. in isolated unit tests).
    """
    from ultimate_pipeline.domain_gap.map_stats_xodr import XODRMapStatsExtractor
    from ultimate_pipeline.domain_gap.gap_analyzer import DomainGapAnalyzer

    if footprint not in ("hull", "bbox"):
        raise ValueError(f"footprint must be 'hull' or 'bbox', got {footprint!r}")

    auto_root = ET.parse(auto_xodr).getroot()
    manual_root = ET.parse(manual_xodr).getroot()

    auto_off = read_offset(auto_root)
    auto_proj = read_georef_proj4(auto_root)
    manual_proj = read_georef_proj4(manual_root)
    manual_bbox = manual_geometry_bbox(manual_root)

    if footprint == "hull":
        hull_pts = manual_geometry_convex_hull(manual_root)
        poly = transform_manual_points_to_auto_local(hull_pts, manual_proj, auto_proj, auto_off)
    else:
        poly = transform_manual_bbox_to_auto_local(manual_bbox, manual_proj, auto_proj, auto_off)

    auto_roads = auto_root.findall("road")
    kept_roads = crop_roads_to_polygon(auto_roads, poly)
    keep_j = kept_junction_ids(kept_roads)

    bld_shift = building_frame_shift
    bld_shift_source = "explicit"
    if bld_shift == "auto":
        bld_shift_source = "settings_gps_bounds"
        try:
            from ultimate_pipeline.config.settings import SETTINGS
            gps = SETTINGS.load_gps_bounds()
            bld_shift = building_frame_shift_to_auto_local(
                osm_lat_min=gps["lat_min"], osm_lon_min=gps["lon_min"],
                auto_proj4=auto_proj, auto_offset=auto_off,
            )
        except Exception:
            bld_shift = (0.0, 0.0)
            bld_shift_source = "unavailable_fallback_zero"

    all_buildings = collect_building_objects(auto_root)
    kept_buildings = crop_buildings_to_polygon(all_buildings, poly, shift=bld_shift)

    cropped = ET.Element("OpenDRIVE")
    for r in kept_roads:
        cropped.append(r)
    for j in auto_root.findall("junction"):
        if j.get("id") in keep_j:
            cropped.append(j)
    if kept_buildings:
        # Buildings are collected map-wide (their container road may not itself be
        # in-footprint), so re-home the kept ones on a synthetic holder road purely for
        # XODRMapStatsExtractor's `road.findall(".//object")` object-count scan. This does
        # not affect road_length/junction/lane stats (the holder road has length=0 and is
        # not a real road).
        holder = ET.SubElement(cropped, "road", id="__cropped_buildings__", junction="-1", length="0")
        objs = ET.SubElement(holder, "objects")
        for b in kept_buildings:
            objs.append(b)

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
            "footprint_kind": footprint,
            "auto_offset": auto_off,
            "auto_proj4": auto_proj,
            "manual_proj4": manual_proj,
            "manual_bbox_native": manual_bbox,
            "footprint_local_bounds": poly.bounds,
            "crop_rule": "road kept if planView-geometry centroid inside manual footprint polygon",
            "building_crop_rule": (
                "building kept if (frame-shifted) outline cornerGlobal centroid inside manual "
                "footprint polygon; buildings collected map-wide (not scoped to their "
                "container road)"
            ),
            "building_frame_shift": bld_shift,
            "building_frame_shift_source": bld_shift_source,
            "full_auto_building_count": len(all_buildings),
            "cropped_auto_building_count": len(kept_buildings),
        },
    )
