from __future__ import annotations

"""RQ5a plumbing smoke test: run train_launcher.main() -- the REAL training
entrypoint (invoked in production both as a subprocess by
run_generalization_experiments.py and by direct import in
perception/run_training.py's "local" backend) -- end-to-end against a small
synthetic dataset shaped exactly like a real capture:

    <dataset_root>/rgb/<camera>/<frame:08d>.png          RGB uint8
    <dataset_root>/semseg_raw/<camera>/<frame:08d>.png   single-channel uint8
                                                          class ids in
                                                          [0, CARLA_SEMANTIC_MAX_CLASS_ID]
                                                          plus CARLA's Any(255)
                                                          sentinel (see
                                                          dataset_generator.py's
                                                          path_template docs and
                                                          carla_classes.py).

RQ5a (synthetic-to-real transfer) needs a real trained checkpoint, which needs
real CARLA-captured data, which is blocked on a live CARLA connection. This
test does NOT attempt to produce a usable/trained checkpoint -- it is a pure
integration/plumbing smoke test proving that, once real captured data exists,
the full training code path (dataset loading -> class-weight scan -> model
forward -> loss incl. Any(255) ignore_index -> backward -> optimizer step ->
checkpoint save) executes cleanly through the actual CLI entrypoint (main(),
driven by argv, exactly as a real invocation would).
"""

import sys

import numpy as np
import torch
from PIL import Image

from ultimate_pipeline.perception.carla_classes import CARLA_SEMANTIC_ANY_CLASS_ID
from ultimate_pipeline.perception.semantic_classes import CARLA_SEMANTIC_NUM_CLASSES


def _write_synthetic_dataset(root, camera: str, n=3, h=32, w=32,
                              num_classes=CARLA_SEMANTIC_NUM_CLASSES, seed=42):
    """Structurally-correct fake capture: random RGB + random per-pixel class
    ids (with a sprinkling of CARLA's Any(255) sentinel, as real captures
    contain), matching dataset_generator.py's rgb/<cam>/ + semseg_raw/<cam>/
    layout and <frame:08d>.png naming exactly. Content is meaningless -- only
    shape/format needs to match a real capture.
    """
    rgb_dir = root / "rgb" / camera
    lab_dir = root / "semseg_raw" / camera
    rgb_dir.mkdir(parents=True)
    lab_dir.mkdir(parents=True)
    rng = np.random.default_rng(seed)
    for i in range(n):
        rgb = rng.integers(0, 255, size=(h, w, 3), dtype=np.uint8)
        Image.fromarray(rgb, mode="RGB").save(rgb_dir / f"{i:08d}.png")

        lab = rng.integers(0, num_classes, size=(h, w), dtype=np.uint8)
        any_mask = rng.random((h, w)) < 0.1
        lab[any_mask] = CARLA_SEMANTIC_ANY_CLASS_ID
        Image.fromarray(lab, mode="L").save(lab_dir / f"{i:08d}.png")


def test_train_launcher_main_runs_end_to_end_on_synthetic_dataset(tmp_path, monkeypatch):
    """Drive the actual CLI entrypoint (argv -> argparse -> training loop ->
    checkpoint save), not a hand-reimplemented subset of it, so this catches
    argparse wiring bugs, class-weight-scan integration, out-dir resolution,
    and checkpoint I/O -- not just the dataset/loss pieces already covered by
    test_train_launcher_any_255.py.
    """
    dataset_dir = tmp_path / "synthetic_run"
    out_dir = tmp_path / "out"
    camera = "front_left_camera"
    _write_synthetic_dataset(dataset_dir, camera, n=3, h=32, w=32)

    argv = [
        "train_launcher.py",
        "--dataset", str(dataset_dir),
        "--camera", camera,
        "--out-dir", str(out_dir),
        "--epochs", "1",
        "--batch", "2",
        "--lr", "1e-4",
        "--num-classes", str(CARLA_SEMANTIC_NUM_CLASSES),
        "--limit", "0",
        "--device", "cpu",
        "--num-workers", "0",
    ]
    monkeypatch.setattr(sys, "argv", argv)

    from ultimate_pipeline.perception import train_launcher

    train_launcher.main()  # must not raise: real end-to-end plumbing smoke test

    ckpts = sorted(out_dir.glob("seg_fcn_epoch*.pt"))
    assert len(ckpts) == 1, f"expected exactly one epoch-1 checkpoint, got {ckpts}"

    # Checkpoint must actually be a loadable, shape-correct state_dict for the
    # same architecture main() trains -- catches silent save/load corruption
    # or an architecture/num-classes mismatch, not just "a file exists".
    state = torch.load(ckpts[0], map_location="cpu")
    fresh = train_launcher._build_model(CARLA_SEMANTIC_NUM_CLASSES)
    fresh.load_state_dict(state)  # raises on any key/shape mismatch
