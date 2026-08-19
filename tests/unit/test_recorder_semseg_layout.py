from __future__ import annotations

"""C8 — SensorRecorder (record_route_fixed / record_route live-capture path)
must emit the same canonical layout as capture_writer:

    rgb/<cam>/<frame>.png          RGB image
    semseg_raw/<cam>/<frame>.png   TRAINING LABEL: single-channel uint8,
                                   pixel value == CARLA semantic class id
    semseg_viz/<cam>/<frame>.png   optional palette copy (human viewing)

Before this fix the recorder applied CityScapesPalette to the semseg frame
BEFORE save_to_disk, so `semseg_raw/` held palette colors instead of raw
class ids (SEV-1 in reports/post_audit_hardening/PIPELINE_CRITICAL_AUDIT_20260816.md),
and per-camera subdirs were not pairable (rgb/<cam>/ vs semseg_raw/semseg_<cam>/).

All tests are offline: sensors and carla.Image are duck-typed fakes.
"""

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image as PILImage

from ultimate_pipeline.sensors.recorder import RecorderConfig, SensorRecorder
from ultimate_pipeline.perception.min_train_segmentation import SegDataset


class _FakeTransform:
    class _Location:
        x = y = z = 0.0

    class _Rotation:
        roll = pitch = yaw = 0.0

    location = _Location()
    rotation = _Rotation()


class _FakeSensor:
    """Duck-typed carla.Sensor: stores the recorder callback, never connects."""

    def __init__(self, type_id: str):
        self.type_id = type_id
        self._callback = None
        self._stopped = False

    def listen(self, callback) -> None:
        self._callback = callback

    def stop(self) -> None:
        self._stopped = True

    def get_transform(self) -> _FakeTransform:
        return _FakeTransform()


class _FakeCarlaImage:
    """Duck-typed carla.Image (BGRA8 raw buffer)."""

    def __init__(self, bgra: np.ndarray, frame: int = 0):
        assert bgra.ndim == 3 and bgra.shape[2] == 4
        self.raw_data = bgra.tobytes()
        self.height = int(bgra.shape[0])
        self.width = int(bgra.shape[1])
        self.frame = frame
        self._converted = False

    def convert(self, converter) -> None:
        # Mimic carla.Image.convert: replace the buffer with an RGB view.
        arr = np.frombuffer(self.raw_data, dtype=np.uint8).reshape(
            (self.height, self.width, 4)
        )
        rgb = np.ascontiguousarray(arr[:, :, :3][:, :, ::-1])  # BGRA -> RGB
        self.raw_data = rgb.tobytes()
        self._converted = True

    def save_to_disk(self, path: str) -> None:
        arr = np.frombuffer(self.raw_data, dtype=np.uint8)
        if arr.size == self.height * self.width * 4:
            arr = arr.reshape((self.height, self.width, 4))[:, :, :3][:, :, ::-1]
        else:
            arr = arr.reshape((self.height, self.width, 3))
        PILImage.fromarray(arr, mode="RGB").save(path)


def _make_frame(h: int = 6, w: int = 8, seed: int = 0, frame: int = 1):
    rng = np.random.default_rng(seed)
    rgb_bgra = np.zeros((h, w, 4), dtype=np.uint8)
    rgb_bgra[:, :, :3] = rng.integers(0, 255, size=(h, w, 3), dtype=np.uint8)

    ids = np.zeros((h, w), dtype=np.uint8)
    ids[: h // 2, :] = 7   # Road
    ids[h // 2:, :] = 10   # Vehicle
    seg_bgra = np.zeros((h, w, 4), dtype=np.uint8)
    seg_bgra[:, :, 2] = ids  # BGRA -> R channel (index 2) carries the class id

    return _FakeCarlaImage(rgb_bgra, frame=frame), _FakeCarlaImage(
        seg_bgra, frame=frame
    ), ids


def _make_recorder(
    tmp_path, sensors: dict, *, segmentation_mode: str = "cityscapes"
) -> SensorRecorder:
    cfg = RecorderConfig(
        fps=10,
        synchronous=True,
        fixed_delta_seconds=0.1,
        image_format="png",
        segmentation_mode=segmentation_mode,
        write_sensor_transforms=False,
        write_world_snapshot=False,
    )
    return SensorRecorder(
        world=object(),  # any truthy object satisfies the attach gate offline
        ego_vehicle=None,
        sensors=sensors,
        out_dir=str(tmp_path / "rec"),
        cfg=cfg,
    )


def _fire_and_finalize(recorder: SensorRecorder, frames: list) -> None:
    for sensor in recorder.sensors.values():
        assert sensor._callback is not None, "recorder must have attached a callback"
        for fake_img in frames:
            sensor._callback(fake_img)
    recorder.prepare_for_destroy()


def test_semseg_raw_labels_are_raw_class_ids_not_palette(tmp_path):
    """semseg_raw/<cam>/<frame>.png must be a single-channel uint8 image whose
    pixel values equal the injected class ids — never palette colorized."""
    _, seg_img, ids = _make_frame()
    recorder = _make_recorder(
        tmp_path,
        {"front_left_camera": _FakeSensor("sensor.camera.semantic_segmentation")},
    )
    _fire_and_finalize(recorder, [seg_img])

    label_path = tmp_path / "rec" / "semseg_raw" / "front_left_camera" / "00000001.png"
    assert label_path.is_file(), "semseg_raw/<cam>/<frame>.png must exist"

    with PILImage.open(label_path) as img:
        assert img.mode == "L", "training label must be single-channel uint8"
        saved = np.array(img)
    assert saved.shape == ids.shape
    assert np.array_equal(saved, ids), (
        "semseg_raw pixel values must equal the raw class ids; a palette "
        "conversion must not be applied to the training label"
    )
    assert not recorder.get_save_errors_tail(), recorder.get_save_errors_tail()


def test_semseg_subdir_pairs_with_rgb_camera_name(tmp_path):
    """Thesis rig names semantic sensors `semseg_<cam>`; the recorder must
    strip the modality prefix so rgb/<cam>/ and semseg_raw/<cam>/ share one
    camera name (the pairing contract of min_train_segmentation/eval)."""
    rgb_img, seg_img, _ = _make_frame()
    recorder = _make_recorder(
        tmp_path,
        {
            "front_left_camera": _FakeSensor("sensor.camera.rgb"),
            "semseg_front_left_camera": _FakeSensor(
                "sensor.camera.semantic_segmentation"
            ),
        },
    )
    _fire_and_finalize(recorder, [rgb_img, seg_img])

    rgb_dir = tmp_path / "rec" / "rgb" / "front_left_camera"
    seg_dir = tmp_path / "rec" / "semseg_raw" / "front_left_camera"
    assert rgb_dir.is_dir(), f"rgb must land under {rgb_dir}"
    assert seg_dir.is_dir(), f"semseg must land under {seg_dir}"
    assert len(list(rgb_dir.glob("*.png"))) == 1
    assert len(list(seg_dir.glob("*.png"))) == 1
    # No prefixed semseg_* subdir may be produced.
    assert not (tmp_path / "rec" / "semseg_raw" / "semseg_front_left_camera").exists()


def test_dominik_style_rgb_and_seg_prefixes_are_stripped(tmp_path):
    """Dominik rig keys sensors `rgb_<cam>` / `seg_<cam>`; both prefixes must
    be stripped so the pair shares the camera subdir name."""
    rgb_img, seg_img, _ = _make_frame()
    recorder = _make_recorder(
        tmp_path,
        {
            "rgb_front_left_camera": _FakeSensor("sensor.camera.rgb"),
            "seg_front_left_camera": _FakeSensor(
                "sensor.camera.semantic_segmentation"
            ),
        },
    )
    _fire_and_finalize(recorder, [rgb_img, seg_img])

    assert (tmp_path / "rec" / "rgb" / "front_left_camera" / "00000001.png").is_file()
    assert (tmp_path / "rec" / "semseg_raw" / "front_left_camera" / "00000001.png").is_file()


def test_cityscapes_mode_writes_viz_under_semseg_viz_not_semseg_raw(tmp_path):
    """segmentation_mode='cityscapes' (default) additionally writes a palette
    copy to semseg_viz/<cam>/ — never into semseg_raw/."""
    _, seg_img, ids = _make_frame()
    recorder = _make_recorder(
        tmp_path,
        {"cam_a": _FakeSensor("sensor.camera.semantic_segmentation")},
        segmentation_mode="cityscapes",
    )
    _fire_and_finalize(recorder, [seg_img])

    raw = tmp_path / "rec" / "semseg_raw" / "cam_a" / "00000001.png"
    viz = tmp_path / "rec" / "semseg_viz" / "cam_a" / "00000001.png"
    assert raw.is_file()
    assert viz.is_file(), "cityscapes mode must keep the human-viewable palette copy"
    saved_raw = np.array(PILImage.open(raw))
    assert np.array_equal(saved_raw, ids), "semseg_raw stays raw even in viz mode"
    with PILImage.open(viz) as img:
        assert img.mode == "RGB", "viz copy is a color image, never a label"


def test_raw_mode_does_not_write_semseg_viz(tmp_path):
    """segmentation_mode='raw' writes only the raw training label."""
    _, seg_img, _ = _make_frame()
    recorder = _make_recorder(
        tmp_path,
        {"cam_a": _FakeSensor("sensor.camera.semantic_segmentation")},
        segmentation_mode="raw",
    )
    _fire_and_finalize(recorder, [seg_img])

    assert (tmp_path / "rec" / "semseg_raw" / "cam_a" / "00000001.png").is_file()
    assert not (tmp_path / "rec" / "semseg_viz").exists()


def test_trainer_reads_recorder_output_round_trip(tmp_path):
    """End-to-end: recorder output must be directly consumable by the
    trainer's SegDataset (same pairing + label encoding as capture_writer)."""
    rgb_img, seg_img, ids = _make_frame()
    recorder = _make_recorder(
        tmp_path,
        {
            "front_left_camera": _FakeSensor("sensor.camera.rgb"),
            "semseg_front_left_camera": _FakeSensor(
                "sensor.camera.semantic_segmentation"
            ),
        },
        segmentation_mode="raw",
    )
    _fire_and_finalize(recorder, [rgb_img, seg_img])

    ds = SegDataset(tmp_path / "rec", cam="front_left_camera")
    assert len(ds) > 0, "SegDataset must find the rgb/semseg_raw pair"
    x, y = ds[0]
    assert x.shape[0] == 3
    assert np.array_equal(y.numpy().astype(np.uint8), ids)


def test_manifest_records_canonical_output_dirs(tmp_path):
    """recorder_manifest.json per-sensor output_dir must point at the
    canonical (prefix-stripped) subdirectories."""
    rgb_img, seg_img, _ = _make_frame()
    recorder = _make_recorder(
        tmp_path,
        {
            "front_left_camera": _FakeSensor("sensor.camera.rgb"),
            "semseg_front_left_camera": _FakeSensor(
                "sensor.camera.semantic_segmentation"
            ),
        },
        segmentation_mode="raw",
    )
    _fire_and_finalize(recorder, [rgb_img, seg_img])
    recorder.close()

    manifest = json.loads(
        (tmp_path / "rec" / "recorder_manifest.json").read_text(encoding="utf-8")
    )
    dirs = [Path(s["output_dir"]) for s in manifest["sensors"]]
    assert (tmp_path / "rec" / "rgb" / "front_left_camera") in dirs
    assert (tmp_path / "rec" / "semseg_raw" / "front_left_camera") in dirs
    assert not any("semseg_front_left_camera" in str(d) for d in dirs)


@pytest.mark.parametrize(
    ("sensor_name", "sensor_kind", "expected"),
    [
        ("front_left_camera", "rgb", "front_left_camera"),
        ("semseg_front_left_camera", "semseg_raw", "front_left_camera"),
        ("seg_front_left_camera", "semseg_raw", "front_left_camera"),
        ("rgb_front_left_camera", "rgb", "front_left_camera"),
        ("Seg_Front_Left", "semseg_raw", "Front_Left"),
        ("middle_lidar", "lidar", "middle_lidar"),
        ("front_camera_main", "rgb", "front_camera_main"),
    ],
)
def test_canonical_sensor_subdir(sensor_name, sensor_kind, expected):
    assert SensorRecorder._canonical_sensor_subdir(sensor_name, sensor_kind) == expected
