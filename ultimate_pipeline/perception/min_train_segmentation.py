#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ultimate_pipeline/perception/min_train_segmentation.py

Minimal PyTorch semantic segmentation trainer.

- Uses torchvision FCN (fcn_resnet50) as a quick baseline.
- Reads:
    rgb/<cam>/*.png
    semseg_raw/<cam>/*.png  (uint8 class ids)
- Writes:
    out_dir/checkpoints/model_last.pt
    out_dir/metrics.json

NEW-248: a manifest-driven mode (``--split-dir``) trains on exactly the frames
listed in a governed RQ5 split manifest, and a real generated-validation loop
writes ``TRAINING_HISTORY.json``. Class weights may only be derived from the
training split, never from validation, generated-test or manual-test labels.

This is a minimal working solution to unblock thesis experiments.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

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
    scan_label_class_counts,
)
from ultimate_pipeline.perception.semantic_classes import (
    CARLA_SEMANTIC_NUM_CLASSES,
    validate_num_classes,
)

TRAINING_HISTORY_SCHEMA = "rq5_training_history_v1"
TRAINING_HISTORY_FILENAME = "TRAINING_HISTORY.json"


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


class ManifestSegDataset(Dataset):
    """
    NEW-248: train/validate on exactly the frames of a governed split manifest.

    A directory listing and a governed split are different things. Reading the
    manifest removes any possibility that ``--limit`` slicing, a stale file in
    the directory, or a re-capture silently changed which frames were used.

    Each entry must carry an explicit ``rgb_path``/``label_path`` and a
    ``sample_identity`` (the paired content digest), so the frames actually
    loaded can be tied back to the leakage audit.
    """

    def __init__(self, manifest: Any, role: str = "generated_train", limit: int = 0):
        from ultimate_pipeline.perception.dataset_split_authority import (
            SplitAuthorityError,
            load_split_manifest,
        )

        if isinstance(manifest, (str, Path)):
            manifest = load_split_manifest(manifest)
        if not isinstance(manifest, dict):
            raise SplitAuthorityError("split manifest must be a mapping")

        declared_role = str(manifest.get("role") or "")
        if declared_role and role and declared_role != role:
            raise SplitAuthorityError(
                f"split manifest declares role {declared_role!r}, not {role!r}; refusing to "
                "train on a manifest that names a different role"
            )

        entries = list(manifest.get("entries") or [])
        if not entries:
            raise SplitAuthorityError(f"split manifest for role {role!r} has no entries")

        self.role = role or declared_role
        self.items: List[Tuple[Path, Path]] = []
        self.sample_identities: List[str] = []
        self.group_keys: List[str] = []
        missing: List[str] = []
        for entry in entries:
            rgb_path = Path(str(entry["rgb_path"]))
            label_path = Path(str(entry["label_path"]))
            if not rgb_path.is_file() or not label_path.is_file():
                missing.append(entry.get("filename") or str(entry))
                continue
            self.items.append((rgb_path, label_path))
            self.sample_identities.append(str(entry.get("sample_identity") or ""))
            self.group_keys.append(str(entry.get("group_key") or ""))

        if missing:
            raise SplitAuthorityError(
                f"{len(missing)} frame(s) listed in the {self.role} split manifest are missing "
                f"from disk (first: {missing[:3]}); a governed split may not be partially loaded"
            )
        if limit and limit > 0:
            self.items = self.items[:limit]
            self.sample_identities = self.sample_identities[:limit]
            self.group_keys = self.group_keys[:limit]

    @property
    def label_paths(self) -> List[str]:
        return [str(label) for _, label in self.items]

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


def _load_frame_pair(rgb_path: Path, lab_path: Path) -> Tuple[torch.Tensor, torch.Tensor]:
    img = Image.open(rgb_path).convert("RGB")
    lab = Image.open(lab_path).convert("L")
    x = TF.to_tensor(img)
    arr = np.array(lab, dtype=np.uint8)
    assert_label_ids_in_range(arr)
    return x, torch.from_numpy(arr.astype(np.int64))


def evaluate_validation_pass(
    model: Any,
    dataloader: DataLoader,
    criterion: Any,
    device: Any,
    *,
    num_classes: int = CARLA_SEMANTIC_NUM_CLASSES,
    compute_miou: bool = False,
) -> Dict[str, Any]:
    """
    NEW-248: one generated-validation pass.

    Runs in eval mode with gradients disabled. ``validation_loss`` is always
    measured. ``validation_miou`` is computed only when ``compute_miou`` is
    requested, because it costs a full confusion matrix per frame and the
    protocol uses it as a diagnostic, not as a selection signal.

    This function never sees manual-test data. It is not a checkpoint selector:
    protocol v2 fixes the governed checkpoint at the final epoch.
    """
    import torch as _torch

    model.eval()
    running = 0.0
    batches = 0
    confusion = np.zeros((int(num_classes), int(num_classes)), dtype=np.int64) if compute_miou else None
    ignore_index = int(CARLA_SEMANTIC_ANY_CLASS_ID)

    with _torch.no_grad():
        for x, y in dataloader:
            x = x.to(device)
            y = y.to(device)
            out = model(x)["out"]
            loss = criterion(out, y)
            running += float(loss.item())
            batches += 1
            if confusion is not None:
                pred = out.argmax(dim=1).detach().cpu().numpy().reshape(-1)
                truth = y.detach().cpu().numpy().reshape(-1)
                keep = truth != ignore_index
                pred = pred[keep]
                truth = truth[keep]
                np.add.at(confusion, (truth, pred), 1)

    model.train()
    result: Dict[str, Any] = {
        "validation_loss": (running / batches) if batches else None,
        "validation_batches": int(batches),
    }
    if confusion is not None:
        result["validation_miou"] = _confusion_miou(confusion, int(num_classes), ignore_index)
    return result


def _confusion_miou(confusion: np.ndarray, num_classes: int, ignore_index: int) -> Optional[float]:
    """Mean IoU over classes that actually occur in the ground truth."""
    present = [c for c in range(num_classes) if c != ignore_index and int(confusion[c].sum()) > 0]
    if not present:
        return None
    ious: List[float] = []
    for c in present:
        tp = float(confusion[c, c])
        fp = float(confusion[:, c].sum() - tp)
        fn = float(confusion[c].sum() - tp)
        denom = tp + fp + fn
        if denom <= 0:
            continue
        ious.append(tp / denom)
    return (float(np.mean(ious)) if ious else None)


def write_training_history(
    out_dir: Any,
    history: Dict[str, Any],
    *,
    filename: str = TRAINING_HISTORY_FILENAME,
) -> Path:
    """Persist ``TRAINING_HISTORY.json`` for the convergence gate to read."""
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / filename
    target.write_text(json.dumps(history, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


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
    ap.add_argument("--seed", type=int, default=None,
                    help="frozen-protocol seed (NEW-218): torch.manual_seed + seeded "
                         "DataLoader order. Default None preserves legacy behavior.")
    # NEW-248: research-strict + manifest-driven mode
    ap.add_argument(
        "--research-strict",
        action="store_true",
        help="NEW-248: forbid auto-discovery, implicit camera/seed, implicit splits and "
             "non-zero --limit; a missing explicit dataset is a hard failure",
    )
    ap.add_argument(
        "--split-dir",
        default=None,
        help="Directory holding the governed *_manifest.json files from "
             "dataset_split_authority (required in research-strict mode)",
    )
    ap.add_argument("--train-role", default="generated_train")
    ap.add_argument("--validation-role", default="generated_validation")
    ap.add_argument(
        "--validation-miou",
        action="store_true",
        help="Compute generated-validation mIoU as a diagnostic (never a selection signal)",
    )
    return ap.parse_args()


def main():
    args = parse_args()
    ds_root = Path(args.dataset)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_dir = out_dir / "checkpoints"
    ckpt_dir.mkdir(exist_ok=True)

    if args.research_strict:
        if args.split_dir is None:
            raise SystemExit(
                "research-strict mode requires an explicit --split-dir; implicit split "
                "creation is forbidden"
            )
        if int(args.limit) > 0:
            raise SystemExit(
                "research-strict mode forbids --limit; a prefix of a governed split is not the split"
            )

    if args.split_dir:
        from ultimate_pipeline.perception.dataset_split_authority import SPLIT_FILENAMES, load_split_manifest

        split_dir = Path(args.split_dir)
        train_manifest = load_split_manifest(split_dir / SPLIT_FILENAMES[args.train_role])
        ds = ManifestSegDataset(train_manifest, role=args.train_role)
        val_ds = None
        val_path = split_dir / SPLIT_FILENAMES[args.validation_role]
        if val_path.is_file():
            val_ds = ManifestSegDataset(
                load_split_manifest(val_path), role=args.validation_role
            )
        class_weight_paths = ds.label_paths
    else:
        ds = SegDataset(ds_root, args.camera, limit=args.limit)
        val_ds = None
        class_weight_paths = None

    if args.seed is not None:
        # Frozen-protocol path (NEW-218): fully seeded order. num_workers=0
        # keeps ordering a pure function of the seed (no worker RNG split).
        torch.manual_seed(int(args.seed))
        generator = torch.Generator().manual_seed(int(args.seed))
        dl = DataLoader(ds, batch_size=args.batch, shuffle=True, num_workers=0,
                        pin_memory=True, generator=generator)
    else:
        # Legacy path: unchanged behavior.
        dl = DataLoader(ds, batch_size=args.batch, shuffle=True, num_workers=2, pin_memory=True)

    val_dl = None
    if val_ds is not None:
        val_dl = DataLoader(val_ds, batch_size=args.batch, shuffle=False, num_workers=0)

    num_classes = validate_num_classes(args.num_classes)
    model = torchvision.models.segmentation.fcn_resnet50(weights=None, num_classes=num_classes)
    model.to(args.device)

    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    class_counts = None
    class_weights = None
    if not args.no_class_weights:
        # NEW-248: class statistics come from the training split only. A whole-root
        # scan would include validation/generated-test frames, and a manual root
        # would be a protocol violation, so an explicit manifest is used whenever
        # one is supplied.
        if class_weight_paths is not None:
            class_counts = scan_label_class_counts(class_weight_paths, num_classes=num_classes)
        else:
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
        "seed": args.seed,
        "class_weighting": {
            "enabled": not args.no_class_weights,
            "scheme": args.class_weight_scheme if not args.no_class_weights else None,
            "source": "train_split_manifest" if class_weight_paths is not None else "dataset_root_scan",
            "counts": class_counts.tolist() if class_counts is not None else None,
            "weights": class_weights.detach().cpu().tolist() if class_weights is not None else None,
        },
    }
    model.train()
    history_epochs: List[Dict[str, Any]] = []
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

        record: Dict[str, Any] = {"epoch": ep + 1, "train_loss": ep_loss}
        if val_dl is not None:
            record.update(
                evaluate_validation_pass(
                    model,
                    val_dl,
                    loss_fn,
                    args.device,
                    num_classes=num_classes,
                    compute_miou=bool(args.validation_miou),
                )
            )
        history_epochs.append(record)
        # NEW-248 / protocol v2: the final-epoch checkpoint is the governed
        # checkpoint. Validation never selects a different epoch.
        torch.save(model.state_dict(), (ckpt_dir / "model_last.pt").as_posix())

    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    write_training_history(
        out_dir,
        {
            "schema": TRAINING_HISTORY_SCHEMA,
            "claim_scope": "TEST_FIXTURE_ONLY",
            "seed": args.seed,
            "epochs_requested": int(args.epochs),
            "checkpoint_policy": {
                "checkpoint_policy": "final_epoch_only",
                "validation_selects_epoch": False,
                "early_stopping": False,
                "selection_consults_manual": False,
            },
            "validation_dataset_role": args.validation_role if val_dl is not None else None,
            "epochs": history_epochs,
        },
    )
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