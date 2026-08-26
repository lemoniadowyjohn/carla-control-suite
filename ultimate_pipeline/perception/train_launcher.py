#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ultimate_pipeline/perception/train_launcher.py

Config-driven training entrypoint (local PC OR HPC).

This script intentionally does NOT depend on CARLA. It only needs:
- a recorded dataset directory with:
    rgb/<camera>/XXXXXXXX.png
    semseg_raw/<camera>/XXXXXXXX.png

It reads defaults from SETTINGS (config/settings.py), but CLI args override.

Typical local (single GPU):
    python -m ultimate_pipeline.perception.train_launcher --dataset /path/to/run --camera front_left_camera

Typical HPC (single node, multi-GPU) with torchrun:
    torchrun --standalone --nproc_per_node=4 -m ultimate_pipeline.perception.train_launcher \
        --dataset /path/to/run --camera front_left_camera --ddp
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Optional

import torch
from torch import nn, optim
from torch.utils.data import DataLoader

from torchvision import models
from torchvision.transforms import functional as TF

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.perception.carla_classes import CARLA_SEMANTIC_ANY_CLASS_ID
from ultimate_pipeline.perception.class_weights import (
    compute_class_weights,
    scan_dataset_class_counts,
)
from ultimate_pipeline.perception.min_train_segmentation import SemanticSegDataset


def _resolve_out_dir(out_dir: str) -> Path:
    p = Path(out_dir)
    if not p.is_absolute():
        # place relative outputs under project root
        root = Path(__file__).resolve().parents[2]
        p = root / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def _find_latest_dataset(base: Path) -> Optional[Path]:
    """Best-effort discovery of the newest folder that looks like a dataset."""
    if not base.exists():
        return None
    candidates = []
    for p in base.rglob("*"):
        if not p.is_dir():
            continue
        if (p / "rgb").is_dir() and (p / "semseg_raw").is_dir():
            candidates.append(p)
    if not candidates:
        return None
    return max(candidates, key=lambda x: x.stat().st_mtime)


def _init_ddp(enabled: bool) -> tuple[bool, int, int]:
    """Initialize torch.distributed if launched via torchrun/srun."""
    if not enabled:
        return False, 0, 1

    if not torch.distributed.is_available():
        raise RuntimeError("torch.distributed not available in this PyTorch build.")

    world_size = int(os.environ.get("WORLD_SIZE", "1"))
    rank = int(os.environ.get("RANK", "0"))

    if world_size <= 1:
        return False, 0, 1

    torch.distributed.init_process_group(backend="nccl" if torch.cuda.is_available() else "gloo")
    return True, rank, world_size


def _build_model(num_classes: int) -> nn.Module:
    model = models.segmentation.fcn_resnet50(weights=None, num_classes=int(num_classes))
    return model


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=str, default=SETTINGS.TRAINING_DATASET_DIR or "", help="Dataset root directory")
    parser.add_argument("--camera", type=str, default=SETTINGS.TRAINING_CAMERA)
    parser.add_argument("--out-dir", type=str, default=SETTINGS.TRAINING_OUT_DIR)
    parser.add_argument("--epochs", type=int, default=SETTINGS.TRAIN_EPOCHS)
    parser.add_argument("--batch", type=int, default=SETTINGS.TRAIN_BATCH)
    parser.add_argument("--lr", type=float, default=SETTINGS.TRAIN_LR)
    parser.add_argument("--num-classes", type=int, default=SETTINGS.TRAIN_NUM_CLASSES)
    parser.add_argument("--limit", type=int, default=SETTINGS.TRAIN_LIMIT)
    parser.add_argument("--device", type=str, default=SETTINGS.TRAIN_DEVICE)
    parser.add_argument("--num-workers", type=int, default=SETTINGS.TRAIN_NUM_WORKERS)
    parser.add_argument("--ddp", action="store_true", default=SETTINGS.TRAIN_USE_DDP)
    parser.add_argument(
        "--class-weight-scheme",
        choices=("median_frequency", "inverse_frequency"),
        default="median_frequency",
    )
    parser.add_argument("--no-class-weights", action="store_true")
    args = parser.parse_args()

    dataset_root = Path(args.dataset) if args.dataset else Path()
    if not dataset_root.exists():
        # Try to auto-discover a dataset under BASE_OUTPUT_DIR
        guess = _find_latest_dataset(Path(SETTINGS.BASE_OUTPUT_DIR))
        if guess is None:
            raise FileNotFoundError(
                f"Dataset directory not found. Provided: '{args.dataset}'. "
                f"Also couldn't auto-discover under BASE_OUTPUT_DIR={SETTINGS.BASE_OUTPUT_DIR}"
            )
        dataset_root = guess
        print(f"📦 Auto-selected latest dataset: {dataset_root}")

    out_dir = _resolve_out_dir(args.out_dir)

    ddp_enabled, rank, world_size = _init_ddp(args.ddp)
    is_main = (rank == 0)

    device = torch.device(args.device if (args.device != "cuda" or torch.cuda.is_available()) else "cpu")
    if is_main:
        print(f"🧠 Training task: segmentation (FCN-ResNet50)")
        print(f"   dataset={dataset_root}")
        print(f"   camera={args.camera}")
        print(f"   out_dir={out_dir}")
        print(f"   epochs={args.epochs} batch={args.batch} lr={args.lr} classes={args.num_classes}")
        print(f"   device={device} ddp={ddp_enabled} world_size={world_size}")

    ds = SemanticSegDataset(dataset_root, cam=args.camera, limit=args.limit if args.limit > 0 else None)
    if ddp_enabled:
        sampler = torch.utils.data.distributed.DistributedSampler(ds, shuffle=True)
        shuffle = False
    else:
        sampler = None
        shuffle = True

    dl = DataLoader(
        ds,
        batch_size=args.batch,
        shuffle=shuffle,
        sampler=sampler,
        num_workers=int(args.num_workers),
        pin_memory=(device.type == "cuda"),
    )

    model = _build_model(args.num_classes).to(device)
    if ddp_enabled:
        local_rank = int(os.environ.get("LOCAL_RANK", "0"))
        if device.type == "cuda":
            torch.cuda.set_device(local_rank)
        model = torch.nn.parallel.DistributedDataParallel(model, device_ids=[local_rank] if device.type == "cuda" else None)

    class_weights = None
    if not args.no_class_weights:
        class_counts = scan_dataset_class_counts(
            dataset_root,
            camera=args.camera,
            limit=args.limit,
            num_classes=args.num_classes,
        )
        class_weights = compute_class_weights(
            class_counts,
            num_classes=args.num_classes,
            scheme=args.class_weight_scheme,
        ).to(device)
        if is_main:
            present = int((class_weights > 0).sum().item())
            print(
                f"   class_weights={args.class_weight_scheme} "
                f"present_classes={present}/{args.num_classes}"
            )
    # ignore_index: CARLA's Any(255) sentinel is a legitimate label value, not one of
    # the model's num_classes output channels -- see C27 (same fix applied to
    # min_train_segmentation.py's independently-constructed loss function).
    criterion = nn.CrossEntropyLoss(weight=class_weights, ignore_index=CARLA_SEMANTIC_ANY_CLASS_ID)
    optimizer = optim.Adam(model.parameters(), lr=float(args.lr))

    model.train()
    for epoch in range(int(args.epochs)):
        if ddp_enabled:
            assert sampler is not None
            sampler.set_epoch(epoch)

        running = 0.0
        for x, y in dl:
            x = x.to(device, non_blocking=True)
            y = y.to(device, non_blocking=True)

            optimizer.zero_grad(set_to_none=True)
            out = model(x)["out"]
            loss = criterion(out, y)
            loss.backward()
            optimizer.step()
            running += float(loss.item())

        if is_main:
            avg = running / max(1, len(dl))
            print(f"Epoch {epoch+1}/{args.epochs}  loss={avg:.4f}")

            ckpt = out_dir / f"seg_fcn_epoch{epoch+1:03d}.pt"
            # unwrap DDP
            state = model.module.state_dict() if hasattr(model, "module") else model.state_dict()
            torch.save(state, ckpt)
            print(f"✅ Saved {ckpt}")

    if ddp_enabled:
        torch.distributed.destroy_process_group()


if __name__ == "__main__":
    main()
