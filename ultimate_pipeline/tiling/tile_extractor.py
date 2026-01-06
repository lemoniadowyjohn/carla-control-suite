# ultimate_pipeline/tiling/tile_extractor.py
# ------------------------------------------------------------
# Semantics-aware tiler for OpenDRIVE (XODR)
#
# Key properties:
# - Preserves global driving semantics across tiles
# - Allows successor/predecessor leakage (tracked in metadata)
# - Supports buffered / overlapping tiles
# - Highway-aware adaptive buffering (optional, deterministic)
#
# IMPORTANT:
# - This module treats tiles as OBSERVATION WINDOWS by default
# - Standalone routability is optional and settings-guarded
# ------------------------------------------------------------

import os
import xml.etree.ElementTree as ET
from typing import List, Tuple, Dict, Optional, Iterable

# ------------------------------------------------------------
# Settings (guarded import)
# ------------------------------------------------------------
try:
    from ultimate_pipeline.config.settings import SETTINGS  # type: ignore
except Exception:
    SETTINGS = None


def _get_setting(name: str, default):
    if SETTINGS is None:
        return default
    return getattr(SETTINGS, name, default)


# ------------------------------------------------------------
# Defaults
# ------------------------------------------------------------
DEFAULT_PRESERVE_GLOBAL_LANE_TYPES_IN_TILES = True
DEFAULT_ALLOW_SUCCESSOR_OUTSIDE_TILE = True
DEFAULT_TILE_BUFFER_M = 30.0  # ⬅ CRITICAL: prevents lane truncation

# Highway-aware buffering (deterministic, explainable)
DEFAULT_ENABLE_HIGHWAY_AWARE_BUFFER = True
DEFAULT_HIGHWAY_BUFFER_ALPHA = 0.15  # meters per meter of highway length
HIGHWAY_TYPES = {"motorway", "trunk", "primary"}

# ------------------------------------------------------------
# Utilities
# ------------------------------------------------------------
def deep_clone(elem: ET.Element) -> ET.Element:
    new = ET.Element(elem.tag, attrib=dict(elem.attrib))
    new.text = elem.text
    new.tail = elem.tail
    for child in elem:
        new.append(deep_clone(child))
    return new


def _tile_road_ids(tile_root: ET.Element) -> set:
    return {r.get("id") for r in tile_root.findall("road") if r.get("id")}


def _build_parent_map(root: ET.Element) -> Dict[ET.Element, ET.Element]:
    return {c: p for p in root.iter() for c in list(p)}


def _drop_links_outside_tile(tile_root: ET.Element) -> None:
    road_ids = _tile_road_ids(tile_root)
    parent_map = _build_parent_map(tile_root)

    for link in tile_root.findall(".//lane/link/*"):
        road = link.get("road")
        if road and road not in road_ids:
            parent = parent_map.get(link)
            if parent is not None:
                parent.remove(link)


# ------------------------------------------------------------
# Lane semantics helpers
# ------------------------------------------------------------
def _mark_global_driving_lanes(src_root: ET.Element) -> int:
    """
    NOTE:
    This MUTATES the in-memory XODR tree used only for tiling.
    It is NOT written back to disk.
    """
    n = 0
    for lane in src_root.findall(".//lane[@type='driving']"):
        if lane.get("was_driving") != "true":
            lane.set("was_driving", "true")
            n += 1
    return n


def _is_lane_driving_in_tile(lane: ET.Element, preserve_global: bool) -> bool:
    if lane.get("type") == "driving":
        return True
    if preserve_global and lane.get("was_driving") == "true":
        return True
    return False


def _lane_successor_points_outside_tile(lane: ET.Element, tile_road_ids: set) -> bool:
    succ = lane.find("link/successor")
    return bool(succ is not None and succ.get("road") not in tile_road_ids)


def _lane_predecessor_points_outside_tile(lane: ET.Element, tile_road_ids: set) -> bool:
    pred = lane.find("link/predecessor")
    return bool(pred is not None and pred.get("road") not in tile_road_ids)


# ------------------------------------------------------------
# Geometry helpers
# ------------------------------------------------------------
def _road_bounds(road: ET.Element) -> Tuple[float, float, float, float]:
    xs, ys = [], []
    for g in road.findall(".//planView/geometry"):
        try:
            xs.append(float(g.get("x", "0.0")))
            ys.append(float(g.get("y", "0.0")))
        except ValueError:
            pass
    if not xs or not ys:
        return 0.0, 0.0, 0.0, 0.0
    return min(xs), min(ys), max(xs), max(ys)


def _road_length(road: ET.Element) -> float:
    length = 0.0
    for g in road.findall(".//planView/geometry"):
        try:
            length += float(g.get("length", "0.0"))
        except Exception:
            pass
    return length


def _is_highway(road: ET.Element) -> bool:
    return road.get("type") in HIGHWAY_TYPES


# ------------------------------------------------------------
# Tile construction helpers (moved out of tile())
# ------------------------------------------------------------
def _iter_tile_origins(
    min_x: float, max_x: float,
    min_y: float, max_y: float,
    tile_size: float
) -> Iterable[Tuple[int, int, float, float]]:
    ix = 0
    x = min_x
    while x < max_x:
        iy = 0
        y = min_y
        while y < max_y:
            yield ix, iy, x, y
            iy += 1
            y += tile_size
        ix += 1
        x += tile_size


def _compute_effective_buffer(
    base_buffer: float,
    roads: List[ET.Element],
    enable_highway_buffer: bool,
    alpha: float,
) -> float:
    if not enable_highway_buffer:
        return base_buffer

    extra = 0.0
    for r in roads:
        if _is_highway(r):
            extra = max(extra, _road_length(r) * alpha)

    return base_buffer + extra


def _build_tile_root(
    src_root: ET.Element,
    roads: List[ET.Element],
    tile_name: str,
    core_bounds: Tuple[float, float, float, float],
    buffer_m: float,
) -> ET.Element:
    core_min_x, core_min_y, core_max_x, core_max_y = core_bounds
    buf_min_x = core_min_x - buffer_m
    buf_max_x = core_max_x + buffer_m
    buf_min_y = core_min_y - buffer_m
    buf_max_y = core_max_y + buffer_m

    tile_root = ET.Element("OpenDRIVE")
    header = src_root.find("header")
    tile_root.append(deep_clone(header) if header is not None else ET.Element("header"))
    tile_root.find("header").set("name", tile_name)

    for r in roads:
        mnx, mny, mxx, mxy = _road_bounds(r)
        if not (mxx < buf_min_x or mnx > buf_max_x or mxy < buf_min_y or mny > buf_max_y):
            tile_root.append(deep_clone(r))

    return tile_root


def _analyze_tile_lanes(tile_root: ET.Element, preserve_global: bool) -> dict:
    road_ids = _tile_road_ids(tile_root)

    driving_like = 0
    succ_out = 0
    pred_out = 0

    for lane in tile_root.findall(".//lane"):
        if not _is_lane_driving_in_tile(lane, preserve_global):
            continue

        driving_like += 1

        if _lane_successor_points_outside_tile(lane, road_ids):
            succ_out += 1
            lane.set("_successor_outside_tile", "true")

        if _lane_predecessor_points_outside_tile(lane, road_ids):
            pred_out += 1
            lane.set("_predecessor_outside_tile", "true")

    return {
        "driving_like": driving_like,
        "successor_outside": succ_out,
        "predecessor_outside": pred_out,
    }


def _finalize_tile(
    tile_root: ET.Element,
    tile_name: str,
    out_dir: str,
    *,
    core_bounds: Tuple[float, float, float, float],
    buffer_m: float,
    analysis: dict,
    preserve_global: bool,
    allow_outside: bool,
    strict: bool,
) -> Tuple[str, dict]:
    if tile_root.findall("road") and analysis["driving_like"] == 0:
        msg = (
            f"[TILER NOTICE] {tile_name}: no locally-routable driving lanes. "
            "Tile remains valid as a global-map subgraph."
        )
        print(f"⚠ {msg}")

    out_path = os.path.join(out_dir, f"{tile_name}.xodr")
    ET.ElementTree(tile_root).write(out_path, encoding="utf-8", xml_declaration=True)

    succ_out = analysis["successor_outside"]
    pred_out = analysis["predecessor_outside"]
    driving_like = analysis["driving_like"]

    health = {
        "is_drivable": driving_like > 0,
        "num_roads": len(tile_root.findall("road")),
        "num_driving_lanes_xml": len(tile_root.findall(".//lane[@type='driving']")),
        "num_driving_lanes_semantic": driving_like,
        "bounds": {
            "core": {
                "xmin": core_bounds[0],
                "ymin": core_bounds[1],
                "xmax": core_bounds[2],
                "ymax": core_bounds[3],
            },
            "buffer_m": buffer_m,
        },
        "semantics": {
            "preserve_global_lane_types_in_tiles": preserve_global,
            "allow_successor_outside_tile": allow_outside,
            "drivable_in_full_map": driving_like > 0,
            "locally_closed_routing_graph": (succ_out == 0 and pred_out == 0),
            "successor_leakage": succ_out > 0,
            "predecessor_leakage": pred_out > 0,
        },
    }

    return out_path, health


# ------------------------------------------------------------
# Public API
# ------------------------------------------------------------
class TileExtractor:

    @staticmethod
    def tile(
        input_xodr: str,
        out_dir: str,
        *,
        tile_size: float = 1000.0,
        strict_semantics: bool = False,
        preserve_global_lane_types_in_tiles: Optional[bool] = None,
        allow_successor_outside_tile: Optional[bool] = None,
        tile_buffer_m: Optional[float] = None,
    ) -> Tuple[List[str], Dict[str, dict]]:

        preserve_global = preserve_global_lane_types_in_tiles \
            if preserve_global_lane_types_in_tiles is not None \
            else _get_setting("PRESERVE_GLOBAL_LANE_TYPES_IN_TILES", True)

        allow_outside = allow_successor_outside_tile \
            if allow_successor_outside_tile is not None \
            else _get_setting("ALLOW_SUCCESSOR_OUTSIDE_TILE", True)

        base_buffer = tile_buffer_m \
            if tile_buffer_m is not None \
            else float(_get_setting("TILE_BUFFER_M", DEFAULT_TILE_BUFFER_M))

        # Safety clamp (deterministic)
        base_buffer = max(0.0, min(base_buffer, 100.0))

        enable_highway_buffer = _get_setting(
            "ENABLE_HIGHWAY_AWARE_TILE_BUFFER",
            DEFAULT_ENABLE_HIGHWAY_AWARE_BUFFER,
        )
        alpha = float(_get_setting("HIGHWAY_TILE_BUFFER_ALPHA", DEFAULT_HIGHWAY_BUFFER_ALPHA))

        tree = ET.parse(input_xodr)
        root = tree.getroot()
        roads = list(root.findall("road"))

        if not roads:
            return [], {}

        _mark_global_driving_lanes(root)

        xs, ys = [], []
        for r in roads:
            mnx, mny, mxx, mxy = _road_bounds(r)
            xs.extend([mnx, mxx])
            ys.extend([mny, mxy])

        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        os.makedirs(out_dir, exist_ok=True)

        tiles: List[str] = []
        tile_health: Dict[str, dict] = {}

        for ix, iy, x, y in _iter_tile_origins(min_x, max_x, min_y, max_y, tile_size):
            tile_name = f"tile_{ix}_{iy}"
            core_bounds = (x, y, x + tile_size, y + tile_size)

            effective_buffer = _compute_effective_buffer(
                base_buffer,
                roads,
                enable_highway_buffer,
                alpha,
            )

            tile_root = _build_tile_root(
                root,
                roads,
                tile_name,
                core_bounds,
                effective_buffer,
            )

            if not tile_root.findall("road"):
                continue

            if not allow_outside:
                _drop_links_outside_tile(tile_root)

            analysis = _analyze_tile_lanes(tile_root, preserve_global)

            out_path, health = _finalize_tile(
                tile_root,
                tile_name,
                out_dir,
                core_bounds=core_bounds,
                buffer_m=effective_buffer,
                analysis=analysis,
                preserve_global=preserve_global,
                allow_outside=allow_outside,
                strict=strict_semantics,
            )

            tiles.append(out_path)
            tile_health[tile_name] = health

        return tiles, tile_health
