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

NEW-248: research-strict mode
----------------------------
``--research-strict`` turns every historical convenience into a hard failure:

    auto-discovery of the "latest" dataset      forbidden
    fallback when an explicit dataset is missing forbidden
    latest-checkpoint fallback                  forbidden
    implicit split creation                     forbidden
    implicit camera                             forbidden
    implicit seed                               forbidden
    mtime-based selection                       forbidden
    non-zero --limit (prefix of a split)        forbidden

The reason is that each of those is a way for a governed run to silently train
on something other than what was requested, and the resulting checkpoint would
still carry a manifest that looks legitimate.

Outside research-strict mode the previous development behaviour is preserved
exactly, so existing callers and tests are unaffected.

Typical local (single GPU), single dataset:
    python -m ultimate_pipeline.perception.train_launcher --dataset /path/to/run --camera front_left_camera

NEW-234: multi-root training (RQ5 K-sweep):
    python -m ultimate_pipeline.perception.train_launcher \\
        --datasets /path/to/gen_001 /path/to/gen_002 /path/to/gen_003 \\
        --camera front_left_camera

NEW-244: every run is seed-governed via ``--seed`` (see rq5_provenance.seed_everything).

NEW-243: on success a ``model_manifest.json`` is written next to the
checkpoints, binding the checkpoint SHA-256 to the dataset identities, git SHA,
protocol digest, architecture, optimizer, learning rate and seed.

NEW-248 (governed RQ5): ``--split-dir`` trains on exactly the frames of a
governed split manifest, runs a real generated-validation pass each epoch and
writes ``TRAINING_HISTORY.json``. Class weights are derived from the training
split manifest only.

Typical HPC (single node, multi-GPU) with torchrun:
    torchrun --standalone --nproc_per_node=4 -m ultimate_pipeline.perception.train_launcher \\
        --dataset /path/to/run --camera front_left_camera --ddp
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
    scan_label_class_counts,
    scan_multi_root_class_counts,
)
from ultimate_pipeline.perception.min_train_segmentation import (
    ManifestSegDataset,
    MultiRootSegDataset,
    SemanticSegDataset,
    evaluate_validation_pass,
    write_training_history,
)
from ultimate_pipeline.perception.rq5_provenance import (
    MULTI_ROOT_TRAIN,
    apply_determinism_contract,
    build_model_manifest,
    combine_dataset_identities,
    canonical_dumps,
    dataset_content_identity,
    sha256_text,
    write_model_manifest,
)

DEFAULT_SEED = 1337

#: Protocol v2 values a research-strict run may not deviate from.
STRICT_PROTOCOL_VALUES: Dict[str, Any] = {
    "epochs": 3,
    "batch_size": 4,
    "learning_rate": 1e-4,
    "optimizer": "Adam",
    "augmentations": "none",
}


class ResearchStrictError(SystemExit):
    """Raised when a research-strict precondition is violated."""

    def __init__(self, message: str):
        super().__init__(f"research-strict: {message}")


def _resolve_out_dir(out_dir: str) -> Path:
    p = Path(out_dir)
    if not p.is_absolute():
        # place relative outputs under project root
        root = Path(__file__).resolve().parents[2]
        p = root / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def _find_latest_dataset(base: Path) -> Optional[Path]:
    """
    Best-effort discovery of the newest folder that looks like a dataset.

    Preserved for legacy development convenience only. It selects by filesystem
    mtime, which is exactly the anti-pattern research-strict mode forbids.
    """
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


def enforce_research_strict(args: argparse.Namespace) -> Dict[str, Any]:
    """
    Validate every research-strict precondition and return the enforced record.

    The record is embedded in the run's ``model_manifest.json`` so a reader can
    see not only that strict mode was on, but which explicit values it pinned.
    """
    enforced: Dict[str, Any] = {
        "research_strict": True,
        "auto_dataset_discovery": False,
        "missing_dataset_fallback": False,
        "latest_checkpoint_fallback": False,
        "implicit_split_creation": False,
        "implicit_camera": False,
        "implicit_seed": False,
        "mtime_selection": False,
        "limit_truncation": False,
    }

    if args.split_dir is None:
        raise ResearchStrictError(
            "an explicit --split-dir is required; implicit split creation is forbidden. "
            "Generate the governed splits with tools/rq5_preflight.py or "
            "dataset_split_authority.build_split_authority first."
        )
    if not Path(args.split_dir).is_dir():
        raise ResearchStrictError(f"--split-dir does not exist: {args.split_dir}")
    if args.datasets and args.dataset:
        raise ResearchStrictError(
            "--dataset and --datasets are mutually exclusive in research-strict mode; the "
            "governed split manifest is the single source of training frames"
        )
    if int(args.limit) > 0:
        raise ResearchStrictError(
            f"--limit {args.limit} is forbidden; a prefix of a governed split is not the split"
        )
    if args.camera is None:
        raise ResearchStrictError("--camera must be given explicitly; inference is forbidden")
    if args.seed is None:
        raise ResearchStrictError("--seed must be given explicitly; inference is forbidden")
    if args.no_manifest:
        raise ResearchStrictError("--no-manifest is forbidden; provenance is not optional")
    if int(args.dataset_identity_max_files or 0) > 0:
        raise ResearchStrictError(
            "--dataset-identity-max-files is forbidden: a partial identity cannot be bound to "
            "an authoritative role"
        )

    # Protocol v2 hyperparameter fidelity.
    for name, expected in STRICT_PROTOCOL_VALUES.items():
        observed = {
            "epochs": int(args.epochs),
            "batch_size": int(args.batch),
            "learning_rate": float(args.lr),
        }.get(name)
        if observed is None:
            continue
        if abs(float(observed) - float(expected)) > 0:
            raise ResearchStrictError(
                f"protocol v2 freezes {name}={expected}; refusing to train with {name}={observed}"
            )
    if args.class_weight_scheme != "median_frequency":
        raise ResearchStrictError(
            f"protocol v2 freezes class weighting to median_frequency, not {args.class_weight_scheme!r}"
        )

    enforced["pinned"] = {
        "epochs": int(args.epochs),
        "batch_size": int(args.batch),
        "learning_rate": float(args.lr),
        "camera": str(args.camera),
        "seed": int(args.seed),
        "split_dir": str(Path(args.split_dir).resolve()),
        "optimizer": "Adam",
        "augmentations": "none",
    }
    return enforced


def _resolve_dataset_roots(args: argparse.Namespace, *, strict: bool = False) -> List[Path]:
    """
    Resolve the training roots for this invocation.

    NEW-234: ``--datasets`` yields every supplied root (true multi-root
    training). ``--dataset`` yields exactly one. Supplying both is a hard error
    rather than a silent preference, because a caller that thinks it trained on
    K roots while the trainer saw one is precisely the defect being closed.

    In research-strict mode no fallback of any kind is taken: a missing explicit
    dataset is a hard failure and another dataset is never substituted.
    """
    if args.datasets and args.dataset:
        raise SystemExit(
            "--dataset and --datasets are mutually exclusive: --dataset trains on "
            "exactly one root, --datasets trains on the union of all supplied roots"
        )

    if strict:
        if args.datasets or args.dataset:
            roots = [Path(p) for p in (args.datasets or [args.dataset])]
        else:
            roots = []
        for root in roots:
            if not root.is_dir():
                raise ResearchStrictError(f"explicitly requested dataset root not found: {root}")
        return roots

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


def _load_split_manifests(split_dir: Path) -> Dict[str, Dict[str, Any]]:
    from ultimate_pipeline.perception.dataset_split_authority import (
        SPLIT_FILENAMES,
        load_split_manifest,
    )

    directory = Path(split_dir)
    manifests: Dict[str, Dict[str, Any]] = {}
    for role, filename in SPLIT_FILENAMES.items():
        path = directory / filename
        if path.is_file():
            manifests[role] = load_split_manifest(path)
    return manifests


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
    # --- NEW-248: research-strict + governed split manifest mode -----------
    parser.add_argument(
        "--research-strict",
        action="store_true",
        help="NEW-248: forbid auto-discovery, implicit camera/seed, implicit splits, "
             "fallbacks, mtime selection and --limit truncation",
    )
    parser.add_argument(
        "--split-dir",
        type=str,
        default=None,
        help="Directory containing the governed *_manifest.json files produced by "
             "dataset_split_authority (required in research-strict mode)",
    )
    parser.add_argument("--train-role", type=str, default="generated_train")
    parser.add_argument("--validation-role", type=str, default="generated_validation")
    parser.add_argument(
        "--validation-miou",
        action="store_true",
        help="Record generated-validation mIoU as a diagnostic (protocol v2: never a "
             "selection signal; the final-epoch checkpoint is the governed checkpoint)",
    )
    parser.add_argument(
        "--protocol",
        type=str,
        default=None,
        help="Path to the frozen protocol file bound into model_manifest.json "
             "(default: configs/rq5_protocol_freeze_v2.json)",
    )
    args = parser.parse_args()

    # --- NEW-248: strict preconditions BEFORE any discovery or fallback ----
    strict_record: Optional[Dict[str, Any]] = None
    split_manifests: Dict[str, Dict[str, Any]] = {}
    if args.research_strict:
        # Re-parse the explicitness of camera/seed: argparse defaults hide
        # whether the caller actually supplied them.
        argv = set(sys.argv[1:])
        if not any(a == "--camera" or a.startswith("--camera=") for a in argv):
            args.camera = None
        if not any(a == "--seed" or a.startswith("--seed=") for a in argv):
            args.seed = None
        strict_record = enforce_research_strict(args)
        split_manifests = _load_split_manifests(Path(args.split_dir))
        for required in (args.train_role, args.validation_role):
            if required not in split_manifests:
                raise ResearchStrictError(
                    f"split-dir does not contain a manifest for role {required!r}"
                )

    dataset_roots = _resolve_dataset_roots(args, strict=bool(args.research_strict))
    multi_root = len(dataset_roots) > 1

    out_dir = _resolve_out_dir(args.out_dir)

    ddp_enabled, rank, world_size = _init_ddp(args.ddp)
    is_main = (rank == 0)

    device = torch.device(args.device if (args.device != "cuda" or torch.cuda.is_available()) else "cpu")

    # NEW-244/NEW-248: seed BEFORE model construction, dataset sampling and
    # DataLoader creation so every stochastic element of the run is bound to one
    # recorded seed. apply_determinism_contract also records the determinism
    # settings actually applied rather than the ones intended.
    determinism = apply_determinism_contract(args.seed, strict=bool(args.research_strict))
    seed_record = determinism.seed_record
    generator = torch.Generator()
    generator.manual_seed(int(args.seed))

    if is_main:
        print(f"🧠 Training task: segmentation (FCN-ResNet50)")
        if dataset_roots:
            print(f"   datasets({len(dataset_roots)})={', '.join(p.as_posix() for p in dataset_roots)}")
        if args.split_dir:
            print(f"   split_dir={args.split_dir} roles={sorted(split_manifests)}")
        print(f"   camera={args.camera}")
        print(f"   out_dir={out_dir}")
        print(f"   epochs={args.epochs} batch={args.batch} lr={args.lr} classes={args.num_classes}")
        print(f"   device={device} ddp={ddp_enabled} world_size={world_size}")
        print(f"   seed={args.seed} research_strict={bool(args.research_strict)}")

    limit = args.limit if args.limit > 0 else None

    # --- dataset construction ---------------------------------------------
    class_weight_paths: Optional[List[str]] = None
    ds: Any
    if args.split_dir:
        ds = ManifestSegDataset(split_manifests[args.train_role], role=args.train_role)
        class_weight_paths = ds.label_paths
        if is_main:
            print(f"   manifest_train frames={len(ds)} groups={len(set(ds.group_keys))}")
    elif multi_root:
        ds = MultiRootSegDataset(dataset_roots, cam=args.camera, limit=limit)
        if is_main:
            print(f"   multi_root=True frames={len(ds)} per_root={ds.root_frame_counts}")
            for name in ds.unpaired_rgb[:10]:
                print(f"   ⚠️  unpaired rgb (no label): {name}")
            for name in ds.unpaired_labels[:10]:
                print(f"   ⚠️  unpaired label (no rgb): {name}")
    else:
        ds = SemanticSegDataset(dataset_roots[0], cam=args.camera, limit=limit)

    val_ds = None
    if args.split_dir and args.validation_role in split_manifests:
        val_ds = ManifestSegDataset(split_manifests[args.validation_role], role=args.validation_role)
        if is_main:
            print(f"   manifest_validation frames={len(val_ds)}")

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
    val_dl = None
    if val_ds is not None:
        val_dl = DataLoader(val_ds, batch_size=args.batch, shuffle=False, num_workers=0)

    model = _build_model(args.num_classes).to(device)
    if ddp_enabled:
        local_rank = int(os.environ.get("LOCAL_RANK", "0"))
        if device.type == "cuda":
            torch.cuda.set_device(local_rank)
        model = torch.nn.parallel.DistributedDataParallel(
            model, device_ids=[local_rank] if device.type == "cuda" else None
        )

    # --- class weights: training split only (NEW-248) ----------------------
    class_weights = None
    class_counts = None
    class_weight_source = "disabled"
    if not args.no_class_weights:
        if class_weight_paths is not None:
            class_counts = scan_label_class_counts(class_weight_paths, num_classes=args.num_classes)
            class_weight_source = f"train_split_manifest:{args.train_role}"
        elif multi_root:
            class_counts = scan_multi_root_class_counts(
                dataset_roots,
                camera=args.camera,
                limit=args.limit,
                num_classes=args.num_classes,
            )
            class_weight_source = "dataset_roots_scan"
        else:
            class_counts = scan_dataset_class_counts(
                dataset_roots[0],
                camera=args.camera,
                limit=args.limit,
                num_classes=args.num_classes,
            )
            class_weight_source = "dataset_root_scan"
        class_weights = compute_class_weights(
            class_counts,
            num_classes=args.num_classes,
            scheme=args.class_weight_scheme,
        ).to(device)
        if is_main:
            present = int((class_weights > 0).sum().item())
            print(
                f"   class_weights={args.class_weight_scheme} source={class_weight_source} "
                f"present_classes={present}/{args.num_classes}"
            )

    # ignore_index: CARLA's Any(255) sentinel is a legitimate label value, not one of
    # the model's num_classes output channels -- see C27 (same fix applied to
    # min_train_segmentation.py's independently-constructed loss function).
    criterion = nn.CrossEntropyLoss(weight=class_weights, ignore_index=CARLA_SEMANTIC_ANY_CLASS_ID)
    optimizer = optim.Adam(model.parameters(), lr=float(args.lr))

    class_weighting_policy = {
        "enabled": not args.no_class_weights,
        "scheme": args.class_weight_scheme if not args.no_class_weights else None,
        "source": class_weight_source,
        "computed_from": "generated training split only",
        "forbidden_sources": [
            "generated_validation",
            "generated_test",
            "manual_test",
            "real_target",
        ],
        "class_counts": class_counts.tolist() if class_counts is not None else None,
    }

    model.train()
    last_ckpt: Optional[Path] = None
    epoch_records: List[Dict[str, Any]] = []
    for epoch in range(int(args.epochs)):
        if ddp_enabled:
            assert sampler is not None
            sampler.set_epoch(epoch)

        running = 0.0
        seen = 0
        for x, y in dl:
            x = x.to(device, non_blocking=True)
            y = y.to(device, non_blocking=True)

            optimizer.zero_grad(set_to_none=True)
            out = model(x)["out"]
            loss = criterion(out, y)
            loss.backward()
            optimizer.step()
            running += float(loss.item())
            seen += int(x.size(0))

        train_loss = running / max(1, len(dl))
        record: Dict[str, Any] = {"epoch": epoch + 1, "train_loss": train_loss}

        # NEW-248: a real generated-validation pass, for diagnostics and
        # convergence only. It never selects a checkpoint.
        if val_dl is not None:
            record.update(
                evaluate_validation_pass(
                    model,
                    val_dl,
                    criterion,
                    device,
                    num_classes=int(args.num_classes),
                    compute_miou=bool(args.validation_miou),
                )
            )

        if is_main:
            print(f"Epoch {epoch+1}/{args.epochs}  loss={train_loss:.4f}")
            if record.get("validation_loss") is not None:
                print(f"    validation_loss={record['validation_loss']:.4f}")

            ckpt = out_dir / f"seg_fcn_epoch{epoch+1:03d}.pt"
            # unwrap DDP
            state = model.module.state_dict() if hasattr(model, "module") else model.state_dict()
            torch.save(state, ckpt)
            last_ckpt = ckpt
            print(f"✅ Saved {ckpt}")
        epoch_records.append(record)

    training_history = {
        "schema": "rq5_training_history_v1",
        "claim_scope": "TEST_FIXTURE_ONLY",
        "seed": int(args.seed),
        "epochs_requested": int(args.epochs),
        "epochs_completed": len(epoch_records),
        "research_strict": bool(args.research_strict),
        "checkpoint_policy": {
            "checkpoint_policy": "final_epoch_only",
            "validation_selects_epoch": False,
            "early_stopping": False,
            "selection_consults_manual": False,
        },
        "validation_dataset_role": args.validation_role if val_dl is not None else None,
        "validation_miou_recorded": bool(args.validation_miou),
        "class_weighting": {
            "scheme": args.class_weight_scheme,
            "source": class_weight_source,
        },
        "epochs": epoch_records,
    }
    if is_main:
        write_training_history(out_dir, training_history)

    # NEW-243/NEW-248: bind the final checkpoint to the run that produced it.
    if is_main and last_ckpt is not None and not args.no_manifest:
        max_files = args.dataset_identity_max_files or None

        if args.split_dir:
            # Identity comes from the governed split manifests, so the identity
            # describes exactly the frames that were trained on.
            role_identities = {
                role: {
                    "schema": manifest.get("schema"),
                    "identity_sha256": manifest.get("dataset_identity_sha256"),
                    "complete": bool(manifest.get("dataset_identity_complete")),
                    "root": manifest.get("dataset_root"),
                    "camera": manifest.get("camera"),
                    "role": role,
                    "frame_count": manifest.get("frame_count"),
                    "group_kind": manifest.get("group_kind"),
                }
                for role, manifest in split_manifests.items()
            }
            train_identity = role_identities[args.train_role]
            validation_identity = role_identities.get(args.validation_role)
            test_identities = {
                role: ident for role, ident in role_identities.items() if role.endswith("_test")
            }
            train_roots = [str(split_manifests[args.train_role].get("dataset_root"))]
        else:
            identities = [
                dataset_content_identity(root, args.camera, max_files=max_files)
                for root in dataset_roots
            ]
            train_identity = (
                combine_dataset_identities(identities, strategy=MULTI_ROOT_TRAIN)
                if multi_root
                else identities[0]
            )
            validation_identity = None
            test_identities = {}
            train_roots = [p.as_posix() for p in dataset_roots]

        if args.research_strict:
            # A partial identity cannot back an authoritative role.
            for role, identity in (
                [("generated_train", train_identity)]
                + ([("generated_validation", validation_identity)] if validation_identity else [])
                + list(test_identities.items())
            ):
                if not identity.get("complete"):
                    raise ResearchStrictError(
                        f"role {role!r} carries an incomplete dataset identity; research-strict "
                        "runs may not bind a partial identity"
                    )

        manifest = build_model_manifest(
            checkpoint=last_ckpt,
            train_dataset_identity=train_identity,
            train_roots=train_roots,
            validation_identity=validation_identity,
            test_dataset_identities=test_identities,
            architecture_version="fcn_resnet50_torchvision_default",
            num_classes=int(args.num_classes),
            class_mapping={
                "num_classes": int(args.num_classes),
                "ignore_index": int(CARLA_SEMANTIC_ANY_CLASS_ID),
                "label_space": "carla_semantic_tagn",
            },
            camera=args.camera or "",
            optimizer="Adam",
            learning_rate=float(args.lr),
            epochs=int(args.epochs),
            batch_size=int(args.batch),
            seed=int(args.seed),
            augmentation_policy="none",
            protocol_path=args.protocol,
            class_weighting_policy=class_weighting_policy,
            determinism=determinism.to_dict(),
            training_history={
                "epochs": len(epoch_records),
                "training_history_sha256": sha256_text(canonical_dumps(training_history)),
                "validation_role": training_history["validation_dataset_role"],
            },
            extra={
                "multi_root": bool(multi_root),
                "train_frame_count": len(ds),
                "train_frame_counts_per_root": (
                    ds.root_frame_counts if (multi_root and hasattr(ds, "root_frame_counts")) else None
                ),
                "seed_applied": seed_record,
                "ddp": bool(ddp_enabled),
                "world_size": int(world_size),
                "split_dir": str(Path(args.split_dir).resolve()) if args.split_dir else None,
                "research_strict": strict_record,
                "training_history_file": "TRAINING_HISTORY.json" if is_main else None,
            },
        )
        manifest_path = write_model_manifest(out_dir, manifest)
        print(f"🔒 Wrote model manifest → {manifest_path}")

    if ddp_enabled:
        torch.distributed.destroy_process_group()

    return 0


if __name__ == "__main__":
    sys.exit(main())