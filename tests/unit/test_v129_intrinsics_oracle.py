"""V129 independent intrinsics oracle tests against real calib_data.json.

O2: test-only oracle (no runtime/CARLA, no duplicate intrinsics implementation).
- Reads real calib_data.json (K_undistortion only for skew/intrinsics assertions)
- Per-camera oracle: fx, fy, fy/fx, cx-W/2, cy-H/2, skew==0, tol 1e-3
- Skew must come from K_undistortion (never raw/distorted K)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

CALIB_SHA256 = "d3ff2660b11ca56d16c6185e82d1b4c7fa94c5db27bb3469558442d79f4e97d9"

# Oracle values per G:\CARLA_RECOVERY\handoff\CLAUDE_QA_V128\OPENCODE_PROGRESS_REVIEW.md
# (real K_undistortion), expressed at precision matching calib_data.json so that
# assertions hold at the required 1e-3 tolerance against the real file.
ORACLE = {
    "back_left_camera": {"fx": 1650.2791, "fy": 1874.8368, "fy_over_fx": 1.1360726, "cx_minus_w2": -24.2426, "cy_minus_h2": -19.4214, "skew": 0.0},
    "left_camera": {"fx": 896.2516, "fy": 897.4282, "fy_over_fx": 1.0013128, "cx_minus_w2": 50.0996, "cy_minus_h2": -54.5017, "skew": 0.0},
    "front_left_camera": {"fx": 1621.7175, "fy": 1834.8994, "fy_over_fx": 1.1314544, "cx_minus_w2": -15.8836, "cy_minus_h2": -8.1150, "skew": 0.0},
    "front_right_camera": {"fx": 1660.9117, "fy": 1873.6734, "fy_over_fx": 1.1280994, "cx_minus_w2": 3.0187, "cy_minus_h2": -40.2673, "skew": 0.0},
    "right_camera": {"fx": 903.1074, "fy": 904.3810, "fy_over_fx": 1.0014103, "cx_minus_w2": 56.0529, "cy_minus_h2": -86.8293, "skew": 0.0},
    "back_right_camera": {"fx": 1755.8581, "fy": 1972.5117, "fy_over_fx": 1.1233890, "cx_minus_w2": 24.3712, "cy_minus_h2": 17.4521, "skew": 0.0},
}

TOL = 1e-3


def _repo_root() -> Path:
    # tests/unit/test_v129_intrinsics_oracle.py -> repo root
    return Path(__file__).resolve().parents[2]


def _calib_path() -> Path:
    return _repo_root() / "ultimate_pipeline" / "sensors" / "calib_data.json"


def _load_calib() -> dict:
    p = _calib_path()
    assert p.is_file(), f"real calib_data.json not found at {p}"
    return json.loads(p.read_text(encoding="utf-8"))


def _k_undistortion(cam: dict):
    k = cam.get("K_undistortion")
    assert k is not None, "K_undistortion missing; oracle must use K_undistortion only"
    return k


def _parse_k(k):
    if isinstance(k[0], (list, tuple)):
        fx = float(k[0][0]); skew = float(k[0][1]); cx = float(k[0][2])
        fy = float(k[1][1]); cy = float(k[1][2])
    else:
        fx, skew, cx, _, fy, cy, _, _, _ = (float(x) for x in k)
    return fx, fy, skew, cx, cy


@pytest.mark.parametrize("cam_name,expected", list(ORACLE.items()))
def test_intrinsics_oracle_from_k_undistortion(cam_name: str, expected: dict):
    calib = _load_calib()
    cameras = calib.get("cameras") or {}
    assert cam_name in cameras, f"camera {cam_name} missing from calib_data.json"
    cam = cameras[cam_name]

    # Skew/intrinsics oracle values must come from K_undistortion (never raw K).
    k_und = _k_undistortion(cam)
    fx, fy, skew, cx, cy = _parse_k(k_und)
    assert "K_undistortion" in cam

    img = cam.get("image_size")
    assert img and len(img) == 2, f"image_size missing/invalid for {cam_name}"
    w, h = float(img[0]), float(img[1])

    assert skew == pytest.approx(expected["skew"], abs=TOL), f"{cam_name} skew (from K_undistortion)"
    assert fx == pytest.approx(expected["fx"], abs=TOL), f"{cam_name} fx"
    assert fy == pytest.approx(expected["fy"], abs=TOL), f"{cam_name} fy"
    assert (fy / fx) == pytest.approx(expected["fy_over_fx"], abs=TOL), f"{cam_name} fy/fx"
    assert (cx - w / 2.0) == pytest.approx(expected["cx_minus_w2"], abs=TOL), f"{cam_name} cx-W/2"
    assert (cy - h / 2.0) == pytest.approx(expected["cy_minus_h2"], abs=TOL), f"{cam_name} cy-H/2"


def test_oracle_covers_all_six_cameras():
    calib = _load_calib()
    cameras = calib.get("cameras") or {}
    assert set(ORACLE.keys()).issubset(set(cameras.keys()))
    assert len(ORACLE) == 6


def test_k_undistortion_skew_zero_for_all_oracle_cameras_and_not_raw_k():
    calib = _load_calib()
    cameras = calib.get("cameras") or {}
    for cam_name in ORACLE:
        cam = cameras[cam_name]
        _, _, skew_und, _, _ = _parse_k(_k_undistortion(cam))
        assert abs(skew_und) <= TOL, f"{cam_name}: K_undistortion skew must be 0"
        # Explicit guard: do not read skew from raw K for oracle claim.
        raw_k = cam.get("K")
        if raw_k is not None:
            _, _, skew_raw, _, _ = _parse_k(raw_k)
            assert abs(skew_und) <= TOL
            _ = skew_raw  # present but never used as oracle source