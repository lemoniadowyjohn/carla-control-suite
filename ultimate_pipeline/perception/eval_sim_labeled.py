#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Labeled simulation evaluation for semantic segmentation models.

Computes mIoU and pixel accuracy on labeled CARLA sim data.

Inputs:
 - `--model`: path to a torchvision.models.segmentation.fcn_resnet50 state_dict
 - `--dataset`: dataset root with rgb/<cam>/*.png and semseg_raw/<cam>/*.png

Outputs:
 - JSON report with mIoU, pixel_accuracy, per_class_iou, frames_count
 - Prints: "Wrote labeled sim eval: <path>"
 - Prints: "mIoU=... pixel_accuracy=... frames=N"
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

import torch
import torch.nn.functional as F
from torchvision import models

from ultimate_pipeline.perception.carla_classes import assert_label_ids_in_range
from ultimate_pipeline.perception.semantic_classes import (
    CARLA_SEMANTIC_NUM_CLASSES,
    validate_num_classes,
)


def _find_paired_files(
    dataset_root: Path, camera: str
) -> List[Tuple[Path, Path]]:
    """Find paired RGB and semseg files."""
    rgb_dir = dataset_root / "rgb" / camera
    seg_dir = dataset_root / "semseg_raw" / camera

    if not rgb_dir.exists() or not seg_dir.exists():
        return []

    pairs = []
    for rgb_path in sorted(rgb_dir.glob("*.png")):
        seg_path = seg_dir / rgb_path.name
        if seg_path.exists():
            pairs.append((rgb_path, seg_path))

    return pairs


def _load_rgb(path: Path, resize: Optional[Tuple[int, int]] = None) -> torch.Tensor:
    """Load RGB image as tensor [C,H,W] in [0,1]."""
    img = Image.open(path).convert("RGB")
    if resize is not None:
        img = img.resize(resize, resample=Image.BILINEAR)
    arr = np.asarray(img, dtype=np.float32) / 255.0
    x = torch.from_numpy(arr).permute(2, 0, 1)  # C,H,W
    return x


def _load_semseg(path: Path, resize: Optional[Tuple[int, int]] = None) -> torch.Tensor:
    """Load semantic segmentation label as tensor [H,W] with class indices."""
    img = Image.open(path)
    if resize is not None:
        img = img.resize(resize, resample=Image.NEAREST)
    # CARLA semseg_raw is typically RGB where R channel encodes class ID
    arr = np.asarray(img)
    if arr.ndim == 3:
        # Use red channel as class index (CARLA convention)
        arr = arr[:, :, 0]
    assert_label_ids_in_range(arr)
    return torch.from_numpy(arr.astype(np.int64))


def _compute_iou_per_class(
    pred: torch.Tensor, target: torch.Tensor, num_classes: int
) -> Dict[int, float]:
    """Compute IoU for each class present in target."""
    pred_np = pred.cpu().numpy().flatten()
    target_np = target.cpu().numpy().flatten()

    iou_per_class = {}
    for c in range(num_classes):
        pred_c = pred_np == c
        target_c = target_np == c

        if not target_c.any():
            continue  # Skip classes not present in target

        intersection = (pred_c & target_c).sum()
        union = (pred_c | target_c).sum()

        if union > 0:
            iou_per_class[c] = float(intersection / union)
        else:
            iou_per_class[c] = 0.0

    return iou_per_class


def _compute_pixel_accuracy(pred: torch.Tensor, target: torch.Tensor) -> float:
    """Compute overall pixel accuracy."""
    correct = (pred == target).sum().item()
    total = target.numel()
    return float(correct / total) if total > 0 else 0.0


def evaluate_model(
    model_path: Path,
    dataset_root: Path,
    camera: str,
    num_classes: int = CARLA_SEMANTIC_NUM_CLASSES,
    device: str = "cpu",
    limit: int = 0,
) -> Dict:
    """Evaluate model on labeled sim dataset.

    Returns:
        Dict with mIoU, pixel_accuracy, per_class_iou, frames_count
    """
    device_obj = torch.device(device if (device != "cuda" or torch.cuda.is_available()) else "cpu")
    num_classes = validate_num_classes(num_classes)

    # Load model
    model = models.segmentation.fcn_resnet50(weights=None, num_classes=num_classes)
    state_dict = torch.load(model_path, map_location="cpu")
    model.load_state_dict(state_dict, strict=False)
    model.to(device_obj)
    model.eval()

    # Find paired files
    pairs = _find_paired_files(dataset_root, camera)
    if limit > 0:
        pairs = pairs[:limit]

    if not pairs:
        return {
            "mIoU": 0.0,
            "pixel_accuracy": 0.0,
            "per_class_iou": {},
            "frames_count": 0,
            "error": f"No paired RGB/semseg files found in {dataset_root} for camera {camera}",
        }

    # Accumulate per-class IoUs and pixel accuracy
    all_class_ious: Dict[int, List[float]] = {}
    pixel_accuracies = []

    with torch.no_grad():
        for rgb_path, seg_path in pairs:
            # Load data
            rgb = _load_rgb(rgb_path).unsqueeze(0).to(device_obj)
            target = _load_semseg(seg_path).to(device_obj)

            # Predict
            logits = model(rgb)["out"]
            pred = logits.argmax(dim=1).squeeze(0)

            # Resize pred to match target if needed
            if pred.shape != target.shape:
                pred = F.interpolate(
                    pred.unsqueeze(0).unsqueeze(0).float(),
                    size=target.shape,
                    mode="nearest"
                ).squeeze().long()

            # Compute metrics
            class_ious = _compute_iou_per_class(pred, target, num_classes)
            for c, iou in class_ious.items():
                if c not in all_class_ious:
                    all_class_ious[c] = []
                all_class_ious[c].append(iou)

            pixel_acc = _compute_pixel_accuracy(pred, target)
            pixel_accuracies.append(pixel_acc)

    # Aggregate
    per_class_iou = {c: float(np.mean(ious)) for c, ious in all_class_ious.items()}
    mean_iou = float(np.mean(list(per_class_iou.values()))) if per_class_iou else 0.0
    mean_pixel_acc = float(np.mean(pixel_accuracies)) if pixel_accuracies else 0.0

    return {
        "mIoU": mean_iou,
        "pixel_accuracy": mean_pixel_acc,
        "per_class_iou": per_class_iou,
        "frames_count": len(pairs),
        "model": str(model_path.resolve()),
        "dataset": str(dataset_root.resolve()),
        "camera": camera,
        "device": str(device_obj),
    }


def parse_args():
    ap = argparse.ArgumentParser(description="Labeled sim evaluation for segmentation")
    ap.add_argument("--model", required=True, help="Path to model checkpoint (state_dict)")
    ap.add_argument("--dataset", required=True, help="Dataset root with rgb/<cam>/ and semseg_raw/<cam>/")
    ap.add_argument("--camera", default="front_left_camera", help="Camera subdirectory name")
    ap.add_argument("--out-json", default="sim_labeled_eval.json", help="Output JSON path")
    ap.add_argument("--num-classes", type=int, default=CARLA_SEMANTIC_NUM_CLASSES)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--limit", type=int, default=0, help="Max frames to evaluate (0=all)")
    return ap.parse_args()


def main() -> None:
    args = parse_args()

    result = evaluate_model(
        model_path=Path(args.model),
        dataset_root=Path(args.dataset),
        camera=args.camera,
        num_classes=args.num_classes,
        device=args.device,
        limit=args.limit,
    )

    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"Wrote labeled sim eval: {out_path}")
    print(f"mIoU={result['mIoU']:.6f} pixel_accuracy={result['pixel_accuracy']:.6f} frames={result['frames_count']}")


if __name__ == "__main__":
    main()
