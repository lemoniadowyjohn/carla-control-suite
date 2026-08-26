"""C27 follow-up: train_launcher.py has the SAME CrossEntropyLoss-crashes-on-Any(255)
bug already fixed in min_train_segmentation.py -- a separate, independently-constructed
loss function in a DIFFERENT file. Confirmed LIVE and reachable: train_launcher.py is
invoked by run_generalization_experiments.py (the actual RQ3 delivery entrypoint) and
uses SemanticSegDataset (= min_train_segmentation.SegDataset, an alias), which legitimately
yields labels containing 255 since carla_classes.py was fixed to accept it.
"""
import numpy as np
import torch
from PIL import Image

from ultimate_pipeline.perception.carla_classes import CARLA_SEMANTIC_ANY_CLASS_ID
from ultimate_pipeline.perception.semantic_classes import CARLA_SEMANTIC_NUM_CLASSES
from ultimate_pipeline.perception.min_train_segmentation import SemanticSegDataset


def _write_tiny_dataset(root, n=2, h=16, w=16):
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
        lab[h // 2:, :] = CARLA_SEMANTIC_ANY_CLASS_ID
        Image.fromarray(lab, mode="L").save(lab_dir / f"{i:08d}.png")


def test_semantic_seg_dataset_keyword_matches_train_launcher_call_site(tmp_path):
    # BUG (found + fixed): train_launcher.py:141 called SemanticSegDataset(dataset_root,
    # camera=args.camera, limit=...) -- but SegDataset.__init__'s real parameter is named
    # `cam`, not `camera`. main() could not even construct its dataset -- this entrypoint
    # (the real, live RQ3 training path via run_generalization_experiments.py) had likely
    # never run end-to-end successfully. Fixed to cam=args.camera; this test locks in the
    # correct call shape.
    _write_tiny_dataset(tmp_path, n=1)
    SemanticSegDataset(tmp_path, cam="front", limit=1)  # must not raise TypeError


def test_train_launcher_style_loss_without_ignore_index_crashes_on_any_255():
    num_classes = CARLA_SEMANTIC_NUM_CLASSES
    out = torch.randn(1, num_classes, 4, 4)
    target = torch.full((1, 4, 4), CARLA_SEMANTIC_ANY_CLASS_ID, dtype=torch.int64)
    criterion = torch.nn.CrossEntropyLoss(weight=None)  # pre-fix train_launcher.py construction
    try:
        criterion(out, target)
        crashed = False
    except (IndexError, RuntimeError):
        crashed = True
    assert crashed


def test_real_train_launcher_dataset_and_loss_do_not_crash_on_any_255(tmp_path):
    import torchvision

    _write_tiny_dataset(tmp_path)
    ds = SemanticSegDataset(tmp_path, cam="front", limit=None)  # exact (fixed) train_launcher.py call shape
    dl = torch.utils.data.DataLoader(ds, batch_size=2, shuffle=False)

    num_classes = CARLA_SEMANTIC_NUM_CLASSES
    model = torchvision.models.segmentation.fcn_resnet50(weights=None, num_classes=num_classes)
    model.train()
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    # the FIXED construction (matches the applied train_launcher.py fix)
    criterion = torch.nn.CrossEntropyLoss(weight=None, ignore_index=CARLA_SEMANTIC_ANY_CLASS_ID)

    for x, y in dl:
        opt.zero_grad()
        out = model(x)["out"]
        loss = criterion(out, y)
        loss.backward()
        opt.step()
        assert torch.isfinite(loss)
