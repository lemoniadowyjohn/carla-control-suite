"""C27: min_train_segmentation.py's loss function must ignore Any(255) pixels.

Third instance of the same bug class (after capture_writer's assert_label_ids_in_range
and eval_sim_labeled's pixel_accuracy): SegDataset now legitimately yields label tensors
containing 255 (CARLA's Any sentinel, since carla_classes.py was fixed to accept it), but
the training loop's `torch.nn.CrossEntropyLoss(weight=class_weights)` had no `ignore_index`.
PyTorch's CrossEntropyLoss requires target values in [0, num_classes) or the configured
ignore_index -- passing 255 with num_classes=29 raises IndexError, i.e. training would
CRASH on the first batch containing an Any pixel, not just misreport a metric.

class_weights.scan_label_class_counts is already safe (np.bincount sliced to
[:num_classes], silently excludes 255) -- verified, not touched here.
"""
import numpy as np
import torch
from PIL import Image

from ultimate_pipeline.perception.carla_classes import CARLA_SEMANTIC_ANY_CLASS_ID
from ultimate_pipeline.perception.semantic_classes import CARLA_SEMANTIC_NUM_CLASSES
from ultimate_pipeline.perception.min_train_segmentation import SegDataset


def _write_tiny_dataset(root, n=3, h=16, w=16):
    rgb_dir = root / "rgb" / "front"
    lab_dir = root / "semseg_raw" / "front"
    rgb_dir.mkdir(parents=True)
    lab_dir.mkdir(parents=True)
    rng = np.random.default_rng(0)
    for i in range(n):
        rgb = rng.integers(0, 255, size=(h, w, 3), dtype=np.uint8)
        Image.fromarray(rgb, mode="RGB").save(rgb_dir / f"{i:08d}.png")
        lab = np.zeros((h, w), dtype=np.uint8)
        lab[: h // 2, :] = 7
        lab[h // 2:, :] = CARLA_SEMANTIC_ANY_CLASS_ID  # every frame has real Any pixels
        Image.fromarray(lab, mode="L").save(lab_dir / f"{i:08d}.png")


def test_crossentropy_without_ignore_index_crashes_on_any_255():
    num_classes = CARLA_SEMANTIC_NUM_CLASSES
    out = torch.randn(1, num_classes, 4, 4)
    target = torch.full((1, 4, 4), CARLA_SEMANTIC_ANY_CLASS_ID, dtype=torch.int64)
    loss_fn = torch.nn.CrossEntropyLoss()  # the pre-fix construction (no ignore_index)
    try:
        loss_fn(out, target)
        crashed = False
    except (IndexError, RuntimeError):
        crashed = True
    assert crashed, "expected CrossEntropyLoss to reject an unconfigured 255 target"


def test_crossentropy_with_ignore_index_handles_any_255_without_crashing():
    # A realistic MIXED target (some named-class pixels, some Any) -- not the degenerate
    # all-Any case, which legitimately produces NaN (0/0 mean over zero valid elements;
    # documented PyTorch CrossEntropyLoss behavior, not a bug to work around here).
    num_classes = CARLA_SEMANTIC_NUM_CLASSES
    out = torch.randn(1, num_classes, 4, 4)
    target = torch.full((1, 4, 4), CARLA_SEMANTIC_ANY_CLASS_ID, dtype=torch.int64)
    target[0, :2, :] = 7  # half named-class pixels
    loss_fn = torch.nn.CrossEntropyLoss(ignore_index=CARLA_SEMANTIC_ANY_CLASS_ID)
    loss = loss_fn(out, target)
    assert torch.isfinite(loss)  # does not crash, and is a well-defined real number


def test_seg_dataset_yields_any_255_labels_without_crashing(tmp_path):
    _write_tiny_dataset(tmp_path)
    ds = SegDataset(tmp_path, "front")
    x, y = ds[0]
    assert CARLA_SEMANTIC_ANY_CLASS_ID in y.unique().tolist()


def test_real_training_step_on_a_tiny_dataset_with_any_255_does_not_crash_and_loss_is_finite(tmp_path):
    import torchvision

    _write_tiny_dataset(tmp_path, n=2, h=16, w=16)
    ds = SegDataset(tmp_path, "front")
    dl = torch.utils.data.DataLoader(ds, batch_size=2, shuffle=False)

    num_classes = CARLA_SEMANTIC_NUM_CLASSES
    model = torchvision.models.segmentation.fcn_resnet50(weights=None, num_classes=num_classes)
    model.train()
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = torch.nn.CrossEntropyLoss(ignore_index=CARLA_SEMANTIC_ANY_CLASS_ID)

    for x, y in dl:
        opt.zero_grad()
        out = model(x)["out"]
        loss = loss_fn(out, y)
        loss.backward()
        opt.step()
        assert torch.isfinite(loss)
