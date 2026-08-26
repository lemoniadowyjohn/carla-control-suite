"""C27: capture must correctly handle CARLA's `Any` semantic class.

carla.CityObjectLabel.Any == 255 (verified against the installed carla package;
distinct from the 0-28 named-class range, CARLA's sentinel for unclassified/
miscellaneous pixels -- a normal, common occurrence in real captures, not
corruption). CARLA_SEMANTIC_MAX_CLASS_ID == 28, so assert_label_ids_in_range
previously rejected ANY frame containing an Any pixel -- i.e. it would crash on
essentially every real CARLA semantic capture. This was never caught because
CARLA has been broken all session, so capture_writer.save_capture_frame was
never actually fed a real (or realistic) frame containing id=255.
"""
import numpy as np
import pytest

from ultimate_pipeline.perception.capture_writer import save_capture_frame
from ultimate_pipeline.perception.carla_classes import assert_label_ids_in_range


class _FakeCarlaImage:
    def __init__(self, bgra: np.ndarray):
        assert bgra.ndim == 3 and bgra.shape[2] == 4
        self.raw_data = bgra.tobytes()
        self.height = int(bgra.shape[0])
        self.width = int(bgra.shape[1])


def _seg_frame_with_any(h=6, w=8):
    ids = np.zeros((h, w), dtype=np.uint8)
    ids[: h // 2, :] = 7      # a named class (RoadLines)
    ids[h // 2:, :] = 255     # carla.CityObjectLabel.Any -- a real, legitimate value
    bgra = np.zeros((h, w, 4), dtype=np.uint8)
    bgra[:, :, 2] = ids
    return _FakeCarlaImage(bgra), ids


def test_assert_label_ids_in_range_accepts_any_255():
    _, ids = _seg_frame_with_any()
    assert_label_ids_in_range(ids)  # must NOT raise


def test_capture_does_not_crash_on_a_frame_containing_any_255(tmp_path):
    seg_image, ids = _seg_frame_with_any()
    result = save_capture_frame(
        tmp_path, camera="cam0", frame=1, seg_image=seg_image, label_mode="semantic"
    )
    assert result.semseg_raw_path is not None
    assert result.semseg_raw_path.is_file()


def test_written_raw_label_preserves_255_verbatim(tmp_path):
    from PIL import Image as PILImage

    seg_image, ids = _seg_frame_with_any()
    result = save_capture_frame(
        tmp_path, camera="cam0", frame=1, seg_image=seg_image, label_mode="semantic"
    )
    written = np.array(PILImage.open(result.semseg_raw_path))
    assert (written == ids).all()
    assert 255 in written


def test_assert_label_ids_in_range_still_rejects_true_corruption():
    # A value that is neither a named class (0-28) nor Any (255) is real corruption.
    bad = np.array([[7, 200]], dtype=np.uint8)
    with pytest.raises(ValueError):
        assert_label_ids_in_range(bad)
