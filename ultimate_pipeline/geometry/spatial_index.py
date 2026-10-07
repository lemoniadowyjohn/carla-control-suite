#!/usr/bin/env python3
"""Spatial indexes for nearest neighbor, point-in-polygon, tile assignment."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np

try:
    from scipy.spatial import KDTree
    HAS_SCIPY = True
except ImportError:
    KDTree = None
    HAS_SCIPY = False

try:
    from rtree import index as rtree_index
    HAS_RTREE = True
except ImportError:
    rtree_index = None
    HAS_RTREE = False


@dataclass
class SpatialIndex:
    """Unified spatial index supporting KDTree, R-tree, and STRtree-like operations."""
    points: np.ndarray  # [N, 2] or [N, 3]
    metadata: list[Any] = field(default_factory=list)
    kdtree: Optional[Any] = None
    rtree: Optional[Any] = None
    bounds: Optional[tuple[float, float, float, float]] = None

    def __post_init__(self):
        if len(self.points) > 0 and self.kdtree is None and HAS_SCIPY:
            self.kdtree = KDTree(self.points[:, :2])

    @classmethod
    def from_coords(cls, coords: np.ndarray, metadata: Optional[list] = None) -> "SpatialIndex":
        """Create index from coordinate array."""
        coords = np.asarray(coords)
        if coords.ndim == 1:
            coords = coords.reshape(-1, 2)
        if metadata is None:
            metadata = list(range(len(coords)))
        return cls(points=coords, metadata=metadata)

    @classmethod
    def from_geojson(cls, geojson_path: Path) -> "SpatialIndex":
        """Build index from GeoJSON file."""
        import json
        data = json.loads(geojson_path.read_text())
        points = []
        metadata = []
        for feature in data.get("features", []):
            geom = feature.get("geometry", {})
            if geom.get("type") == "Point":
                coords = geom.get("coordinates", [])
                if len(coords) >= 2:
                    points.append(coords[:2])
                    metadata.append(feature.get("properties", {}))
        return cls.from_coords(np.array(points), metadata)

    def query_knn(self, query_points: np.ndarray, k: int = 1) -> tuple[np.ndarray, np.ndarray]:
        """K-nearest neighbors query.
        
        Args:
            query_points: [M, 2] query points
            k: Number of neighbors
            
        Returns:
            (distances [M, k], indices [M, k])
        """
        if self.kdtree is None:
            raise ValueError("KDTree not available - install scipy")
        query_points = np.asarray(query_points)
        if query_points.ndim == 1:
            query_points = query_points.reshape(1, -1)
        return self.kdtree.query(query_points[:, :2], k=k)

    def query_radius(self, query_points: np.ndarray, radius: float) -> list[np.ndarray]:
        """Radius query - return indices of points within radius.
        
        Args:
            query_points: [M, 2] query points
            radius: Search radius
            
        Returns:
            List of index arrays for each query point
        """
        if self.kdtree is None:
            raise ValueError("KDTree not available - install scipy")
        query_points = np.asarray(query_points)
        if query_points.ndim == 1:
            query_points = query_points.reshape(1, -1)
        return self.kdtree.query_ball_point(query_points[:, :2], r=radius)

    def query_bbox(self, bbox: tuple[float, float, float, float]) -> np.ndarray:
        """Bounding box query using R-tree if available, else KDTree approximation.
        
        Args:
            bbox: (minx, miny, maxx, maxy)
            
        Returns:
            Indices of points within bbox
        """
        minx, miny, maxx, maxy = bbox
        if self.kdtree is not None:
            # Approximate with KDTree radius query from bbox center
            cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
            radius = max(maxx - cx, maxy - cy) * 1.5
            idxs = self.kdtree.query_ball_point([cx, cy], r=radius)
            if idxs:
                pts = self.points[idxs]
                mask = (pts[:, 0] >= minx) & (pts[:, 0] <= maxx) & \
                       (pts[:, 1] >= miny) & (pts[:, 1] <= maxy)
                return np.array(idxs)[mask]
            return np.array([], dtype=int)

        # Fallback to linear scan
        pts = self.points
        mask = (pts[:, 0] >= minx) & (pts[:, 0] <= maxx) & \
               (pts[:, 1] >= miny) & (pts[:, 1] <= maxy)
        return np.where(mask)[0]

    def build_rtree(self, capacity: int = 10) -> None:
        """Build R-tree index for polygon/rectangle queries."""
        if not HAS_RTREE:
            return
        props = rtree_index.Property()
        props.capacity = capacity
        self.rtree = rtree_index.Index(properties=props)
        for i, pt in enumerate(self.points):
            if len(pt) >= 2:
                self.rtree.insert(i, (pt[0], pt[1], pt[0], pt[1]))

    def rtree_intersection(self, bbox: tuple[float, float, float, float]) -> list[int]:
        """R-tree intersection query."""
        if self.rtree is None:
            self.build_rtree()
        return list(self.rtree.intersection(bbox))

    def nearest(self, query_point: np.ndarray) -> tuple[int, float]:
        """Find nearest point (index, distance)."""
        if self.kdtree is None:
            raise ValueError("KDTree not available")
        query_point = np.asarray(query_point)
        if query_point.ndim == 1:
            query_point = query_point.reshape(1, -1)
        dist, idx = self.kdtree.query(query_point[:, :2], k=1)
        return int(idx), float(dist)

    def save(self, path: Path):
        """Save index to disk."""
        data = {
            "points": self.points.tolist(),
            "metadata": self.metadata,
            "bounds": self.bounds,
        }
        path.write_text(json.dumps(data), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "SpatialIndex":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            points=np.array(data["points"]),
            metadata=data.get("metadata", []),
            bounds=data.get("bounds"),
        )


# Tile assignment using spatial index
@dataclass
class TileAssignmentIndex:
    """Spatial index for tile assignment with fast polygon queries."""
    tile_bounds: dict[tuple[int, int], tuple[float, float, float, float]] = field(default_factory=dict)
    tile_polygons: dict[tuple[int, int], list[tuple[float, float]]] = field(default_factory=dict)
    rtree: Optional[Any] = None
    tile_size: float = 1000.0

    def __post_init__(self):
        if HAS_RTREE and self.tile_polygons:
            self._build_rtree()

    def _build_rtree(self):
        props = rtree_index.Property()
        self.rtree = rtree_index.Index(properties=props)
        for (tx, ty), poly in self.tile_polygons.items():
            if len(poly) >= 3:
                xs = [p[0] for p in poly]
                ys = [p[1] for p in poly]
                bbox = (min(xs), min(ys), max(xs), max(ys))
                self.rtree.insert(hash((tx, ty)), bbox)

    @classmethod
    def from_grid(cls, tile_size: float, origin: tuple[float, float] = (0, 0),
                  tx_range: tuple[int, int] = (-5, 15), ty_range: tuple[int, int] = (-5, 15)) -> "TileAssignmentIndex":
        """Create index for regular grid tiles."""
        index = cls(tile_size=tile_size)
        for tx in range(tx_range[0], tx_range[1] + 1):
            for ty in range(ty_range[0], ty_range[1] + 1):
                x0 = origin[0] + tx * tile_size
                y0 = origin[1] + ty * tile_size
                x1 = x0 + tile_size
                y1 = y0 + tile_size
                index.tile_bounds[(tx, ty)] = (x0, y0, x1, y1)
                index.tile_polygons[(tx, ty)] = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        return index

    def assign_point(self, x: float, y: float) -> tuple[int, int]:
        """Assign point to tile using R-tree or direct grid math."""
        if self.rtree is not None:
            hits = list(self.rtree.intersection((x, y, x, y)))
            if hits:
                # Convert hash back to tile index (approximate)
                for (tx, ty) in self.tile_bounds:
                    if hash((tx, ty)) == hits[0]:
                        return (tx, ty)
        # Fallback: direct grid math
        return (int(x // self.tile_size), int(y // self.tile_size))

    def assign_points_batch(self, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
        """Batch assign points to tiles using grid math."""
        return np.column_stack([
            (xs // self.tile_size).astype(int),
            (ys // self.tile_size).astype(int),
        ])

    def query_tile(self, tx: int, ty: int) -> tuple[float, float, float, float]:
        """Get tile bounds."""
        return self.tile_bounds.get((tx, ty), (0, 0, self.tile_size, self.tile_size))

    def get_adjacent_tiles(self, tx: int, ty: int) -> list[tuple[int, int]]:
        """Get 8-connected adjacent tiles."""
        return [
            (tx + dx, ty + dy)
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            if not (dx == 0 and dy == 0)
        ]


# Building footprint spatial index
@dataclass
class BuildingIndex:
    """Spatial index for building footprints."""
    polygons: list[np.ndarray]  # Each polygon: [N_vertices, 2]
    metadata: list[dict] = field(default_factory=list)
    centroids: np.ndarray = field(default_factory=lambda: np.empty((0, 2)))
    rtree: Optional[Any] = None

    def __post_init__(self):
        if len(self.polygons) > 0:
            self.centroids = np.array([np.mean(p, axis=0) for p in self.polygons])
            if HAS_RTREE:
                self._build_rtree()

    def _build_rtree(self):
        props = rtree_index.Property()
        self.rtree = rtree_index.Index(properties=props)
        for i, poly in enumerate(self.polygons):
            xs = poly[:, 0]
            ys = poly[:, 1]
            self.rtree.insert(i, (xs.min(), ys.min(), xs.max(), ys.max()))

    @classmethod
    def from_polygons(cls, polygons: list[np.ndarray], metadata: Optional[list] = None) -> "BuildingIndex":
        if metadata is None:
            metadata = [{} for _ in polygons]
        return cls(polygons=polygons, metadata=metadata)

    def query_bbox(self, bbox: tuple[float, float, float, float]) -> list[int]:
        """Return indices of polygons intersecting bbox."""
        if self.rtree is None:
            return list(range(len(self.polygons)))
        return list(self.rtree.intersection(bbox))

    def nearest_building(self, x: float, y: float) -> tuple[int, float]:
        """Find nearest building centroid."""
        if len(self.centroids) == 0:
            return -1, float('inf')
        idx = np.argmin(np.sum((self.centroids - [x, y])**2, axis=1))
        dist = np.sqrt(np.sum((self.centroids[idx] - [x, y])**2))
        return int(idx), float(dist)

    def point_in_building(self, x: float, y: float) -> Optional[int]:
        """Return building index containing point, or None."""
        # Quick bbox filter
        candidate_idxs = self.query_bbox((x - 10, y - 10, x + 10, y + 10))
        for idx in candidate_idxs:
            if self._point_in_polygon(x, y, self.polygons[idx]):
                return idx
        return None

    @staticmethod
    def _point_in_polygon(x: float, y: float, poly: np.ndarray) -> bool:
        """Ray casting point-in-polygon test."""
        n = len(poly)
        if n < 3:
            return False
        inside = False
        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n]
            if ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1) + x1):
                inside = not inside
        return inside

    def save(self, path: Path):
        data = {
            "polygons": [p.tolist() for p in self.polygons],
            "metadata": self.metadata,
        }
        path.write_text(json.dumps(data), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "BuildingIndex":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            polygons=[np.array(p) for p in data["polygons"]],
            metadata=data.get("metadata", []),
        )