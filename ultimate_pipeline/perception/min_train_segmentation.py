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

import numpy as np
from PIL import Image

import torch
from torch.utils.data import Dataset, DataLoader
import torchvision
from torchvision.transforms import functional as TF


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
        y = torch.from_numpy(np.array(lab, dtype=np.uint8).astype(np.int64))
        return x, y


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, help="path to datasets/<name>")
    ap.add_argument("--camera", default="front")
    ap.add_argument("--out-dir", default="runs/seg_baseline")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--num-classes", type=int, default=256)
    ap.add_argument("--limit", type=int, default=0)
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

    model = torchvision.models.segmentation.fcn_resnet50(weights=None, num_classes=args.num_classes)
    model.to(args.device)

    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    loss_fn = torch.nn.CrossEntropyLoss()

    metrics = {"loss": []}
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
