from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from ultimate_pipeline.core.georef_utils import normalize_georeference, parse_georeference
from ultimate_pipeline.geometry.geometry_math import sample_parampoly3_points


def identity_transform() -> Dict[str, float]:
    return {"scale": 1.0, "cos": 1.0, "sin": 0.0, "tx": 0.0, "ty": 0.0}


def _compute_bbox(pts: List[Tuple[float, float]]) -> Dict[str, float]:
    if not pts:
        return {"minx": 0.0, "maxx": 0.0, "miny": 0.0, "maxy": 0.0}
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return {"minx": min(xs), "maxx": max(xs), "miny": min(ys), "maxy": max(ys)}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except Exception:
        return float(default)
    if not math.isfinite(parsed):
        return float(default)
    return float(parsed)


def _sample_transformed_geometry_points(geom: ET.Element) -> List[Tuple[float, float]]:
    x0 = _safe_float(geom.get("x"), 0.0)
    y0 = _safe_float(geom.get("y"), 0.0)
    hdg = _safe_float(geom.get("hdg"), 0.0)
    length = max(0.0, _safe_float(geom.get("length"), 0.0))
    t_values = (0.0, 0.5, 1.0)

    if geom.find("arc") is not None:
        curvature = _safe_float(geom.find("arc").get("curvature"), 0.0)
        if abs(curvature) <= 1e-12:
            return [
                (x0 + (length * float(t) * math.cos(hdg)), y0 + (length * float(t) * math.sin(hdg)))
                for t in t_values
            ]
        points: List[Tuple[float, float]] = []
        for t in t_values:
            ds = length * float(t)
            theta = hdg + curvature * ds
            xx = x0 + (math.sin(theta) - math.sin(hdg)) / curvature
            yy = y0 - (math.cos(theta) - math.cos(hdg)) / curvature
            points.append((xx, yy))
        return points

    if geom.find("paramPoly3") is not None:
        return sample_parampoly3_points(geom, x0, y0, hdg, length, t_values)

    return [
        (x0 + (length * float(t) * math.cos(hdg)), y0 + (length * float(t) * math.sin(hdg)))
        for t in t_values
    ]


def compute_translation_from_bbox(auto_xodr: str, gps_bounds: Dict, crs: str) -> Dict[str, float]:
    """Deterministic translation from canonical GPS bbox center to auto geometry centroid.

    Returns dict with dx, dy and auto_bbox for provenance.
    """
    from ultimate_pipeline.domain_gap.deterministic_alignment import (
        compute_auto_bbox_and_centroid,
        project_center_from_gps_bounds,
    )

    bbox, (ax, ay), _ = compute_auto_bbox_and_centroid(Path(auto_xodr))
    tx, ty = project_center_from_gps_bounds(gps_bounds, crs)
    return {"dx": float(tx - ax), "dy": float(ty - ay), "auto_bbox": bbox.__dict__}



def _subsample_points(pts: List[Tuple[float, float]], max_points: Optional[int]) -> List[Tuple[float, float]]:
    if not max_points or max_points <= 0 or len(pts) <= max_points:
        return pts
    step = max(1, len(pts) // max_points)
    return pts[::step][:max_points]


def _extract_xy_geometry_stream_regex(xodr_path: str, max_points: Optional[int] = None) -> List[Tuple[float, float]]:
    """
    Streaming regex extractor for <geometry ... x=".." y=".."> start points.
    - No XML parse
    - No full-file read
    - Robust to attribute order + scientific notation
    """
    import io

    pat_xy = re.compile(r'<geometry\b[^>]*\bx="([-0-9.eE+]+)"[^>]*\by="([-0-9.eE+]+)"', re.IGNORECASE)
    pat_yx = re.compile(r'<geometry\b[^>]*\by="([-0-9.eE+]+)"[^>]*\bx="([-0-9.eE+]+)"', re.IGNORECASE)

    pts: List[Tuple[float, float]] = []
    tail = ""

    # text mode w/ errors ignored handles weird encodings without dying
    with open(xodr_path, "r", encoding="utf-8", errors="ignore") as f:
        while True:
            chunk = f.read(4 * 1024 * 1024)  # 4MB
            if not chunk:
                break
            buf = tail + chunk

            for m in pat_xy.finditer(buf):
                try:
                    pts.append((float(m.group(1)), float(m.group(2))))
                except Exception:
                    pass
                if max_points and len(pts) >= max_points:
                    return pts

            for m in pat_yx.finditer(buf):
                try:
                    pts.append((float(m.group(2)), float(m.group(1))))
                except Exception:
                    pass
                if max_points and len(pts) >= max_points:
                    return pts

            # keep a tail so tags split across chunk boundaries still match
            tail = buf[-2048:]

    return pts


def _bbox_center(bbox: Dict[str, float]) -> Tuple[float, float]:
    return (bbox["minx"] + bbox["maxx"]) / 2.0, (bbox["miny"] + bbox["maxy"]) / 2.0


def _localname(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _extract_xy_planview_geometry_file(xodr_path: str) -> List[Tuple[float, float]]:
    """Stream-extract planView geometry start points from an XODR file.

    Robust against:
    - huge XODR (manual maps)
    - scientific notation
    - x/y attribute order (uses attrib dict)
    """
    import xml.etree.ElementTree as ET

    pts: List[Tuple[float, float]] = []
    stack: List[str] = []
    try:
        for ev, el in ET.iterparse(xodr_path, events=("start", "end")):
            name = _localname(el.tag)
            if ev == "start":
                stack.append(name)
                if name == "geometry" and len(stack) >= 2 and stack[-2] == "planView":
                    ax = el.attrib.get("x")
                    ay = el.attrib.get("y")
                    if ax is None or ay is None:
                        continue
                    try:
                        pts.append((float(ax), float(ay)))
                    except Exception:
                        continue
            else:
                if stack:
                    stack.pop()
                el.clear()
        return pts
    except Exception:
        return pts


def _extract_xy_anywhere_text(text: str) -> List[Tuple[float, float]]:
    # tiny-test fallback only
    pts: List[Tuple[float, float]] = []
    for m in re.finditer(r'x="([-0-9.eE+]+)"\s+y="([-0-9.eE+]+)"', text):
        try:
            pts.append((float(m.group(1)), float(m.group(2))))
        except Exception:
            pass
    for m in re.finditer(r'y="([-0-9.eE+]+)"\s+x="([-0-9.eE+]+)"', text):
        try:
            pts.append((float(m.group(2)), float(m.group(1))))
        except Exception:
            pass
    return pts


def _extract_georeference_proj4(xodr_path: str) -> str:
    try:
        tree = ET.parse(str(xodr_path))
    except Exception as exc:
        raise RuntimeError(f"Failed to parse XODR for CRS extraction: {xodr_path}: {exc}") from exc

    root = tree.getroot()
    header = root.find("header")
    if header is None:
        raise RuntimeError(f"Missing <header> in XODR: {xodr_path}")
    geo = header.find("geoReference")
    raw = geo.text if geo is not None else ""
    norm = normalize_georeference(raw)
    valid, params_complete, norm = parse_georeference(norm)
    if not valid:
        raise RuntimeError(f"Missing or invalid geoReference in XODR: {xodr_path}")
    if not params_complete:
        raise RuntimeError(f"Incomplete geoReference in XODR: {xodr_path}")
    return str(norm)


def _reproject_points(
    pts: List[Tuple[float, float]], source_proj4: str, target_proj4: str
) -> List[Tuple[float, float]]:
    try:
        from pyproj import CRS, Transformer
    except Exception as exc:
        raise RuntimeError("pyproj is required for CRS reprojection in GeoAligner") from exc

    try:
        src_crs = CRS.from_user_input(source_proj4)
        dst_crs = CRS.from_user_input(target_proj4)
        tf = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    except Exception as exc:
        raise RuntimeError(f"Failed to build CRS transformer ({source_proj4} -> {target_proj4}): {exc}") from exc

    out: List[Tuple[float, float]] = []
    for x, y in pts:
        try:
            xx, yy = tf.transform(float(x), float(y))
            out.append((float(xx), float(yy)))
        except Exception as exc:
            raise RuntimeError(f"Failed to reproject geometry point ({x}, {y}): {exc}") from exc
    return out


def _rmse(a: List[Tuple[float, float]], b: List[Tuple[float, float]]) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return float("inf")
    s = 0.0
    for i in range(n):
        dx = a[i][0] - b[i][0]
        dy = a[i][1] - b[i][1]
        s += dx * dx + dy * dy
    return math.sqrt(s / n)


def _apply_similarity(
    pts: List[Tuple[float, float]], scale: float, c: float, sn: float, tx: float, ty: float
) -> List[Tuple[float, float]]:
    return [(scale * (c * x - sn * y) + tx, scale * (sn * x + c * y) + ty) for x, y in pts]


def _norm_angle(angle: float) -> float:
    angle = (angle + math.pi) % (2.0 * math.pi) - math.pi
    if angle <= -math.pi:
        angle += 2.0 * math.pi
    return angle


def _bbox_iou(a: Dict[str, float], b: Dict[str, float]) -> float:
    ix1 = max(float(a["minx"]), float(b["minx"]))
    iy1 = max(float(a["miny"]), float(b["miny"]))
    ix2 = min(float(a["maxx"]), float(b["maxx"]))
    iy2 = min(float(a["maxy"]), float(b["maxy"]))
    iw = max(ix2 - ix1, 0.0)
    ih = max(iy2 - iy1, 0.0)
    inter = iw * ih
    area_a = max(float(a["maxx"]) - float(a["minx"]), 0.0) * max(float(a["maxy"]) - float(a["miny"]), 0.0)
    area_b = max(float(b["maxx"]) - float(b["minx"]), 0.0) * max(float(b["maxy"]) - float(b["miny"]), 0.0)
    union = area_a + area_b - inter
    if union <= 0.0:
        return 0.0
    return float(inter / union)


def _estimate_rigid_svd(
    src: List[Tuple[float, float]], dst: List[Tuple[float, float]]
) -> Tuple[float, float, float, float, float]:
    """2D rigid transform (rotation+translation, scale locked to 1.0) src->dst using SVD."""
    import numpy as np

    n = min(len(src), len(dst))
    if n < 2:
        return 1.0, 1.0, 0.0, 0.0, 0.0

    X = np.array(src[:n], dtype=np.float64)
    Y = np.array(dst[:n], dtype=np.float64)

    muX = X.mean(axis=0)
    muY = Y.mean(axis=0)

    Xc = X - muX
    Yc = Y - muY

    var_x = float(np.sum(Xc * Xc) / n)
    if not np.isfinite(var_x) or var_x <= 0.0:
        return 1.0, 1.0, 0.0, float(muY[0] - muX[0]), float(muY[1] - muX[1])

    Sigma = (Yc.T @ Xc) / n
    U, svals, Vt = np.linalg.svd(Sigma)
    S = np.eye(2, dtype=np.float64)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        S[-1, -1] = -1.0
    R = U @ S @ Vt
    scale = 1.0
    t = muY - (scale * (R @ muX))

    c = float(R[0, 0])
    sn = float(R[1, 0])
    return float(scale), c, sn, float(t[0]), float(t[1])


def _estimate_rigid_no_scale(
    src: List[Tuple[float, float]], dst: List[Tuple[float, float]]
) -> Tuple[float, float, float, float, float]:
    """2D rigid transform (rotation+translation, scale fixed to 1.0) src->dst."""
    import numpy as np

    n = min(len(src), len(dst))
    if n < 2:
        sx = sum(p[0] for p in src) / max(len(src), 1)
        sy = sum(p[1] for p in src) / max(len(src), 1)
        dx = sum(p[0] for p in dst) / max(len(dst), 1)
        dy = sum(p[1] for p in dst) / max(len(dst), 1)
        return 1.0, 1.0, 0.0, float(dx - sx), float(dy - sy)

    X = np.asarray(src[:n], dtype=np.float64)
    Y = np.asarray(dst[:n], dtype=np.float64)

    mu_x = X.mean(axis=0)
    mu_y = Y.mean(axis=0)
    Xc = X - mu_x
    Yc = Y - mu_y

    H = Xc.T @ Yc
    U, _svals, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T
    if np.linalg.det(R) < 0:
        Vt[-1, :] *= -1.0
        R = Vt.T @ U.T

    t = mu_y - (R @ mu_x)
    c = float(R[0, 0])
    sn = float(R[1, 0])
    return 1.0, c, sn, float(t[0]), float(t[1])


def _mean_xy(pts: List[Tuple[float, float]]) -> Tuple[float, float]:
    if not pts:
        return 0.0, 0.0
    n = float(len(pts))
    return (
        sum(float(x) for x, _ in pts) / n,
        sum(float(y) for _, y in pts) / n,
    )


def _transform_from_rotation_and_means(
    src_pts: List[Tuple[float, float]],
    dst_pts: List[Tuple[float, float]],
    angle_deg: float,
) -> Tuple[float, float, float, float, float]:
    theta = math.radians(float(angle_deg))
    c = math.cos(theta)
    sn = math.sin(theta)
    src_mx, src_my = _mean_xy(src_pts)
    dst_mx, dst_my = _mean_xy(dst_pts)
    tx = float(dst_mx - (c * src_mx - sn * src_my))
    ty = float(dst_my - (sn * src_mx + c * src_my))
    return 1.0, float(c), float(sn), tx, ty


def _search_small_rotation(
    src_pts: List[Tuple[float, float]],
    dst_pts: List[Tuple[float, float]],
    max_abs_angle_deg: float = 2.5,
    coarse_step_deg: float = 0.25,
    fine_step_deg: float = 0.05,
    search_max_points: int = 4000,
) -> Dict[str, Any]:
    if len(src_pts) < 2 or len(dst_pts) < 2:
        scale, c, sn, tx, ty = _transform_from_rotation_and_means(src_pts, dst_pts, 0.0)
        return {
            "transform": {"scale": scale, "cos": c, "sin": sn, "tx": tx, "ty": ty},
            "angle_deg": 0.0,
            "objective_rms": None,
            "used": False,
            "reason": "insufficient_points",
            "coarse_step_deg": coarse_step_deg,
            "fine_step_deg": fine_step_deg,
            "max_abs_angle_deg": max_abs_angle_deg,
        }

    try:
        import numpy as np
        from scipy.spatial import cKDTree
    except Exception:
        scale, c, sn, tx, ty = _transform_from_rotation_and_means(src_pts, dst_pts, 0.0)
        return {
            "transform": {"scale": scale, "cos": c, "sin": sn, "tx": tx, "ty": ty},
            "angle_deg": 0.0,
            "objective_rms": None,
            "used": False,
            "reason": "scipy_unavailable",
            "coarse_step_deg": coarse_step_deg,
            "fine_step_deg": fine_step_deg,
            "max_abs_angle_deg": max_abs_angle_deg,
        }

    src_search = _subsample_points(src_pts, min(len(src_pts), int(search_max_points)))
    dst_search = _subsample_points(dst_pts, min(len(dst_pts), int(search_max_points)))
    if len(src_search) < 2 or len(dst_search) < 2:
        scale, c, sn, tx, ty = _transform_from_rotation_and_means(src_pts, dst_pts, 0.0)
        return {
            "transform": {"scale": scale, "cos": c, "sin": sn, "tx": tx, "ty": ty},
            "angle_deg": 0.0,
            "objective_rms": None,
            "used": False,
            "reason": "insufficient_search_points",
            "coarse_step_deg": coarse_step_deg,
            "fine_step_deg": fine_step_deg,
            "max_abs_angle_deg": max_abs_angle_deg,
        }

    src_arr = np.asarray(src_search, dtype=np.float64)
    dst_arr = np.asarray(dst_search, dtype=np.float64)
    dst_tree = cKDTree(dst_arr)

    def _score_angle(angle_deg: float) -> float:
        scale, c, sn, tx, ty = _transform_from_rotation_and_means(src_search, dst_search, angle_deg)
        transformed = np.empty_like(src_arr)
        transformed[:, 0] = scale * (c * src_arr[:, 0] - sn * src_arr[:, 1]) + tx
        transformed[:, 1] = scale * (sn * src_arr[:, 0] + c * src_arr[:, 1]) + ty
        dists, _ = dst_tree.query(transformed, k=1)
        return float(np.sqrt(np.mean(dists * dists)))

    best_angle = 0.0
    best_score = float("inf")
    steps = max(int(round((2.0 * max_abs_angle_deg) / coarse_step_deg)), 1)
    for idx in range(steps + 1):
        angle = -max_abs_angle_deg + (idx * coarse_step_deg)
        score = _score_angle(angle)
        if score < best_score:
            best_score = score
            best_angle = angle

    fine_lo = max(best_angle - coarse_step_deg, -max_abs_angle_deg)
    fine_hi = min(best_angle + coarse_step_deg, max_abs_angle_deg)
    fine_steps = max(int(round((fine_hi - fine_lo) / fine_step_deg)), 1)
    for idx in range(fine_steps + 1):
        angle = fine_lo + (idx * fine_step_deg)
        score = _score_angle(angle)
        if score < best_score:
            best_score = score
            best_angle = angle

    scale, c, sn, tx, ty = _transform_from_rotation_and_means(src_pts, dst_pts, best_angle)
    return {
        "transform": {"scale": scale, "cos": c, "sin": sn, "tx": tx, "ty": ty},
        "angle_deg": float(best_angle),
        "objective_rms": float(best_score),
        "used": True,
        "reason": None,
        "coarse_step_deg": coarse_step_deg,
        "fine_step_deg": fine_step_deg,
        "max_abs_angle_deg": max_abs_angle_deg,
    }


@dataclass
class GeoAligner:
    @staticmethod
    def estimate_from_xodr(
        manual_xodr: str,
        auto_xodr: str,
        icp_iters: int = 5,  # Deprecated: not consumed; alignment is single SE(2) pass, not ICP.
        step_m: float = 1.0,
        trim_ratio: float = 0.1,
        verbose: bool = False,
        out_dir: Optional[str] = None,
        max_points: Optional[int] = None,
        strict: bool = False,
    ) -> Dict[str, Any]:
        manual_pts = _extract_xy_planview_geometry_file(str(manual_xodr))
        auto_pts = _extract_xy_planview_geometry_file(str(auto_xodr))
        manual_crs = ""
        auto_crs = ""
        crs_alignment_applied = False
        centroid_delta_before_m = None
        centroid_delta_after_m = None
        bbox_iou_after_reprojection = None

        # Robust fallbacks (NO full-file reads for huge manual maps)
        if not manual_pts:
            manual_pts = _extract_xy_geometry_stream_regex(str(manual_xodr), max_points=max_points)
        if not auto_pts:
            auto_pts = _extract_xy_geometry_stream_regex(str(auto_xodr), max_points=max_points)

        # tiny-test fallback only (last resort)
        if not manual_pts:
            try:
                manual_pts = _extract_xy_anywhere_text(Path(manual_xodr).read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                pass
        if not auto_pts:
            try:
                auto_pts = _extract_xy_anywhere_text(Path(auto_xodr).read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                pass

        # Reproject auto geometry into manual CRS before matching.
        try:
            manual_crs = _extract_georeference_proj4(str(manual_xodr))
            auto_crs = _extract_georeference_proj4(str(auto_xodr))
            if manual_crs != auto_crs:
                manual_bbox_pre = _compute_bbox(manual_pts)
                auto_bbox_pre = _compute_bbox(auto_pts)
                if manual_pts and auto_pts:
                    mcx, mcy = _bbox_center(manual_bbox_pre)
                    acx, acy = _bbox_center(auto_bbox_pre)
                    centroid_delta_before_m = math.hypot(mcx - acx, mcy - acy)
                auto_pts = _reproject_points(auto_pts, auto_crs, manual_crs)
                crs_alignment_applied = True
                manual_bbox_post = _compute_bbox(manual_pts)
                auto_bbox_post = _compute_bbox(auto_pts)
                if manual_pts and auto_pts:
                    mcx, mcy = _bbox_center(manual_bbox_post)
                    acx, acy = _bbox_center(auto_bbox_post)
                    centroid_delta_after_m = math.hypot(mcx - acx, mcy - acy)
                    bbox_iou_after_reprojection = _bbox_iou(manual_bbox_post, auto_bbox_post)
        except Exception as exc:
            if strict:
                raise RuntimeError(f"GeoAlignment CRS reprojection failed: {exc}") from exc

        manual_pts = _subsample_points(manual_pts, max_points)
        auto_pts = _subsample_points(auto_pts, max_points)

        n_points = min(len(manual_pts), len(auto_pts))
        if n_points == 0:
            manual_bbox = _compute_bbox(manual_pts)
            auto_bbox = _compute_bbox(auto_pts)

            if out_dir:
                Path(out_dir).mkdir(parents=True, exist_ok=True)
                (Path(out_dir) / "alignment_debug.json").write_text(
                    json.dumps(
                        {
                            "reason": "zero_correspondences",
                            "manual_points_count": len(manual_pts),
                            "auto_points_count": len(auto_pts),
                            "manual_bbox": manual_bbox,
                            "auto_bbox": auto_bbox,
                            "manual_xodr": str(manual_xodr),
                            "auto_xodr": str(auto_xodr),
                        },
                        indent=2,
                        ensure_ascii=True,
                    ),
                    encoding="utf-8",
                )

            tx = ty = 0.0

            if strict:
                raise RuntimeError(
                    f"GeoAlignment failed: zero correspondences. manual_pts={len(manual_pts)} auto_pts={len(auto_pts)}"
                )

            tx = ty = 0.0
            if manual_pts and auto_pts:
                m_cx, m_cy = _bbox_center(manual_bbox)
                a_cx, a_cy = _bbox_center(auto_bbox)
                tx, ty = m_cx - a_cx, m_cy - a_cy

            return {
                "transform": {"scale": 1.0, "cos": 1.0, "sin": 0.0, "tx": tx, "ty": ty},
                "crs_alignment_applied": bool(crs_alignment_applied),
                "source_crs": auto_crs or None,
                "target_crs": manual_crs or None,
                "diagnostics": {
                    "rmse_before": float("inf"),
                    "rmse_after": float("inf"),
                    "n_points": 0,
                    "fallback_used": True,
                    "fallback_reason": "zero_correspondences",
                    "crs_alignment_applied": bool(crs_alignment_applied),
                    "source_crs": auto_crs or None,
                    "target_crs": manual_crs or None,
                },
            }

        rmse_before = _rmse(manual_pts, auto_pts)
        manual_bbox = _compute_bbox(manual_pts)
        auto_bbox = _compute_bbox(auto_pts)

        init_scale, init_c, init_sn, init_tx, init_ty = _transform_from_rotation_and_means(
            auto_pts, manual_pts, 0.0
        )
        initially_aligned = _apply_similarity(auto_pts, init_scale, init_c, init_sn, init_tx, init_ty)
        rmse_after_initial_rigid = _rmse(manual_pts, initially_aligned)

        search = _search_small_rotation(auto_pts, manual_pts)
        transform = search["transform"]
        scale = float(transform["scale"])
        c = float(transform["cos"])
        sn = float(transform["sin"])
        tx = float(transform["tx"])
        ty = float(transform["ty"])
        aligned = _apply_similarity(auto_pts, scale, c, sn, tx, ty)
        rmse_after = _rmse(manual_pts, aligned)

        return {
            "transform": {"scale": scale, "cos": c, "sin": sn, "tx": tx, "ty": ty},
            "crs_reprojection": {
                "applied": bool(crs_alignment_applied),
                "src_crs": auto_crs or None,
                "dst_crs": manual_crs or None,
                "centroid_delta_before_m": centroid_delta_before_m,
                "centroid_delta_after_m": centroid_delta_after_m,
                "bbox_iou_after_reprojection": bbox_iou_after_reprojection,
            },
            "crs_alignment_applied": bool(crs_alignment_applied),
            "source_crs": auto_crs or None,
            "target_crs": manual_crs or None,
            "alignment_method": "mean_translation_plus_small_angle_search",
            "icp_iters": None,
            "icp_iters_note": "parameter declared but not consumed; alignment uses mean-centroid translation plus deterministic small-angle search, not iterative ICP",
            "alignment_method_note": (
                "Rigid SE(2) fit with scale locked to 1.0. The initialization is mean-centroid "
                "translation after CRS reprojection, followed by a deterministic small-angle search "
                "that minimizes nearest-neighbor start-point RMS from transformed auto geometry to "
                "manual geometry."
            ),
            "diagnostics": {
                "rmse_after_initial_rigid": float(rmse_after_initial_rigid),
                "rmse_before": float(rmse_before),
                "rmse_after": float(rmse_after),
                "n_points": int(n_points),
                "fallback_used": False,
                "manual_bbox": manual_bbox,
                "auto_bbox": auto_bbox,
                "crs_alignment_applied": bool(crs_alignment_applied),
                "source_crs": auto_crs or None,
                "target_crs": manual_crs or None,
                "rigid_only": True,
                "scale_locked": 1.0,
                "init_method": "mean_centroid_translation",
                "rotation_deg_after_init": 0.0,
                "angle_search_used": bool(search.get("used")),
                "angle_search_reason": search.get("reason"),
                "angle_search_best_deg": float(search.get("angle_deg") or 0.0),
                "angle_search_objective_rms": search.get("objective_rms"),
                "angle_search_window_deg": float(search.get("max_abs_angle_deg") or 0.0),
                "angle_search_coarse_step_deg": float(search.get("coarse_step_deg") or 0.0),
                "angle_search_fine_step_deg": float(search.get("fine_step_deg") or 0.0),
                "fit_metric": "planView geometry start-point correspondence RMSE",
                "fit_metric_note": (
                    "Diagnostic metric (planView start-point RMSE); not proven equivalent "
                    "to ICP optimization objective. Monotonic increase does not imply ICP "
                    "failure - see chap7 alignment interpretation."
                ),
                "metric_note": (
                    "Rigid SE(2) fit with scale locked to 1.0 after CRS reprojection. "
                    "The reported angle-search objective is nearest-neighbor start-point RMS "
                    "from transformed auto geometry to manual geometry."
                ),
            },
        }

    @staticmethod
    def apply_to_xodr(
        in_xodr: str,
        out_xodr: Optional[str] = None,
        transform: Union[Dict[str, float], Dict[str, Any], None] = None,
    ) -> Union[bool, str]:
        bundle: Dict[str, Any]
        if transform is None:
            bundle = {"transform": identity_transform()}
        elif isinstance(transform, dict):
            bundle = transform
        else:
            bundle = {"transform": identity_transform()}

        transform_dict: Dict[str, Any]
        if "transform" in bundle and isinstance(bundle.get("transform"), dict):
            transform_dict = bundle["transform"]
        else:
            transform_dict = bundle

        scale = float(transform_dict.get("scale", 1.0))
        c = float(transform_dict.get("cos", 1.0))
        sn = float(transform_dict.get("sin", 0.0))
        tx = float(transform_dict.get("tx", 0.0))
        ty = float(transform_dict.get("ty", 0.0))
        rot = math.atan2(sn, c)

        crs_meta = bundle.get("crs_reprojection") if isinstance(bundle.get("crs_reprojection"), dict) else {}
        source_crs = str(crs_meta.get("src_crs") or bundle.get("source_crs") or "").strip()
        target_crs = str(crs_meta.get("dst_crs") or bundle.get("target_crs") or "").strip()
        reproject_before_transform = bool(crs_meta.get("applied")) and bool(source_crs and target_crs and source_crs != target_crs)

        projector = None
        if reproject_before_transform:
            try:
                from pyproj import CRS, Transformer

                projector = Transformer.from_crs(
                    CRS.from_user_input(source_crs),
                    CRS.from_user_input(target_crs),
                    always_xy=True,
                )
            except Exception as exc:
                raise RuntimeError(f"GeoAligner.apply_to_xodr could not build CRS transformer: {exc}") from exc

        import xml.etree.ElementTree as ET
        import copy
        import logging
        from io import BytesIO

        tree = ET.parse(in_xodr)
        root = tree.getroot()

        # Step 1: Handle Road Elevation Preservation (Task 1)
        # Rigid transform in XY does not affect elevation profile z(s).
        for road in root.findall("road"):
            road_id = road.get("id", "UNKNOWN")
            elev_prof = road.find("elevationProfile")

            # Check for non-zero elevation before potential (re-)assignment
            source_has_non_zero = False
            if elev_prof is not None:
                for el in elev_prof.findall("elevation"):
                    try:
                        a = float(el.get("a", "0.0"))
                        if abs(a) > 1e-6:
                            source_has_non_zero = True
                            break
                    except Exception:
                        pass

            # Re-build/Ensure elevationProfile to match instructions (even if redundant in-place)
            if elev_prof is not None:
                # Task: Replace it with: copy the elevationProfile element from the corresponding source road
                # In this in-place context, we deepcopy it to ensure it's detached from any weirdness
                new_elev_prof = copy.deepcopy(elev_prof)
                road.remove(elev_prof)
                road.append(new_elev_prof)
            else:
                # Step 4: If missing, insert flat one
                new_elev_prof = ET.SubElement(road, "elevationProfile")
                ET.SubElement(new_elev_prof, "elevation", {"s": "0.0", "a": "0.000000", "b": "0.0", "c": "0.0", "d": "0.0"})

            # Step 5: Warning log if elevation lost (source was non-zero, but output is flat)
            final_elev = road.find("elevationProfile/elevation")
            if final_elev is not None:
                try:
                    final_a = float(final_elev.get("a", "0.0"))
                    if source_has_non_zero and abs(final_a) < 1e-6:
                        logging.warning("elevation_lost road_id=%s", road_id)
                except Exception:
                    pass

        n = 0
        for geom in root.findall(".//road/planView/geometry"):
            x = geom.get("x"); y = geom.get("y")
            if x is None or y is None:
                continue
            try:
                xf = float(x); yf = float(y)
                x_src = xf
                y_src = yf
                if projector is not None:
                    xf, yf = projector.transform(xf, yf)
            except Exception:
                continue
            geom.set("x", f"{scale * (c * xf - sn * yf) + tx:.8f}")
            geom.set("y", f"{scale * (sn * xf + c * yf) + ty:.8f}")
            hdg = geom.get("hdg")
            if hdg is not None:
                try:
                    hdg_val = float(hdg)
                    if projector is not None:
                        step_m = max(0.5, min(float(geom.get("length", "1.0") or "1.0"), 2.0))
                        qx = x_src + math.cos(hdg_val) * step_m
                        qy = y_src + math.sin(hdg_val) * step_m
                        qx_reproj, qy_reproj = projector.transform(qx, qy)
                        dx = qx_reproj - xf
                        dy = qy_reproj - yf
                        if abs(dx) > 1e-9 or abs(dy) > 1e-9:
                            hdg_val = math.atan2(dy, dx)
                    geom.set("hdg", f"{_norm_angle(hdg_val + rot):.12f}")
                except Exception:
                    pass
            n += 1

        if n == 0:
            return "" if out_xodr is None else False

        transformed_points: List[Tuple[float, float]] = []
        for geom in root.findall(".//road/planView/geometry"):
            transformed_points.extend(_sample_transformed_geometry_points(geom))
        bbox = _compute_bbox(transformed_points)

        try:
            from ultimate_pipeline.core.georef_utils import normalize_georeference
            header = root.find("header")
            if header is None:
                header = ET.SubElement(root, "header")
            if header is not None:
                header.set("west", f"{bbox['minx']:.8f}")
                header.set("east", f"{bbox['maxx']:.8f}")
                header.set("south", f"{bbox['miny']:.8f}")
                header.set("north", f"{bbox['maxy']:.8f}")
                geo = header.find("geoReference")
                if geo is not None:
                    if target_crs:
                        geo.text = normalize_georeference(target_crs)
                    elif geo.text:
                        geo.text = normalize_georeference(geo.text)
        except Exception:
            pass

        if out_xodr is None:
            buf = BytesIO()
            tree.write(buf, encoding="utf-8", xml_declaration=True)
            return buf.getvalue().decode("utf-8")

        Path(out_xodr).parent.mkdir(parents=True, exist_ok=True)
        tree.write(out_xodr, encoding="utf-8", xml_declaration=True)
        return True
