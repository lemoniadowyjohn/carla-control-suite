from __future__ import annotations

import numpy as np

from ultimate_pipeline.perception.label_quality import label_stats, is_degenerate_label


def test_label_stats_counts_classes_and_fractions():
    m = np.array([[0, 0, 7], [7, 10, 10]], dtype=np.uint8)  # classes {0,7,10}, each count 2
    s = label_stats(m)
    assert s["n_classes"] == 3
    assert abs(s["nonbackground_fraction"] - 4 / 6) < 1e-9  # non-zero pixels
    assert abs(s["dominant_class_fraction"] - 2 / 6) < 1e-9


def test_all_background_mask_is_degenerate():
    m = np.zeros((8, 8), dtype=np.uint8)
    assert is_degenerate_label(m) is True


def test_single_pixel_class_is_degenerate_by_dominance():
    m = np.zeros((10, 10), dtype=np.uint8)
    m[0, 0] = 7  # 99% class 0 -> dominant fraction 0.99 > 0.98
    assert is_degenerate_label(m) is True


def test_diverse_mask_is_not_degenerate():
    m = np.zeros((10, 10), dtype=np.uint8)
    m[:5] = 7
    m[5:8] = 10  # classes {0,7,10}; dominant 0.5
    assert is_degenerate_label(m) is False


def test_write_png_raw_ids_extracts_r_channel_class_ids(tmp_path):
    # Characterization: the seg generator's label extraction must equal the R
    # channel (BGRA) of the semantic image, exactly (locks R8's label pipeline).
    from ultimate_pipeline.perception.segmentation_dataset_generator_queues import (
        _write_png_raw_ids,
    )
    from PIL import Image

    h, w = 4, 5
    ids = np.arange(h * w, dtype=np.uint8).reshape(h, w)
    bgra = np.zeros((h, w, 4), dtype=np.uint8)
    bgra[:, :, 2] = ids  # R channel carries the class id

    class _FakeImg:
        raw_data = bgra.tobytes()
        height = h
        width = w

    out = tmp_path / "raw.png"
    _write_png_raw_ids(_FakeImg(), out)
    back = np.array(Image.open(out))
    assert back.shape == (h, w)
    assert np.array_equal(back, ids)
