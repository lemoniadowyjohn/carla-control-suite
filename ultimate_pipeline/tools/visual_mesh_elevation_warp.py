#!/usr/bin/env python3
"""Apply a DEM vertical datum to OSM2World OBJ environment meshes.

OSM2World OBJ coordinates are local: x=east, y=up, z=south.  The existing
visual-layer config disables terrain, so ground vertices are emitted at y=0
while the OpenDRIVE roads use real DEM heights.  This tool preserves the local
object height already encoded in y and adds the sampled DEM elevation at each
vertex's geographic location.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

from ultimate_pipeline.enrichment.coordinate_control import (
    VERIFIED_XODR_FRAME,
    VERIFIED_XODR_GEOMETRY_CRS_PROJ4,
    parse_obj_origin,
)


DemSampler = Callable[[float, float], Optional[float]]


@dataclass(frozen=True)
class ObjOrigin:
    lat: float
    lon: float
    ele: float


@dataclass
class WarpStats:
    vertices_total: int = 0
    vertices_warped: int = 0
    dem_missing: int = 0
    y_before_min: Optional[float] = None
    y_before_max: Optional[float] = None
    y_after_min: Optional[float] = None
    y_after_max: Optional[float] = None
    y_warped_after_min: Optional[float] = None
    y_warped_after_max: Optional[float] = None
    dem_height_min: Optional[float] = None
    dem_height_max: Optional[float] = None
    x_min: Optional[float] = None
    x_max: Optional[float] = None
    z_min: Optional[float] = None
    z_max: Optional[float] = None

    @property
    def missing_ratio(self) -> float:
        if self.vertices_total <= 0:
            return 1.0
        return float(self.dem_missing) / float(self.vertices_total)

    @property
    def y_before_range(self) -> float:
        if self.y_before_min is None or self.y_before_max is None:
            return 0.0
        return float(self.y_before_max) - float(self.y_before_min)

    @property
    def y_after_range(self) -> float:
        if self.y_after_min is None or self.y_after_max is None:
            return 0.0
        return float(self.y_after_max) - float(self.y_after_min)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["missing_ratio"] = self.missing_ratio
        data["y_before_range"] = self.y_before_range
        data["y_after_range"] = self.y_after_range
        return data

    def record_vertex(self, x: float, y_before: float, z: float, y_after: float) -> None:
        self.vertices_total += 1
        self.y_before_min = _min_optional(self.y_before_min, y_before)
        self.y_before_max = _max_optional(self.y_before_max, y_before)
        self.y_after_min = _min_optional(self.y_after_min, y_after)
        self.y_after_max = _max_optional(self.y_after_max, y_after)
        self.x_min = _min_optional(self.x_min, x)
        self.x_max = _max_optional(self.x_max, x)
        self.z_min = _min_optional(self.z_min, z)
        self.z_max = _max_optional(self.z_max, z)

    def record_warped_height(self, dem_height: float, y_after: float) -> None:
        self.dem_height_min = _min_optional(self.dem_height_min, dem_height)
        self.dem_height_max = _max_optional(self.dem_height_max, dem_height)
        self.y_warped_after_min = _min_optional(self.y_warped_after_min, y_after)
        self.y_warped_after_max = _max_optional(self.y_warped_after_max, y_after)


def _min_optional(current: Optional[float], value: float) -> float:
    return value if current is None else min(current, value)


def _max_optional(current: Optional[float], value: float) -> float:
    return value if current is None else max(current, value)


def _meters_per_degree_lat(lat_deg: float) -> float:
    lat = math.radians(lat_deg)
    return (
        111132.92
        - 559.82 * math.cos(2.0 * lat)
        + 1.175 * math.cos(4.0 * lat)
        - 0.0023 * math.cos(6.0 * lat)
    )


def _meters_per_degree_lon(lat_deg: float) -> float:
    lat = math.radians(lat_deg)
    return (
        111412.84 * math.cos(lat)
        - 93.5 * math.cos(3.0 * lat)
        + 0.118 * math.cos(5.0 * lat)
    )


def local_obj_to_lonlat(
    origin: ObjOrigin,
    *,
    x_east_m: float,
    z_south_m: float,
) -> Tuple[float, float]:
    """Map OSM2World local x/z meters back to lon/lat.

    OBJ x is positive east. OBJ z is positive south, so northward movement is
    negative z.  The approximation is bounded to city-scale DEM sampling and
    avoids trusting the disputed OpenDRIVE geoReference for this visual mesh.
    """
    lat = float(origin.lat) - float(z_south_m) / _meters_per_degree_lat(origin.lat)
    lon = float(origin.lon) + float(x_east_m) / _meters_per_degree_lon(origin.lat)
    return lon, lat


def _parse_vertex(line: str) -> Optional[Tuple[float, float, float]]:
    stripped = line.strip()
    if not stripped:
        return None
    parts = stripped.split()
    if len(parts) < 4 or parts[0] != "v":
        return None
    try:
        return float(parts[1]), float(parts[2]), float(parts[3])
    except ValueError:
        return None


def _warp_vertex_line(
    line: str,
    *,
    origin: ObjOrigin,
    sample_dem: DemSampler,
    stats: WarpStats,
) -> str:
    vertex = _parse_vertex(line)
    if vertex is None:
        return line
    x, y, z = vertex
    lon, lat = local_obj_to_lonlat(origin, x_east_m=x, z_south_m=z)
    dem_height = sample_dem(lon, lat)
    if dem_height is None or not math.isfinite(float(dem_height)):
        stats.dem_missing += 1
        stats.record_vertex(x, y, z, y)
        return line

    y_after = float(y) + float(dem_height) - float(origin.ele)
    stats.vertices_warped += 1
    stats.record_vertex(x, y, z, y_after)
    stats.record_warped_height(float(dem_height), y_after)
    return f"v {x:.6f} {y_after:.6f} {z:.6f}\n"


def warp_obj_lines(
    lines: Iterable[str],
    *,
    origin: ObjOrigin,
    sample_dem: DemSampler,
) -> Tuple[List[str], WarpStats]:
    stats = WarpStats()
    warped = [
        _warp_vertex_line(line, origin=origin, sample_dem=sample_dem, stats=stats)
        for line in lines
    ]
    return warped, stats


def warp_obj_file(
    input_obj: Path,
    output_obj: Path,
    *,
    origin: ObjOrigin,
    sample_dem: DemSampler,
) -> WarpStats:
    stats = WarpStats()
    output_obj.parent.mkdir(parents=True, exist_ok=True)
    with input_obj.open("r", encoding="utf-8", errors="replace") as src:
        with output_obj.open("w", encoding="utf-8", newline="\n") as dst:
            for line in src:
                dst.write(
                    _warp_vertex_line(
                        line,
                        origin=origin,
                        sample_dem=sample_dem,
                        stats=stats,
                    )
                )
    return stats


class RasterDemSampler:
    """Small in-memory sampler for a WGS84 or projected GeoTIFF DEM."""

    def __init__(self, dem_path: Path):
        try:
            import rasterio
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("rasterio is required for DEM-backed OBJ warping") from exc

        self.dem_path = Path(dem_path)
        self.dataset = rasterio.open(str(dem_path))
        self.band = self.dataset.read(1)
        self.nodata = self.dataset.nodata
        self.crs = self.dataset.crs
        self._transformer = None
        if self.crs is not None:
            try:
                is_geographic = bool(getattr(self.crs, "is_geographic", False))
            except Exception:
                is_geographic = "GEOGCS" in str(self.crs).upper()
            if not is_geographic:
                try:
                    from rasterio.warp import transform

                    def _to_dem(lon: float, lat: float) -> Tuple[float, float]:
                        xs, ys = transform("EPSG:4326", self.crs, [lon], [lat])
                        return float(xs[0]), float(ys[0])

                    self._transformer = _to_dem
                except Exception as exc:  # pragma: no cover
                    raise RuntimeError(
                        f"DEM CRS {self.crs} is not geographic and cannot be transformed"
                    ) from exc

    def __call__(self, lon: float, lat: float) -> Optional[float]:
        sample_x, sample_y = float(lon), float(lat)
        if self._transformer is not None:
            sample_x, sample_y = self._transformer(sample_x, sample_y)
        try:
            row, col = self.dataset.index(sample_x, sample_y)
        except Exception:
            return None
        if row < 0 or col < 0 or row >= self.band.shape[0] or col >= self.band.shape[1]:
            return None
        value = float(self.band[row, col])
        if self.nodata is not None and abs(value - float(self.nodata)) < 1e-6:
            return None
        if value <= -9998.0 or value >= 9998.0 or math.isnan(value):
            return None
        return value

    def metadata(self) -> dict:
        bounds = self.dataset.bounds
        return {
            "path": str(self.dem_path),
            "crs": str(self.crs),
            "bounds": {
                "left": float(bounds.left),
                "bottom": float(bounds.bottom),
                "right": float(bounds.right),
                "top": float(bounds.top),
            },
            "width": int(self.dataset.width),
            "height": int(self.dataset.height),
            "nodata": self.nodata,
            "dtype": str(self.band.dtype),
        }


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_float(value: Optional[str], default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _eval_road_elevation_at_s(road: ET.Element, s: float) -> float:
    elevs = sorted(
        road.findall("./elevationProfile/elevation"),
        key=lambda elem: _safe_float(elem.get("s"), 0.0),
    )
    if not elevs:
        return 0.0
    active = elevs[0]
    for elem in elevs:
        if _safe_float(elem.get("s"), 0.0) <= float(s):
            active = elem
        else:
            break
    ds = max(0.0, float(s) - _safe_float(active.get("s"), 0.0))
    a = _safe_float(active.get("a"), 0.0)
    b = _safe_float(active.get("b"), 0.0)
    c = _safe_float(active.get("c"), 0.0)
    d = _safe_float(active.get("d"), 0.0)
    return float(a + b * ds + c * ds * ds + d * ds * ds * ds)


def summarize_abs_residuals(residuals: Sequence[float]) -> dict:
    values = sorted(abs(float(value)) for value in residuals)
    if not values:
        return {
            "count": 0,
            "min_abs_m": None,
            "mean_abs_m": None,
            "median_abs_m": None,
            "p95_abs_m": None,
            "max_abs_m": None,
        }
    p95_index = int(0.95 * (len(values) - 1))
    return {
        "count": int(len(values)),
        "min_abs_m": float(values[0]),
        "mean_abs_m": float(sum(values) / len(values)),
        "median_abs_m": float(statistics.median(values)),
        "p95_abs_m": float(values[p95_index]),
        "max_abs_m": float(values[-1]),
    }


def verify_xodr_dem_elevation_consistency(
    xodr_path: Path,
    *,
    sample_dem: DemSampler,
    sample_limit: int = 2000,
    p95_threshold_m: float = 10.0,
) -> dict:
    """Compare existing OpenDRIVE elevationProfile values to DEM samples.

    Samples planView geometry anchors only.  This is a vertical-datum verifier,
    not a geometric mutation step.
    """
    try:
        from pyproj import CRS, Transformer
    except Exception as exc:  # pragma: no cover
        return {
            "verdict": "FAIL_CLOSED",
            "reason": f"pyproj_unavailable:{exc}",
            "sample_limit": int(sample_limit),
        }

    root = ET.parse(str(xodr_path)).getroot()
    transformer = Transformer.from_crs(
        CRS.from_proj4(VERIFIED_XODR_GEOMETRY_CRS_PROJ4),
        "EPSG:4326",
        always_xy=True,
    )
    residuals: List[float] = []
    dem_missing = 0
    sampled_points = 0
    for road in root.findall("./road"):
        for geom in road.findall("./planView/geometry"):
            if sampled_points >= int(sample_limit):
                break
            x = _safe_float(geom.get("x"), 0.0)
            y = _safe_float(geom.get("y"), 0.0)
            s = _safe_float(geom.get("s"), 0.0)
            try:
                lon, lat = transformer.transform(x, y)
            except Exception:
                dem_missing += 1
                sampled_points += 1
                continue
            dem_height = sample_dem(float(lon), float(lat))
            sampled_points += 1
            if dem_height is None:
                dem_missing += 1
                continue
            xodr_height = _eval_road_elevation_at_s(road, s)
            residuals.append(float(xodr_height) - float(dem_height))
        if sampled_points >= int(sample_limit):
            break

    summary = summarize_abs_residuals(residuals)
    missing_ratio = 1.0 if sampled_points <= 0 else float(dem_missing) / float(sampled_points)
    p95 = summary.get("p95_abs_m")
    ok = bool(
        sampled_points > 0
        and summary["count"] > 0
        and missing_ratio <= 0.02
        and p95 is not None
        and float(p95) <= float(p95_threshold_m)
    )
    return {
        "verdict": "PASS" if ok else "FAIL_CLOSED",
        "xodr_path": str(xodr_path),
        "xodr_geometry_frame": VERIFIED_XODR_FRAME,
        "xodr_geometry_crs_proj4": VERIFIED_XODR_GEOMETRY_CRS_PROJ4,
        "sample_limit": int(sample_limit),
        "sampled_points": int(sampled_points),
        "dem_missing": int(dem_missing),
        "missing_ratio": float(missing_ratio),
        "p95_threshold_m": float(p95_threshold_m),
        "residual_summary": summary,
        "note": "Samples planView geometry anchors; verifies vertical source consistency only.",
    }


def _origin_from_obj(input_obj: Path) -> ObjOrigin:
    raw = parse_obj_origin(input_obj)
    if raw is None:
        raise RuntimeError(f"OBJ header lacks OSM2World coordinate origin: {input_obj}")
    return ObjOrigin(lat=float(raw["lat"]), lon=float(raw["lon"]), ele=float(raw["ele"]))


def build_report(
    *,
    input_obj: Path,
    output_obj: Path,
    dem_path: Path,
    origin: ObjOrigin,
    sampler: RasterDemSampler,
    stats: WarpStats,
    max_missing_ratio: float,
    road_dem_check: Optional[dict] = None,
) -> dict:
    ok = stats.vertices_total > 0 and stats.vertices_warped > 0
    ok = bool(ok and stats.missing_ratio <= float(max_missing_ratio))
    if road_dem_check is not None:
        ok = bool(ok and road_dem_check.get("verdict") == "PASS")
    report = {
        "schema": "D1_VISUAL_MESH_ELEVATION_WARP/v1",
        "verdict": "PASS" if ok else "FAIL_CLOSED",
        "input_obj": str(input_obj),
        "output_obj": str(output_obj),
        "dem_tif": str(dem_path),
        "input_obj_sha256": sha256_file(input_obj),
        "output_obj_sha256": sha256_file(output_obj) if output_obj.exists() else "",
        "dem_sha256": sha256_file(dem_path),
        "origin": asdict(origin),
        "osm2world_frame": "x=east, y=up, z=south; 1 unit ~= 1 m",
        "warp_rule": "new_vertex_y = original_vertex_y + sampled_dem_elevation - obj_origin_elevation",
        "road_authority": "CARLA_GENERATED_ROAD; OSM2World roads remain excluded",
        "dem": sampler.metadata(),
        "stats": stats.to_dict(),
        "max_missing_ratio": float(max_missing_ratio),
    }
    if road_dem_check is not None:
        report["road_dem_elevation_check"] = road_dem_check
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-obj", required=True, type=Path)
    parser.add_argument("--output-obj", required=True, type=Path)
    parser.add_argument("--dem", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--max-missing-ratio", type=float, default=0.02)
    parser.add_argument("--xodr", type=Path)
    parser.add_argument("--xodr-sample-limit", type=int, default=2000)
    parser.add_argument("--road-dem-p95-threshold-m", type=float, default=10.0)
    args = parser.parse_args(argv)

    origin = _origin_from_obj(args.input_obj)
    sampler = RasterDemSampler(args.dem)
    stats = warp_obj_file(
        args.input_obj,
        args.output_obj,
        origin=origin,
        sample_dem=sampler,
    )
    report = build_report(
        input_obj=args.input_obj,
        output_obj=args.output_obj,
        dem_path=args.dem,
        origin=origin,
        sampler=sampler,
        stats=stats,
        max_missing_ratio=args.max_missing_ratio,
        road_dem_check=(
            verify_xodr_dem_elevation_consistency(
                args.xodr,
                sample_dem=sampler,
                sample_limit=args.xodr_sample_limit,
                p95_threshold_m=args.road_dem_p95_threshold_m,
            )
            if args.xodr
            else None
        ),
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"verdict": report["verdict"], "stats": report["stats"]}, indent=2))
    return 0 if report["verdict"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
