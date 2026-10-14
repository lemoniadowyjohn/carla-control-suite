"""Canonical Coordinate Frame Contract for CARLA Large Map Pipeline.

Single source of truth for all CRS definitions, transformations, and frame metadata.
All pipeline stages must import from this module; duplicate bare-tmerc definitions
elsewhere are deprecated and must be removed.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Tuple, Optional, Union, List
import pyproj

__version__ = "1.0.0"
__contract_sha256__ = None  # populated at module load


# ============================================================================
# Frame definitions
# ============================================================================

# WGS84 geographic (EPSG:4326)
FRAME_WGS84 = "WGS84"
FRAME_WGS84_CRS = "EPSG:4326"

# Osm2Odr native: bare transverse mercator, no offsets, no scale
FRAME_NATIVE = "NATIVE"
FRAME_NATIVE_CRS = (
    "+proj=tmerc +lat_0=0 +lon_0=0 +k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
)

# CARLA/OpenDRIVE local: native minus pinned rebase
FRAME_LOCAL = "LOCAL"
FRAME_LOCAL_CRS = FRAME_NATIVE_CRS  # same projection, different origin

# EPSG:32632 UTM zone 32N -- distinct from NATIVE, requires reprojection
FRAME_EPSG_32632 = "EPSG_32632"
FRAME_EPSG_32632_CRS = (
    "+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 +datum=WGS84 +units=m +no_defs"
)

# Pinned map rebase offset (authoritative from map registry)
REBASE_DX = 832671.676
REBASE_DY = 5458671.104
REBASE_OFFSET = (REBASE_DX, REBASE_DY)

# Map-of-record SHA256 (auto_map_of_record)
MAP_OF_RECORD_SHA256 = "370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8"
MAP_OF_RECORD_BYTES = 149799632
MAP_OF_RECORD_ROLE = "auto_map_of_record"

# Frame ID strings for binding
FRAME_ID_WGS84 = "wgs84_geographic"
FRAME_ID_NATIVE = "osm2odr_native_tmerc"
FRAME_ID_LOCAL = "ingolstadt_local_rebased"
FRAME_ID_EPSG_32632 = "utm_32n"

# Axis order: all frames are (easting, northing) == (x, y) == (lon, lat) in projected
# WGS84: (lon, lat) per EPSG:4326 axis order
# Native/Local/EPSG32632: (x, y) = (easting, northing)
AXIS_ORDER = "xy"

# Units: all projected frames are metres
UNITS = "metres"


# ============================================================================
# Transformer cache
# ============================================================================

_TF_CACHE: Dict[Tuple[str, str], pyproj.Transformer] = {}


def _tf(src: str, dst: str) -> pyproj.Transformer:
    key = (src, dst)
    if key not in _TF_CACHE:
        _TF_CACHE[key] = pyproj.Transformer.from_crs(src, dst, always_xy=True)
    return _TF_CACHE[key]


def _tf_crs(src_crs: str, dst_crs: str) -> pyproj.Transformer:
    """Create transformer from CRS strings."""
    key = (f"crs:{src_crs}", f"crs:{dst_crs}")
    if key not in _TF_CACHE:
        _TF_CACHE[key] = pyproj.Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    return _TF_CACHE[key]


# ============================================================================
# Core transformation APIs (8 required)
# ============================================================================

def wgs84_to_native(lon: float, lat: float) -> Tuple[float, float]:
    """WGS84 geographic -> Osm2Odr native bare tmerc."""
    x, y = _tf(FRAME_WGS84_CRS, FRAME_NATIVE_CRS).transform(lon, lat)
    return (float(x), float(y))


def native_to_wgs84(x: float, y: float) -> Tuple[float, float]:
    """Osm2Odr native bare tmerc -> WGS84 geographic."""
    lon, lat = _tf(FRAME_NATIVE_CRS, FRAME_WGS84_CRS).transform(x, y)
    return (float(lon), float(lat))


def native_to_local(x: float, y: float) -> Tuple[float, float]:
    """Osm2Odr native -> CARLA local (minus pinned rebase)."""
    return (float(x - REBASE_DX), float(y - REBASE_DY))


def local_to_native(x: float, y: float) -> Tuple[float, float]:
    """CARLA local -> Osm2Odr native (plus pinned rebase)."""
    return (float(x + REBASE_DX), float(y + REBASE_DY))


def wgs84_to_local(lon: float, lat: float) -> Tuple[float, float]:
    """WGS84 geographic -> CARLA local (composite)."""
    x, y = wgs84_to_native(lon, lat)
    return native_to_local(x, y)


def local_to_wgs84(x: float, y: float) -> Tuple[float, float]:
    """CARLA local -> WGS84 geographic (composite)."""
    x_n, y_n = local_to_native(x, y)
    return native_to_wgs84(x_n, y_n)


def native_to_epsg32632(x: float, y: float) -> Tuple[float, float]:
    """Osm2Odr native -> EPSG:32632 (actual reprojection, NOT offset-only)."""
    x32, y32 = _tf_crs(FRAME_NATIVE_CRS, FRAME_EPSG_32632_CRS).transform(x, y)
    return (float(x32), float(y32))


def epsg32632_to_native(x: float, y: float) -> Tuple[float, float]:
    """EPSG:32632 -> Osm2Odr native (actual reprojection)."""
    xn, yn = _tf_crs(FRAME_EPSG_32632_CRS, FRAME_NATIVE_CRS).transform(x, y)
    return (float(xn), float(yn))


# ============================================================================
# Batch/vectorized APIs
# ============================================================================

def wgs84_to_native_vec(lons: List[float], lats: List[float]) -> Tuple[List[float], List[float]]:
    xs, ys = _tf(FRAME_WGS84_CRS, FRAME_NATIVE_CRS).transform(lons, lats)
    return (list(xs), list(ys))


def native_to_wgs84_vec(xs: List[float], ys: List[float]) -> Tuple[List[float], List[float]]:
    lons, lats = _tf(FRAME_NATIVE_CRS, FRAME_WGS84_CRS).transform(xs, ys)
    return (list(lons), list(lats))


def native_to_local_vec(xs: List[float], ys: List[float]) -> Tuple[List[float], List[float]]:
    return ([float(x - REBASE_DX) for x in xs], [float(y - REBASE_DY) for y in ys])


def local_to_native_vec(xs: List[float], ys: List[float]) -> Tuple[List[float], List[float]]:
    return ([float(x + REBASE_DX) for x in xs], [float(y + REBASE_DY) for y in ys])


# ============================================================================
# Contract metadata
# ============================================================================

@dataclass(frozen=True)
class FrameContract:
    """Immutable frame contract binding all frame semantics to a map version."""
    version: str = __version__
    map_sha256: str = MAP_OF_RECORD_SHA256
    map_bytes: int = MAP_OF_RECORD_BYTES
    map_role: str = MAP_OF_RECORD_ROLE
    rebase_offset: Tuple[float, float] = REBASE_OFFSET
    frames: Dict[str, Dict[str, Any]] = field(default_factory=lambda: {
        FRAME_WGS84: {
            "frame_id": FRAME_ID_WGS84,
            "crs": FRAME_WGS84_CRS,
            "axis_order": AXIS_ORDER,
            "units": "degrees"
        },
        FRAME_NATIVE: {
            "frame_id": FRAME_ID_NATIVE,
            "crs": FRAME_NATIVE_CRS,
            "axis_order": AXIS_ORDER,
            "units": UNITS
        },
        FRAME_LOCAL: {
            "frame_id": FRAME_ID_LOCAL,
            "crs": FRAME_LOCAL_CRS,
            "axis_order": AXIS_ORDER,
            "units": UNITS,
            "rebase_offset": REBASE_OFFSET
        },
        FRAME_EPSG_32632: {
            "frame_id": FRAME_ID_EPSG_32632,
            "crs": FRAME_EPSG_32632_CRS,
            "axis_order": AXIS_ORDER,
            "units": UNITS
        }
    })

    def to_json(self) -> str:
        return json.dumps({
            "version": self.version,
            "map_sha256": self.map_sha256,
            "map_bytes": self.map_bytes,
            "map_role": self.map_role,
            "rebase_offset": {"dx": self.rebase_offset[0], "dy": self.rebase_offset[1]},
            "frames": self.frames
        }, indent=2)

    @classmethod
    def from_json(cls, s: str) -> "FrameContract":
        data = json.loads(s)
        return cls(
            version=data["version"],
            map_sha256=data["map_sha256"],
            map_bytes=data["map_bytes"],
            map_role=data["map_role"],
            rebase_offset=(data["rebase_offset"]["dx"], data["rebase_offset"]["dy"]),
            frames=data["frames"]
        )


def get_contract() -> FrameContract:
    """Return the canonical frame contract for the current map of record."""
    return FrameContract()


def verify_contract(contract: FrameContract) -> bool:
    """Verify a contract matches the canonical expectations."""
    return (
        contract.version == __version__ and
        contract.map_sha256 == MAP_OF_RECORD_SHA256 and
        contract.map_bytes == MAP_OF_RECORD_BYTES and
        contract.map_role == MAP_OF_RECORD_ROLE and
        contract.rebase_offset == REBASE_OFFSET
    )


# ============================================================================
# Deprecated string (for compatibility)
# ============================================================================

DEPRECATED_CRS_AUTHORITY_STRING = (
    "local Cartesian via fixed offset from UTM-32N (EPSG:32632)"
)
"""Deprecated: the old registry crs_authority text. Do not use for new code."""


# ============================================================================
# Module self-verification
# ============================================================================

if __name__ == "__main__":
    # Round-trip test
    lon, lat = 11.5, 48.75
    x_n, y_n = wgs84_to_native(lon, lat)
    x_l, y_l = native_to_local(x_n, y_n)
    x_n2, y_n2 = local_to_native(x_l, y_l)
    lon2, lat2 = native_to_wgs84(x_n2, y_n2)
    print(f"WGS84: ({lon}, {lat})")
    print(f"NATIVE: ({x_n:.6f}, {y_n:.6f})")
    print(f"LOCAL: ({x_l:.6f}, {y_l:.6f})")
    print(f"Round-trip WGS84: ({lon2:.10f}, {lat2:.10f})")
    print(f"Error: {abs(lon-lon2):.2e}, {abs(lat-lat2):.2e}")

    # EPSG:32632 round-trip
    x32, y32 = native_to_epsg32632(x_n, y_n)
    xn2, yn2 = epsg32632_to_native(x32, y32)
    print(f"NATIVE->EPSG32632: ({x32:.6f}, {y32:.6f})")
    print(f"Round-trip NATIVE: ({xn2:.10f}, {yn2:.10f})")
    print(f"Error: {abs(x_n-xn2):.2e}, {abs(y_n-yn2):.2e}")

    # Contract
    c = get_contract()
    print(c.to_json())
    print("verify:", verify_contract(c))