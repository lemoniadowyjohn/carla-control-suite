from __future__ import annotations

import json
import math
import os
import re
import xml.etree.ElementTree as ET
from typing import Optional, Tuple, Any, Literal

EXPLICIT_AUTHORITATIVE_GRID = "EXPLICIT_AUTHORITATIVE"
INFERRED_DIAGNOSTIC_GRID = "INFERRED_DIAGNOSTIC"


class TileGridSpecV2:
    """Explicit authoritative grid specification.

    Production consumers must require EXPLICIT_AUTHORITATIVE instances.
    INFERRED_DIAGNOSTIC instances are diagnostic only and production_eligible=False.
    """

    __slots__ = (
        "schema_version",
        "origin_x",
        "origin_y",
        "tile_size_m",
        "buffer_m",
        "coordinate_frame",
        "structure_xodr_sha",
        "grid_producer",
        "tile_index_convention",
        "source_manifest_sha",
        "authority",
        "production_eligible",
    )

    def __init__(
        self,
        schema_version: str = "v2",
        origin_x: float = 0.0,
        origin_y: float = 0.0,
        tile_size_m: float = 0.0,
        buffer_m: Optional[float] = None,
        coordinate_frame: str = "CARLA_RHS",
        structure_xodr_sha: Optional[str] = None,
        grid_producer: Optional[str] = None,
        tile_index_convention: str = "standard",  # "standard" or "negative"
        source_manifest_sha: Optional[str] = None,
        authority: Literal[EXPLICIT_AUTHORITATIVE_GRID, INFERRED_DIAGNOSTIC_GRID] =
            INFERRED_DIAGNOSTIC_GRID,
        production_eligible: bool = False,
    ) -> None:
        # Validate origin_x
        if not math.isfinite(origin_x):
            raise ValueError("origin_x must be finite")
        # Validate origin_y
        if not math.isfinite(origin_y):
            raise ValueError("origin_y must be finite")
        # Validate tile_size_m
        if not math.isfinite(tile_size_m):
            raise ValueError("tile_size_m must be finite")
        if tile_size_m is not None and tile_size_m <= 0:
            raise ValueError("tile_size_m must be > 0")
        if tile_size_m is not None and tile_size_m > 2000:
            raise ValueError("tile_size_m must be <= 2000 for CARLA production")
        # Validate buffer_m
        if buffer_m is not None and not math.isfinite(buffer_m):
            raise ValueError("buffer_m must be finite if specified")

        # Assign attributes
        self.schema_version = schema_version
        self.origin_x = origin_x
        self.origin_y = origin_y
        self.tile_size_m = tile_size_m
        self.buffer_m = buffer_m
        self.coordinate_frame = coordinate_frame
        self.structure_xodr_sha = structure_xodr_sha
        self.grid_producer = grid_producer
        self.tile_index_convention = tile_index_convention
        self.source_manifest_sha = source_manifest_sha
        self.authority = authority
        self.production_eligible = production_eligible

    def __repr__(self) -> str:
        return (
            f"TileGridSpecV2(origin_x={self.origin_x}, origin_y={self.origin_y}, "
            f"tile_size_m={self.tile_size_m}, buffer_m={self.buffer_m}, "
            f"authority={self.authority}, production_eligible={self.production_eligible})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TileGridSpecV2):
            return NotImplemented
        return (
            self.origin_x == other.origin_x
            and self.origin_y == other.origin_y
            and self.tile_size_m == other.tile_size_m
            and self.buffer_m == other.buffer_m
            and self.authority == other.authority
            and self.production_eligible == other.production_eligible
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.origin_x,
                self.origin_y,
                self.tile_size_m,
                self.buffer_m,
                self.authority,
                self.production_eligible,
            )
        )


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _read_json_strict(path: str) -> Optional[dict]:
    """Read JSON file strictly - returns None if file missing or unparseable."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _tile_id_ij(name: str) -> Optional[Tuple[int, int]]:
    """Parse tile index from filename.

    Supports both standard (tile_0_0) and negative indices (tile_-1_0, tile_0_-3).
    Malformed names return None.
    """
    m = re.match(r"tile_([_-]?\d+)_([_-]?\d+)\.xodr$", os.path.basename(name))
    if not m:
        return None
    try:
        i = int(m.group(1))
        j = int(m.group(2))
        return i, j
    except ValueError:
        return None


def _bounds_from_xodr(path: str) -> Optional[Tuple[float, float, float, float]]:
    """Extract planar bounding box from XODR planView geometry.

    Returns (minx, miny, maxx, maxy) or None if no geometry found.
    Handles both namespaced and non-namespaced XODR files.
    """
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception:
        return None

    # Collect all geometry elements by iterating, handling namespace if present
    geometries = []
    for elem in root.iter():
        # Check if this element is a geometry element
        tag = elem.tag
        # Handle namespaced tags: {http://...}geometry or just geometry
        local_tag = tag.split("}")[-1] if "}" in tag else tag
        if local_tag == "geometry":
            geometries.append(elem)

    xs, ys = [], []
    for g in geometries:
        # Get x and y attributes
        x_attr = g.get("x")
        y_attr = g.get("y")
        if x_attr is None or y_attr is None:
            continue
        try:
            x = float(x_attr)
            y = float(y_attr)
        except (ValueError, TypeError):
            continue
        if not math.isfinite(x) or not math.isfinite(y):
            continue
        xs.append(x)
        ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def load_grid_spec_from_meta_or_tiles(
    tiles_dir: str,
    *,
    mode: Literal["explicit", "diagnostic"] = "explicit",
) -> Optional[TileGridSpecV2]:
    """Load grid spec with explicit authority separation.

    In 'explicit' mode: requires tile_metadata.json or tile_manifest.json with
    authoritative values. No inference from tile geometry.

    In 'diagnostic' mode: may infer from tile geometry as fallback, but returns
    authority=INFERRED_DIAGNOSTIC and production_eligible=false.

    Key design decisions:
    - No recursive search for generic keys (e.g. 'buffer' in nested dicts cannot
      override grid authority).
    - Unknown buffer is represented as None, never silently defaulted to 50m.
    - Tile name parser supports negative indices.
    - Multi-tile consistency check before diagnostic inference.
    """

    # ---- Step 1: Load explicit metadata if available ----
    meta_candidates = [
        os.path.join(tiles_dir, "tile_metadata.json"),
        os.path.join(os.path.dirname(tiles_dir), "tile_metadata.json"),
    ]
    manifest_candidates = [
        os.path.join(tiles_dir, "tile_manifest.json"),
        os.path.join(os.path.dirname(tiles_dir), "tile_manifest.json"),
    ]

    meta = None
    for p in meta_candidates:
        if os.path.isfile(p):
            meta = _read_json_strict(p)
            if isinstance(meta, dict):
                break

    manifest = None
    for p in manifest_candidates:
        if os.path.isfile(p):
            manifest = _read_json_strict(p)
            if isinstance(manifest, dict):
                break

    # ---- Step 2: Parse only documented schema locations (no recursive key search) ----
    origin_x: Optional[float] = None
    origin_y: Optional[float] = None
    tile_size_m: Optional[float] = None
    buffer_m: Optional[float] = None

    if isinstance(meta, dict):
        # Explicit documented keys only - no recursive search for generic keys
        for k in ("origin_x", "origin_y", "tile_size_m", "buffer_m"):
            if k in meta:
                v = meta[k]
                try:
                    if k == "origin_x":
                        origin_x = float(v)
                    elif k == "origin_y":
                        origin_y = float(v)
                    elif k == "tile_size_m":
                        tile_size_m = float(v)
                    elif k == "buffer_m":
                        buffer_m = float(v)
                except (ValueError, TypeError):
                    pass

    if isinstance(manifest, dict):
        for k in ("origin_x", "origin_y", "tile_size_m", "buffer_m"):
            if k in manifest:
                v = manifest[k]
                try:
                    if k == "origin_x":
                        origin_x = float(v)
                    elif k == "origin_y":
                        origin_y = float(v)
                    elif k == "tile_size_m":
                        tile_size_m = float(v)
                    elif k == "buffer_m":
                        buffer_m = float(v)
                except (ValueError, TypeError):
                    pass

    # ---- Step 3: Mode handling ----
    if mode == "explicit":
        # Explicit mode: require all mandatory values from metadata
        if origin_x is None or origin_y is None or tile_size_m is None:
            return None
        if not math.isfinite(origin_x) or not math.isfinite(origin_y):
            return None
        if not math.isfinite(tile_size_m) or tile_size_m <= 0 or tile_size_m > 2000:
            return None
        # Buffer may be None (unknown) or explicit value; never silently defaulted
        return TileGridSpecV2(
            origin_x=origin_x,
            origin_y=origin_y,
            tile_size_m=tile_size_m,
            buffer_m=buffer_m,
            authority=EXPLICIT_AUTHORITATIVE_GRID,
            production_eligible=True,
        )

    # ---- Step 4: Diagnostic mode fallback ----
    if mode == "diagnostic":
        # If we have explicit authoritative values, return them as authoritative
        if origin_x is not None and origin_y is not None and tile_size_m is not None:
            if not math.isfinite(origin_x) or not math.isfinite(origin_y):
                return None
            if not math.isfinite(tile_size_m) or tile_size_m <= 0 or tile_size_m > 2000:
                return None
            return TileGridSpecV2(
                origin_x=origin_x,
                origin_y=origin_y,
                tile_size_m=tile_size_m,
                buffer_m=buffer_m,
                authority=EXPLICIT_AUTHORITATIVE_GRID,
                production_eligible=True,
            )

        # Fallback: infer from tile geometry (diagnostic only, not production eligible)
        tiles = [
            f
            for f in os.listdir(tiles_dir)
            if f.lower().endswith(".xodr") and f.startswith("tile_")
        ]

        if not tiles:
            return None

        # Use multiple tiles for consistency check
        tiles_sorted = sorted(tiles, key=lambda n: (_tile_id_ij(n) or (9999, 9999)))

        candidate_sizes: set[float] = set()
        candidate_origin_x: set[float] = set()
        candidate_origin_y: set[float] = set()
        tiles_examined = 0

        for t in tiles_sorted[:30]:
            ij = _tile_id_ij(t)
            if ij is None:
                continue
            i, j = ij
            tpath = os.path.join(tiles_dir, t)
            b = _bounds_from_xodr(tpath)
            if b is None:
                continue

            minx, miny, maxx, maxy = b
            w = maxx - minx
            h = maxy - miny

            if w <= 0 or h <= 0 or not math.isfinite(w) or not math.isfinite(h):
                continue

            # Infer tile size from this tile's bbox ONLY if buffer is known and finite
            inferred_size_val = None
            if tile_size_m is None and buffer_m is not None and math.isfinite(buffer_m):
                size = ((w + h) / 2.0) - 2.0 * buffer_m
                if math.isfinite(size) and size > 0:
                    inferred_size_val = float(round(size / 10.0) * 10.0)
                    candidate_sizes.add(inferred_size_val)
                    print(f'    -> inferred size: {inferred_size_val}')

            # Compute candidate origin using known or inferred tile_size_m
            effective_tile_size = tile_size_m if tile_size_m is not None and math.isfinite(tile_size_m) else inferred_size_val
            if effective_tile_size is not None and math.isfinite(effective_tile_size):
                candidate_origin_x.add(float(minx - i * effective_tile_size))
                candidate_origin_y.add(float(miny - j * effective_tile_size))
                print(f'    -> added origins: cx={minx - i * effective_tile_size}, cy={miny - j * effective_tile_size} (using tile_size_m={effective_tile_size})')

            tiles_examined += 1

        # Check for consistency: need at least 2 tiles with same inferred size
        # to establish grid authority, but allow single-tile inference as diagnostic
        if len(candidate_sizes) >= 2:
            # Multiple tiles with same inferred size -> consistent grid
            pass
        elif len(candidate_sizes) == 1 and tiles_examined >= 1:
            # Single tile with inferred size -> diagnostic only, not production eligible
            # (cannot verify consistency without multiple tiles)
            candidate_sizes = {next(iter(candidate_sizes))}
            # Still add origin candidates from available tiles
            # (we already added them in the loop above)
        else:
            # Insufficient data for even diagnostic inference
            return None

        if len(candidate_sizes) == 1 and len(candidate_origin_x) >= 1 and len(candidate_origin_y) >= 1:
            # We have at least one consistent origin from available tiles
            inferred_size = next(iter(candidate_sizes))
            # Use the most common origin candidate
            from statistics import median
            origin_x_vals = list(candidate_origin_x)
            origin_y_vals = list(candidate_origin_y)
            rep_origin_x = median(origin_x_vals)
            rep_origin_y = median(origin_y_vals)

            if not math.isfinite(rep_origin_x) or not math.isfinite(rep_origin_y):
                return None
            if not math.isfinite(inferred_size) or inferred_size <= 0 or inferred_size > 2000:
                return None

            return TileGridSpecV2(
                origin_x=rep_origin_x,
                origin_y=rep_origin_y,
                tile_size_m=inferred_size,
                buffer_m=buffer_m,
                authority=INFERRED_DIAGNOSTIC_GRID,
                production_eligible=False,
            )

        # If we get here, insufficient data for even diagnostic inference
        return None

    return None