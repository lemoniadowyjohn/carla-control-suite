"""Source-bound WGS84 transforms for the pinned Ingolstadt maps.

The automatic map stores Osm2Odr-native transverse-Mercator local coordinates;
its OpenDRIVE header offset must be added before inverse projection.  The manual
Grid0828 map stores EPSG:32632 easting/northing directly.  This module keeps
those operations explicit and binds every result to the verified map and
registry digests.  It does not treat a rigid shape alignment as georeferencing.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from pyproj import CRS, Transformer

from ultimate_pipeline.carla_tools.map_registry import (
    PINNED_MAP_REGISTRY,
    STRUCTURED_FRAME,
    verify_pinned_map,
)


CONTRACT_VERSION = "ingolstadt-map-coordinate-frame/v1"
AUTO_FRAME_KEY = "auto_map_of_record"
MANUAL_FRAME_KEY = "manual_grid0828"
AUTO_TRANSFORM_ID = "osm2odr-native-tmerc0-header-offset-v1"
MANUAL_TRANSFORM_ID = "epsg32632-axis-order-xy-v1"
AUTO_NATIVE_PROJ4 = (
    "+proj=tmerc +lat_0=0 +lon_0=0 +k=1 +x_0=0 +y_0=0 "
    "+datum=WGS84 +units=m +no_defs"
)
MANUAL_EPSG = 32632
MANUAL_CRS_AUTHORITY = (
    "EPSG:32632 (+proj=tmerc +lon_0=9 +k=0.9996 +x_0=500000)"
)
INGOLSTADT_WGS84_BOUNDS = {
    "lat_min": 48.74935649548228,
    "lat_max": 48.77444431571603,
    "lon_min": 11.422268084715878,
    "lon_max": 11.47882091528412,
}


class MapCoordinateError(ValueError):
    """A map pin, frame declaration, or requested coordinate is not admissible."""


@dataclass(frozen=True)
class MapCoordinateFrame:
    registry_key: str
    frame_id: str
    frame_kind: str
    map_sha256: str
    registry_sha256: str
    transform_id: str
    source_sha256: str | None
    offset_x: float
    offset_y: float
    _forward: Transformer
    _inverse: Transformer

    def wgs84_to_map(
        self, lon: float, lat: float, *, source_id: str
    ) -> dict[str, Any]:
        """Project an in-scope WGS84 waypoint and return digest-bound coordinates."""
        lon, lat = _require_wgs84(lon, lat)
        if not isinstance(source_id, str) or not source_id.strip():
            raise MapCoordinateError("waypoint source_id must be nonempty text")
        x, y = self._forward.transform(lon, lat, errcheck=True)
        x -= self.offset_x
        y -= self.offset_y
        if not (math.isfinite(x) and math.isfinite(y)):
            raise MapCoordinateError("projection produced nonfinite map coordinates")
        return {
            "contract_version": CONTRACT_VERSION,
            "registry_key": self.registry_key,
            "map_sha256": self.map_sha256,
            "registry_sha256": self.registry_sha256,
            "frame_id": self.frame_id,
            "frame_kind": self.frame_kind,
            "transform_id": self.transform_id,
            "source_data_sha256": self.source_sha256,
            "waypoint_source_id": source_id.strip(),
            "source_crs": "EPSG:4326",
            "source_axis_order": "longitude,latitude",
            "target_axis_order": "x,y",
            "target_units": "metres",
            "wgs84": {"lon": lon, "lat": lat},
            "map_xy": {"x": x, "y": y},
        }

    def map_to_wgs84(self, x: float, y: float) -> tuple[float, float]:
        """Inverse project map-local metres; reject points outside the study crop."""
        x = _finite_number(x, "x") + self.offset_x
        y = _finite_number(y, "y") + self.offset_y
        lon, lat = self._inverse.transform(x, y, errcheck=True)
        return _require_wgs84(lon, lat)


def load_map_coordinate_frame(
    name: str,
    *,
    base_dir: str | Path | None = None,
    registry: Mapping[str, Mapping[str, Any]] | None = None,
) -> MapCoordinateFrame:
    """Verify a pinned XODR and its CRS header before constructing its transform.

    ``registry`` is an injection point for isolated unit fixtures. Production
    callers should omit it so the code-owned map registry is authoritative.
    """
    selected_registry = registry if registry is not None else PINNED_MAP_REGISTRY
    try:
        receipt = verify_pinned_map(
            name,
            base_dir=Path(base_dir) if base_dir is not None else None,
            registry={k: dict(v) for k, v in selected_registry.items()},
        )
    except Exception as exc:
        raise MapCoordinateError(f"pinned map verification failed: {exc}") from exc

    key = receipt["registry_key"]
    if key not in (AUTO_FRAME_KEY, MANUAL_FRAME_KEY):
        raise MapCoordinateError(f"map {key!r} has no governed Ingolstadt route frame")
    if receipt.get("verification_status") != "VERIFIED":
        raise MapCoordinateError("map content identity is not verified")
    if receipt.get("sha256_actual") != receipt.get("sha256_expected"):
        raise MapCoordinateError("map content digest does not match its registry pin")
    if receipt.get("frame_status") != STRUCTURED_FRAME:
        raise MapCoordinateError("map registry does not contain a structured frame")

    entry = selected_registry[key]
    transform_id = receipt.get("frame_transform_id")
    if key == AUTO_FRAME_KEY:
        expected_source = entry.get("frame_source_sha256")
        if (
            receipt.get("frame_kind") != "rebased_local"
            or receipt.get("crs_authority") != _auto_authority()
            or transform_id != AUTO_TRANSFORM_ID
            or not expected_source
            or expected_source != PINNED_MAP_REGISTRY[AUTO_FRAME_KEY].get("frame_source_sha256")
            or receipt.get("frame_source_sha256") != expected_source
        ):
            raise MapCoordinateError("automatic map CRS provenance is incomplete or inconsistent")
        target_crs = CRS.from_proj4(AUTO_NATIVE_PROJ4)
        offset_x = _finite_number(receipt.get("rebase_dx"), "rebase_dx")
        offset_y = _finite_number(receipt.get("rebase_dy"), "rebase_dy")
        source_sha = str(expected_source)
    else:
        if (
            receipt.get("frame_kind") != "projected_crs"
            or receipt.get("crs_authority") != MANUAL_CRS_AUTHORITY
            or transform_id != MANUAL_TRANSFORM_ID
        ):
            raise MapCoordinateError("manual map CRS provenance is incomplete or inconsistent")
        target_crs = CRS.from_epsg(MANUAL_EPSG)
        offset_x = offset_y = 0.0
        source_sha = None

    path = Path(receipt["resolved_path"])
    geo_reference, header_offset = _read_header(path)
    if key == AUTO_FRAME_KEY:
        if not geo_reference:
            raise MapCoordinateError("automatic XODR has no native geoReference")
        try:
            header_crs = CRS.from_user_input(geo_reference)
        except Exception as exc:
            raise MapCoordinateError("automatic XODR geoReference is invalid") from exc
        if not header_crs.equals(target_crs):
            raise MapCoordinateError("automatic XODR geoReference differs from its declared native CRS")
        if header_offset is None or not _same_offset(header_offset, (offset_x, offset_y)):
            raise MapCoordinateError("automatic XODR header offset differs from the pinned rebase")
    elif geo_reference:
        try:
            header_crs = CRS.from_user_input(geo_reference)
        except Exception as exc:
            raise MapCoordinateError("manual XODR geoReference is invalid") from exc
        if not header_crs.equals(target_crs):
            raise MapCoordinateError("manual XODR geoReference conflicts with EPSG:32632 registry")
    elif header_offset is not None and not _same_offset(header_offset, (0.0, 0.0)):
        raise MapCoordinateError("manual XODR has an undeclared coordinate offset")

    return MapCoordinateFrame(
        registry_key=key,
        frame_id=str(receipt["frame_id"]),
        frame_kind=str(receipt["frame_kind"]),
        map_sha256=str(receipt["sha256_actual"]),
        registry_sha256=str(receipt["registry_sha256"]),
        transform_id=str(transform_id),
        source_sha256=source_sha,
        offset_x=offset_x,
        offset_y=offset_y,
        _forward=Transformer.from_crs(CRS.from_epsg(4326), target_crs, always_xy=True),
        _inverse=Transformer.from_crs(target_crs, CRS.from_epsg(4326), always_xy=True),
    )


def _auto_authority() -> str:
    return f"OSM2ODR native tmerc: {AUTO_NATIVE_PROJ4}"


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise MapCoordinateError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise MapCoordinateError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise MapCoordinateError(f"{name} must be a finite number")
    return result


def _require_wgs84(lon: Any, lat: Any) -> tuple[float, float]:
    lon = _finite_number(lon, "longitude")
    lat = _finite_number(lat, "latitude")
    bounds = INGOLSTADT_WGS84_BOUNDS
    if not (bounds["lon_min"] <= lon <= bounds["lon_max"]):
        raise MapCoordinateError("longitude is outside the frozen Ingolstadt study bounds")
    if not (bounds["lat_min"] <= lat <= bounds["lat_max"]):
        raise MapCoordinateError("latitude is outside the frozen Ingolstadt study bounds")
    return lon, lat


def _read_header(path: Path) -> tuple[str | None, tuple[float, float] | None]:
    try:
        with path.open("rb") as stream:
            for _event, element in ET.iterparse(stream, events=("end",)):
                if element.tag != "header":
                    continue
                geo = element.find("geoReference")
                offset = element.find("offset")
                geo_text = (geo.text or "").strip() if geo is not None else ""
                header_offset = None
                if offset is not None:
                    header_offset = (
                        _finite_number(offset.get("x"), "header offset x"),
                        _finite_number(offset.get("y"), "header offset y"),
                    )
                return geo_text or None, header_offset
    except (OSError, ET.ParseError) as exc:
        raise MapCoordinateError(f"cannot read pinned XODR header: {exc}") from exc
    raise MapCoordinateError("pinned XODR has no header")


def _same_offset(actual: tuple[float, float], expected: tuple[float, float]) -> bool:
    return all(math.isclose(a, e, rel_tol=0.0, abs_tol=1e-9) for a, e in zip(actual, expected))
