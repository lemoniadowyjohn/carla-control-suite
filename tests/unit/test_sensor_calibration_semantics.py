import json
import math

import numpy as np
import pytest

from ultimate_pipeline.sensors.calibration_contract import (
    CALIBRATION_SEMANTICS,
    canonical_calib_path,
    effective_camera_intrinsics,
    rig_round_trip_check,
    validate_calibration_contract,
)


def _tiny_calib():
    return {
        "cameras": {
            "front": {
                "K": [[100.0, 0.0, 50.0], [0.0, 100.0, 25.0], [0.0, 0.0, 1.0]],
                "D": [1.0, 2.0, 3.0, 4.0],
                "K_undistortion": [
                    [200.0, 0.0, 80.0],
                    [0.0, 210.0, 45.0],
                    [0.0, 0.0, 1.0],
                ],
                "image_size": [400, 200],
                "cTv": [
                    [1.0, 0.0, 0.0, 1.0],
                    [0.0, 1.0, 0.0, 2.0],
                    [0.0, 0.0, 1.0, 3.0],
                    [0.0, 0.0, 0.0, 1.0],
                ],
            }
        },
        "lidars": {
            "middle": {
                "vTl": [
                    [1.0, 0.0, 0.0, 4.0],
                    [0.0, 1.0, 0.0, 0.0],
                    [0.0, 0.0, 1.0, 0.0],
                    [0.0, 0.0, 0.0, 1.0],
                ]
            }
        },
    }


def test_effective_camera_intrinsics_ignore_real_k_and_distortion():
    cam = _tiny_calib()["cameras"]["front"]
    effective = effective_camera_intrinsics(cam)

    assert effective["width_px"] == 400
    assert effective["height_px"] == 200
    assert effective["fx"] == pytest.approx(200.0)
    assert effective["fy"] == pytest.approx(210.0)
    assert effective["cx"] == pytest.approx(80.0)
    assert effective["cy"] == pytest.approx(45.0)
    assert effective["ignored_sources"] == ["K", "D"]
    assert effective["source"] == "K_undistortion_ideal_pinhole"
    assert effective["horizontal_fov_deg"] == pytest.approx(
        2.0 * math.degrees(math.atan(400.0 / (2.0 * 200.0)))
    )


def test_missing_k_undistortion_fails_closed():
    cam = _tiny_calib()["cameras"]["front"]
    cam.pop("K_undistortion")

    with pytest.raises(RuntimeError, match="K_undistortion"):
        effective_camera_intrinsics(cam)


def test_rig_round_trip_uses_ctv_direct_and_vtl_inverse(tmp_path):
    calib_path = tmp_path / "calib_data.json"
    calib_path.write_text(json.dumps(_tiny_calib()), encoding="utf-8")

    report = rig_round_trip_check(calib_path)

    assert report["verdict"] == "PASS"
    np.testing.assert_allclose(
        report["cameras"]["front"]["vehicle_to_camera_matrix"],
        _tiny_calib()["cameras"]["front"]["cTv"],
    )
    np.testing.assert_allclose(
        report["lidars"]["middle"]["vehicle_to_lidar_matrix"],
        np.linalg.inv(np.asarray(_tiny_calib()["lidars"]["middle"]["vTl"], dtype=float)),
    )


def test_canonical_calib_file_exists_and_validates():
    path = canonical_calib_path()

    assert path.exists()
    report = validate_calibration_contract(path)

    assert report["verdict"] == "PASS"
    assert report["calibration_semantics"] == CALIBRATION_SEMANTICS
    assert report["camera_count"] >= 1
    assert report["lidar_count"] >= 1
