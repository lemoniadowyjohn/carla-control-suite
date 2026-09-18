#!/usr/bin/env python3

from __future__ import annotations

import json
import math
import os
import sys
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

from pyproj import CRS, Transformer

# Make project root importable when running this file directly.
ROOT = os.path.abspath(os.path.join(__file__, "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.geometry.geometry_math import sample_parampoly3_points
from ultimate_pipeline.enrichment.elevation_importer import (
    HEADER_OFFSET_GPS_ANCHOR_THRESHOLD_M,
    _apply_header_offset,
    _bbox_center,
    _compute_xodr_planview_bbox,
    _default_header_offset,
    _infer_map_crs,
    _offset_from_gps_anchor,
    _read_header_offset,
)


RETRY_INTERSECTION_RATIO_THRESHOLD = 0.10


def _bbox_area(bbox: Optional[Dict[str, float]]) -> float:
    if not isinstance(bbox, dict):
        return 0.0
    try:
        dx = max(0.0, float(bbox["maxx"]) - float(bbox["minx"]))
        dy = max(0.0, float(bbox["maxy"]) - float(bbox["miny"]))
        return float(dx * dy)
    except Exception:
        return 0.0


def _bbox_intersection(
    a: Optional[Dict[str, float]], b: Optional[Dict[str, float]]
) -> Optional[Dict[str, float]]:
    if not isinstance(a, dict) or not isinstance(b, dict):
        return None
    try:
        minx = max(float(a["minx"]), float(b["minx"]))
        miny = max(float(a["miny"]), float(b["miny"]))
        maxx = min(float(a["maxx"]), float(b["maxx"]))
        maxy = min(float(a["maxy"]), float(b["maxy"]))
        if maxx <= minx or maxy <= miny:
            return None
        return {
            "minx": float(minx),
            "miny": float(miny),
            "maxx": float(maxx),
            "maxy": float(maxy),
        }
    except Exception:
        return None


def _project_wgs84_to_map_crs(
    lon_center: float, lat_center: float, map_crs: Any
) -> Optional[Tuple[float, float]]:
    if map_crs is None:
        return None
    try:
        tf = Transformer.from_crs(
            CRS.from_user_input("EPSG:4326"),
            map_crs,
            always_xy=True,
        )
        x_proj, y_proj = tf.transform(float(lon_center), float(lat_center))
        return float(x_proj), float(y_proj)
    except Exception:
        return None


class XODRCropperGPS:
    """
    Crop an OpenDRIVE file around a GPS lat/lon center.

    Crop geometry is evaluated in the map CRS frame and with the same effective
    header offset policy used by the DEM importer diagnostics.
    """

    def __init__(self) -> None:
        self._legacy_transformer: Optional[Transformer] = None

    def _legacy_project_from_settings(
        self, lon_center: float, lat_center: float
    ) -> Tuple[float, float]:
        """
        Backward-compatible fallback projection when map CRS cannot be inferred.
        """
        if self._legacy_transformer is None:
            gps = SETTINGS.load_gps_bounds()
            lat0 = gps.get("lat_min", 48.75)
            lon0 = gps.get("lon_min", 11.42)
            proj_string = (
                f"+proj=tmerc +lat_0={lat0} +lon_0={lon0} "
                "+k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
            )
            self._legacy_transformer = Transformer.from_crs(
                "EPSG:4326",
                proj_string,
                always_xy=True,
            )
        cx, cy = self._legacy_transformer.transform(
            float(lon_center), float(lat_center)
        )
        return float(cx), float(cy)

    def _resolve_effective_offset(
        self,
        xodr_path: str,
        map_crs: Any,
        lat_center: float,
        lon_center: float,
    ) -> Dict[str, Any]:
        header_offset_original = _read_header_offset(xodr_path)
        header_offset_source = (
            "xodr_header_offset"
            if header_offset_original is not None
            else "missing_default_zero"
        )
        if header_offset_original is None:
            header_offset_original = _default_header_offset()

        header_offset = dict(header_offset_original)
        header_offset_policy = "xodr_header"
        header_offset_error_m: Optional[float] = None

        local_raw_bbox = _compute_xodr_planview_bbox(
            xodr_path,
            header_offset=_default_header_offset(),
        )
        local_center = _bbox_center(local_raw_bbox)
        gps_center_proj = _project_wgs84_to_map_crs(lon_center, lat_center, map_crs)

        if local_center is not None and gps_center_proj is not None:
            cx_header, cy_header = _apply_header_offset(
                float(local_center[0]),
                float(local_center[1]),
                header_offset_original,
            )
            header_offset_error_m = float(
                math.hypot(
                    float(cx_header) - float(gps_center_proj[0]),
                    float(cy_header) - float(gps_center_proj[1]),
                )
            )
            if header_offset_error_m > float(HEADER_OFFSET_GPS_ANCHOR_THRESHOLD_M):
                anchored = _offset_from_gps_anchor(
                    local_raw_bbox,
                    gps_center_proj,
                    header_offset_original,
                )
                if anchored is not None:
                    header_offset = dict(anchored)
                    header_offset_policy = "gps_anchor_override"

        # Thesis strict policy: Option A offset discipline forbids gps-anchor overrides.
        thesis_strict = (
            os.getenv("UP_THESIS_STRICT", "").strip().lower() in ("1", "true", "yes", "on")
            or bool(getattr(SETTINGS, "THESIS_STRICT", False))
        )
        suppressed = False
        if thesis_strict and header_offset_policy == "gps_anchor_override":
            header_offset = dict(header_offset_original)
            header_offset_policy = "xodr_header_strict_forced"
            suppressed = True

        return {
            "header_offset_source": str(header_offset_source),
            "header_offset_original": dict(header_offset_original),
            "effective_offset_used": dict(header_offset),
            "header_offset_policy": str(header_offset_policy),
            "header_offset_error_m": header_offset_error_m,
            "local_raw_bbox": local_raw_bbox,
            "gps_anchor_override_suppressed": bool(suppressed),
        }

    @staticmethod
    def _sample_geometry_points(
        geom: ET.Element,
        x_s: float,
        y_s: float,
        hdg: float,
        length: float,
        curvature: Optional[float],
    ) -> List[Tuple[float, float]]:
        if length <= 0.0:
            return [(float(x_s), float(y_s))]

        line_t = (0.0, 1.0)
        arc_t = (0.0, 0.5, 1.0)
        parampoly3_t = (0.0, 0.25, 0.5, 0.75, 1.0)
        curvature_v = float(curvature) if curvature is not None else 0.0

        if geom.find("paramPoly3") is not None:
            return sample_parampoly3_points(
                geom=geom,
                x0=float(x_s),
                y0=float(y_s),
                hdg=float(hdg),
                length=float(length),
                t_values=parampoly3_t,
            )

        if abs(curvature_v) <= 1e-12:
            cos_h = math.cos(hdg)
            sin_h = math.sin(hdg)
            return [
                (
                    float(x_s) + float(length) * float(t) * cos_h,
                    float(y_s) + float(length) * float(t) * sin_h,
                )
                for t in line_t
            ]

        # Constant-curvature arc in OpenDRIVE local frame.
        sin_h0 = math.sin(hdg)
        cos_h0 = math.cos(hdg)
        k = curvature_v
        points: List[Tuple[float, float]] = []
        for t in arc_t:
            s = float(length) * float(t)
            hs = float(hdg) + float(k) * float(s)
            x_p = float(x_s) + (math.sin(hs) - sin_h0) / float(k)
            y_p = float(y_s) + (-math.cos(hs) + cos_h0) / float(k)
            points.append((x_p, y_p))
        return points

    @staticmethod
    def _road_in_radius(
        road: ET.Element,
        cx: float,
        cy: float,
        radius_m: float,
        effective_offset: Dict[str, float],
    ) -> bool:
        planview = road.find("planView")
        if planview is None:
            return False

        r = float(radius_m)
        for geom in planview.findall("geometry"):
            x_raw = geom.get("x")
            y_raw = geom.get("y")
            if x_raw is None or y_raw is None:
                continue

            try:
                x_s, y_s = _apply_header_offset(
                    float(x_raw),
                    float(y_raw),
                    effective_offset,
                )
                length = float(geom.get("length") or 0.0)
                hdg = float(geom.get("hdg") or 0.0)
            except Exception:
                continue

            curvature: Optional[float] = None
            arc = geom.find("arc")
            if arc is not None:
                try:
                    curvature = float(arc.get("curvature") or 0.0)
                except Exception:
                    curvature = None

            # Sample along each geometry segment so curved roads that pass
            # through the crop radius are retained even if endpoints are outside.
            for x_p, y_p in XODRCropperGPS._sample_geometry_points(
                geom=geom,
                x_s=float(x_s),
                y_s=float(y_s),
                hdg=float(hdg),
                length=float(length),
                curvature=curvature,
            ):
                if math.hypot(float(x_p) - float(cx), float(y_p) - float(cy)) <= r:
                    return True

        return False

    def _collect_kept_roads(
        self,
        roads: List[ET.Element],
        cx: float,
        cy: float,
        radius_m: float,
        effective_offset: Dict[str, float],
    ) -> List[ET.Element]:
        keep: List[ET.Element] = []
        for road in roads:
            if self._road_in_radius(
                road=road,
                cx=float(cx),
                cy=float(cy),
                radius_m=float(radius_m),
                effective_offset=effective_offset,
            ):
                keep.append(road)
        return keep

    @staticmethod
    def _write_report(path: str, payload: Dict[str, Any]) -> None:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except Exception:
            pass
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    def crop_gps(
        self,
        input_xodr: str,
        output_xodr: str,
        lat_center: float,
        lon_center: float,
        r: float = 300.0,
    ) -> Dict[str, Any]:
        """
        Crop around GPS center within radius ``r`` (meters).

        Returns a QA report payload and writes it next to ``output_xodr``.
        """
        qa_path = os.path.splitext(output_xodr)[0] + ".qa.json"
        qa: Dict[str, Any] = {
            "ok": False,
            "input_xodr": str(input_xodr),
            "output_xodr": str(output_xodr),
            "qa_report_json": str(qa_path),
            "crop_center_wgs84": {
                "lat": float(lat_center),
                "lon": float(lon_center),
            },
            "crop_radius_m": float(r),
            "retry_attempted": False,
            "retry_radius_m": None,
            "retry_roads_kept": None,
            "roads_kept_initial": 0,
            "roads_kept": 0,
        }

        try:
            map_crs, map_crs_source, _map_crs_raw = _infer_map_crs(input_xodr, None)
            map_crs_proj4 = ""
            if map_crs is not None:
                try:
                    map_crs_proj4 = " ".join(str(map_crs.to_proj4()).split())
                except Exception:
                    map_crs_proj4 = str(map_crs)

            offset_info = self._resolve_effective_offset(
                xodr_path=input_xodr,
                map_crs=map_crs,
                lat_center=float(lat_center),
                lon_center=float(lon_center),
            )
            effective_offset_used = dict(
                offset_info.get("effective_offset_used") or _default_header_offset()
            )

            crop_center_map_crs = _project_wgs84_to_map_crs(
                float(lon_center), float(lat_center), map_crs
            )
            crop_center_source = "map_crs_inferred"
            if crop_center_map_crs is None:
                crop_center_map_crs = self._legacy_project_from_settings(
                    float(lon_center), float(lat_center)
                )
                crop_center_source = "settings_tmerc_fallback"
            cx, cy = crop_center_map_crs

            map_bbox = _compute_xodr_planview_bbox(
                input_xodr,
                header_offset=effective_offset_used,
            )
            crop_bbox = {
                "minx": float(cx - float(r)),
                "miny": float(cy - float(r)),
                "maxx": float(cx + float(r)),
                "maxy": float(cy + float(r)),
            }
            inter_bbox = _bbox_intersection(crop_bbox, map_bbox)
            inter_area = _bbox_area(inter_bbox)
            crop_area = _bbox_area(crop_bbox)
            intersection_ratio = (
                float(inter_area / crop_area) if crop_area > 0.0 else 0.0
            )

            qa.update(
                {
                    "map_crs_source": str(map_crs_source or ""),
                    "map_crs_proj4": str(map_crs_proj4 or ""),
                    "header_offset_policy": str(
                        offset_info.get("header_offset_policy") or ""
                    ),
                    "header_offset_source": str(
                        offset_info.get("header_offset_source") or ""
                    ),
                    "header_offset_original": offset_info.get("header_offset_original"),
                    "effective_offset_used": effective_offset_used,
                    "header_offset_error_m": offset_info.get("header_offset_error_m"),
                    "crop_center_map_crs": {
                        "x": float(cx),
                        "y": float(cy),
                    },
                    "crop_center_map_crs_source": crop_center_source,
                    "map_bbox_in_map_crs": map_bbox,
                    "crop_bbox_in_map_crs": crop_bbox,
                    "intersection_ratio": float(intersection_ratio),
                    "intersection_ratio_basis": "intersection_area / crop_bbox_area",
                }
            )

            tree = ET.parse(input_xodr)
            root = tree.getroot()
            roads = root.findall("road")

            keep = self._collect_kept_roads(
                roads=roads,
                cx=float(cx),
                cy=float(cy),
                radius_m=float(r),
                effective_offset=effective_offset_used,
            )
            qa["roads_total"] = len(roads)
            qa["roads_kept_initial"] = len(keep)

            if (
                len(keep) == 0
                and float(intersection_ratio) > float(RETRY_INTERSECTION_RATIO_THRESHOLD)
            ):
                retry_radius = float(r) * 2.0
                qa["retry_attempted"] = True
                qa["retry_radius_m"] = float(retry_radius)
                retry_bbox = {
                    "minx": float(cx - retry_radius),
                    "miny": float(cy - retry_radius),
                    "maxx": float(cx + retry_radius),
                    "maxy": float(cy + retry_radius),
                }
                qa["retry_crop_bbox_in_map_crs"] = retry_bbox

                keep_retry = self._collect_kept_roads(
                    roads=roads,
                    cx=float(cx),
                    cy=float(cy),
                    radius_m=retry_radius,
                    effective_offset=effective_offset_used,
                )
                qa["retry_roads_kept"] = len(keep_retry)
                if keep_retry:
                    keep = keep_retry
                    qa["crop_radius_m_effective"] = float(retry_radius)
                    qa["crop_bbox_in_map_crs"] = retry_bbox
                else:
                    qa["crop_radius_m_effective"] = float(r)
            else:
                qa["crop_radius_m_effective"] = float(r)

            qa["roads_kept"] = len(keep)

            # Replace road set.
            for road_node in roads:
                root.remove(road_node)
            for road_node in keep:
                root.append(road_node)

            tree.write(output_xodr, encoding="utf-8", xml_declaration=True)
            qa["ok"] = True

            print(
                "[GPS_QA_CROP] map_crs_source=%s map_crs_proj4=%s"
                % (qa.get("map_crs_source", ""), qa.get("map_crs_proj4", ""))
            )
            print(
                "[GPS_QA_CROP] header_offset_policy=%s effective_offset_used=%s"
                % (
                    qa.get("header_offset_policy", ""),
                    qa.get("effective_offset_used", {}),
                )
            )
            print(
                "[GPS_QA_CROP] crop_center_wgs84=%s crop_center_map_crs=%s radius_m=%s"
                % (
                    qa.get("crop_center_wgs84", {}),
                    qa.get("crop_center_map_crs", {}),
                    qa.get("crop_radius_m_effective", qa.get("crop_radius_m", 0.0)),
                )
            )
            print(
                "[GPS_QA_CROP] map_bbox_in_map_crs=%s crop_bbox_in_map_crs=%s intersection_ratio=%.6f"
                % (
                    qa.get("map_bbox_in_map_crs"),
                    qa.get("crop_bbox_in_map_crs"),
                    float(qa.get("intersection_ratio", 0.0)),
                )
            )
            print(
                "[GPS_QA_CROP] wrote %s (roads kept: %d)"
                % (output_xodr, int(len(keep)))
            )
            return qa
        except Exception as exc:
            qa["ok"] = False
            qa["error"] = str(exc)
            print(f"[GPS_QA_CROP] failed: {exc}")
            raise
        finally:
            try:
                self._write_report(qa_path, qa)
                print(f"[GPS_QA_CROP] QA report -> {qa_path}")
            except Exception as report_exc:
                print(f"[GPS_QA_CROP] QA report write failed: {report_exc}")
