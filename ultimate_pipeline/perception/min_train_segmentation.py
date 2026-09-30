#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minimal PyTorch semantic segmentation trainer.

- Uses torchvision FCN (fcn_resnet50) as a quick baseline.
- Reads:
    rgb/<cam>/*.png
    semseg_raw/<cam>/*.png  (uint8 class ids)
- Writes:
    out_dir/checkpoints/model_last.pt
    out_dir/metrics.json

This is a minimal working solution to unblock thesis experiments.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
from PIL import Image

import torch
from torch.utils.data import Dataset, DataLoader
import torchvision
from torchvision.transforms import functional as TF

from ultimate_pipeline.perception.carla_classes import (
    CARLA_SEMANTIC_ANY_CLASS_ID,
    assert_label_ids_in_range,
)
from ultimate_pipeline.perception.class_weights import (
    compute_class_weights,
    scan_dataset_class_counts,
)
from ultimate_pipeline.perception.semantic_classes import (
    CARLA_SEMANTIC_NUM_CLASSES,
    validate_num_classes,
)


class SegDataset(Dataset):
    def __init__(self, root: Path, cam: str, limit: int = 0):
        self.rgb_dir = root / "rgb" / cam
        self.lab_dir = root / "semseg_raw" / cam
        self.items = sorted([p for p in self.rgb_dir.glob("*.png")])
        if limit and limit > 0:
            self.items = self.items[:limit]

    def __len__(self):
        return len(self.items)

    def __getitem__(self, idx):
        rgb_path = self.items[idx]
        lab_path = self.lab_dir / rgb_path.name
        img = Image.open(rgb_path).convert("RGB")
        lab = Image.open(lab_path).convert("L")

        x = TF.to_tensor(img)
        arr = np.array(lab, dtype=np.uint8)
        assert_label_ids_in_range(arr)
        y = torch.from_numpy(arr.astype(np.int64))
        return x, y


class MultiRootSegDataset(Dataset):
    """NEW-234: train on a true union of K dataset roots.

    The RQ5 K-sweep varies K = number of generated maps used for training. A
    single-root dataset cannot express that: passing only ``dataset_roots[0]`` to
    the trainer meant K=1, K=3 and K=5 could all train on the same first
    dataset while their manifests claimed 1/3/5 roots.

    This dataset indexes ``(root, rgb_path, lab_path)`` triples across every
    supplied root. Only *paired* frames are indexed -- a root that has an RGB
    frame with no matching label would otherwise raise deep inside
    ``__getitem__`` at batch time, i.e. after the run has already been recorded.

    The member order is deterministic: roots in the order supplied, frames
    sorted by filename within each root. That keeps the K-sweep reproducible for
    a fixed seed and keeps ``limit`` slicing meaningful.
    """

    def __init__(self, roots, cam: str, limit: int = 0):
        if isinstance(roots, (str, Path)):
            roots = [roots]
        roots = [Path(r) for r in (roots or [])]
        if not roots:
            raise ValueError("MultiRootSegDataset requires at least one dataset root")
        if len(roots) != len({str(r.resolve()) for r in roots if r.exists()}):
            raise ValueError(
                "MultiRootSegDataset received duplicate dataset roots: "
                + ", ".join(str(r) for r in roots)
            )

        self.roots = roots
        self.camera = str(cam)
        self.items: List[Tuple[Path, Path]] = []
        self.unpaired_rgb: List[str] = []
        self.unpaired_labels: List[str] = []

        for root in roots:
            rgb_dir = root / "rgb" / self.camera
            lab_dir = root / "semseg_raw" / self.camera
            if not rgb_dir.is_dir() or not lab_dir.is_dir():
                raise FileNotFoundError(
                    f"dataset root {root} does not contain both rgb/{self.camera} and "
                    f"semseg_raw/{self.camera}"
                )
            rgb_names = {p.name for p in rgb_dir.glob("*.png")}
            lab_names = {p.name for p in lab_dir.glob("*.png")}
            for name in sorted(rgb_names - lab_names):
                self.unpaired_rgb.append(f"{root.as_posix()}/rgb/{self.camera}/{name}")
            for name in sorted(lab_names - rgb_names):
                self.unpaired_labels.append(
                    f"{root.as_posix()}/semseg_raw/{self.camera}/{name}"
                )
            for name in sorted(rgb_names & lab_names):
                self.items.append((rgb_dir / name, lab_dir / name))

        if not self.items:
            raise FileNotFoundError(
                f"no paired rgb/semseg_raw/<{self.camera}> frames found across roots: "
                + ", ".join(r.as_posix() for r in roots)
            )

        if limit and limit > 0:
            self.items = self.items[:limit]

    @property
    def root_frame_counts(self) -> Dict[str, int]:
        """Frames contributed by each root, for manifest/evidence recording."""
        counts: Dict[str, int] = {r.as_posix(): 0 for r in self.roots}
        for rgb_path, _ in self.items:
            for root in self.roots:
                try:
                    rgb_path.relative_to(root)
                except ValueError:
                    continue
                counts[root.as_posix()] += 1
                break
        return counts

    def __len__(self):
        return len(self.items)

    def __getitem__(self, idx):
        rgb_path, lab_path = self.items[idx]
        img = Image.open(rgb_path).convert("RGB")
        lab = Image.open(lab_path).convert("L")

        x = TF.to_tensor(img)
        arr = np.array(lab, dtype=np.uint8)
        assert_label_ids_in_range(arr)
        y = torch.from_numpy(arr.astype(np.int64))
        return x, y


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, help="path to datasets/<name>")
    ap.add_argument("--camera", default="front")
    ap.add_argument("--out-dir", default="runs/seg_baseline")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--num-classes", type=int, default=CARLA_SEMANTIC_NUM_CLASSES)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--class-weight-scheme",
        choices=("median_frequency", "inverse_frequency"),
        default="median_frequency",
    )
    ap.add_argument("--no-class-weights", action="store_true")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    return ap.parse_args()


def main():
    args = parse_args()
    ds_root = Path(args.dataset)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_dir = out_dir / "checkpoints"
    ckpt_dir.mkdir(exist_ok=True)

    ds = SegDataset(ds_root, args.camera, limit=args.limit)
    dl = DataLoader(ds, batch_size=args.batch, shuffle=True, num_workers=2, pin_memory=True)

    num_classes = validate_num_classes(args.num_classes)
    model = torchvision.models.segmentation.fcn_resnet50(weights=None, num_classes=num_classes)
    model.to(args.device)

    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    class_counts = None
    class_weights = None
    if not args.no_class_weights:
        class_counts = scan_dataset_class_counts(
            ds_root,
            camera=args.camera,
            limit=args.limit,
            num_classes=num_classes,
        )
        class_weights = compute_class_weights(
            class_counts,
            num_classes=num_classes,
            scheme=args.class_weight_scheme,
        ).to(args.device)
    # ignore_index: CARLA's Any(255) sentinel is a legitimate label value (unclassified/
    # miscellaneous pixels), but is not one of the model's num_classes output channels --
    # without this, CrossEntropyLoss raises on the first batch containing an Any pixel.
    loss_fn = torch.nn.CrossEntropyLoss(weight=class_weights, ignore_index=CARLA_SEMANTIC_ANY_CLASS_ID)

    metrics = {
        "loss": [],
        "class_weighting": {
            "enabled": not args.no_class_weights,
            "scheme": args.class_weight_scheme if not args.no_class_weights else None,
            "counts": class_counts.tolist() if class_counts is not None else None,
            "weights": class_weights.detach().cpu().tolist() if class_weights is not None else None,
        },
    }
    model.train()
    for ep in range(args.epochs):
        total = 0.0
        n = 0
        for x, y in dl:
            x = x.to(args.device)
            y = y.to(args.device)
            opt.zero_grad()
            out = model(x)["out"]
            loss = loss_fn(out, y)
            loss.backward()
            opt.step()
            total += float(loss.item()) * x.size(0)
            n += x.size(0)
        ep_loss = total / max(1, n)
        metrics["loss"].append({"epoch": ep, "loss": ep_loss})
        print(f"epoch {ep}: loss={ep_loss:.4f}")
        torch.save(model.state_dict(), (ckpt_dir / "model_last.pt").as_posix())

    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"✅ Training done → {out_dir}")


if __name__ == "__main__":
    main()


# -----------------------------------------------------------------------------
# Backward-compat alias
# -----------------------------------------------------------------------------
# Some helper launchers in this repo expect a class name called
# `SemanticSegDataset`. Keep an alias so imports don't explode.
SemanticSegDataset = SegDataset

# NEW-234: explicit alias for the governed multi-root variant used by the RQ5
# K-sweep. Kept separate from ``SemanticSegDataset`` so existing single-root
# callers (and their expectations) are unchanged.
MultiRootSemanticSegDataset = MultiRootSegDataset
