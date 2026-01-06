from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import List, Tuple, Dict, Any, Optional

import numpy as np

XY = Tuple[float, float]


# =============================================================================
# Public helper
# =============================================================================

def identity_transform() -> Dict[str, Any]:
    return {
        "R": [[1.0, 0.0], [0.0, 1.0]],
        "t": [0.0, 0.0],
        "scale": 1.0,
        "theta": 0.0,
        "diagnostics": {
            "method": "identity",
            "rmse_before": None,
            "rmse_after": None,
            "inliers": None,
            "pairs": None,
            "iterations": 0,
        },
    }


# =============================================================================
# Utils
# =============================================================================

def _safe_float(val: str, default: float = 0.0) -> float:
    try:
        return float(val)
    except Exception:
        return default


def _wrap_angle(a: float) -> float:
    # wrap to [-pi, pi]
    return (a + math.pi) % (2 * math.pi) - math.pi


def _as_np2(x: List[XY]) -> np.ndarray:
    if not x:
        return np.zeros((0, 2), dtype=np.float64)
    return np.asarray(x, dtype=np.float64)


# =============================================================================
# Geometry sampling (straight + arc)
# =============================================================================

def _sample_geometry(geom: ET.Element, step_m: float = 20.0) -> List[XY]:
    """
    Sample an OpenDRIVE <geometry> element into XY points.

    Supported:
      - line (no child element)
      - arc (<arc curvature="..."/>)

    This uses a consistent parametric integration for arcs.
    """
    x0 = _safe_float(geom.get("x", "0"))
    y0 = _safe_float(geom.get("y", "0"))
    hdg0 = _safe_float(geom.get("hdg", "0"))
    length = _safe_float(geom.get("length", "0"))

    if length <= 0:
        return []

    n = max(2, int(math.ceil(length / max(step_m, 1e-6))))
    s_vals = np.linspace(0.0, length, n + 1)

    arc = geom.find("arc")
    pts: List[XY] = []

    if arc is None:
        # Straight line
        cos_h = math.cos(hdg0)
        sin_h = math.sin(hdg0)
        for s in s_vals:
            pts.append((x0 + s * cos_h, y0 + s * sin_h))
        return pts

    k = _safe_float(arc.get("curvature", "0.0"), 0.0)

    if abs(k) < 1e-12:
        # effectively straight
        return _sample_geometry(geom, step_m=step_m)

    # Arc integration:
    # heading(s) = hdg0 + k*s
    # position(s) = [x0, y0] + ∫ [cos(heading(u)), sin(heading(u))] du
    # Closed form:
    # x(s) = x0 + (sin(hdg0 + k*s) - sin(hdg0))/k
    # y(s) = y0 - (cos(hdg0 + k*s) - cos(hdg0))/k
    for s in s_vals:
        hdg = hdg0 + k * s
        x = x0 + (math.sin(hdg) - math.sin(hdg0)) / k
        y = y0 - (math.cos(hdg) - math.cos(hdg0)) / k
        pts.append((x, y))

    return pts


def _sample_points_from_xodr(
    path: str,
    *,
    step_m: float = 20.0,
    max_points: int = 5000,
) -> np.ndarray:
    """
    Sample (x,y) points from all road/planView geometries.

    Notes:
      - We intentionally oversample a bit, then downsample deterministically.
      - Deterministic subsampling (linspace indices) keeps reproducibility.
    """
    tree = ET.parse(path)
    root = tree.getroot()

    pts: List[XY] = []
    for road in root.findall("road"):
        plan = road.find("planView")
        if plan is None:
            continue
        for g in plan.findall("geometry"):
            pts.extend(_sample_geometry(g, step_m=step_m))

    arr = _as_np2(pts)
    if arr.shape[0] == 0:
        return arr

    if arr.shape[0] > max_points:
        idx = np.linspace(0, arr.shape[0] - 1, num=max_points).astype(int)
        arr = arr[idx]

    return arr


# =============================================================================
# Similarity transform estimation (Kabsch + scale)
# =============================================================================

def _estimate_similarity_transform(src: np.ndarray, dst: np.ndarray) -> Dict[str, Any]:
    """
    Estimate similarity transform mapping src -> dst:
        dst ≈ s * R * src + t
    """
    if src.shape != dst.shape or src.shape[0] < 3:
        raise ValueError("Need >=3 paired points with same shape to estimate transform")

    src_mean = src.mean(axis=0)
    dst_mean = dst.mean(axis=0)
    X = src - src_mean
    Y = dst - dst_mean

    H = X.T @ Y
    U, S, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T

    # reflection fix
    if np.linalg.det(R) < 0:
        Vt[1, :] *= -1
        R = Vt.T @ U.T

    var_src = float((X * X).sum())
    s = 1.0 if var_src < 1e-12 else float(S.sum() / var_src)

    t = dst_mean - s * (R @ src_mean)

    theta = math.atan2(R[1, 0], R[0, 0])

    return {
        "R": R.tolist(),
        "t": t.tolist(),
        "scale": float(s),
        "theta": float(theta),
        "src_mean": src_mean.tolist(),
        "dst_mean": dst_mean.tolist(),
    }


def _apply_transform_pts(pts: np.ndarray, tf: Dict[str, Any]) -> np.ndarray:
    R = np.asarray(tf["R"], dtype=np.float64)
    t = np.asarray(tf["t"], dtype=np.float64)
    s = float(tf.get("scale", 1.0))
    return (s * (pts @ R.T)) + t  # (N,2)


def _rmse(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape[0] == 0:
        return 0.0
    d = a - b
    return float(np.sqrt((d * d).sum(axis=1).mean()))


# =============================================================================
# Correspondence: nearest neighbors (no SciPy)
# =============================================================================

def _pair_by_nearest_neighbor(src: np.ndarray, dst: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Pair each src point with its nearest dst point.
    Returns:
      paired_src (N,2), paired_dst (N,2), distances (N,)
    Complexity: O(N*M) naive. We keep N,M small via sampling caps.
    """
    if src.shape[0] == 0 or dst.shape[0] == 0:
        return src[:0], dst[:0], np.zeros((0,), dtype=np.float64)

    # (N,1,2) - (1,M,2) => (N,M,2)
    diff = src[:, None, :] - dst[None, :, :]
    dist2 = (diff * diff).sum(axis=2)  # (N,M)
    j = dist2.argmin(axis=1)          # (N,)
    d = np.sqrt(dist2[np.arange(src.shape[0]), j])
    return src, dst[j], d


def _trim_inliers(src: np.ndarray, dst: np.ndarray, d: np.ndarray, trim_ratio: float) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Keep only the best (1-trim_ratio) fraction by distance.
    """
    if src.shape[0] == 0:
        return src, dst, d
    trim_ratio = float(np.clip(trim_ratio, 0.0, 0.95))
    keep = max(3, int(math.ceil(src.shape[0] * (1.0 - trim_ratio))))
    idx = np.argsort(d)[:keep]
    return src[idx], dst[idx], d[idx]


# =============================================================================
# Main class
# =============================================================================

class GeoAligner:
    """
    Robust 2D similarity alignment between two OpenDRIVE maps.

    Key idea:
      - We DO NOT assume same sampling order = correspondence.
      - Instead we do a small trimmed ICP loop:
          estimate tf -> transform src -> nearest-neighbor pairing -> re-estimate tf
    """

    @staticmethod
    def estimate_from_xodr(
        manual_xodr: str,
        auto_xodr: str,
        *,
        step_m: float = 25.0,
        max_points: int = 6000,
        icp_iters: int = 6,
        trim_ratio: float = 0.35,
        early_stop_rmse: float = 0.05,
        verbose: bool = True,
    ) -> Dict[str, Any]:
        """
        Returns transform mapping AUTO -> MANUAL.

        Parameters tuned for city-scale maps.
        """
        dst = _sample_points_from_xodr(manual_xodr, step_m=step_m, max_points=max_points)
        src0 = _sample_points_from_xodr(auto_xodr, step_m=step_m, max_points=max_points)

        if dst.shape[0] < 3 or src0.shape[0] < 3:
            raise RuntimeError("No/insufficient geometry points found in one or both XODR files")

        # Start with centroids alignment (translation only)
        tf = identity_transform()
        tf["t"] = (dst.mean(axis=0) - src0.mean(axis=0)).tolist()

        # baseline pairing RMSE
        src_tf = _apply_transform_pts(src0, tf)
        _, paired_dst, d0 = _pair_by_nearest_neighbor(src_tf, dst)
        rmse_before = float(np.sqrt((d0 * d0).mean())) if d0.size else None

        if verbose:
            print(f"[GeoAlign] points: auto={src0.shape[0]} manual={dst.shape[0]}")
            print(f"[GeoAlign] baseline NN rmse: {rmse_before:.3f} m" if rmse_before is not None else "[GeoAlign] baseline NN rmse: n/a")

        best_tf = tf
        best_rmse = rmse_before if rmse_before is not None else float("inf")

        last_rmse = best_rmse

        for it in range(int(max(1, icp_iters))):
            src_tf = _apply_transform_pts(src0, best_tf)

            paired_src, paired_dst, d = _pair_by_nearest_neighbor(src_tf, dst)
            paired_src, paired_dst, d = _trim_inliers(paired_src, paired_dst, d, trim_ratio=trim_ratio)

            if paired_src.shape[0] < 3:
                break

            # Estimate transform in ORIGINAL src space:
            # We currently have pairs: (src_tf) ↔ (dst). Need mapping src0 -> dst.
            # Since src_tf = T(best_tf)(src0), we estimate delta on src_tf and then compose.
            delta = _estimate_similarity_transform(paired_src, paired_dst)

            # Compose: new_tf = delta ∘ best_tf
            new_tf = GeoAligner.compose(delta, best_tf)

            # Evaluate
            src_new = _apply_transform_pts(src0, new_tf)
            _, paired_dst2, d2 = _pair_by_nearest_neighbor(src_new, dst)
            rmse_now = float(np.sqrt((d2 * d2).mean())) if d2.size else float("inf")

            if verbose:
                print(f"[GeoAlign] iter {it+1}/{icp_iters} rmse={rmse_now:.3f} m (inliers={paired_src.shape[0]})")

            if rmse_now < best_rmse:
                best_rmse = rmse_now
                best_tf = new_tf

            # early stopping
            if rmse_now <= early_stop_rmse:
                break
            if abs(last_rmse - rmse_now) < 1e-4:
                break
            last_rmse = rmse_now

        # finalize diagnostics
        src_best = _apply_transform_pts(src0, best_tf)
        _, paired_dst3, d3 = _pair_by_nearest_neighbor(src_best, dst)
        rmse_after = float(np.sqrt((d3 * d3).mean())) if d3.size else None

        best_tf["source"] = auto_xodr
        best_tf["target"] = manual_xodr
        best_tf["diagnostics"] = {
            "method": "trimmed_icp_nn",
            "rmse_before": rmse_before,
            "rmse_after": rmse_after,
            "pairs": int(d3.size),
            "inliers": int(max(0, int(math.ceil(d3.size * (1.0 - float(np.clip(trim_ratio, 0.0, 0.95))))))),
            "iterations": int(min(icp_iters, (it + 1))),
            "params": {
                "step_m": step_m,
                "max_points": max_points,
                "icp_iters": icp_iters,
                "trim_ratio": trim_ratio,
                "early_stop_rmse": early_stop_rmse,
            },
        }

        # keep theta wrapped
        best_tf["theta"] = float(_wrap_angle(float(best_tf.get("theta", 0.0))))

        return best_tf

    # -------------------------------------------------------------------------
    # Transform composition
    # -------------------------------------------------------------------------

    @staticmethod
    def compose(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compose similarity transforms:
          x' = Ta(x)
          x'' = Tb(x')
        return Tb ∘ Ta

        Each transform is:
          T(x) = s * R x + t
        """
        Ra = np.asarray(a["R"], dtype=np.float64)
        ta = np.asarray(a["t"], dtype=np.float64)
        sa = float(a.get("scale", 1.0))

        Rb = np.asarray(b["R"], dtype=np.float64)
        tb = np.asarray(b["t"], dtype=np.float64)
        sb = float(b.get("scale", 1.0))

        # Tb(Ta(x)) = sb*Rb*(sa*Ra*x + ta) + tb
        #           = (sb*sa) * (Rb*Ra) * x + (sb*Rb*ta + tb)
        R = (Rb @ Ra)
        s = sb * sa
        t = (sb * (Rb @ ta)) + tb

        theta = math.atan2(R[1, 0], R[0, 0])

        return {
            "R": R.tolist(),
            "t": t.tolist(),
            "scale": float(s),
            "theta": float(theta),
        }

    # -------------------------------------------------------------------------
    # Apply to XODR
    # -------------------------------------------------------------------------

    @staticmethod
    def apply_to_xodr(
        in_xodr: str,
        out_xodr: str,
        transform: Dict[str, Any],
        *,
        adjust_hdg: bool = True,
        precision: int = 6,
    ) -> None:
        """
        Apply similarity transform to all <geometry x,y,hdg>.

        x', y' = s * R @ [x,y] + t
        hdg'   = hdg + theta (optional)

        NOTE:
        This is intentionally limited to planView geometry placement. If your XODR
        includes other XY anchors (signals/objects), extend similarly.
        """
        R = np.asarray(transform["R"], dtype=np.float64)
        t = np.asarray(transform["t"], dtype=np.float64)
        s = float(transform.get("scale", 1.0))
        theta = float(transform.get("theta", 0.0))

        tree = ET.parse(in_xodr)
        root = tree.getroot()

        fmt = f"{{:.{precision}f}}"

        for geom in root.findall(".//geometry"):
            x = _safe_float(geom.get("x", "0.0"), 0.0)
            y = _safe_float(geom.get("y", "0.0"), 0.0)

            vec = np.array([x, y], dtype=np.float64)
            new_vec = (s * (R @ vec)) + t

            geom.set("x", fmt.format(new_vec[0]))
            geom.set("y", fmt.format(new_vec[1]))

            if adjust_hdg:
                hdg = _safe_float(geom.get("hdg", "0.0"), 0.0)
                geom.set("hdg", fmt.format(_wrap_angle(hdg + theta)))

        tree.write(out_xodr, encoding="utf-8", xml_declaration=True)
