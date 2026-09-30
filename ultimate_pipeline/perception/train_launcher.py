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
import json
import os
from pathlib import Path
from typing import Optional

import torch
from torch import nn, optim
from torch.utils.data import DataLoader, ConcatDataset

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


def _set_global_seed(seed: int) -> int:
    """Seed python/numpy/torch/CUDA and return the seed actually applied.

    Previously the launcher had NO seed at all (NEW-239): every run was
    non-reproducible and the recorded "seed" was fabricated after the fact.
    """
    import random

    seed = int(seed)
    random.seed(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except Exception:  # pragma: no cover - numpy is a hard dep in practice
        pass
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    # Keep cuDNN deterministic so a recorded seed actually reproduces.
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    os.environ["PYTHONHASHSEED"] = str(seed)
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    return seed


def _validate_split_manifest(path: Path) -> dict:
    """Refuse to train when the governed train/validation/test split is absent.

    NEW-240: the K-sweep swept over test data because no split was enforced;
    NEW-241: the code claimed `manual_test` while actually evaluating on
    `real_u` (train-split).  Both require an explicit, checked manifest.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"GOVERNED training: split manifest not found: {path}. A governed "
            "run must name its splits explicitly rather than infer them."
        )
    manifest = json.loads(path.read_text(encoding="utf-8"))

    required = ("generated_train", "generated_validation", "generated_test", "manual_test")
    missing = [k for k in required if not manifest.get(k)]
    if missing:
        raise ValueError(
            f"GOVERNED training: split manifest {path} is missing required "
            f"splits {missing}. Required (non-empty): {list(required)}."
        )

    def _frames(key: str) -> list:
        value = manifest[key]
        if isinstance(value, dict):
            out: list = []
            for v in value.values():
                out.extend(_frames_from(v))
            return out
        return _frames_from(value)

    def _frames_from(value) -> list:
        if isinstance(value, str):
            return [value]
        if isinstance(value, (list, tuple)):
            return [f for f in value if isinstance(f, str)]
        return []

    seen: dict = {}
    for key in required:
        for frame in _frames(key):
            if frame in seen and seen[frame] != key:
                raise ValueError(
                    f"GOVERNED training: frame '{frame}' appears in both "
                    f"'{seen[frame]}' and '{key}' in {path}. Train/val/test "
                    "must be disjoint."
                )
            seen[frame] = key

    # The held-out manual test set must not appear in any training split.
    train_frames = set(_frames("generated_train")) | set(_frames("generated_validation"))
    leaked = sorted(train_frames & set(_frames("manual_test")))
    if leaked:
        raise ValueError(
            f"GOVERNED training: {len(leaked)} manual_test frame(s) also appear "
            f"in a training split of {path}: {leaked[:8]}"
        )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        action="append",
        default=None,
        help="Dataset root directory. Repeatable: every listed root is trained on "
        "(the K-sweep previously claimed N datasets but silently used only "
        "dataset_roots[0] -- NEW-234).",
    )
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
    parser.add_argument(
        "--seed",
        type=int,
        default=int(getattr(SETTINGS, "TRAINING_SEED", 0) or 0),
        help="Global seed for python/numpy/torch/dataloader workers. Recorded in "
        "training_provenance.json (NEW-239).",
    )
    parser.add_argument(
        "--governed",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Fail closed when a requested dataset root is missing (default). "
        "Auto-discovery of 'the latest dataset' is diagnostic-only.",
    )
    parser.add_argument(
        "--diagnostic-auto-discover",
        action="store_true",
        help="Diagnostic escape hatch: fall back to _find_latest_dataset under "
        "BASE_OUTPUT_DIR when a requested root is absent. Never use for "
        "reproducible training runs.",
    )
    parser.add_argument(
        "--split-manifest",
        type=str,
        default="",
        help="Path to a governed split manifest. When set, training refuses to "
        "run unless it defines generated_train / generated_validation / "
        "generated_test / manual_test with no frame overlap (NEW-240).",
    )
    args = parser.parse_args()

    # ---- global determinism (NEW-239): set every seed before any data/model
    # construction, and record what was actually applied.
    applied_seed = _set_global_seed(int(args.seed))

    # ---- governed dataset resolution (NEW-236): missing roots fail closed.
    dataset_roots = [Path(p) for p in (args.dataset or [])]
    if not dataset_roots and SETTINGS.TRAINING_DATASET_DIR:
        dataset_roots = [Path(SETTINGS.TRAINING_DATASET_DIR)]

    missing = [str(p) for p in dataset_roots if not p.exists()]
    if missing:
        if args.diagnostic_auto_discover or not args.governed:
            guess = _find_latest_dataset(Path(SETTINGS.BASE_OUTPUT_DIR))
            if guess is None:
                raise FileNotFoundError(
                    f"Dataset directory not found: {missing}. "
                    f"Auto-discovery under BASE_OUTPUT_DIR={SETTINGS.BASE_OUTPUT_DIR} "
                    f"also found nothing."
                )
            print(
                "⚠ DIAGNOSTIC auto-discovery selected "
                f"{guess} for {missing}; this run is NOT governed/reproducible."
            )
            dataset_roots = [guess]
        else:
            raise FileNotFoundError(
                "GOVERNED training: requested dataset root(s) missing: "
                f"{missing}. Refusing to substitute an unrelated dataset. "
                "Pass --diagnostic-auto-discover if a non-reproducible "
                "diagnostic run is genuinely intended."
            )
    if not dataset_roots:
        raise FileNotFoundError("GOVERNED training: no dataset root provided via --dataset.")

    # Duplicate roots silently double-weight a condition; reject instead.
    if len(set(str(p) for p in dataset_roots)) != len(dataset_roots):
        raise ValueError(
            f"GOVERNED training: duplicate dataset roots requested: {dataset_roots}"
        )

    # ---- governed split manifest (NEW-240/NEW-241)
    if args.split_manifest:
        _validate_split_manifest(Path(args.split_manifest))

    out_dir = _resolve_out_dir(args.out_dir)

    ddp_enabled, rank, world_size = _init_ddp(args.ddp)
    is_main = (rank == 0)

    device = torch.device(args.device if (args.device != "cuda" or torch.cuda.is_available()) else "cpu")
    if is_main:
        print(f"🧠 Training task: segmentation (FCN-ResNet50)")
        print(f"   datasets={dataset_roots}")
        print(f"   camera={args.camera}")
        print(f"   out_dir={out_dir}")
        print(f"   epochs={args.epochs} batch={args.batch} lr={args.lr} classes={args.num_classes}")
        print(f"   device={device} ddp={ddp_enabled} world_size={world_size}")
        print(f"   seed={applied_seed} governed={args.governed}")

    # NEW-234: train on EVERY requested root. The K-sweep previously passed N
    # roots but the launcher only ever read dataset_roots[0], so
    # generated_k_k008 was byte-identical to k001 in terms of data consumed.
    per_root = [
        SemanticSegDataset(root, cam=args.camera, limit=args.limit if args.limit > 0 else None)
        for root in dataset_roots
    ]
    empty = [str(r) for r, d in zip(dataset_roots, per_root) if len(d) == 0]
    if empty:
        raise FileNotFoundError(
            f"GOVERNED training: dataset root(s) contain no rgb/{args.camera} "
            f"frames: {empty}"
        )
    ds = per_root[0] if len(per_root) == 1 else ConcatDataset(per_root)

    # Worker seeding: without this the recorded seed does not reproduce the
    # per-epoch shuffling of a multi-worker DataLoader (NEW-239).
    _generator = torch.Generator()
    _generator.manual_seed(applied_seed)

    def _seed_worker(_worker_id: int) -> None:
        worker_seed = applied_seed + _worker_id
        import random as _random

        _random.seed(worker_seed)
        try:
            import numpy as _np

            _np.random.seed(worker_seed % (2**32))
        except Exception:  # pragma: no cover
            pass
        torch.manual_seed(worker_seed)

    if ddp_enabled:
        sampler = torch.utils.data.distributed.DistributedSampler(
            ds, shuffle=True, seed=applied_seed
        )
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
        worker_init_fn=_seed_worker if int(args.num_workers) > 0 else None,
        generator=_generator,
    )

    model = _build_model(args.num_classes).to(device)
    if ddp_enabled:
        local_rank = int(os.environ.get("LOCAL_RANK", "0"))
        if device.type == "cuda":
            torch.cuda.set_device(local_rank)
        model = torch.nn.parallel.DistributedDataParallel(model, device_ids=[local_rank] if device.type == "cuda" else None)

    class_weights = None
    if not args.no_class_weights:
        # Aggregate class counts across EVERY training root (NEW-234): a
        # single-root scan silently under-counted weights for k>1 conditions.
        class_counts = None
        for root in dataset_roots:
            counts = scan_dataset_class_counts(
                root,
                camera=args.camera,
                limit=args.limit,
                num_classes=args.num_classes,
            )
            class_counts = counts if class_counts is None else (class_counts + counts)
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

    # ---- provenance (NEW-239): record what was ACTUALLY run, not what was
    # requested. This is the file downstream evidence uses for "the seed was
    # recorded", so it must reflect the applied values.
    if is_main:
        provenance = {
            "schema": "TRAINING_PROVENANCE/v1",
            "seed_requested": int(args.seed),
            "seed_applied": int(applied_seed),
            "seeding": {
                "python": True,
                "numpy": True,
                "torch": True,
                "torch_cuda": bool(torch.cuda.is_available()),
                "dataloader_generator": True,
                "worker_init_fn": int(args.num_workers) > 0,
                "cudnn_deterministic": True,
            },
            "dataset_roots": [str(p) for p in dataset_roots],
            "dataset_frames": [len(d) for d in per_root],
            "camera": args.camera,
            "epochs": int(args.epochs),
            "batch_size": int(args.batch),
            "lr": float(args.lr),
            "num_classes": int(args.num_classes),
            "class_weight_scheme": args.class_weight_scheme,
            "device": args.device,
            "governed": bool(args.governed),
            "diagnostic_auto_discover": bool(args.diagnostic_auto_discover),
            "split_manifest": str(args.split_manifest) if args.split_manifest else None,
            "torch_version": getattr(torch, "__version__", None),
        }
        (out_dir / "training_provenance.json").write_text(
            json.dumps(provenance, indent=2), encoding="utf-8"
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
