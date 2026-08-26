"""C27: eval_sim_labeled.py metrics on a KNOWN confusion, including CARLA's Any (255)
sentinel class -- now legitimately present in loaded labels since carla_classes.py was
fixed to accept it (previously assert_label_ids_in_range rejected it outright).

_compute_iou_per_class already (accidentally) excludes Any=255 -- its `range(num_classes)`
loop never reaches 255, so mIoU is safe. But _compute_pixel_accuracy has no such
exclusion: it counts every pixel, and since the segmentation model's head has only
`num_classes` (29) output channels, a prediction can NEVER equal target==255 -- every
Any-labeled pixel is an unavoidable miss, systematically deflating pixel accuracy by
however many Any pixels are in the scene (commonly sky/unclassified geometry).
"""
import torch

from ultimate_pipeline.perception.eval_sim_labeled import (
    _compute_iou_per_class,
    _compute_pixel_accuracy,
)
from ultimate_pipeline.perception.carla_classes import CARLA_SEMANTIC_ANY_CLASS_ID


def test_iou_per_class_known_confusion():
    # 2x2 target: class 7 top row, class 10 bottom row. pred gets top row exactly
    # right, bottom row half right (one pixel predicted as 7 instead of 10).
    target = torch.tensor([[7, 7], [10, 10]], dtype=torch.int64)
    pred = torch.tensor([[7, 7], [10, 7]], dtype=torch.int64)
    ious = _compute_iou_per_class(pred, target, num_classes=29)
    # class 7: intersection={2 correct top}=2, union={2 top + 1 wrong-bottom}=3 -> 2/3
    assert abs(ious[7] - (2 / 3)) < 1e-9
    # class 10: intersection=1 (bottom-right correct), union=2 (both target 10s) -> 1/2
    assert abs(ious[10] - 0.5) < 1e-9


def test_pixel_accuracy_known_confusion_no_any():
    target = torch.tensor([[7, 7], [10, 10]], dtype=torch.int64)
    pred = torch.tensor([[7, 7], [10, 7]], dtype=torch.int64)
    acc = _compute_pixel_accuracy(pred, target)
    assert abs(acc - 0.75) < 1e-9  # 3/4 correct


def test_pixel_accuracy_is_deflated_by_unanswerable_any_pixels_without_ignore_index():
    # 1 Any(255) pixel a 29-class model can NEVER predict correctly, mixed with 3
    # perfectly-predicted named-class pixels. A metric that "fairly" scores only
    # answerable pixels should report 1.0, not 0.75.
    target = torch.tensor([[7, 7], [10, CARLA_SEMANTIC_ANY_CLASS_ID]], dtype=torch.int64)
    pred = torch.tensor([[7, 7], [10, 3]], dtype=torch.int64)  # perfect on all named pixels
    acc = _compute_pixel_accuracy(pred, target, ignore_index=CARLA_SEMANTIC_ANY_CLASS_ID)
    assert abs(acc - 1.0) < 1e-9, (
        f"pixel accuracy should exclude the unanswerable Any pixel and report 1.0, got {acc}"
    )


def test_pixel_accuracy_without_ignore_index_still_counts_everything_backward_compat():
    # No ignore_index passed -> old behavior preserved (counts all pixels, including Any).
    target = torch.tensor([[7, 7], [10, CARLA_SEMANTIC_ANY_CLASS_ID]], dtype=torch.int64)
    pred = torch.tensor([[7, 7], [10, 3]], dtype=torch.int64)
    acc = _compute_pixel_accuracy(pred, target)
    assert abs(acc - 0.75) < 1e-9


def test_iou_per_class_never_scores_any_as_a_class():
    target = torch.tensor([[CARLA_SEMANTIC_ANY_CLASS_ID, 7]], dtype=torch.int64)
    pred = torch.tensor([[7, 7]], dtype=torch.int64)
    ious = _compute_iou_per_class(pred, target, num_classes=29)
    assert CARLA_SEMANTIC_ANY_CLASS_ID not in ious
