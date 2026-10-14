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

Typical local (single GPU), single dataset:
    python -m ultimate_pipeline.perception.train_launcher --dataset /path/to/run --camera front_left_camera

NEW-234: multi-root training (RQ5 K-sweep):
    python -m ultimate_pipeline.perception.train_launcher \\
        --datasets /path/to/gen_001 /path/to/gen_002 /path/to/gen_003 \\
        --camera front_left_camera

    ``--datasets`` trains on a *true union* of every supplied root. Previously
    the RQ5 runner recorded K roots in its training manifest but passed only the
    first root to this script, so K=1/K=3/K=5 could all train on the same data.
    ``--dataset`` remains supported and is mutually exclusive with
    ``--datasets``.

NEW-244: every run is seed-governed via ``--seed`` (see rq5_provenance.seed_everything).

NEW-243: on success a ``model_manifest.json`` is written next to the
    checkpoints, binding the checkpoint SHA-256 to the dataset identities, git SHA,
    architecture, optimizer, learning rate and seed.

NEW-277: DATASET_ACCEPTANCE is enforced fail-closed before any model is built.
    Every root must contain ``rgb/<camera>`` and ``semseg_raw/<camera>`` and must
    contribute at least one *paired* frame; the union must be non-empty after
    ``--limit``. Previously ``SegDataset`` (``SemanticSegDataset``) yielded zero
    items for an empty or half-populated ``rgb/<camera>``, so the epoch loop ran
    zero batches and the launcher still emitted a checkpoint and a NEW-243
    ``model_manifest.json`` -- authoritative-looking provenance for a model
    trained on nothing. There is no override flag by design. The verdict is
    recorded in the manifest under ``extra.dataset_acceptance``.

Typical HPC (single node, multi-GPU) with torchrun:
    torchrun --standalone --nproc_per_node=4 -m ultimate_pipeline.perception.train_launcher \\
        --dataset /path/to/run --camera front_left_camera --ddp
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional

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
    scan_multi_root_class_counts,
)
from ultimate_pipeline.perception.min_train_segmentation import (
    MultiRootSegDataset,
    SemanticSegDataset,
)
from ultimate_pipeline.perception.semantic_classes import validate_num_classes
from ultimate_pipeline.perception.rq5_provenance import (
    MULTI_ROOT_TRAIN,
    build_model_manifest,
    combine_dataset_identities,
    dataset_content_identity,
    seed_everything,
    write_model_manifest,
)

DEFAULT_SEED = 1337


class DatasetAcceptanceError(RuntimeError):
    """Raised when a dataset root fails DATASET_ACCEPTANCE (NEW-277).

    This is deliberately a distinct exception type so a caller can tell an
    acceptance rejection apart from an incidental I/O or decoding failure.
    """


def evaluate_dataset_acceptance(
    roots: List[Path], camera: str, limit: Optional[int] = None
) -> dict:
    """DATASET_ACCEPTANCE (NEW-277): decide whether these roots may be trained on.

    Returns a machine-readable report with ``accepted`` plus the evidence that
    produced the verdict. Never raises for a merely-unacceptable dataset; the
    caller decides whether to enforce.

    Criteria (all must hold):

    1. every root contains both ``rgb/<camera>`` and ``semseg_raw/<camera>``;
    2. every root contributes at least one rgb/semseg frame *pair* -- a frame
       name present in one directory but not the other is unusable, because
       the label is resolved by name at ``__getitem__`` time;
    3. the union across roots is non-empty after ``limit`` is applied.

    Rationale: without this, ``SegDataset`` (``SemanticSegDataset``) happily
    yields zero items for an empty or half-populated ``rgb/<camera>``, the
    epoch loop executes zero batches, and the launcher still writes a
    checkpoint plus a NEW-243 ``model_manifest.json``. That produces
    authoritative-looking provenance for a model trained on nothing, which is
    precisely the false-confidence failure this gate exists to prevent.
    """
    per_root: List[dict] = []
    reasons: List[str] = []

    for root in roots:
        rgb_dir = Path(root) / "rgb" / camera
        lab_dir = Path(root) / "semseg_raw" / camera
        entry: dict = {
            "root": Path(root).as_posix(),
            "camera": camera,
            "rgb_dir": rgb_dir.as_posix(),
            "label_dir": lab_dir.as_posix(),
            "rgb_dir_present": rgb_dir.is_dir(),
            "label_dir_present": lab_dir.is_dir(),
            "rgb_frames": 0,
            "label_frames": 0,
            "paired_frames": 0,
            "unpaired_rgb": [],
            "unpaired_labels": [],
        }

        if not entry["rgb_dir_present"] or not entry["label_dir_present"]:
            missing = []
            if not entry["rgb_dir_present"]:
                missing.append(f"rgb/{camera}")
            if not entry["label_dir_present"]:
                missing.append(f"semseg_raw/{camera}")
            entry["error"] = "missing required dataset directory: " + ", ".join(missing)
            reasons.append(f"{entry['root']}: {entry['error']}")
            per_root.append(entry)
            continue

        rgb_names = {p.name for p in rgb_dir.glob("*.png")}
        lab_names = {p.name for p in lab_dir.glob("*.png")}
        paired = rgb_names & lab_names
        entry["rgb_frames"] = len(rgb_names)
        entry["label_frames"] = len(lab_names)
        entry["paired_frames"] = len(paired)
        entry["unpaired_rgb"] = sorted(rgb_names - lab_names)
        entry["unpaired_labels"] = sorted(lab_names - rgb_names)

        if not paired:
            entry["error"] = (
                "no paired rgb/semseg_raw frames "
                f"(rgb={len(rgb_names)}, semseg_raw={len(lab_names)})"
            )
            reasons.append(f"{entry['root']}: {entry['error']}")
        per_root.append(entry)

    total_paired = sum(int(e["paired_frames"]) for e in per_root)
    effective = total_paired if not (limit and limit > 0) else min(total_paired, int(limit))

    if not reasons and effective <= 0:
        reasons.append(
            "no trainable frames remain after applying --limit "
            f"(paired={total_paired}, limit={limit})"
        )

    return {
        "accepted": not reasons,
        "camera": camera,
        "limit": limit,
        "total_paired_frames": total_paired,
        "effective_frames": effective,
        "per_root": per_root,
        "reasons": reasons,
        "criteria": [
            "every root has rgb/<camera> and semseg_raw/<camera>",
            "every root has >=1 paired rgb/semseg frame",
            "union is non-empty after --limit",
        ],
    }


def enforce_dataset_acceptance(
    roots: List[Path], camera: str, limit: Optional[int] = None
) -> dict:
    """DATASET_ACCEPTANCE (NEW-277): fail closed unless every root is acceptable.

    Raises ``DatasetAcceptanceError`` with the full rejection evidence. There is
    deliberately no override flag: an escape hatch would restore the exact
    false-confidence hole this gate closes.
    """
    report = evaluate_dataset_acceptance(roots, camera, limit=limit)
    if report["accepted"]:
        return report
    raise DatasetAcceptanceError(
        "DATASET_ACCEPTANCE rejected this training set; refusing to train and "
        "refusing to write a checkpoint or model_manifest.json.\n"
        + "\n".join(f"  - {r}" for r in report["reasons"])
    )


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


def _resolve_dataset_roots(args: argparse.Namespace) -> List[Path]:
    """
    Resolve the training roots for this invocation.

    NEW-234: ``--datasets`` yields every supplied root (true multi-root
    training). ``--dataset`` yields exactly one. Supplying both is a hard error
    rather than a silent preference, because a caller that thinks it trained on
    K roots while the trainer saw one is precisely the defect being closed.
    """
    if args.datasets and args.dataset:
        raise SystemExit(
            "--dataset and --datasets are mutually exclusive: --dataset trains on "
            "exactly one root, --datasets trains on the union of all supplied roots"
        )

    roots: List[Path] = [Path(p) for p in (args.datasets or ([args.dataset] if args.dataset else []))]
    if not roots:
        # Preserve the historical SETTINGS-driven default (run_training.py's
        # "local" backend relies on it) before falling back to auto-discovery.
        configured = getattr(SETTINGS, "TRAINING_DATASET_DIR", "") or ""
        if configured:
            roots = [Path(configured)]
    if not roots:
        # Preserve the historical auto-discovery behaviour for single-root runs.
        guess = _find_latest_dataset(Path(SETTINGS.BASE_OUTPUT_DIR))
        if guess is None:
            raise FileNotFoundError(
                "No dataset root supplied (--dataset / --datasets) and couldn't "
                f"auto-discover under BASE_OUTPUT_DIR={SETTINGS.BASE_OUTPUT_DIR}"
            )
        roots = [guess]
        print(f"📦 Auto-selected latest dataset: {roots[0]}")

    for root in roots:
        if not root.exists():
            if len(roots) == 1:
                guess = _find_latest_dataset(Path(SETTINGS.BASE_OUTPUT_DIR))
                if guess is not None:
                    roots[0] = guess
                    print(f"📦 Auto-selected latest dataset: {guess}")
                    continue
            raise FileNotFoundError(f"Dataset directory not found: {root}")
    return roots


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=str, default=None, help="Single dataset root directory")
    parser.add_argument(
        "--datasets",
        nargs="+",
        type=str,
        default=None,
        help="NEW-234: train on the union of these dataset roots (RQ5 K-sweep)",
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
        default=DEFAULT_SEED,
        help=(
            "NEW-244: governed experiment seed applied to random/numpy/torch/CUDA "
            f"and the DataLoader generator (default {DEFAULT_SEED})"
        ),
    )
    parser.add_argument(
        "--no-manifest",
        action="store_true",
        help="NEW-243: skip writing model_manifest.json (diagnostic runs only)",
    )
    parser.add_argument(
        "--dataset-identity-max-files",
        type=int,
        default=0,
        help="Optional cap on files digested per dataset root when computing content identity (0 = no cap)",
    )
    args = parser.parse_args()

    dataset_roots = _resolve_dataset_roots(args)
    multi_root = len(dataset_roots) > 1

    # NEW-277 (DATASET_ACCEPTANCE): fail closed BEFORE any model construction,
    # checkpoint or manifest is produced. This must precede the dataset build so
    # an unacceptable set cannot yield a signed manifest for an untrained model.
    acceptance = enforce_dataset_acceptance(
        dataset_roots, args.camera, limit=(args.limit if args.limit > 0 else None)
    )
    print(
        f"✅ DATASET_ACCEPTANCE: {acceptance['total_paired_frames']} paired frame(s) "
        f"across {len(dataset_roots)} root(s) for camera={args.camera}"
    )

    # Validate num_classes against CARLA semantic class policy (same as
    # min_train_segmentation.py does) so a too-small --num-classes fails
    # fast with a clear message instead of a confusing "out of bounds" error
    # deep in the loss function.
    args.num_classes = validate_num_classes(args.num_classes)

    out_dir = _resolve_out_dir(args.out_dir)

    ddp_enabled, rank, world_size = _init_ddp(args.ddp)
    is_main = (rank == 0)

    device = torch.device(args.device if (args.device != "cuda" or torch.cuda.is_available()) else "cpu")

    # NEW-244: seed BEFORE model construction, dataset sampling and DataLoader
    # creation so every stochastic element of the run is bound to one recorded
    # seed. A single source of truth lives in rq5_provenance.seed_everything.
    seed_record = seed_everything(args.seed)
    generator = torch.Generator()
    generator.manual_seed(int(args.seed))

    if is_main:
        print(f"🧠 Training task: segmentation (FCN-ResNet50)")
        roots_text = ", ".join(p.as_posix() for p in dataset_roots)
        print(f"   datasets({len(dataset_roots)})={roots_text}")
        print(f"   camera={args.camera}")
        print(f"   out_dir={out_dir}")
        print(f"   epochs={args.epochs} batch={args.batch} lr={args.lr} classes={args.num_classes}")
        print(f"   device={device} ddp={ddp_enabled} world_size={world_size}")
        print(f"   seed={args.seed}")

    limit = args.limit if args.limit > 0 else None
    if multi_root:
        ds = MultiRootSegDataset(dataset_roots, cam=args.camera, limit=limit)
        if is_main:
            print(f"   multi_root=True frames={len(ds)} per_root={ds.root_frame_counts}")
            for name in ds.unpaired_rgb[:10]:
                print(f"   ⚠️  unpaired rgb (no label): {name}")
            for name in ds.unpaired_labels[:10]:
                print(f"   ⚠️  unpaired label (no rgb): {name}")
    else:
        ds = SemanticSegDataset(dataset_roots[0], cam=args.camera, limit=limit)

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
        generator=generator,
    )

    model = _build_model(args.num_classes).to(device)
    if ddp_enabled:
        local_rank = int(os.environ.get("LOCAL_RANK", "0"))
        if device.type == "cuda":
            torch.cuda.set_device(local_rank)
        model = torch.nn.parallel.DistributedDataParallel(model, device_ids=[local_rank] if device.type == "cuda" else None)

    class_weights = None
    if not args.no_class_weights:
        if multi_root:
            class_counts = scan_multi_root_class_counts(
                dataset_roots,
                camera=args.camera,
                limit=args.limit,
                num_classes=args.num_classes,
            )
        else:
            class_counts = scan_dataset_class_counts(
                dataset_roots[0],
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
    last_ckpt: Optional[Path] = None
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
            last_ckpt = ckpt
            print(f"✅ Saved {ckpt}")

    # NEW-243: bind the final checkpoint to the run that produced it.
    if is_main and last_ckpt is not None and not args.no_manifest:
        max_files = args.dataset_identity_max_files or None
        identities = [
            dataset_content_identity(root, args.camera, max_files=max_files)
            for root in dataset_roots
        ]
        train_identity = (
            combine_dataset_identities(identities, strategy=MULTI_ROOT_TRAIN)
            if multi_root
            else identities[0]
        )
        manifest = build_model_manifest(
            checkpoint=last_ckpt,
            train_dataset_identity=train_identity,
            train_roots=[p.as_posix() for p in dataset_roots],
            architecture_version="fcn_resnet50_torchvision_default",
            num_classes=int(args.num_classes),
            class_mapping={
                "num_classes": int(args.num_classes),
                "ignore_index": int(CARLA_SEMANTIC_ANY_CLASS_ID),
                "label_space": "carla_semantic_tagn",
            },
            camera=args.camera,
            optimizer="Adam",
            learning_rate=float(args.lr),
            epochs=int(args.epochs),
            batch_size=int(args.batch),
            seed=int(args.seed),
            augmentation_policy="none",
            extra={
                "multi_root": bool(multi_root),
                "train_frame_count": len(ds),
                "train_frame_counts_per_root": (
                    ds.root_frame_counts if multi_root else None
                ),
                "seed_applied": seed_record,
                "ddp": bool(ddp_enabled),
                "world_size": int(world_size),
                # NEW-277: bind the acceptance verdict into the manifest so a
                # consumer can see the training set was admitted by an explicit
                # gate rather than merely discovered.
                "dataset_acceptance": acceptance,
            },
        )
        manifest_path = write_model_manifest(out_dir, manifest)
        print(f"🔒 Wrote model manifest → {manifest_path}")

    if ddp_enabled:
        torch.distributed.destroy_process_group()

    return 0


if __name__ == "__main__":
    sys.exit(main())
