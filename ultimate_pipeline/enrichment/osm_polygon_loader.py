#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
import os

# ---------------------------------------------------------------------
# Make project root importable when running this file directly
# ---------------------------------------------------------------------
ROOT = os.path.abspath(os.path.join(__file__, "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import math
from dataclasses import field

from pyproj import Transformer

from ultimate_pipeline.enrichment.building_extruder import BuildingFootprint


# ---------------------------------------------------------------------
# Coordinate system / transformer
# ---------------------------------------------------------------------
# Use the SAME frame as the road network's <geoReference>: a BARE tmerc projection
# (implicit lat_0=0/lon_0=0 -- the global equator/prime-meridian origin), matching
# Osm2Odr's own convention and
# ultimate_pipeline.domain_gap.local_registration.BARE_TMERC_DEFAULT.
#
# C29 (2026-08-26): this used to be `+lat_0=<gps.lat_min> +lon_0=<gps.lon_min>` -- a
# DIFFERENT tmerc origin (the configured GPS bbox corner) than roads. Verified on the
# real pinned map: building cornerGlobal centroid was 7,665m from the road centroid as
# a direct result. Buildings must project through the same global frame roads use so
# that scripts/regen_map_of_record.py's _rebase_to_local (which also had to be extended
# to shift cornerGlobal points, see the same C29 fix) produces a consistent local frame.
PROJ_STRING = "+proj=tmerc +datum=WGS84 +units=m +no_defs"

# Global transformer: WGS84 (lon, lat) → local tmerc (x, y) in meters
TRANSFORMER = Transformer.from_crs(
    "EPSG:4326",
    PROJ_STRING,
    always_xy=True,
)


class OSMPolygonLoader:
    """
    Load building footprints from OSM XML / GeoJSON and convert lat/lon into
    the same projected coordinate system used by the OpenDRIVE geoReference.

    Output: list of BuildingFootprint dataclasses.
    """

    # ------------------------------------------------------------------
    # OSM XML loader
    # ------------------------------------------------------------------
    @staticmethod
    def load_buildings_from_osm(
        osm_path: str,
        ref_lat: Optional[float] = None,
        ref_lon: Optional[float] = None,
        min_area: float = 5.0,
    ) -> List[BuildingFootprint]:
        """
        Parse building footprints from an OSM .osm or .xml file.

        min_area is in square meters in projected coordinates.
        """
        if not Path(osm_path).exists():
            raise FileNotFoundError(
                f"OSM building source not found: {osm_path}\n"
                "Run: python -m ultimate_pipeline.enrichment.fetch_overpass "
                f"--bbox ... --out {osm_path}"
            )
        tree = ET.parse(osm_path)
        root = tree.getroot()

        # Collect OSM nodes: id -> (lat, lon)
        nodes: Dict[str, Tuple[float, float]] = {}
        for n in root.findall("node"):
            nid = n.get("id")
            if nid is None:
                continue
            try:
                lat = float(n.get("lat", "0"))
                lon = float(n.get("lon", "0"))
            except (TypeError, ValueError):
                continue
            nodes[nid] = (lat, lon)

        if not nodes:
            return []

        # Shoelace area formula in projected coordinates
        def polygon_area(coords: List[Tuple[float, float]]) -> float:
            if len(coords) < 3:
                return 0.0
            a = 0.0
            for i in range(len(coords)):
                x1, y1 = coords[i]
                x2, y2 = coords[(i + 1) % len(coords)]
                a += x1 * y2 - x2 * y1
            return abs(a) * 0.5

        buildings: List[BuildingFootprint] = []

        for way in root.findall("way"):
            tags = {t.get("k"): t.get("v") for t in way.findall("tag")}
            if "building" not in tags:
                continue

            nds = [nd.get("ref") for nd in way.findall("nd")]
            nds = [nid for nid in nds if nid is not None]
            if len(nds) < 3:
                continue

            coords_xy: List[Tuple[float, float]] = []
            for nid in nds:
                if nid not in nodes:
                    continue
                lat, lon = nodes[nid]

                # Transform to projected coordinates (meters)
                x, y = TRANSFORMER.transform(lon, lat)
                coords_xy.append((x, y))

            if len(coords_xy) < 3:
                continue

            # Ensure closed polygon
            if coords_xy[0] != coords_xy[-1]:
                coords_xy.append(coords_xy[0])

            # Ignore tiny stuff (sheds, balconies, etc.)
            if polygon_area(coords_xy) < min_area:
                continue

            # Height estimation
            height = 10.0  # fallback
            if "building:levels" in tags:
                try:
                    height = float(tags["building:levels"]) * 3.0
                except Exception:
                    pass

            bid = way.get("id", None)
            bname = tags.get("name", None)

            buildings.append(
                BuildingFootprint(
                    footprint=coords_xy,
                    height=height,
                    id=f"osm_bld_{bid}" if bid else None,
                    name=bname,
                )
            )

        # --- multipolygon relation buildings (C25/C49) ---------------------------
        # The way-loop above handles standalone `<way building=...>`. OSM also
        # models buildings as `<relation type="multipolygon">` (courtyards,
        # multi-part footprints) whose `building` tag is on the RELATION, not the
        # member ways. We now preserve inner rings (courtyards) and multipart topology.
        ways_raw: Dict[str, List[str]] = {}
        for w in root.findall("way"):
            wid = w.get("id")
            if wid is not None:
                ways_raw[wid] = [nd.get("ref") for nd in w.findall("nd") if nd.get("ref") is not None]

        def _stitch_rings(way_ids: List[str]) -> List[List[str]]:
            """Chain member ways by shared endpoints into closed node-ref rings."""
            segs = [list(ways_raw[w]) for w in way_ids if w in ways_raw and len(ways_raw[w]) >= 2]
            rings: List[List[str]] = []
            while segs:
                ring = segs.pop(0)
                progressed = True
                while ring and ring[0] != ring[-1] and progressed:
                    progressed = False
                    for i, seg in enumerate(segs):
                        if seg[0] == ring[-1]:
                            ring += seg[1:]; segs.pop(i); progressed = True; break
                        if seg[-1] == ring[-1]:
                            ring += list(reversed(seg))[1:]; segs.pop(i); progressed = True; break
                        if seg[-1] == ring[0]:
                            ring = seg[:-1] + ring; segs.pop(i); progressed = True; break
                        if seg[0] == ring[0]:
                            ring = list(reversed(seg))[:-1] + ring; segs.pop(i); progressed = True; break
                if len(ring) >= 4 and ring[0] == ring[-1]:
                    rings.append(ring)  # else: unclosable -> skip (fail-open)
            return rings

        def _node_refs_to_xy(node_refs: List[str]) -> List[Tuple[float, float]]:
            """Convert node refs to projected XY coordinates."""
            coords_xy: List[Tuple[float, float]] = []
            for nid in node_refs:
                if nid in nodes:
                    lat, lon = nodes[nid]
                    coords_xy.append(TRANSFORMER.transform(lon, lat))
            return coords_xy

        def _emit_part(outer_ring: List[str], inner_rings: List[List[str]], rtags: Dict[str, str], obj_id: Optional[str]) -> None:
            """Emit a building part with outer ring and inner rings (holes)."""
            outer_xy = _node_refs_to_xy(outer_ring)
            if len(outer_xy) < 3:
                return
            if outer_xy[0] != outer_xy[-1]:
                outer_xy.append(outer_xy[0])
            if polygon_area(outer_xy) < min_area:
                return

            inners_xy: List[List[Tuple[float, float]]] = []
            for inner in inner_rings:
                inner_xy = _node_refs_to_xy(inner)
                if len(inner_xy) < 3:
                    continue
                if inner_xy[0] != inner_xy[-1]:
                    inner_xy.append(inner_xy[0])
                if polygon_area(inner_xy) < min_area:
                    continue
                inners_xy.append(inner_xy)

            h = 10.0
            if "building:levels" in rtags:
                try:
                    h = float(rtags["building:levels"]) * 3.0
                except Exception:
                    pass

            buildings.append(
                BuildingFootprint(
                    footprint=outer_xy,
                    height=h,
                    id=obj_id,
                    name=rtags.get("name"),
                    inners=inners_xy,
                )
            )

        def _ring_centroid_xy(ring: List[str]) -> Tuple[float, float]:
            """Compute centroid of a ring in XY space."""
            xy = _node_refs_to_xy(ring)
            if len(xy) < 3:
                return (0.0, 0.0)
            mx = sum(p[0] for p in xy) / len(xy)
            my = sum(p[1] for p in xy) / len(xy)
            return (mx, my)

        def _point_in_polygon_xy(point: Tuple[float, float], polygon: List[Tuple[float, float]]) -> bool:
            """Ray-casting point-in-polygon test in XY space."""
            x, y = point
            inside = False
            n = len(polygon)
            if n < 3:
                return False
            for i in range(n):
                x1, y1 = polygon[i]
                x2, y2 = polygon[(i + 1) % n]
                if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1) + x1):
                    inside = not inside
            return inside

        for rel in root.findall("relation"):
            rtags = {t.get("k"): t.get("v") for t in rel.findall("tag")}
            if rtags.get("type") != "multipolygon" or "building" not in rtags:
                continue

            # Separate outer and inner members
            outer_ids = [
                m.get("ref") for m in rel.findall("member")
                if m.get("type") == "way" and m.get("role") in ("outer", "", None) and m.get("ref")
            ]
            inner_ids = [
                m.get("ref") for m in rel.findall("member")
                if m.get("type") == "way" and m.get("role") == "inner" and m.get("ref")
            ]

            outer_rings = _stitch_rings(outer_ids)
            inner_rings = _stitch_rings(inner_ids)

            rid = rel.get("id")
            if not outer_rings:
                continue

            # For each outer ring, associate inner rings by point-in-polygon
            for outer in outer_rings:
                outer_xy = _node_refs_to_xy(outer)
                if len(outer_xy) < 3:
                    continue

                associated_inners: List[List[str]] = []
                for inner in inner_rings:
                    inner_centroid = _ring_centroid_xy(inner)
                    if _point_in_polygon_xy(inner_centroid, outer_xy):
                        associated_inners.append(inner)

                _emit_part(outer, associated_inners, rtags, f"osm_bld_rel_{rid}" if rid else None)

        return buildings

    # ------------------------------------------------------------------
    # Optional helper: direct lat/lon → x/y
    # ------------------------------------------------------------------
    @staticmethod
    def _latlon_to_xy(lat: float, lon: float) -> Tuple[float, float]:
        """
        Helper to project a single WGS84 coordinate into local CRS.
        """
        x, y = TRANSFORMER.transform(lon, lat)
        return x, y

    # ------------------------------------------------------------------
    # GeoJSON loader (buildings.geojson)
    # ------------------------------------------------------------------
    @staticmethod
    def load_buildings_from_geojson(path: str, min_area: float = 5.0):
        import json

        if not Path(path).exists():
            raise FileNotFoundError(
                f"Overpass JSON export not found: {path}\n"
                "Run: python -m ultimate_pipeline.enrichment.fetch_overpass "
                f"--bbox ... --out {path}"
            )

        def polygon_area(coords):
            a = 0.0
            for i in range(len(coords)):
                x1, y1 = coords[i]
                x2, y2 = coords[(i + 1) % len(coords)]
                a += x1 * y2 - x2 * y1
            return abs(a) * 0.5

        def _height_from_props(props):
            height = 10.0
            if "building:levels" in props:
                try:
                    height = float(props["building:levels"]) * 3.0
                except Exception:
                    pass
            return height

        def _ring_to_xy(ring):
            coords_xy = []
            for lon, lat in ring:
                x, y = TRANSFORMER.transform(lon, lat)
                coords_xy.append((x, y))
            return coords_xy

        def _emit_part(buildings, outer_ring, inner_rings, props):
            """Emit a building part with outer and inner rings."""
            outer_xy = _ring_to_xy(outer_ring)
            if len(outer_xy) < 3:
                return
            if outer_xy[0] != outer_xy[-1]:
                outer_xy.append(outer_xy[0])
            if polygon_area(outer_xy) < min_area:
                return

            inners_xy: List[List[Tuple[float, float]]] = []
            for inner in inner_rings:
                inner_xy = _ring_to_xy(inner)
                if len(inner_xy) < 3:
                    continue
                if inner_xy[0] != inner_xy[-1]:
                    inner_xy.append(inner_xy[0])
                if polygon_area(inner_xy) < min_area:
                    continue
                inners_xy.append(inner_xy)

            buildings.append(
                BuildingFootprint(
                    footprint=outer_xy,
                    height=_height_from_props(props),
                    id=props.get("id"),
                    name=props.get("name"),
                    inners=inners_xy,
                )
            )

        def _ring_centroid(ring):
            if not ring:
                return (0.0, 0.0)
            mx = sum(p[0] for p in ring) / len(ring)
            my = sum(p[1] for p in ring) / len(ring)
            return (mx, my)

        def _point_in_polygon(point, polygon):
            x, y = point
            inside = False
            n = len(polygon)
            if n < 3:
                return False
            for i in range(n):
                x1, y1 = polygon[i]
                x2, y2 = polygon[(i + 1) % n]
                if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1) + x1):
                    inside = not inside
            return inside

        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            data = json.load(f)

        buildings = []

        if data.get("type") == "FeatureCollection":
            for feat in data.get("features", []):
                geom = feat.get("geometry")
                if not geom or geom.get("type") != "Polygon":
                    continue

                props = dict(feat.get("properties", {}) or {})
                outer_ring = geom["coordinates"][0]
                inner_rings = geom["coordinates"][1:] if len(geom["coordinates"]) > 1 else []
                _emit_part(buildings, outer_ring, inner_rings, props)

            print(f"[BUILDINGS] Loaded {len(buildings)} building footprints from GeoJSON")
            return buildings

        # Overpass JSON often arrives with a .geojson extension but stores
        # building ways under top-level `elements`.
        for elem in data.get("elements", []):
            if elem.get("type") != "way":
                continue
            tags = dict(elem.get("tags", {}) or {})
            if "building" not in tags:
                continue
            geometry = elem.get("geometry") or []
            if len(geometry) < 3:
                continue
            outer_ring = []
            for pt in geometry:
                try:
                    outer_ring.append((float(pt["lon"]), float(pt["lat"])))
                except Exception:
                    outer_ring = []
                    break
            if len(outer_ring) < 3:
                continue
            props = dict(tags)
            if elem.get("id") is not None:
                props.setdefault("id", f"osm_bld_{elem.get('id')}")
            _emit_part(buildings, outer_ring, [], props)

        # --- multipolygon relation buildings (C28/C49) ----------------------------
        # Overpass "out geom" relations carry `building` on the RELATION, not the
        # member ways, and each member already embeds its own ordered point list
        # (no node-ref table to stitch). Preserve inner rings (courtyards).
        for elem in data.get("elements", []):
            if elem.get("type") != "relation":
                continue
            tags = dict(elem.get("tags", {}) or {})
            if tags.get("type") != "multipolygon" or "building" not in tags:
                continue
            rel_id = elem.get("id")
            props = dict(tags)
            props.setdefault("id", f"osm_bld_rel_{rel_id}" if rel_id is not None else None)

            outer_members = []
            inner_members = []
            for mem in elem.get("members", []):
                if mem.get("type") != "way":
                    continue
                role = mem.get("role", "")
                geometry = mem.get("geometry") or []
                if len(geometry) < 3:
                    continue
                ring = []
                for pt in geometry:
                    try:
                        ring.append((float(pt["lon"]), float(pt["lat"])))
                    except Exception:
                        ring = []
                        break
                if len(ring) < 3:
                    continue
                if ring[0] != ring[-1]:
                    ring = ring + [ring[0]]
                if role == "inner":
                    inner_members.append(ring)
                else:
                    outer_members.append(ring)

            # Associate inner rings with outer rings by point-in-polygon
            def _ring_centroid_lonlat(ring):
                if not ring:
                    return (0.0, 0.0)
                mx = sum(p[0] for p in ring) / len(ring)
                my = sum(p[1] for p in ring) / len(ring)
                return (mx, my)

            def _point_in_polygon_lonlat(point, polygon):
                x, y = point
                inside = False
                n = len(polygon)
                if n < 3:
                    return False
                for i in range(n):
                    x1, y1 = polygon[i]
                    x2, y2 = polygon[(i + 1) % n]
                    if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1) + x1):
                        inside = not inside
                return inside

            for outer in outer_members:
                outer_xy = _ring_to_xy(outer)
                if len(outer_xy) < 3:
                    continue

                associated_inners = []
                for inner in inner_members:
                    inner_centroid = _ring_centroid_lonlat(inner)
                    if _point_in_polygon_lonlat(inner_centroid, outer):
                        associated_inners.append(inner)

                _emit_part(buildings, outer, associated_inners, props)

        print(f"[BUILDINGS] Loaded {len(buildings)} building footprints from Overpass JSON")
        return buildings
