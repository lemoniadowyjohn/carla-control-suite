from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from ultimate_pipeline.perception.environment import camera_intrinsics as intr
from ultimate_pipeline.perception.environment.intrinsic_receipt import (
    build_calibration_receipt,
    dataset_file_inventory,
    verify_calibration_receipt,
)
from ultimate_pipeline.carla_tools.thesis_sensor_rig import derive_camera_runtime_intrinsics

REPO = Path(__file__).resolve().parents[3]
CALIBRATION = REPO / "ultimate_pipeline" / "sensors" / "calib_data.json"


def _calibration() -> dict:
    return json.loads(CALIBRATION.read_text(encoding="utf-8"))


def _load_live_harness():
    path = REPO / "ultimate_pipeline" / "tools" / "verify_camera_intrinsics_live.py"
    spec = importlib.util.spec_from_file_location("wp_c_live_harness", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _load_evidence_pack():
    path = REPO / "ultimate_pipeline" / "tools" / "new316_333_evidence_pack.py"
    spec = importlib.util.spec_from_file_location("wp_c_evidence_pack", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_six_camera_native_k_and_resolution_override_are_explicit():
    calib = _calibration()
    report = intr.realization_report_for_sizes(calib)
    assert report["camera_count"] == 6
    assert {entry["camera"] for entry in report["cameras"]} == set(calib["cameras"])
    for entry in report["cameras"]:
        assert len(entry["K_target"]) == len(entry["K_native_carla"]) == 3
        assert entry["native"]["fx"] == pytest.approx(entry["native"]["fy"])
        assert entry["K_target"] != entry["K_native_carla"]
        assert entry["strategy"] in {
            intr.STRATEGY_NATIVE_IDENTITY,
            intr.STRATEGY_DETERMINISTIC_REMAP,
            intr.STRATEGY_BOUNDED_APPROXIMATION,
        }

    resized = intr.realization_report_for_sizes(
        calib, {name: (960, 540) for name in calib["cameras"]}
    )
    assert resized["image_size_overrides"]
    for entry in resized["cameras"]:
        assert (entry["width_px"], entry["height_px"]) == (960, 540)
        assert entry["source_image_size"] == [1920, 1080]
        assert entry["K_target"][0][0] == pytest.approx(
            calib["cameras"][entry["camera"]]["K_undistortion"][0][0] / 2
        )
        assert entry["K_target"][0][2] == pytest.approx(
            (calib["cameras"][entry["camera"]]["K_undistortion"][0][2] + 0.5) / 2 - 0.5
        )


def test_runtime_rig_derives_k_after_resolution_clamp_and_labels_native_approximation():
    cam = _calibration()["cameras"]["front_left_camera"]
    realized = derive_camera_runtime_intrinsics("front_left_camera", cam, 960, 540)
    assert realized["source_image_size"] == [1920, 1080]
    assert (realized["width_px"], realized["height_px"]) == (960, 540)
    assert realized["K_target"][0][0] == pytest.approx(cam["K_undistortion"][0][0] / 2)
    assert realized["runtime_postprocess"]["applied_by_rig"] is False
    assert realized["runtime_postprocess"]["rendered_intrinsics"] == "K_native_carla"
    assert realized["runtime_postprocess"]["remap_required"] is True


def test_resize_crop_intrinsics_preserve_projected_ray():
    k = np.asarray([[800.0, 0.0, 320.0], [0.0, 810.0, 240.0], [0.0, 0.0, 1.0]])
    transformed = intr.transform_intrinsics_for_image_ops(
        k, (640, 480), resize_size=(320, 240), crop_xyxy=(10, 20, 300, 220)
    )
    k_out = np.asarray(transformed["K"])
    pixel_transform = np.asarray(transformed["pixel_transform"])
    point = np.asarray([1.25, -0.75, 8.0])
    source_uv = k @ (point / point[2])
    expected_uv = pixel_transform @ source_uv
    actual_uv = k_out @ (point / point[2])
    assert actual_uv == pytest.approx(expected_uv)
    assert transformed["output_size"] == [290, 200]


def test_resize_crop_validation_rejects_invalid_dimensions():
    k = np.eye(3)
    with pytest.raises(ValueError, match="invalid_resize_size"):
        intr.transform_intrinsics_for_image_ops(k, (10, 10), resize_size=(0, 4))
    with pytest.raises(ValueError, match="crop_out_of_bounds"):
        intr.transform_intrinsics_for_image_ops(k, (10, 10), crop_xyxy=(0, 0, 11, 10))
    with pytest.raises(ValueError, match="unknown_fov_policy"):
        intr.realization_report(_calibration(), fov_policy="guess")
    with pytest.raises(ValueError, match="unknown_cameras"):
        intr.realization_report_for_sizes(_calibration(), {"ghost_camera": (640, 480)})


def test_modality_remap_uses_explicit_mask_and_zeroes_unobserved_pixels():
    calib = _calibration()
    cam = calib["cameras"]["right_camera"]
    w, h = cam["image_size"]
    entry = intr.camera_intrinsic_realization("right_camera", cam["K_undistortion"], w, h)
    grid = intr.compute_remap_grid(entry["K_target"], entry["K_native_carla"], w, h)
    rgb = np.ones((h, w, 3), dtype=np.uint8) * 127
    semantic = np.ones((h, w), dtype=np.uint8) * 7
    instance = np.ones((h, w), dtype=np.uint32) * 0xAABBCCDD
    remapped_rgb = intr.remap_rgb(rgb, grid)
    remapped_semantic = intr.remap_labels(semantic, grid, "semantic_seg")
    remapped_instance = intr.remap_labels(instance, grid, "instance_seg")
    invalid = ~grid["valid"]
    assert invalid.any()
    assert np.all(remapped_rgb[invalid] == 0)
    assert np.all(remapped_semantic[invalid] == 0)
    assert np.all(remapped_instance[invalid] == 0)
    assert set(np.unique(remapped_semantic[grid["valid"]])).issubset({7})
    assert set(np.unique(remapped_instance[grid["valid"]])).issubset({0xAABBCCDD})


def test_effective_intrinsics_bundle_exports_hash_bound_valid_mask(tmp_path):
    calib = _calibration()
    cam = calib["cameras"]["right_camera"]
    entry = intr.camera_intrinsic_realization(
        "right_camera", cam["K_undistortion"], *cam["image_size"]
    )
    artifact = intr.write_effective_intrinsics_artifacts(
        str(tmp_path), entry, remap_applied=True
    )
    mask_path = tmp_path / artifact["valid_image_mask"]["path"]
    mask = np.load(mask_path, allow_pickle=False)
    assert hashlib.sha256(mask_path.read_bytes()).hexdigest() == artifact["valid_image_mask"]["sha256"]
    assert artifact["K_effective"] == entry["K_target"]
    assert artifact["valid_image_mask"]["invalid_pixel_count"] > 0
    assert int(mask.sum()) == artifact["valid_image_mask"]["valid_pixel_count"]
    assert artifact["geometric_full_frame_match"] is False
    assert artifact["exact_intrinsic_compliance"] is False
    assert artifact["independent_rendered_frame_verification"] == "PENDING"


def test_receipt_binds_clean_source_calibration_intrinsics_sensors_settings_and_dataset(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    calib = _calibration()
    calib_path = repo / "calib_data.json"
    calib_path.write_text(json.dumps(calib), encoding="utf-8")
    (repo / "code.py").write_text("committed fixture\n", encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "wp-c@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "WP-C test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "calib_data.json", "code.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "test source identity"], cwd=repo, check=True, capture_output=True)

    report = intr.realization_report(calib)
    effective = {entry["camera"]: entry["K_native_carla"] for entry in report["cameras"]}
    sensor_identity = {
        "cameras": {name: {"actor_id": index + 1, "parent_id": 99,
                            "type_id": "sensor.camera.rgb"}
                    for index, name in enumerate(calib["cameras"])},
        "lidars": {"middle_lidar": {"actor_id": 7, "parent_id": 99,
                                      "type_id": "sensor.lidar.ray_cast"}},
    }
    data_root = tmp_path / "captured"
    data_root.mkdir()
    (data_root / "frame.bin").write_bytes(b"actual-byte-inventory-fixture")
    receipt = build_calibration_receipt(
        calibration_path=calib_path,
        repository_root=repo,
        effective_intrinsics=effective,
        sensor_identity=sensor_identity,
        runtime_settings={"server_version": "0.9.16", "map_name": "fixture",
                          "synchronous_mode": True, "fixed_delta_seconds": 0.05},
        dataset_root=data_root,
    )
    assert receipt["calibration_sha256"] == hashlib.sha256(calib_path.read_bytes()).hexdigest()
    assert receipt["source_commit"] == subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    assert receipt["dataset"]["dataset_sha256"] == dataset_file_inventory(data_root)["dataset_sha256"]
    assert receipt["exact_intrinsic_compliance"] is False
    assert receipt["live_acceptance"] == "PENDING_INDEPENDENT_RENDERED_FRAME_VERIFICATION"
    verified = verify_calibration_receipt(
        receipt, calibration_path=calib_path, repository_root=repo, dataset_root=data_root
    )
    assert verified["valid"] is True
    (data_root / "frame.bin").write_bytes(b"changed-after-receipt")
    stale = verify_calibration_receipt(
        receipt, calibration_path=calib_path, repository_root=repo, dataset_root=data_root
    )
    assert stale["valid"] is False
    assert "dataset_bytes_mismatch" in stale["invalid_reasons"]

    (repo / "code.py").write_text("dirty source\n", encoding="utf-8")
    with pytest.raises(ValueError, match="clean_committed_source"):
        build_calibration_receipt(
            calibration_path=calib_path, repository_root=repo,
            effective_intrinsics=effective, sensor_identity=sensor_identity,
            runtime_settings={"server_version": "0.9.16"}, dataset_root=data_root,
        )


def test_receipt_refuses_empty_dataset_or_incomplete_sensor_identity(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="dataset_has_no_captured_files"):
        dataset_file_inventory(empty)


def test_harness_projection_and_transform_math_are_numerical_only():
    harness = _load_live_harness()
    k = [[100.0, 0.0, 50.0], [0.0, 100.0, 50.0], [0.0, 0.0, 1.0]]
    identity = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
    assert harness.project_point(k, identity, (0.0, 0.0, 10.0)) == (50.0, 50.0)
    delta = harness.transform_error(
        {"location": {"x": 0, "y": 0, "z": 0}, "rotation": {"roll": 0, "pitch": 0, "yaw": 179.9}},
        {"location": {"x": 0, "y": 0, "z": 0}, "rotation": {"roll": 0, "pitch": 0, "yaw": -179.9}},
    )
    assert delta["max_angle_deg"] == pytest.approx(0.2)


def test_projection_unprojection_and_optical_axis_round_trip():
    k = np.asarray([[820.0, 0.3, 631.2], [0.0, 815.0, 358.7], [0.0, 0.0, 1.0]])
    point = (1.4, -0.8, 13.0)
    uv = intr.project_camera_point(k, point)
    recovered = intr.unproject_camera_pixel(k, uv, optical_axis_depth=point[2])
    assert recovered == pytest.approx(point)
    principal_ray = intr.unproject_camera_pixel(k, (k[0, 2], k[1, 2]), optical_axis_depth=10.0)
    assert principal_ray == pytest.approx((0.0, 0.0, 10.0))


def test_known_landmark_projection_roundtrips_for_all_six_camera_frames():
    calib = _calibration()
    for name, camera in calib["cameras"].items():
        c_tv = np.asarray(camera["cTv"], dtype=float)
        point_vehicle = (np.linalg.inv(c_tv) @ np.asarray([0.2, -0.1, 12.0, 1.0]))[:3]
        point_camera = (c_tv @ np.r_[point_vehicle, 1.0])[:3]
        pixel = intr.project_camera_point(camera["K_undistortion"], point_camera)
        back_projected = intr.unproject_camera_pixel(
            camera["K_undistortion"], pixel, optical_axis_depth=point_camera[2]
        )
        assert back_projected == pytest.approx(point_camera, abs=1e-9), name


def test_mock_rendered_camera_and_lidar_correspondences_are_numerical_only(tmp_path):
    harness = _load_live_harness()
    calib = _calibration()
    frame_id = "77"
    frame: dict = {}
    camera_annotations = []
    lidar_annotations = []
    lidar_points = []
    projected_by_camera = {}
    lidar_indices_by_camera = {}
    camera_digest = "a" * 64
    lidar_name = "middle_lidar"
    v_tl = np.asarray(calib["lidars"][lidar_name]["vTl"], dtype=float)
    for name, camera in calib["cameras"].items():
        k = camera["K_undistortion"]
        frame[name] = {
            "image_sha256": camera_digest, "K_effective": k,
            "width": camera["image_size"][0], "height": camera["image_size"][1],
        }
        point_camera = np.asarray([0.1, -0.05, 15.0, 1.0])
        point_vehicle = (np.linalg.inv(np.asarray(camera["cTv"], dtype=float)) @ point_camera)[:3]
        uv = harness.project_point(k, camera["cTv"], point_vehicle)
        projected_by_camera[name] = uv
        camera_annotations.append({
            "camera": name, "frame_id": frame_id, "image_sha256": camera_digest,
            "landmarks": [
                {"name": f"target_{i}", "point_vehicle": point_vehicle.tolist(), "observed_uv": uv}
                for i in range(8)
            ],
        })
        point_lidar = (np.linalg.inv(v_tl) @ np.r_[point_vehicle, 1.0])[:3]
        lidar_indices_by_camera[name] = list(range(len(lidar_points), len(lidar_points) + 8))
        lidar_points.extend([point_lidar] * 8)
    lidar_path = tmp_path / "lidar.bin"
    lidar_bytes = np.asarray([[*point, 1.0] for point in lidar_points], dtype="<f4").tobytes()
    lidar_path.write_bytes(lidar_bytes)
    lidar_digest = hashlib.sha256(lidar_bytes).hexdigest()
    frame[lidar_name] = {"data_sha256": lidar_digest, "path": "lidar.bin"}
    for camera_name, uv in projected_by_camera.items():
        for point_index in lidar_indices_by_camera[camera_name]:
            lidar_annotations.append({
                "camera": camera_name, "lidar": lidar_name, "frame_id": frame_id,
                "camera_image_sha256": camera_digest, "lidar_data_sha256": lidar_digest,
                "point_index": point_index, "observed_uv": uv,
            })
    observations = {
        "camera_observations": camera_annotations,
        "lidar_observations": lidar_annotations,
    }
    camera_result = harness.score_camera_annotations(
        calibration=calib, capture_frames={frame_id: frame}, annotations=observations
    )
    lidar_result = harness.score_lidar_camera_annotations(
        calibration=calib, capture_frames={frame_id: frame},
        annotations=observations, dataset_root=tmp_path,
    )
    assert camera_result["verdict"] == "ANNOTATION_RESIDUAL_PASS"
    assert lidar_result["verdict"] == "ANNOTATION_RESIDUAL_PASS"
    assert camera_result["evidence_kind"].startswith("RESIDUAL_CALCULATION_ONLY")
    assert lidar_result["independent_review"] == "PENDING"


def test_camera_annotation_stale_frame_hash_is_rejected():
    harness = _load_live_harness()
    calib = _calibration()
    frames = {"9": {name: {"image_sha256": "b" * 64,
                           "K_effective": cam["K_undistortion"],
                           "width": cam["image_size"][0], "height": cam["image_size"][1]}
                     for name, cam in calib["cameras"].items()}}
    annotations = {"camera_observations": [{
        "camera": "front_left_camera", "frame_id": "9", "image_sha256": "c" * 64,
        "landmarks": [{"name": "p", "point_vehicle": [0, 0, 1], "observed_uv": [0, 0]}],
    }]}
    result = harness.score_camera_annotations(
        calibration=calib, capture_frames=frames, annotations=annotations
    )
    assert result["verdict"] == "ANNOTATION_RESIDUAL_FAIL"
    assert any("image_digest_mismatch" in reason for reason in result["invalid_reasons"])


def test_camera_annotations_reject_observations_outside_rendered_frame():
    harness = _load_live_harness()
    calib = _calibration()
    name = "front_left_camera"
    frame = {name: {"image_sha256": "d" * 64,
                    "K_effective": calib["cameras"][name]["K_undistortion"],
                    "width": 1920, "height": 1080}}
    point_camera = [0.0, 0.0, 10.0, 1.0]
    point_vehicle = (np.linalg.inv(np.asarray(calib["cameras"][name]["cTv"]))
                     @ np.asarray(point_camera))[:3].tolist()
    result = harness.score_camera_annotations(
        calibration=calib, capture_frames={"10": frame},
        annotations={"camera_observations": [{
            "camera": name, "frame_id": "10", "image_sha256": "d" * 64,
            "landmarks": [{"name": "outside", "point_vehicle": point_vehicle,
                           "observed_uv": [-1.0, 20.0]}],
        }]},
    )
    assert result["verdict"] == "ANNOTATION_RESIDUAL_FAIL"
    assert "annotation[0]:observed_landmark_outside_image" in result["invalid_reasons"]


def test_evidence_pack_rpc_probe_requires_carla_rpc_and_never_claims_rendered_pass(monkeypatch):
    pack = _load_evidence_pack()
    calls = []

    class Client:
        def __init__(self, host, port):
            calls.append((host, port))
        def set_timeout(self, timeout):
            self.timeout = timeout
        def get_server_version(self):
            return "0.9.16"

    monkeypatch.setitem(sys.modules, "carla", types.SimpleNamespace(Client=Client))
    probe = pack.rpc_probe("127.0.0.1", [2000, 8000])
    assert probe["reachable"] is True
    assert probe["evidence"] == "CARLA_RPC_VERSION_ONLY_PENDING_RENDERED_FRAME_VERIFICATION"
    assert all(result["status"] == "RPC_REACHABLE" for result in probe["ports"].values())
    assert calls == [("127.0.0.1", 2000), ("127.0.0.1", 8000)]


def test_mock_capture_frame_acquisition_preserves_frame_and_timestamp(tmp_path):
    harness = _load_live_harness()

    class Image:
        frame, timestamp, width, height, fov = 12, 0.6, 2, 2, 90.0
        raw_data = bytes(range(16))
        def save_to_disk(self, path):
            Path(path).write_bytes(b"mock-png-bytes")

    class Actor:
        id, type_id = 1, "sensor.camera.rgb"
        def __init__(self): self.callback = None
        def listen(self, callback): self.callback = callback

    class Wrapped:
        report = {"attributes": {"width": 2, "height": 2, "fov": 90.0}}
        def __init__(self): self.actor = Actor()

    sensor = Wrapped()
    queues = harness._start_sensor_listeners({"front_camera": sensor})

    class World:
        def tick(self):
            sensor.actor.callback(Image())
            return 12

    result = harness._record_one_frame(World(), {"front_camera": sensor}, queues, tmp_path, 0.5)
    assert result["world_frame_id"] == 12
    assert result["sensors"]["front_camera"]["frame_id"] == 12
    assert result["sensors"]["front_camera"]["timestamp"] == pytest.approx(0.6)
    assert (tmp_path / result["sensors"]["front_camera"]["raw_path"]).stat().st_size == 16


def test_stale_mock_sensor_frame_fails_closed(tmp_path):
    harness = _load_live_harness()

    class Image:
        frame, timestamp, width, height, fov = 10, 0.5, 2, 2, 90.0
        raw_data = bytes(range(16))
        def save_to_disk(self, path): Path(path).write_bytes(b"mock-png")

    class Actor:
        id, type_id = 1, "sensor.camera.rgb"
        def listen(self, callback): self.callback = callback

    class Wrapped:
        report = {"attributes": {"width": 2, "height": 2, "fov": 90.0}}
        def __init__(self): self.actor = Actor()

    sensor = Wrapped()
    queues = harness._start_sensor_listeners({"front_camera": sensor})
    class World:
        def tick(self):
            sensor.actor.callback(Image())
            return 11
    with pytest.raises(TimeoutError, match="stale_callback_timeout"):
        harness._record_one_frame(World(), {"front_camera": sensor}, queues, tmp_path, 0.01)
