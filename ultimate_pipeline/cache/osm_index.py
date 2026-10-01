#!/usr/bin/env python3
"""Reusable OSM index - parse OSM once, assign to many tiles."""
from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from lxml import etree
    HAS_LXML = True
except ImportError:
    import xml.etree.ElementTree as etree
    HAS_LXML = False


@dataclass
class OsmNode:
    """OSM node with coordinates."""
    id: int
    lat: float
    lon: float
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class OsmWay:
    """OSM way with node references."""
    id: int
    nodes: list[int] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class OsmRelation:
    """OSM relation with member references."""
    id: int
    members: list[dict] = field(default_factory=list)  # {type, ref, role}
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class OsmIndex:
    """Indexed OSM document for fast tile assignment."""
    nodes: dict[int, OsmNode] = field(default_factory=dict)
    ways: dict[int, OsmWay] = field(default_factory=dict)
    relations: dict[int, OsmRelation] = field(default_factory=dict)
    buildings: list[OsmWay] = field(default_factory=list)
    bounds: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_file(cls, osm_path: Path, file_type: str = "xml") -> "OsmIndex":
        """Parse OSM file (XML or PBF) and build index."""
        if file_type == "xml":
            return cls._from_xml(osm_path)
        elif file_type == "pbf":
            return cls._from_pbf(osm_path)
        else:
            raise ValueError(f"Unknown OSM file type: {file_type}")

    @classmethod
    def _from_xml(cls, osm_path: Path) -> "OsmIndex":
        """Parse OSM XML file."""
        if HAS_LXML:
            parser = etree.XMLParser(remove_blank_text=True, huge_tree=True)
            tree = etree.parse(str(osm_path), parser)
        else:
            tree = etree.parse(str(osm_path))
        root = tree.getroot()

        index = cls()

        # Parse bounds
        bounds_elem = root.find("bounds")
        if bounds_elem is not None:
            index.bounds = {
                "minlat": float(bounds_elem.get("minlat", 0)),
                "minlon": float(bounds_elem.get("minlon", 0)),
                "maxlat": float(bounds_elem.get("maxlat", 0)),
                "maxlon": float(bounds_elem.get("maxlon", 0)),
            }

        # Parse nodes
        for node_elem in root.findall("node"):
            nid = int(node_elem.get("id", 0))
            lat = float(node_elem.get("lat", 0))
            lon = float(node_elem.get("lon", 0))
            tags = {}
            for tag_elem in node_elem.findall("tag"):
                tags[tag_elem.get("k")] = tag_elem.get("v")
            index.nodes[nid] = OsmNode(id=nid, lat=lat, lon=lon, tags=tags)

        # Parse ways
        for way_elem in root.findall("way"):
            wid = int(way_elem.get("id", 0))
            nodes = []
            tags = {}
            for child in way_elem:
                if child.tag == "nd":
                    nodes.append(int(child.get("ref", 0)))
                elif child.tag == "tag":
                    tags[child.get("k")] = child.get("v")
            way = OsmWay(id=wid, nodes=nodes, tags=tags)
            index.ways[wid] = way

            # Identify buildings
            if tags.get("building"):
                index.buildings.append(way)

        # Parse relations
        for rel_elem in root.findall("relation"):
            rid = int(rel_elem.get("id", 0))
            members = []
            tags = {}
            for child in rel_elem:
                if child.tag == "member":
                    members.append({
                        "type": child.get("type"),
                        "ref": int(child.get("ref", 0)),
                        "role": child.get("role", ""),
                    })
                elif child.tag == "tag":
                    tags[child.get("k")] = child.get("v")
            rel = OsmRelation(id=rid, members=members, tags=tags)
            index.relations[rid] = rel

        return index

    @classmethod
    def _from_pbf(cls, osm_path: Path) -> "OsmIndex":
        """Parse OSM PBF file (requires osmium)."""
        # PBF parsing would use osmium or similar
        # For now, fall back to XML
        return cls._from_xml(osm_path)

    def get_building_polygons(self, transformer=None) -> list[dict]:
        """Extract building polygons with optional coordinate transformation."""
        from pyproj import Transformer
        if transformer is None:
            transformer = Transformer.from_crs("EPSG:4326", "+proj=tmerc +datum=WGS84 +units=m +no_defs", always_xy=True)

        polygons = []
        for way in self.buildings:
            coords = []
            for nid in way.nodes:
                node = self.nodes.get(nid)
                if node:
                    if transformer:
                        x, y = transformer.transform(node.lon, node.lat)
                        coords.append((x, y))
                    else:
                        coords.append((node.lon, node.lat))
            if len(coords) >= 3:
                # Close polygon
                if coords[0] != coords[-1]:
                    coords.append(coords[0])
                polygons.append({
                    "way_id": way.id,
                    "tags": way.tags,
                    "coords": coords,
                })
        return polygons

    def assign_buildings_to_tiles(
        self,
        tile_size: float,
        header_offset: tuple[float, float],
        origin: tuple[float, float] = (0.0, 0.0),
        transformer=None,
    ) -> dict[tuple[int, int], list[dict]]:
        """Assign buildings to tiles by centroid."""
        from pyproj import Transformer
        if transformer is None:
            transformer = Transformer.from_crs("EPSG:4326", "+proj=tmerc +datum=WGS84 +units=m +no_defs", always_xy=True)

        ox, oy = header_offset
        tiles: dict[tuple[int, int], list[dict]] = defaultdict(list)

        for way in self.buildings:
            # Compute centroid in WGS84
            xs, ys = [], []
            for nid in way.nodes:
                node = self.nodes.get(nid)
                if node:
                    xs.append(node.lon)
                    ys.append(node.lat)
            if not xs:
                continue
            centroid_lon = sum(xs) / len(xs)
            centroid_lat = sum(ys) / len(ys)

            # Project to local frame
            gx, gy = transformer.transform(centroid_lon, centroid_lat)
            local_x = gx - ox
            local_y = gy - oy

            # Tile index
            tx = int((local_x - origin[0]) // tile_size)
            ty = int((local_y - origin[1]) // tile_size)

            tiles[(tx, ty)].append({
                "way_id": way.id,
                "tags": way.tags,
                "centroid_local": (local_x, local_y),
            })

        return dict(tiles)

    def save(self, path: Path):
        """Save index to JSON."""
        data = {
            "schema": "osm_index/v1",
            "bounds": self.bounds,
            "nodes": {str(k): {"id": v.id, "lat": v.lat, "lon": v.lon, "tags": v.tags} for k, v in self.nodes.items()},
            "ways": {str(k): {"id": v.id, "nodes": v.nodes, "tags": v.tags} for k, v in self.ways.items()},
            "relations": {str(k): {"id": v.id, "members": v.members, "tags": v.tags} for k, v in self.relations.items()},
            "buildings": [{"id": w.id, "nodes": w.nodes, "tags": w.tags} for w in self.buildings],
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "OsmIndex":
        """Load index from JSON."""
        data = json.loads(path.read_text(encoding="utf-8"))
        index = cls()
        index.bounds = data.get("bounds", {})
        index.nodes = {int(k): OsmNode(**v) for k, v in data["nodes"].items()}
        index.ways = {int(k): OsmWay(**v) for k, v in data["ways"].items()}
        index.relations = {int(k): OsmRelation(**v) for k, v in data["relations"].items()}
        index.buildings = [OsmWay(**w) for w in data["buildings"]]
        return index