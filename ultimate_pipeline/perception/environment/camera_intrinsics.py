#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NEW-320 -- explicit camera intrinsic realization contract.

Scientific problem
-----------------
``calib_data.json`` stores ``K_undistortion`` = ``[[fx,0,cx],[0,fy,cy],[0,0,1]]``
per camera, and the repository describes native CARLA RGB frames as having
exactly that K.  That description is false.

CARLA's camera exposes only ``image_size_x``, ``image_size_y`` and a single
**horizontal** ``fov``.  Its native model is a square-pixel pinhole:

    fx = fy = (width / 2) / tan(fov_h / 2)
    cx = width / 2
    cy = height / 2

so ``fx_native`` is pinned to whatever ``fx`` the horizontal FOV was derived
from, while ``fy_native`` is forced equal to it and both principal points are
forced to the image centre.  Against the current calibration:

    back_left_camera   fy mismatch ~= -11.98 %
    front_left_camera  fy mismatch ~= -11.62 %
    front_right_camera fy mismatch ~= -11.36 %
    back_right_camera  fy mismatch ~= -10.98 %
    right_camera       principal point offset ~= +56 px (x) / -87 px (y)

This module makes that discrepancy explicit and governed rather than implicit.
For every camera it derives ``K_target``, ``K_native_carla``, ``delta_fx``,
``delta_fy``, ``delta_cx``, ``delta_cy`` and relative error percentages, then
selects exactly one realization strategy and records the residual.

Strategy
--------
``NATIVE_IDENTITY``
    ``K_native == K_target``; no remap needed.

``DETERMINISTIC_REMAP`` (preferred rigorous strategy)
    Render with a known CARLA-native pinhole camera, then apply a deterministic
    geometric remapping to the calibrated output K.  Because both intrinsics
    share one optical centre and no rotation, the target-pixel -> native-pixel
    map is the exact homography ``H = K_native @ inv(K_target)``.  Per-modality
    resampling policy is fixed and modality-appropriate.

``INTRINSICS_APPROXIMATION_BOUNDED``
    The residual could not be removed without unacceptable distortion or
    cropping (remap coverage below threshold).  The residual is quantified.
    This is explicitly NOT called exact calibration.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

REALIZATION_SCHEMA = "CAMERA_INTRINSIC_REALIZATION/v1"
INTRINSIC_REALIZATION_FILENAME = "camera_intrinsic_realization.json"

STRATEGY_NATIVE_IDENTITY = "NATIVE_IDENTITY"
STRATEGY_DETERMINISTIC_REMAP = "DETERMINISTIC_REMAP"
STRATEGY_BOUNDED_APPROXIMATION = "INTRINSICS_APPROXIMATION_BOUNDED"

#: Minimum fraction of target pixels that must map inside the native image for
#: a ``DETERMINISTIC_REMAP`` claim.  Below this we declare a bounded
#: approximation instead of pretending exactness.
DEFAULT_MIN_REMAP_COVERAGE = 0.999

#: Per-modality resampling policy.  Labels are NEVER interpolated: bilinear
#: blending of two class ids invents a class id that does not exist.
REMAP_POLICIES: Dict[str, str] = {
    "rgb": "BILINEAR_CONTINUOUS",
    "semantic_seg": "NEAREST_NEIGHBOR_ONLY",
    "instance_seg": "NEAREST_NEIGHBOR_ONLY",
    "depth": "NEAREST_NEIGHBOR_RANGE_PRESERVING",
    "flow": "NEAREST_NEIGHBOR_ONLY",
}

#: Modalities that must never use continuous interpolation.
LABEL_MODALITIES: Tuple[str, ...] = ("semantic_seg", "instance_seg")

#: Maximum pixel-level scale change tolerated before a strategy is downgraded.
DEFAULT_MAX_PIXEL_SCALE_CHANGE = 2.0


def _round6(value: float) -> float:
    return round(float(value), 6)


# ---------------------------------------------------------------------------
# Native CARLA pinhole model
# ---------------------------------------------------------------------------


def horizontal_fov_from_fx(fx: float, width_px: int) -> float:
    """Horizontal FOV that a square-pixel pinhole with ``fx`` implies."""
    if float(fx) <= 1e-9:
        raise ValueError(f"invalid_fx:{fx}")
    return 2.0 * math.degrees(math.atan(float(width_px) / (2.0 * float(fx))))


def native_carla_intrinsics(width_px: int, height_px: int, fov_deg: float) -> Dict[str, Any]:
    """The K matrix a CARLA RGB camera actually realises.

    Square-pixel pinhole driven purely by the horizontal FOV: fx == fy and the
    principal point is the exact image centre.
    """
    w = int(width_px)
    h = int(height_px)
    f = float(fov_deg)
    if w <= 0 or h <= 0:
        raise ValueError(f"invalid_image_size:{w}x{h}")
    if not (0.0 < f < 180.0):
        raise ValueError(f"invalid_fov:{f}")
    focal = (w / 2.0) / math.tan(math.radians(f) / 2.0)
    cx = w / 2.0
    cy = h / 2.0
    return {
        "K": [[focal, 0.0, cx], [0.0, focal, cy], [0.0, 0.0, 1.0]],
        "fx": focal,
        "fy": focal,
        "cx": cx,
        "cy": cy,
        "width_px": w,
        "height_px": h,
        "horizontal_fov_deg": f,
        "model": "carla_native_square_pixel_pinhole_horizontal_fov",
    }


def parse_image_size(value: Any) -> Tuple[int, int]:
    if isinstance(value, Mapping):
        return int(value["width"]), int(value["height"])
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return int(value[0]), int(value[1])
    raise ValueError(f"unsupported_image_size:{value!r}")


def transform_intrinsics_for_image_ops(
    k_matrix: Any,
    source_size: Sequence[int],
    *,
    resize_size: Optional[Sequence[int]] = None,
    crop_xyxy: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    """Transport K through resize and crop using pixel-centre geometry.

    Resize follows the common half-pixel sampling convention:
    ``u' = sx * (u + 0.5) - 0.5`` (and likewise for ``v``).  Cropping is then
    applied in resized-image coordinates.  The returned matrix is the K that
    belongs to the final pixels; callers must not reuse the original K after
    either operation.
    """
    k = as_k_matrix(k_matrix, "K")
    if not np.isfinite(k).all() or abs(float(np.linalg.det(k))) < 1e-12:
        raise ValueError("K_must_be_finite_and_invertible")
    src_w, src_h = (int(source_size[0]), int(source_size[1]))
    if src_w <= 0 or src_h <= 0:
        raise ValueError(f"invalid_source_size:{src_w}x{src_h}")
    if resize_size is None:
        resized_w, resized_h = src_w, src_h
    else:
        resized_w, resized_h = int(resize_size[0]), int(resize_size[1])
    if resized_w <= 0 or resized_h <= 0:
        raise ValueError(f"invalid_resize_size:{resized_w}x{resized_h}")

    sx = resized_w / float(src_w)
    sy = resized_h / float(src_h)
    resize_transform = np.asarray(
        [[sx, 0.0, 0.5 * sx - 0.5],
         [0.0, sy, 0.5 * sy - 0.5],
         [0.0, 0.0, 1.0]], dtype=float
    )
    pixel_transform = resize_transform
    transformed = pixel_transform @ k
    crop = None
    final_w, final_h = resized_w, resized_h
    if crop_xyxy is not None:
        if len(crop_xyxy) != 4:
            raise ValueError("crop_xyxy_must_have_four_values")
        x0, y0, x1, y1 = (int(v) for v in crop_xyxy)
        if not (0 <= x0 < x1 <= resized_w and 0 <= y0 < y1 <= resized_h):
            raise ValueError(
                f"crop_out_of_bounds:{x0},{y0},{x1},{y1}:{resized_w}x{resized_h}"
            )
        crop_transform = np.asarray(
            [[1.0, 0.0, -float(x0)],
             [0.0, 1.0, -float(y0)],
             [0.0, 0.0, 1.0]], dtype=float
        )
        pixel_transform = crop_transform @ pixel_transform
        transformed = pixel_transform @ k
        crop = [x0, y0, x1, y1]
        final_w, final_h = x1 - x0, y1 - y0

    return {
        "K": [[float(v) for v in row] for row in transformed],
        "source_size": [src_w, src_h],
        "resized_size": [resized_w, resized_h],
        "crop_xyxy": crop,
        "output_size": [final_w, final_h],
        "pixel_coordinate_convention": "half_pixel_resize_then_integer_origin_crop",
        "pixel_transform": [
            [float(v) for v in row] for row in pixel_transform
        ],
    }


def as_k_matrix(value: Any, name: str = "K") -> np.ndarray:
    mat = np.asarray(value, dtype=float)
    if mat.shape != (3, 3):
        raise ValueError(f"{name}_must_be_3x3:{mat.shape}")
    return mat


def project_camera_point(k_matrix: Any, point_camera: Sequence[float]) -> Tuple[float, float]:
    """Project a camera-frame 3D point through the full 3x3 intrinsic matrix."""
    k = as_k_matrix(k_matrix)
    point = np.asarray([float(v) for v in point_camera[:3]], dtype=float)
    if point.shape != (3,) or not np.isfinite(point).all() or point[2] <= 1e-9:
        raise ValueError("point_must_be_finite_and_in_front_of_camera")
    pixel = k @ point
    if not np.isfinite(pixel).all() or abs(float(pixel[2])) <= 1e-12:
        raise ValueError("projected_pixel_invalid")
    return float(pixel[0] / pixel[2]), float(pixel[1] / pixel[2])


def unproject_camera_pixel(
    k_matrix: Any, pixel_uv: Sequence[float], *, optical_axis_depth: float
) -> Tuple[float, float, float]:
    """Unproject a pixel to a point whose camera-z equals the supplied depth."""
    k = as_k_matrix(k_matrix)
    u, v = float(pixel_uv[0]), float(pixel_uv[1])
    depth = float(optical_axis_depth)
    if not np.isfinite([u, v, depth]).all() or depth <= 0:
        raise ValueError("pixel_and_depth_must_be_finite_with_positive_depth")
    ray = np.linalg.inv(k) @ np.asarray([u, v, 1.0], dtype=float)
    if abs(float(ray[2])) <= 1e-12:
        raise ValueError("unprojected_ray_parallel_to_image_plane")
    point = ray * (depth / float(ray[2]))
    return tuple(float(v) for v in point)


# ---------------------------------------------------------------------------
# Per-camera realization
# ---------------------------------------------------------------------------


def camera_intrinsic_realization(
    camera_name: str,
    k_target_value: Any,
    width_px: int,
    height_px: int,
    *,
    fov_deg: Optional[float] = None,
    min_coverage: float = DEFAULT_MIN_REMAP_COVERAGE,
    max_pixel_scale_change: float = DEFAULT_MAX_PIXEL_SCALE_CHANGE,
    k_override: Any = None,
) -> Dict[str, Any]:
    """Derive the governed realization for one camera.

    ``fov_deg`` defaults to the FOV implied by ``K_target.fx`` -- which is what
    the production rig actually configures -- so the derived ``K_native`` is
    the honest description of the rendered frames.
    """
    k_target = as_k_matrix(k_target_value, f"{camera_name}.K_target")
    w = int(width_px)
    h = int(height_px)

    fx_t = float(k_target[0, 0])
    fy_t = float(k_target[1, 1])
    cx_t = float(k_target[0, 2])
    cy_t = float(k_target[1, 2])

    fov = float(fov_deg) if fov_deg is not None else horizontal_fov_from_fx(fx_t, w)
    native = native_carla_intrinsics(w, h, fov)

    k_native = (
        as_k_matrix(k_override, f"{camera_name}.K_native_carla")
        if k_override is not None
        else np.asarray(native["K"], dtype=float)
    )
    fx_n = float(k_native[0, 0])
    fy_n = float(k_native[1, 1])
    cx_n = float(k_native[0, 2])
    cy_n = float(k_native[1, 2])

    def _rel(a: float, b: float) -> Optional[float]:
        denom = float(b)
        if abs(denom) < 1e-9:
            return None
        return _round6((float(a) - denom) / denom * 100.0)

    deltas = {
        "delta_fx": _round6(fx_n - fx_t),
        "delta_fy": _round6(fy_n - fy_t),
        "delta_cx": _round6(cx_n - cx_t),
        "delta_cy": _round6(cy_n - cy_t),
    }
    rel_errors = {
        "fx_relative_error_pct": _rel(fx_n, fx_t),
        "fy_relative_error_pct": _rel(fy_n, fy_t),
        "cx_relative_error_pct": _rel(cx_n, cx_t),
        "cy_relative_error_pct": _rel(cy_n, cy_t),
    }

    homography, _ = target_to_native_mapping(k_target, k_native)
    mapping = build_mapping_meta(k_target, k_native, w, h)

    identity = (
        abs(deltas["delta_fx"]) < 1e-6
        and abs(deltas["delta_fy"]) < 1e-6
        and abs(deltas["delta_cx"]) < 1e-6
        and abs(deltas["delta_cy"]) < 1e-6
    )

    strategy = STRATEGY_NATIVE_IDENTITY
    residual_note = "native_intrinsics_match_target_exactly"
    bounded_reason: Optional[str] = None
    crop: Dict[str, Any] = mapping.get("observable_crop") or {}
    unobservable_px: int = int(mapping.get("invalid_pixel_count", 0))

    if not identity:
        coverage = float(mapping["coverage_fraction"])
        scale = float(mapping["max_pixel_scale_change"])
        if coverage < float(min_coverage):
            strategy = STRATEGY_BOUNDED_APPROXIMATION
            bounded_reason = (
                f"remap_coverage_below_threshold:{_round6(coverage)}"
                f"<{_round6(float(min_coverage))}"
            )
            if crop.get("exact_K_realizable_on_crop"):
                residual_note = (
                    "exact_K_realizable_only_on_cropped_field_of_view:"
                    f"{crop['width_px']}x{crop['height_px']}px"
                )
        elif scale > float(max_pixel_scale_change):
            strategy = STRATEGY_BOUNDED_APPROXIMATION
            bounded_reason = (
                f"pixel_scale_change_exceeds_bound:{_round6(scale)}"
                f">{_round6(float(max_pixel_scale_change))}"
            )
        else:
            strategy = STRATEGY_DETERMINISTIC_REMAP
            residual_note = "exact_homographic_realization_no_residual"

    residual = {
        "rmse_fx_px": abs(deltas["delta_fx"]),
        "rmse_fy_px": abs(deltas["delta_fy"]),
        "rmse_cx_px": abs(deltas["delta_cx"]),
        "rmse_cy_px": abs(deltas["delta_cy"]),
        "max_abs_delta_px": _round6(
            max(abs(v) for v in deltas.values())
        ),
        "note": residual_note,
        "unobservable_target_pixels": unobservable_px,
        "observable_crop": crop,
    }

    return {
        "camera": str(camera_name),
        "schema": REALIZATION_SCHEMA,
        "width_px": w,
        "height_px": h,
        "configured_horizontal_fov_deg": _round6(fov),
        "K_target": [[float(v) for v in row] for row in k_target],
        "K_native_carla": [[float(v) for v in row] for row in k_native],
        "target": {"fx": fx_t, "fy": fy_t, "cx": cx_t, "cy": cy_t},
        "native": {"fx": fx_n, "fy": fy_n, "cx": cx_n, "cy": cy_n},
        **deltas,
        **rel_errors,
        "strategy": strategy,
        "bounded_reason": bounded_reason,
        "remap_required": strategy == STRATEGY_DETERMINISTIC_REMAP,
        "mapping": mapping,
        "residual": residual,
        "remap_policies": dict(REMAP_POLICIES),
        "geometric_realization_exact": strategy == STRATEGY_DETERMINISTIC_REMAP,
        "exact_calibration_claim": False,
        "claim_scope": "NUMERICAL_MAPPING_ONLY_LIVE_RENDERED_FRAMES_NOT_INDEPENDENTLY_VERIFIED",
    }


# ---------------------------------------------------------------------------
# Deterministic geometric remapping
# ---------------------------------------------------------------------------


def target_to_native_mapping(
    k_target: Any, k_native: Any
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Exact target-pixel -> native-pixel homography plus coverage evidence.

    Both intrinsics describe the same optical centre and the same optical axis,
    so a ray for target pixel ``p_t`` is ``d = inv(K_target) p_t`` and the same
    ray lands in the native image at ``K_native d``.  Composing gives
    ``H = K_native @ inv(K_target)``.

    Coverage is the fraction of target pixels whose native image lands inside
    the native domain.  Anything outside is **extrapolation** and is reported
    as invalid, never hidden.
    """
    kt = as_k_matrix(k_target, "K_target")
    kn = as_k_matrix(k_native, "K_native_carla")

    homography = kn @ np.linalg.inv(kt)

    mapping_meta = {
        "schema": "CAMERA_REMAP_MAPPING/v1",
        "homography": [[float(v) for v in row] for row in homography],
        "remap_semantics": "H maps homogeneous TARGET pixel coords to NATIVE pixel coords",
        "extrapolation_policy": "forbidden_targets_outside_native_domain_are_masked_invalid",
        "no_hidden_extrapolation": True,
        "homography_sha256": "",
        "coverage_fraction": None,
        "max_pixel_scale_change": None,
    }
    return homography, mapping_meta


def compute_remap_grid(
    k_target: Any,
    k_native: Any,
    width_px: int,
    height_px: int,
) -> Dict[str, Any]:
    """Full remap grid: source coordinates, validity mask and coverage.

    Returns integer source indices (``src_u``/``src_v``) plus a boolean
    ``valid`` mask.  ``valid`` is False wherever the required native pixel is
    outside the native image -- those target pixels simply have no observation.
    """
    kt = as_k_matrix(k_target, "K_target")
    kn = as_k_matrix(k_native, "K_native_carla")
    homography = kn @ np.linalg.inv(kt)

    w = int(width_px)
    h = int(height_px)
    native_w = int(round(float(kn[0, 2]) * 2.0))
    native_h = int(round(float(kn[1, 2]) * 2.0))

    u, v = np.meshgrid(
        np.arange(w, dtype=float), np.arange(h, dtype=float), indexing="xy"
    )
    ones = np.ones_like(u)
    pts = np.stack([u.ravel(), v.ravel(), ones.ravel()], axis=0)
    src = homography @ pts
    with np.errstate(divide="ignore", invalid="ignore"):
        z = src[2]
        su = np.where(z != 0, src[0] / z, np.inf)
        sv = np.where(z != 0, src[1] / z, np.inf)
    su = su.reshape(h, w)
    sv = sv.reshape(h, w)

    finite = np.isfinite(su) & np.isfinite(sv)
    inside = finite & (su >= 0.0) & (su <= (native_w - 1)) & (sv >= 0.0) & (sv <= (native_h - 1))
    valid = inside

    src_u = np.where(finite, np.clip(np.round(su), 0, max(0, native_w - 1)), 0).astype(np.int64)
    src_v = np.where(finite, np.clip(np.round(sv), 0, max(0, native_h - 1)), 0).astype(np.int64)

    du = np.abs(np.diff(su, axis=1)) if w > 1 else np.zeros((h, 1))
    dv = np.abs(np.diff(sv, axis=0)) if h > 1 else np.zeros((1, w))
    step = float(max(np.max(du) if du.size else 0.0, np.max(dv) if dv.size else 0.0))

    coverage = float(np.count_nonzero(valid)) / float(max(1, w * h))

    # Exact region of the target image that IS observable: the bounding box of
    # the valid mask.  When every pixel inside that box is valid, the target K
    # is exactly realizable on the crop (at reduced field of view).
    crop = None
    if bool(valid.any()):
        rows = np.where(valid.any(axis=1))[0]
        cols = np.where(valid.any(axis=0))[0]
        if rows.size and cols.size:
            u0, u1 = int(cols[0]), int(cols[-1]) + 1
            v0, v1 = int(rows[0]), int(rows[-1]) + 1
            inside_full = bool(valid[v0:v1, u0:u1].all())
            crop = {
                "target_u0": u0,
                "target_u1": u1,
                "target_v0": v0,
                "target_v1": v1,
                "width_px": u1 - u0,
                "height_px": v1 - v0,
                "all_pixels_observable": inside_full,
                "crop_area_fraction": _round6(
                    float((u1 - u0) * (v1 - v0)) / float(max(1, w * h))
                ),
                "exact_K_realizable_on_crop": inside_full,
            }

    return {
        "schema": "CAMERA_REMAP_GRID/v1",
        "width_px": w,
        "height_px": h,
        "native_width_px": native_w,
        "native_height_px": native_h,
        "K_target": [[float(x) for x in row] for row in kt],
        "K_native_carla": [[float(x) for x in row] for row in kn],
        "homography": [[float(x) for x in row] for row in homography],
        "src_u": src_u,
        "src_v": src_v,
        "src_u_float": np.where(finite, su, 0.0),
        "src_v_float": np.where(finite, sv, 0.0),
        "valid": valid,
        "coverage_fraction": _round6(coverage),
        "invalid_pixel_count": int(np.count_nonzero(~valid)),
        "observable_crop": crop,
        "max_pixel_scale_change": _round6(step),
        "policies": dict(REMAP_POLICIES),
    }


def build_mapping_meta(
    k_target: Any,
    k_native: Any,
    width_px: int,
    height_px: int,
) -> Dict[str, Any]:
    """Serializable mapping identity/digest evidence (no pixel arrays)."""
    kt = as_k_matrix(k_target, "K_target")
    kn = as_k_matrix(k_native, "K_native_carla")
    homography = kn @ np.linalg.inv(kt)
    grid_meta = compute_remap_grid(kt, kn, width_px, height_px)
    payload = {
        "schema": "CAMERA_REMAP_MAPPING/v1",
        "width_px": int(width_px),
        "height_px": int(height_px),
        "homography": [[_round6(x) for x in row] for row in homography],
        "remap_semantics": "H maps homogeneous TARGET pixel coords to NATIVE pixel coords",
        "extrapolation_policy": "forbidden_targets_outside_native_domain_are_masked_invalid",
        "no_hidden_extrapolation": True,
        "coverage_fraction": grid_meta["coverage_fraction"],
        "invalid_pixel_count": grid_meta["invalid_pixel_count"],
        "observable_crop": grid_meta["observable_crop"],
        "max_pixel_scale_change": grid_meta["max_pixel_scale_change"],
        "policies": dict(REMAP_POLICIES),
        "interpolation": "BILINEAR_CONTINUOUS",
    }
    import hashlib
    import json as _json

    payload["mapping_sha256"] = hashlib.sha256(
        _json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


# ---------------------------------------------------------------------------
# Modality-aware resampling
# ---------------------------------------------------------------------------


def apply_remap(
    source: np.ndarray,
    grid: Mapping[str, Any],
    modality: str,
    *,
    interpolation: Optional[str] = None,
    invalid_value: float = 0.0,
) -> np.ndarray:
    """Single governed entry point for deterministic intrinsic remapping.

    ``interpolation`` is resolved from :data:`REMAP_POLICIES` for the modality.
    If a caller *explicitly* requests an interpolation that contradicts the
    policy -- most importantly bilinear on a label map -- this raises.  That is
    the enforcement point for "semantic remap never uses bilinear": blending two
    class ids would invent a class id that does not exist in the scene.
    """
    policy = REMAP_POLICIES.get(str(modality))
    if policy is None:
        raise ValueError(f"unknown_remap_modality:{modality}")
    if str(modality) in LABEL_MODALITIES:
        if interpolation is not None and str(interpolation).upper() not in (
            "NEAREST", "NEAREST_NEIGHBOR", "NEAREST_NEIGHBOR_ONLY",
        ):
            raise ValueError(
                f"label_modality_forbids_interpolation:{modality}:{interpolation}"
            )
    elif interpolation is not None and str(interpolation).upper() != "BILINEAR":
        raise ValueError(
            f"continuous_modality_requires_bilinear:{modality}:{interpolation}"
        )

    if policy == "NEAREST_NEIGHBOR_ONLY" or policy == "NEAREST_NEIGHBOR_RANGE_PRESERVING":
        out = _nearest(source, grid)
    else:
        out = _bilinear(source, grid)
    # The validity mask is authoritative.  Fill out-of-domain samples as well
    # as returning the mask so a consumer that accidentally drops the mask
    # cannot mistake clipped edge pixels for observations.
    valid = np.asarray(grid["valid"], dtype=bool)
    fill = np.asarray(invalid_value, dtype=out.dtype)
    if out.ndim == 3:
        fill = np.full((out.shape[2],), invalid_value, dtype=out.dtype)
        valid = valid[..., None]
    return np.where(valid, out, fill)


def remap_labels(source: np.ndarray, grid: Mapping[str, Any], modality: str,
                 *, interpolation: Optional[str] = None) -> np.ndarray:
    """Nearest-neighbour resample for a label/id modality (NEW-320)."""
    return apply_remap(source, grid, modality, interpolation=interpolation)


def remap_depth(source: np.ndarray, grid: Mapping[str, Any], *,
                invalid_value: float = 0.0) -> np.ndarray:
    """Depth-aware, geometry-preserving resample.

    The remap is a homography in image space with an unchanged optical centre,
    so the *ray* through a target pixel is identical to the ray through its
    native source pixel.  Range is measured along that ray, so the depth value
    is invariant and nearest-neighbour selection is exact rather than an
    approximation.  Unobserved target pixels are filled with ``invalid_value``;
    nothing is extrapolated.
    """
    return apply_remap(source, grid, "depth", invalid_value=invalid_value)


def remap_rgb(source: np.ndarray, grid: Mapping[str, Any]) -> np.ndarray:
    """Continuous bilinear resample for photometric data."""
    return apply_remap(source, grid, "rgb")


def _nearest(source: np.ndarray, grid: Mapping[str, Any]) -> np.ndarray:
    src = np.asarray(source)
    src_u = np.asarray(grid["src_u"])
    src_v = np.asarray(grid["src_v"])
    return src[src_v, src_u]


def _bilinear(source: np.ndarray, grid: Mapping[str, Any]) -> np.ndarray:
    src = np.asarray(source, dtype=np.float64)
    su = np.asarray(grid["src_u_float"], dtype=np.float64)
    sv = np.asarray(grid["src_v_float"], dtype=np.float64)
    native_h, native_w = src.shape[0], src.shape[1]

    u0 = np.floor(su).astype(np.int64)
    v0 = np.floor(sv).astype(np.int64)
    du = su - u0
    dv = sv - v0

    u0c = np.clip(u0, 0, native_w - 1)
    u1c = np.clip(u0 + 1, 0, native_w - 1)
    v0c = np.clip(v0, 0, native_h - 1)
    v1c = np.clip(v0 + 1, 0, native_h - 1)

    p00 = src[v0c, u0c].astype(np.float64)
    p01 = src[v0c, u1c].astype(np.float64)
    p10 = src[v1c, u0c].astype(np.float64)
    p11 = src[v1c, u1c].astype(np.float64)

    du = du[..., None] if src.ndim == 3 else du
    dv = dv[..., None] if src.ndim == 3 else dv
    top = p00 * (1.0 - du) + p01 * du
    bot = p10 * (1.0 - du) + p11 * du
    return top * (1.0 - dv) + bot * dv


# ---------------------------------------------------------------------------
# Realization report over a whole calibration file
# ---------------------------------------------------------------------------


def realization_report(
    calib_data: Mapping[str, Any],
    *,
    front_only: bool = False,
    fov_policy: str = "derive_from_target_fx",
    min_coverage: float = DEFAULT_MIN_REMAP_COVERAGE,
) -> Dict[str, Any]:
    """Realization report for every camera in a calibration file.

    ``fov_policy='derive_from_target_fx'`` reproduces exactly what the
    production rig configures today.  ``'force_square_pixel'`` instead configures
    the FOV so that ``fy_native == fy_target`` (at the cost of a horizontal FOV
    error) and is provided for comparison.
    """
    cameras = dict(calib_data.get("cameras") or {})
    entries: List[Dict[str, Any]] = []

    for name in sorted(cameras):
        cam = cameras[name]
        if front_only and "front" not in str(name).lower():
            continue
        k_target = cam.get("K_undistortion")
        if k_target is None:
            entries.append(
                {
                    "camera": str(name),
                    "schema": REALIZATION_SCHEMA,
                    "strategy": None,
                    "error": "K_undistortion_missing",
                }
            )
            continue
        try:
            width, height = parse_image_size(cam.get("image_size", [1920, 1080]))
            kt = as_k_matrix(k_target, f"{name}.K_undistortion")
        except Exception as exc:
            entries.append(
                {
                    "camera": str(name),
                    "schema": REALIZATION_SCHEMA,
                    "strategy": None,
                    "error": f"{type(exc).__name__}:{exc}",
                }
            )
            continue

        if fov_policy == "derive_from_target_fx":
            fov = None
        elif fov_policy == "force_square_pixel":
            fov = horizontal_fov_from_fx(float(kt[1, 1]), width)
        else:
            raise ValueError(f"unknown_fov_policy:{fov_policy}")

        entry = camera_intrinsic_realization(
            str(name), kt, width, height,
            fov_deg=fov, min_coverage=min_coverage,
        )
        native = as_k_matrix(entry["K_native_carla"], "K_native_carla")
        entry["mapping"] = build_mapping_meta(kt, native, width, height)
        entries.append(entry)

    strategies: Dict[str, int] = {}
    for entry in entries:
        key = str(entry.get("strategy"))
        strategies[key] = strategies.get(key, 0) + 1

    exact = all(
        e.get("strategy") in (STRATEGY_NATIVE_IDENTITY, STRATEGY_DETERMINISTIC_REMAP)
        for e in entries
    ) and bool(entries)

    return {
        "schema": REALIZATION_SCHEMA,
        "fov_policy": fov_policy,
        "camera_count": len(entries),
        "cameras": entries,
        "strategy_counts": strategies,
        "exact_realization": bool(exact),
        "geometric_realization_exact": bool(exact),
        "exact_intrinsic_compliance": False,
        "live_acceptance": "PENDING_INDEPENDENT_RENDERED_FRAME_VERIFICATION",
        "requires_deterministic_remap": any(
            e.get("strategy") == STRATEGY_DETERMINISTIC_REMAP for e in entries
        ),
        "bounded_approximations": [
            e["camera"] for e in entries
            if e.get("strategy") == STRATEGY_BOUNDED_APPROXIMATION
        ],
        "legacy_claim_withdrawn": (
            "native CARLA frames are NOT K_undistortion; see per-camera "
            "delta_fy / delta_cx / delta_cy"
        ),
    }


def realization_report_for_sizes(
    calib_data: Mapping[str, Any],
    image_sizes: Optional[Mapping[str, Sequence[int]]] = None,
    *,
    fov_policy: str = "derive_from_target_fx",
    min_coverage: float = DEFAULT_MIN_REMAP_COVERAGE,
) -> Dict[str, Any]:
    """Report all cameras at their actual selected output resolutions.

    Overrides are interpreted as resize operations from the calibration's
    declared image size, so K is transported with the same half-pixel rule as
    an actual image resize.  This prevents runtime resolution clamps from
    silently retaining a full-resolution K.
    """
    overrides = dict(image_sizes or {})
    cameras: Dict[str, Any] = {}
    original_cameras = dict(calib_data.get("cameras") or {})
    unknown = set(overrides) - set(original_cameras)
    if unknown:
        raise ValueError(f"image_size_override_unknown_cameras:{sorted(unknown)}")
    for name, source in original_cameras.items():
        cam = dict(source)
        source_w, source_h = parse_image_size(cam.get("image_size", [1920, 1080]))
        chosen = overrides.get(str(name), (source_w, source_h))
        out_w, out_h = int(chosen[0]), int(chosen[1])
        if out_w <= 0 or out_h <= 0:
            raise ValueError(f"invalid_image_size_override:{name}:{out_w}x{out_h}")
        if cam.get("K_undistortion") is None:
            cam["image_size"] = [out_w, out_h]
            cam["source_image_size"] = [source_w, source_h]
            cam["image_operation_contract"] = None
            cameras[str(name)] = cam
            continue
        transformed = transform_intrinsics_for_image_ops(
            cam["K_undistortion"], (source_w, source_h), resize_size=(out_w, out_h)
        )
        cam["K_undistortion"] = transformed["K"]
        cam["image_size"] = [out_w, out_h]
        cam["source_image_size"] = [source_w, source_h]
        cam["image_operation_contract"] = transformed
        cameras[str(name)] = cam

    report = realization_report(
        {"cameras": cameras}, fov_policy=fov_policy, min_coverage=min_coverage
    )
    for entry in report["cameras"]:
        cam = cameras[entry["camera"]]
        entry["source_image_size"] = cam["source_image_size"]
        entry["image_operation_contract"] = cam["image_operation_contract"]
        if entry.get("strategy") is None:
            continue
        entry["effective_K_if_native_output"] = entry["K_native_carla"]
        entry["effective_K_if_deterministically_remapped"] = entry["K_target"]
        entry["valid_image_mask_required_for_remap"] = bool(entry["remap_required"])
    report["image_size_overrides"] = {
        name: [int(size[0]), int(size[1])] for name, size in sorted(overrides.items())
    }
    report["override_scaling_contract"] = "half_pixel_resize_then_integer_origin_crop"
    return report


def write_effective_intrinsics_artifacts(
    output_dir: str,
    realization: Mapping[str, Any],
    *,
    remap_applied: bool,
) -> Dict[str, Any]:
    """Export the effective K and the exact valid-pixel mask for one camera.

    The exported K describes the pixels in the output artifact: native K when
    no remap was applied, requested K when the deterministic remap was applied.
    The mask is always written, including an all-valid mask for native output.
    """
    import hashlib
    import io
    import json
    from pathlib import Path

    camera = str(realization.get("camera") or "")
    if not camera or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in camera):
        raise ValueError("invalid_camera_name_for_artifact")
    width, height = int(realization["width_px"]), int(realization["height_px"])
    if remap_applied:
        if realization.get("strategy") == STRATEGY_NATIVE_IDENTITY:
            valid = np.ones((height, width), dtype=bool)
        else:
            grid = compute_remap_grid(
                realization["K_target"], realization["K_native_carla"], width, height
            )
            valid = np.asarray(grid["valid"], dtype=bool)
        effective_k = realization["K_target"]
        stage = "DETERMINISTIC_REMAP_APPLIED"
    else:
        valid = np.ones((height, width), dtype=bool)
        effective_k = realization["K_native_carla"]
        stage = "NATIVE_CARLA_RENDER"

    buffer = io.BytesIO()
    np.save(buffer, valid.astype(np.uint8), allow_pickle=False)
    mask_bytes = buffer.getvalue()
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    mask_path = root / f"{camera}_valid_mask.npy"
    mask_path.write_bytes(mask_bytes)
    payload = {
        "schema": "EFFECTIVE_CAMERA_INTRINSICS/v1",
        "camera": camera,
        "width_px": width,
        "height_px": height,
        "K_effective": [[float(v) for v in row] for row in effective_k],
        "effective_stage": stage,
        "requested_K_target": realization["K_target"],
        "K_native_carla": realization["K_native_carla"],
        "strategy": realization.get("strategy"),
        "geometric_full_frame_match": bool(
            realization.get("strategy") == STRATEGY_NATIVE_IDENTITY
            or (remap_applied and realization.get("mapping", {}).get("coverage_fraction") == 1.0)
        ),
        "exact_intrinsic_compliance": False,
        "independent_rendered_frame_verification": "PENDING",
        "valid_image_mask": {
            "path": mask_path.name,
            "encoding": "NumPy uint8, 1=observed and 0=invalid",
            "size_bytes": len(mask_bytes),
            "sha256": hashlib.sha256(mask_bytes).hexdigest(),
            "valid_pixel_count": int(np.count_nonzero(valid)),
            "invalid_pixel_count": int(valid.size - np.count_nonzero(valid)),
        },
    }
    payload["effective_intrinsics_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    meta_path = root / f"{camera}_effective_intrinsics.json"
    meta_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload
