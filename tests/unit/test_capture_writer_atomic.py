"""NEW-274: capture_writer must commit frames atomically (temp-rename).

A crash at any point during a frame write must leave either no file or the
previous complete frame -- never a torn PNG, and never a stray temp file.
"""
import numpy as np
import pytest

from ultimate_pipeline.perception import capture_writer
from ultimate_pipeline.perception.capture_writer import save_capture_frame


class _FakeCarlaImage:
    def __init__(self, bgra: np.ndarray):
        assert bgra.ndim == 3 and bgra.shape[2] == 4
        self.raw_data = bgra.tobytes()
        self.height = int(bgra.shape[0])
        self.width = int(bgra.shape[1])


def _rgb_frame(h=6, w=8):
    bgra = np.zeros((h, w, 4), dtype=np.uint8)
    bgra[:, :, 0] = 10
    bgra[:, :, 1] = 20
    bgra[:, :, 2] = 30
    bgra[:, :, 3] = 255
    return _FakeCarlaImage(bgra)


def _seg_frame(h=6, w=8):
    bgra = np.zeros((h, w, 4), dtype=np.uint8)
    bgra[:, :, 2] = 7
    return _FakeCarlaImage(bgra)


def _no_tmps(root):
    return [p for p in root.rglob("*") if p.suffix == ".tmp" or ".tmp" in p.name]


def test_successful_write_leaves_no_temp_files(tmp_path):
    save_capture_frame(
        tmp_path, camera="cam0", frame=1, rgb_image=_rgb_frame(),
        seg_image=_seg_frame(), label_mode="semantic", write_viz=True,
    )
    assert _no_tmps(tmp_path) == []
    assert (tmp_path / "rgb" / "cam0" / "00000001.png").is_file()
    assert (tmp_path / "semseg_raw" / "cam0" / "00000001.png").is_file()
    assert (tmp_path / "semseg_viz" / "cam0" / "00000001.png").is_file()


def test_failed_raw_write_leaves_no_partial_file(tmp_path, monkeypatch):
    real = capture_writer._write_png_raw_ids

    def _boom(image, path):
        with open(path, "wb") as f:
            f.write(b"partial-bytes")
        raise RuntimeError("simulated crash mid-write")

    monkeypatch.setattr(capture_writer, "_write_png_raw_ids", _boom)
    with pytest.raises(RuntimeError):
        save_capture_frame(
            tmp_path, camera="cam0", frame=2, seg_image=_seg_frame(),
            label_mode="semantic",
        )
    # Neither the torn final file nor the temp staging file may survive.
    assert not (tmp_path / "semseg_raw" / "cam0" / "00000002.png").exists()
    assert _no_tmps(tmp_path) == []


def test_overwrite_failure_keeps_previous_complete_frame(tmp_path):
    import PIL.Image as PILImage

    first = save_capture_frame(
        tmp_path, camera="cam0", frame=3, rgb_image=_rgb_frame(),
        label_mode="none",
    )
    before = first.rgb_path.read_bytes()

    # Fail the *second* write of the same frame path mid-save.
    def _boom(self, fp, *a, **k):
        raise RuntimeError("simulated crash mid-save")

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(PILImage.Image, "save", _boom)
        with pytest.raises(RuntimeError):
            save_capture_frame(
                tmp_path, camera="cam0", frame=3, rgb_image=_rgb_frame(),
                label_mode="none",
            )
    finally:
        monkeypatch.undo()
    # Previous complete frame intact, no temp debris.
    assert first.rgb_path.read_bytes() == before
    assert _no_tmps(tmp_path) == []
