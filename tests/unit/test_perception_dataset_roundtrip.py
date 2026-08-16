from __future__ import annotations

"""C8 — perception dataset correctness (raw labels + unified layout).

Characterizes and then locks the fix for the SEV-1 mismatch between what the
capture writers produced (images/+labels/, CityScapes-palette "labels") and
what the trainer/eval/class-weight readers expect (rgb/+semseg_raw/, raw
class ids in the R channel). See reports/post_audit_hardening/C8_perception_dataset_correctness.md.

All tests are offline: CARLA sensor frames are simulated as BGRA numpy
buffers exposed through a duck-typed fake object (raw_data/height/width),
exactly like the existing `_write_png_raw_ids` characterization test in
tests/unit/test_label_quality.py. No live CARLA server is required.
"""

import numpy as np
import pytest
from PIL import Image as PILImage

from ultimate_pipeline.perception.semantic_classes import CARLA_SEMANTIC_NUM_CLASSES
from ultimate_pipeline.perception.label_quality import is_degenerate_label


class _FakeCarlaImage:
    """Duck-typed stand-in for carla.Image (BGRA8 raw buffer)."""

    def __init__(self, bgra: np.ndarray, frame: int = 0, fov: float = 90.0):
        assert bgra.ndim == 3 and bgra.shape[2] == 4
        self.raw_data = bgra.tobytes()
        self.height = int(bgra.shape[0])
        self.width = int(bgra.shape[1])
        self.frame = frame
        self.fov = fov


def _make_synthetic_frame(h: int = 6, w: int = 8, seed: int = 0):
    """Build a synthetic CARLA semantic frame: BGRA buffer with R=class id.

    Returns (fake_rgb_image, fake_seg_image, injected_class_ids).
    """
    rng = np.random.default_rng(seed)
    # RGB "camera" frame (BGRA order, alpha unused)
    rgb_bgra = np.zeros((h, w, 4), dtype=np.uint8)
    rgb_bgra[:, :, :3] = rng.integers(0, 255, size=(h, w, 3), dtype=np.uint8)

    # Semantic frame: at least 2 distinct classes, not background-dominant,
    # so the round-trip result is not itself flagged degenerate.
    ids = np.zeros((h, w), dtype=np.uint8)
    ids[: h // 2, :] = 7   # e.g. "Road"
    ids[h // 2:, :] = 10   # e.g. "Vehicle"
    seg_bgra = np.zeros((h, w, 4), dtype=np.uint8)
    seg_bgra[:, :, 2] = ids  # BGRA -> R channel (index 2) carries the class id

    return _FakeCarlaImage(rgb_bgra), _FakeCarlaImage(seg_bgra), ids


# ---------------------------------------------------------------------------
# RED characterization (pre-fix behavior of the legacy per-module save paths)
# ---------------------------------------------------------------------------


def test_capture_writes_raw_class_ids_not_palette_colors(tmp_path):
    """The training label PNG's R channel must equal the injected class ids,
    not CityScapes palette RGB. Before the fix, dataset_generator applied
    `seg_img.convert(CityScapesPalette)` before saving the "label" — this
    destroys the class id and must no longer happen for the training label.
    """
    from ultimate_pipeline.perception.capture_writer import save_capture_frame

    _, seg_img, ids = _make_synthetic_frame()
    out_root = tmp_path / "ds"

    result = save_capture_frame(
        out_root,
        camera="front",
        frame=1,
        rgb_image=None,
        seg_image=seg_img,
        label_mode="semantic",
    )

    raw_label_path = out_root / "semseg_raw" / "front" / "00000001.png"
    assert raw_label_path.is_file(), "semseg_raw/<cam>/<frame>.png must exist"

    saved = np.array(PILImage.open(raw_label_path))
    assert saved.shape == ids.shape
    assert np.array_equal(saved, ids), (
        "R channel of the saved training label must equal the injected class "
        "ids; palette conversion (or any other transform) must not be applied "
        "to the semseg_raw training label"
    )
    assert result.semseg_raw_path == raw_label_path


def test_capture_does_not_land_training_label_under_labels_dir(tmp_path):
    """The trainer/eval/class-weight readers all look under `semseg_raw/`, not
    `labels/`. A capture run must not produce a `labels/` directory tree for
    the semantic training label (that was the legacy, incompatible layout).
    """
    from ultimate_pipeline.perception.capture_writer import save_capture_frame

    _, seg_img, _ = _make_synthetic_frame()
    out_root = tmp_path / "ds"

    save_capture_frame(
        out_root,
        camera="front",
        frame=1,
        rgb_image=None,
        seg_image=seg_img,
        label_mode="semantic",
    )

    assert not (out_root / "labels").exists(), (
        "capture must not write the training label under labels/<cam>/ "
        "(that layout is unreadable by min_train_segmentation / eval_sim_labeled "
        "/ class_weights, which all read semseg_raw/<cam>/)"
    )


def test_min_train_segmentation_dataset_finds_pairs_from_capture_output(tmp_path):
    """Round-trip: capture-save a synthetic frame, then confirm
    SegDataset (min_train_segmentation) finds >0 rgb/semseg_raw pairs and
    the loaded label tensor matches the injected class ids."""
    from ultimate_pipeline.perception.capture_writer import save_capture_frame
    from ultimate_pipeline.perception.min_train_segmentation import SegDataset

    rgb_img, seg_img, ids = _make_synthetic_frame()
    out_root = tmp_path / "ds"

    save_capture_frame(
        out_root,
        camera="front",
        frame=1,
        rgb_image=rgb_img,
        seg_image=seg_img,
        label_mode="semantic",
    )

    ds = SegDataset(out_root, cam="front")
    assert len(ds) > 0, (
        "SegDataset must find >=1 rgb/semseg_raw pair given the capture's "
        "actual output directories"
    )

    x, y = ds[0]
    assert x.shape[0] == 3  # RGB tensor
    y_np = y.numpy()
    assert y_np.shape == ids.shape
    assert np.array_equal(y_np.astype(np.uint8), ids)
    assert int(y_np.min()) >= 0
    assert int(y_np.max()) < CARLA_SEMANTIC_NUM_CLASSES


# ---------------------------------------------------------------------------
# GREEN: degenerate-label guard
# ---------------------------------------------------------------------------


def test_degenerate_all_background_capture_is_flagged(tmp_path):
    """An all-background synthetic frame must round-trip to a label that
    label_quality.is_degenerate_label flags, proving the raw ids (not
    palette colors, which would never be all-zero the same way) are what's
    actually being persisted and read back."""
    from ultimate_pipeline.perception.capture_writer import save_capture_frame
    from ultimate_pipeline.perception.min_train_segmentation import SegDataset

    h, w = 6, 8
    seg_bgra = np.zeros((h, w, 4), dtype=np.uint8)  # all class id 0 (background)
    rgb_bgra = np.zeros((h, w, 4), dtype=np.uint8)
    seg_img = _FakeCarlaImage(seg_bgra)
    rgb_img = _FakeCarlaImage(rgb_bgra)

    out_root = tmp_path / "ds"
    save_capture_frame(
        out_root,
        camera="front",
        frame=2,
        rgb_image=rgb_img,
        seg_image=seg_img,
        label_mode="semantic",
    )

    ds = SegDataset(out_root, cam="front")
    _, y = ds[0]
    assert is_degenerate_label(y.numpy()) is True


# ---------------------------------------------------------------------------
# Detection labels: explicit no-op, not fabricated empty "valid" labels
# ---------------------------------------------------------------------------


def test_detection_mode_does_not_fabricate_silent_empty_labels(tmp_path):
    """Non-semantic capture must not silently write empty YOLO .txt files
    that downstream code could mistake for "no objects present" ground
    truth. It must either write real boxes or perform an explicit, logged
    no-op (no fabricated per-frame label files)."""
    from ultimate_pipeline.perception.capture_writer import save_capture_frame

    rgb_img, _, _ = _make_synthetic_frame()
    out_root = tmp_path / "ds"

    result = save_capture_frame(
        out_root,
        camera="front",
        frame=1,
        rgb_image=rgb_img,
        seg_image=None,
        label_mode="none",
    )

    assert result.detection_status == "explicit_noop"
    # No fabricated empty label file anywhere under the dataset root.
    txt_files = list(out_root.rglob("*.txt"))
    fabricated_labels = [p for p in txt_files if p.parent.name == "front" and "label" not in p.parent.parts[-2]]
    assert not any(p.stat().st_size == 0 and "detection" not in p.name for p in txt_files), (
        "no silent empty label .txt files should be written for detection mode"
    )


# ---------------------------------------------------------------------------
# Validation: out-of-range ids fail closed
# ---------------------------------------------------------------------------


def test_out_of_range_ids_fail_closed(tmp_path):
    from ultimate_pipeline.perception.capture_writer import save_capture_frame

    h, w = 4, 4
    seg_bgra = np.zeros((h, w, 4), dtype=np.uint8)
    seg_bgra[:, :, 2] = 250  # out of [0, CARLA_SEMANTIC_MAX_CLASS_ID]
    seg_img = _FakeCarlaImage(seg_bgra)
    out_root = tmp_path / "ds"

    with pytest.raises(ValueError):
        save_capture_frame(
            out_root,
            camera="front",
            frame=1,
            rgb_image=None,
            seg_image=seg_img,
            label_mode="semantic",
        )
