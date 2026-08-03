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

from pyproj import Transformer

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.enrichment.building_extruder import BuildingFootprint


# ---------------------------------------------------------------------
# Coordinate system / transformer
# ---------------------------------------------------------------------
# Use the same CRS as <geoReference>, driven by coordinates.json
_gps = SETTINGS.load_gps_bounds()
_lat0 = _gps["lat_min"]
_lon0 = _gps["lon_min"]

PROJ_STRING = (
    f"+proj=tmerc +lat_0={_lat0} +lon_0={_lon0} "
    "+k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
)

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
            lat = float(n.get("lat", "0"))
            lon = float(n.get("lon", "0"))
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

        def _append_building(buildings, ring, props):
            coords_xy = []
            for lon, lat in ring:
                x, y = TRANSFORMER.transform(lon, lat)
                coords_xy.append((x, y))

            if len(coords_xy) < 3:
                return
            if coords_xy[0] != coords_xy[-1]:
                coords_xy.append(coords_xy[0])

            if polygon_area(coords_xy) < min_area:
                return

            buildings.append(
                BuildingFootprint(
                    footprint=coords_xy,
                    height=_height_from_props(props),
                    id=props.get("id"),
                    name=props.get("name"),
                )
            )

        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            data = json.load(f)

        buildings = []

        if data.get("type") == "FeatureCollection":
            for feat in data.get("features", []):
                geom = feat.get("geometry")
                if not geom or geom.get("type") != "Polygon":
                    continue

                props = dict(feat.get("properties", {}) or {})
                ring = geom["coordinates"][0]
                _append_building(buildings, ring, props)

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
            ring = []
            for pt in geometry:
                try:
                    ring.append((float(pt["lon"]), float(pt["lat"])))
                except Exception:
                    ring = []
                    break
            if len(ring) < 3:
                continue
            props = dict(tags)
            if elem.get("id") is not None:
                props.setdefault("id", f"osm_bld_{elem.get('id')}")
            _append_building(buildings, ring, props)

        print(f"[BUILDINGS] Loaded {len(buildings)} building footprints from Overpass JSON")
        return buildings
