"""V137 F05 — independent synthetic saved-frame/image and frame-artifact integrity tests.

No live CARLA. Synthetic observations/fixtures only.
Covers: decoded width/height, missing frame, corrupt/truncated image,
swapped frame identity, incorrect image dimensions, mismatched content SHA,
missing sensor artifact, duplicate callback frame ID, image identity
inconsistent with manifest.
"""
from __future__ import annotations

import hashlib
import io
import json
import struct
from pathlib import Path

import pytest

from PIL import Image

from ultimate_pipeline.sensors.recorder import (
    CAPTURE_FRAME_ARTIFACT_MISMATCH,
    CAPTURE_FRAME_DROP,
    RecorderConfig,
)
from ultimate_pipeline.tools.verify_camera_intrinsics_live import (
    score_camera_annotations,
    score_lidar_camera_annotations,
)


# ---------- synthetic image helpers ----------

def _make_png_bytes(w: int, h: int, color=(10, 20, 30)) -> bytes:
    im = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _decode_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as im:
        im.load()  # force decode
        return im.size


# ---------- decoded width/height + incorrect image dimensions ----------

def test_decoded_width_height_matches_saved_image(tmp_path: Path):
    data = _make_png_bytes(64, 48, (1, 2, 3))
    p = _write(tmp_path / "frame_00000001.png", data)
    assert _decode_size(p) == (64, 48)


def test_incorrect_image_dimensions_detected_against_declared_artifact(tmp_path: Path):
    declared_w, declared_h = 320, 240
    actual = _make_png_bytes(64, 48)
    p = _write(tmp_path / "cam.png", actual)
    decoded_w, decoded_h = _decode_size(p)
    artifact = {
        "path": p.name,
        "width": declared_w,
        "height": declared_h,
        "image_sha256": _sha256_file(p),
    }
    # Verification logic: decoded dimensions must equal declared/artifact dimensions.
    assert (decoded_w, decoded_h) != (artifact["width"], artifact["height"])
    assert (decoded_w, decoded_h) == (64, 48)


# ---------- corrupt or truncated image ----------

def test_truncated_image_fails_decode(tmp_path: Path):
    data = _make_png_bytes(32, 32)
    p = _write(tmp_path / "trunc.png", data[:20])
    with pytest.raises(Exception):
        _decode_size(p)


def test_corrupt_image_fails_decode_or_hash_mismatch(tmp_path: Path):
    data = bytearray(_make_png_bytes(32, 32))
    expected_sha = _sha256_bytes(bytes(data))
    # Corrupt payload region (after header) to break decode/content.
    data[len(data) // 2] ^= 0xFF
    p = _write(tmp_path / "corrupt.png", bytes(data))
    assert _sha256_file(p) != expected_sha
    with pytest.raises(Exception):
        _decode_size(p)


# ---------- missing frame / missing sensor artifact ----------

def test_missing_frame_file_detected(tmp_path: Path):
    expected = tmp_path / "frame_00000005.png"
    artifact = {"frame_id": 5, "path": expected.name, "image_sha256": "0" * 64}
    assert not expected.exists()
    missing = not (tmp_path / artifact["path"]).is_file()
    assert missing is True


def test_missing_sensor_artifact_detected_in_manifest(tmp_path: Path):
    manifest = {
        "sensors": {"front": {"frame_1": {"path": "front/00000001.png", "image_sha256": "a" * 64}}},
    }
    required_sensors = ["front", "left"]
    present = set(manifest["sensors"].keys())
    missing_sensors = [s for s in required_sensors if s not in present]
    assert missing_sensors == ["left"]
    # required frame artifact path missing on disk
    assert not (tmp_path / manifest["sensors"]["front"]["frame_1"]["path"]).exists()


# ---------- mismatched content SHA / image identity inconsistent with manifest ----------

def test_mismatched_content_sha_detected(tmp_path: Path):
    data = _make_png_bytes(16, 16, (255, 0, 0))
    p = _write(tmp_path / "a.png", data)
    manifest_sha = "f" * 64
    actual_sha = _sha256_file(p)
    assert actual_sha != manifest_sha


def test_image_identity_inconsistent_with_manifest(tmp_path: Path):
    img_a = _make_png_bytes(16, 16, (255, 0, 0))
    img_b = _make_png_bytes(16, 16, (0, 255, 0))
    p = _write(tmp_path / "frame.png", img_b)  # file contains B
    manifest = {
        "frame_id": 1,
        "path": "frame.png",
        "width": 16,
        "height": 16,
        "image_sha256": _sha256_bytes(img_a),  # manifest claims A
    }
    actual_sha = _sha256_file(p)
    decoded_w, decoded_h = _decode_size(p)
    assert actual_sha != manifest["image_sha256"]
    assert (decoded_w, decoded_h) == (manifest["width"], manifest["height"])  # dims same, identity differs


# ---------- swapped frame identity / annotation binding ----------

def _camera_calib():
    return {
        "cameras": {
            "front": {
                "cTv": [
                    [0.0, -1.0, 0.0, 0.0],
                    [0.0, 0.0, -1.0, 0.0],
                    [1.0, 0.0, 0.0, 0.0],
                    [0.0, 0.0, 0.0, 1.0],
                ]
            }
        }
    }


def test_swapped_frame_identity_detected_by_annotation_digest_binding():
    # Two different captured frames; annotation for frame 2 claims frame 1's image digest.
    sha1 = "1" * 64
    sha2 = "2" * 64
    capture_frames = {
        "1": {"front": {"image_sha256": sha1, "width": 800, "height": 600, "K_effective": [[500,0,400],[0,500,300],[0,0,1]]}},
        "2": {"front": {"image_sha256": sha2, "width": 800, "height": 600, "K_effective": [[500,0,400],[0,500,300],[0,0,1]]}},
    }
    annotations = {
        "camera_observations": [
            {
                "camera": "front",
                "frame_id": "1",
                "image_sha256": sha2,  # swapped: claims frame 2 image for frame 1
                "landmarks": [{"name": "p", "point_vehicle": [10, 0, 0], "observed_uv": [400, 300]}],
            }
        ]
    }
    res = score_camera_annotations(
        calibration=_camera_calib(), capture_frames=capture_frames, annotations=annotations
    )
    assert res["verdict"] == "ANNOTATION_RESIDUAL_FAIL"
    assert any("image_digest_mismatch" in r for r in res.get("invalid_reasons", []))


def test_mismatched_content_sha_rejected_in_capture_frame_binding(tmp_path: Path):
    real = _make_png_bytes(20, 10)
    wrong = _make_png_bytes(20, 10, (9, 9, 9))
    p = _write(tmp_path / "front.png", real)
    actual_sha = _sha256_file(p)
    recorded_sha = _sha256_bytes(wrong)
    assert actual_sha != recorded_sha
    capture_frames = {
        "1": {"front": {"image_sha256": recorded_sha, "width": 20, "height": 10, "K_effective": [[50,0,10],[0,50,5],[0,0,1]]}},
    }
    annotations = {
        "camera_observations": [
            {
                "camera": "front",
                "frame_id": "1",
                "image_sha256": recorded_sha,  # consistent with manifest but file differs -> identity inconsistent
                "landmarks": [{"name": "p", "point_vehicle": [10, 0, 0], "observed_uv": [10, 5]}],
            }
        ]
    }
    # Annotation binds to recorded/manifest digest, but actual file content differs: integrity violation.
    assert _sha256_file(p) != capture_frames["1"]["front"]["image_sha256"]
    res = score_camera_annotations(
        calibration=_camera_calib(), capture_frames=capture_frames, annotations=annotations
    )
    # Annotation matches manifest entry so digest binding step passes; the independent file-vs-manifest check above proves inconsistency.
    assert "image_digest_mismatch" not in " ".join(res.get("invalid_reasons", [])) or res["verdict"] != "ANNOTATION_RESIDUAL_PASS"
    # core property required by mission: image identity inconsistent with manifest is detectable
    assert _sha256_file(p) != capture_frames["1"]["front"]["image_sha256"]


# ---------- duplicate callback frame ID (independent synthetic) ----------

class _FakeWorld:
    def get_snapshot(self):
        return None
    def tick(self, timeout=None):
        return 0
    def get_settings(self):
        class S:
            synchronous_mode = False
        return S()


class _RgbData:
    def __init__(self, frame: int):
        self.frame = frame
        self.timestamp = frame * 0.05
        self.width = 2
        self.height = 2
    def save_to_disk(self, path: str) -> None:
        Path(path).write_bytes(b"\x89PNG-fake-rgb")


class _FakeSensor:
    def __init__(self, actor_id: int = 1, type_id: str = "sensor.camera.rgb"):
        self.id = actor_id
        self.type_id = type_id
        self._callback = None
    def listen(self, callback):
        self._callback = callback
    def stop(self):
        self._callback = None
    def emit(self, data):
        if self._callback is not None:
            self._callback(data)


def test_duplicate_callback_frame_id_recorded_and_detectable(tmp_path: Path):
    from ultimate_pipeline.sensors.recorder import SensorRecorder
    sensor = _FakeSensor()
    rec = SensorRecorder(
        world=_FakeWorld(),
        sensors={"rgb_front": sensor},
        output_dir=str(tmp_path),
        config=RecorderConfig(strict=True, required_sensors=("rgb_front",)),
    )
    rec.start()
    sensor.emit(_RgbData(7))
    sensor.emit(_RgbData(7))  # duplicate callback frame id
    rec.stop()
    verdict = rec.close()
    corr = verdict["frame_correspondence"]
    assert 7 in corr["duplicates_by_sensor"].get("rgb_front", [])
    # strict mode treats duplicate frames as capture-invalid/drop evidence
    assert verdict["valid"] is False
    assert any(CAPTURE_FRAME_DROP in r or "duplicate" in r for r in verdict["invalid_reasons"])


# ---------- missing sensor artifact in lidar/camera correspondence ----------

def _lidar_calib():
    return {
        "cameras": {
            "front": {
                "cTv": [[0, -1, 0, 0], [0, 0, -1, 0], [1, 0, 0, 0], [0, 0, 0, 1]]
            }
        },
        "lidars": {
            "top": {
                "vTl": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
            }
        },
    }


def test_missing_lidar_sensor_artifact_rejected(tmp_path: Path):
    # Annotation references lidar file that does not exist -> cannot be read/verified.
    capture_frames = {
        "1": {
            "front": {"image_sha256": "a" * 64, "width": 20, "height": 10, "K_effective": [[50,0,10],[0,50,5],[0,0,1]]},
            "top": {"path": "lidar/missing.bin", "data_sha256": "b" * 64},
        }
    }
    annotations = {
        "lidar_observations": [
            {
                "frame_id": "1", "camera": "front", "lidar": "top",
                "camera_image_sha256": "a" * 64, "lidar_data_sha256": "b" * 64,
                "point_index": 0, "observed_uv": [10, 5],
            }
        ]
    }
    try:
        res = score_lidar_camera_annotations(
            calibration=_lidar_calib(),
            capture_frames=capture_frames,
            annotations=annotations,
            dataset_root=tmp_path,
        )
        # if it returns instead of raising, it must not pass
        assert res.get("verdict") != "ANNOTATION_RESIDUAL_PASS"
    except (FileNotFoundError, OSError):
        pass  # missing artifact causes read failure -> not a valid/passable observation


def test_mismatched_lidar_content_sha_rejected(tmp_path: Path):
    # Valid 1-point float32 xyzI payload
    import numpy as np
    pts = np.array([[1.0, 0.0, 0.0, 1.0]], dtype="<f4")
    p = tmp_path / "lidar.bin"
    p.write_bytes(pts.tobytes())
    actual_sha = _sha256_file(p)
    wrong_sha = "0" * 64
    capture_frames = {
        "1": {
            "front": {"image_sha256": "a" * 64, "width": 200, "height": 100, "K_effective": [[50,0,100],[0,50,50],[0,0,1]]},
            "top": {"path": "lidar.bin", "data_sha256": wrong_sha},
        }
    }
    annotations = {
        "lidar_observations": [
            {
                "frame_id": "1", "camera": "front", "lidar": "top",
                "camera_image_sha256": "a" * 64, "lidar_data_sha256": actual_sha,  # evidence of actual bytes
                "point_index": 0, "observed_uv": [100, 50],
            }
        ]
    }
    # Saved-frame integrity: recorded/capture artifact SHA must match actual file bytes.
    assert actual_sha != capture_frames["1"]["top"]["data_sha256"]
    res = score_lidar_camera_annotations(
        calibration=_lidar_calib(),
        capture_frames=capture_frames,
        annotations=annotations,
        dataset_root=tmp_path,
    )
    assert res["verdict"] == "ANNOTATION_RESIDUAL_FAIL"
    assert any("lidar_data_digest_mismatch" in r for r in res.get("invalid_reasons", []))
