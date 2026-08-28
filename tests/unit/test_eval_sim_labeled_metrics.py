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
import numpy as np
import torch
import torchvision
from PIL import Image

from ultimate_pipeline.perception.eval_sim_labeled import (
    _compute_iou_per_class,
    _compute_pixel_accuracy,
    evaluate_model,
)
from ultimate_pipeline.perception.carla_classes import CARLA_SEMANTIC_ANY_CLASS_ID
from ultimate_pipeline.perception.semantic_classes import CARLA_SEMANTIC_NUM_CLASSES


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


def _write_labeled_dataset(root, camera, n=3, h=16, w=16, seed=0):
    rgb_dir = root / "rgb" / camera
    seg_dir = root / "semseg_raw" / camera
    rgb_dir.mkdir(parents=True)
    seg_dir.mkdir(parents=True)
    rng = np.random.default_rng(seed)
    for i in range(n):
        rgb = rng.integers(0, 255, size=(h, w, 3), dtype=np.uint8)
        Image.fromarray(rgb, mode="RGB").save(rgb_dir / f"{i:08d}.png")
        lab = np.zeros((h, w), dtype=np.uint8)
        lab[: h // 2, :] = 7
        lab[h // 2 :, :] = CARLA_SEMANTIC_ANY_CLASS_ID  # real Any pixels, like real captures
        Image.fromarray(lab, mode="L").save(seg_dir / f"{i:08d}.png")


def test_evaluate_model_end_to_end_on_a_real_dataset_and_real_checkpoint(tmp_path):
    """The CLI-level entrypoint (evaluate_model) that RQ3-mIoU's train-auto/eval-manual
    comparison actually calls has never been exercised end-to-end -- only its two
    pure helper functions were unit-tested above. This proves the full path (find
    paired files -> load real PNGs -> real fcn_resnet50 forward pass -> aggregate)
    runs to completion against on-disk data shaped exactly like a real capture_writer
    output (including real Any=255 pixels), and that the aggregated report has the
    schema downstream domain_gap code expects.
    """
    camera = "front_left_camera"
    dataset_root = tmp_path / "dataset"
    _write_labeled_dataset(dataset_root, camera, n=3)

    num_classes = CARLA_SEMANTIC_NUM_CLASSES
    model = torchvision.models.segmentation.fcn_resnet50(weights=None, num_classes=num_classes)
    model_path = tmp_path / "model.pt"
    torch.save(model.state_dict(), model_path)

    result = evaluate_model(
        model_path=model_path,
        dataset_root=dataset_root,
        camera=camera,
        num_classes=num_classes,
        device="cpu",
    )

    assert result["frames_count"] == 3
    assert "error" not in result
    assert 0.0 <= result["mIoU"] <= 1.0
    assert 0.0 <= result["pixel_accuracy"] <= 1.0
    # Any(255) must never leak into per-class IoU as a scored "class".
    assert CARLA_SEMANTIC_ANY_CLASS_ID not in result["per_class_iou"]


def test_evaluate_model_reports_a_clear_error_when_no_paired_files_exist(tmp_path):
    """A camera name mismatch (e.g. dataset written under 'front_left_camera' but
    evaluated with the wrong subdirectory) is a real footgun -- min_train_segmentation.py's
    CLI defaults to camera='front' while eval_sim_labeled.py and the rest of the
    perception CLIs default to 'front_left_camera'. evaluate_model must not silently
    report a fake 0.0 mIoU as if 0 real frames were evaluated; it must surface an
    explicit error so a mismatched --camera flag is caught immediately, not mistaken
    for a real (if bad) RQ3-mIoU number.
    """
    dataset_root = tmp_path / "dataset"
    _write_labeled_dataset(dataset_root, "front_left_camera", n=2)

    num_classes = CARLA_SEMANTIC_NUM_CLASSES
    model = torchvision.models.segmentation.fcn_resnet50(weights=None, num_classes=num_classes)
    model_path = tmp_path / "model.pt"
    torch.save(model.state_dict(), model_path)

    result = evaluate_model(
        model_path=model_path,
        dataset_root=dataset_root,
        camera="front",  # mismatched camera name -- no rgb/front or semseg_raw/front exists
        num_classes=num_classes,
        device="cpu",
    )

    assert result["frames_count"] == 0
    assert result["mIoU"] == 0.0
    assert "error" in result and "front" in result["error"]
