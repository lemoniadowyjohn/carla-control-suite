#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Labeled simulation evaluation for semantic segmentation models.

Computes mIoU and pixel accuracy on labeled CARLA sim data.

NEW-240 / NEW-243 / NEW-245
---------------------------
Three governed-evidence rules this evaluator now enforces:

* **Zero frames is missing evidence, not a measured zero.** Previously a dataset
  with no paired frames produced ``mIoU: 0.0, pixel_accuracy: 0.0,
  frames_count: 0, error: ...`` and the process still exited 0, so the parent
  runner recorded a *successful* evaluation of nothing. Now the no-frames case
  is an explicit failure: metrics are ``null`` (never 0.0), ``status`` is
  ``failed``, and the process exits nonzero under governed mode.
* **Strict checkpoint loading.** ``load_state_dict(..., strict=False)`` was
  called without inspecting ``missing_keys``/``unexpected_keys``, so an
  incompatible checkpoint could partially load and leave the model half
  randomly initialized. Loading is strict by default; ``--allow-partial-load``
  makes a recorded partial load explicit instead of silent.
* **Checkpoint provenance.** The evaluated checkpoint's SHA-256, its companion
  model manifest verification, and the evaluation dataset's content identity are
  recorded in the report so a metric can never be attributed to the wrong
  dataset or an unbound checkpoint.

Inputs:
  - `--model`: path to a torchvision.models.segmentation.fcn_resnet50 state_dict
  - `--dataset`: dataset root with rgb/<cam>/*.png and semseg_raw/<cam>/*.png

Outputs:
  - JSON report with mIoU, pixel_accuracy, per_class_iou, frames_count, status
  - Prints: "Wrote labeled sim eval: <path>"
  - Prints: "mIoU=... pixel_accuracy=... frames=N"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

import torch
import torch.nn.functional as F
from torchvision import models

from ultimate_pipeline.perception.carla_classes import (
    CARLA_SEMANTIC_ANY_CLASS_ID,
    assert_label_ids_in_range,
)
from ultimate_pipeline.perception.rq5_provenance import (
    MODEL_MANIFEST_FILENAME,
    DatasetIdentityError,
    StateDictLoadError,
    dataset_content_identity,
    load_state_dict_governed,
    verify_checkpoint_manifest,
)
from ultimate_pipeline.perception.semantic_classes import (
    CARLA_SEMANTIC_NUM_CLASSES,
    validate_num_classes,
)
from ultimate_pipeline.utils.file_hashing import sha256_file

#: Exit codes with distinct meaning (NEW-240). 0 = metrics measured;
#: 2 = evaluation could not produce metrics (missing evidence); 3 = invalid
#: inputs (bad checkpoint / unusable dataset layout).
EXIT_OK = 0
EXIT_MISSING_EVIDENCE = 2
EXIT_INVALID_INPUT = 3

STATUS_OK = "ok"
STATUS_FAILED = "failed"


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


def _compute_pixel_accuracy(
    pred: torch.Tensor, target: torch.Tensor, ignore_index: Optional[int] = None
) -> float:
    """Compute overall pixel accuracy.

    `ignore_index` excludes pixels unanswerable by construction (e.g. CARLA's
    Any=255 sentinel, which a fixed-num_classes segmentation head can never
    predict) from both numerator and denominator, matching how
    `_compute_iou_per_class` already excludes them from per-class IoU.
    """
    if ignore_index is not None:
        mask = target != ignore_index
        pred = pred[mask]
        target = target[mask]
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
    allow_partial_load: bool = False,
    require_manifest: bool = False,
    min_frames: int = 1,
) -> Dict[str, Any]:
    """Evaluate model on labeled sim dataset.

    Returns a report dict carrying an explicit ``status`` (``ok`` / ``failed``).
    Metric fields are ``None`` -- never ``0.0`` -- whenever no metric was
    measured, so "measured zero" and "no evidence" stay distinguishable
    (NEW-240).
    """
    device_obj = torch.device(device if (device != "cuda" or torch.cuda.is_available()) else "cpu")
    num_classes = validate_num_classes(num_classes)

    report: Dict[str, Any] = {
        "status": STATUS_FAILED,
        "mIoU": None,
        "pixel_accuracy": None,
        "per_class_iou": {},
        "frames_count": 0,
        "model": str(Path(model_path).resolve()),
        "model_sha256": None,
        "model_manifest_verification": None,
        "dataset": str(Path(dataset_root).resolve()),
        "dataset_identity_sha256": None,
        "camera": camera,
        "device": str(device_obj),
        "num_classes": int(num_classes),
        "limit": int(limit),
        "min_frames": int(min_frames),
        "errors": [],
    }

    # NEW-243: identify the checkpoint and its provenance binding.
    try:
        report["model_sha256"] = sha256_file(model_path)
    except OSError as exc:
        report["errors"].append(f"checkpoint_unreadable: {exc}")
        report["error"] = f"Checkpoint not found or unreadable: {model_path}"
        return report

    manifest_path = Path(model_path).parent / MODEL_MANIFEST_FILENAME
    if manifest_path.is_file():
        verification = verify_checkpoint_manifest(
            model_path, manifest_path, require_provenance=require_manifest
        )
        report["model_manifest_verification"] = verification
        if require_manifest and not verification["ok"]:
            report["errors"].extend(verification["failures"])
            report["error"] = "Checkpoint provenance verification failed"
            return report
    elif require_manifest:
        report["errors"].append(
            f"no_companion_manifest: expected {manifest_path.name} next to the checkpoint"
        )
        report["error"] = "No companion model manifest found for the checkpoint"
        return report

    # NEW-245: strict load with explicit, recorded parameter-set verification.
    model = models.segmentation.fcn_resnet50(weights=None, num_classes=num_classes)
    try:
        load_record: Dict[str, Any] = {}
        report["state_dict_load"] = load_state_dict_governed(
            model, model_path, allow_partial=allow_partial_load, record=load_record
        )
    except (StateDictLoadError, FileNotFoundError) as exc:
        report["errors"].append(f"state_dict_load_failed: {exc}")
        report["error"] = f"Checkpoint could not be loaded: {exc}"
        return report
    model.to(device_obj)
    model.eval()

    # NEW-243: bind the metrics to the exact evaluation dataset content.
    try:
        identity = dataset_content_identity(dataset_root, camera)
        report["dataset_identity_sha256"] = identity["identity_sha256"]
        report["dataset_file_count"] = identity["file_count"]
    except DatasetIdentityError as exc:
        report["errors"].append(f"dataset_identity_unavailable: {exc}")

    # Find paired files
    pairs = _find_paired_files(dataset_root, camera)
    if limit > 0:
        pairs = pairs[:limit]

    if not pairs:
        # NEW-240: no frames is MISSING EVIDENCE. Metrics stay null; they must
        # never be reported as a measured 0.0.
        message = f"No paired RGB/semseg files found in {dataset_root} for camera {camera}"
        report["errors"].append("no_paired_frames")
        report["error"] = message
        return report

    if len(pairs) < int(min_frames):
        report["errors"].append(
            f"insufficient_frames: {len(pairs)} < required {int(min_frames)}"
        )
        report["error"] = (
            f"Only {len(pairs)} paired frame(s) available, but this governed "
            f"evaluation requires at least {int(min_frames)}"
        )
        return report

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

            pixel_acc = _compute_pixel_accuracy(
                pred, target, ignore_index=CARLA_SEMANTIC_ANY_CLASS_ID
            )
            pixel_accuracies.append(pixel_acc)

    # Aggregate
    per_class_iou = {c: float(np.mean(ious)) for c, ious in all_class_ious.items()}
    if not per_class_iou:
        # Frames existed, but no evaluable label pixel survived the Any(255)
        # ignore mask. That is still missing evidence, not a measured mIoU of 0.
        report["errors"].append("no_evaluable_label_pixels")
        report["error"] = (
            "No evaluable label pixels remained after excluding the Any(255) sentinel"
        )
        return report

    mean_iou = float(np.mean(list(per_class_iou.values())))
    mean_pixel_acc = float(np.mean(pixel_accuracies)) if pixel_accuracies else None

    report.update(
        {
            "status": STATUS_OK,
            "mIoU": mean_iou,
            "pixel_accuracy": mean_pixel_acc,
            "per_class_iou": per_class_iou,
            "frames_count": len(pairs),
        }
    )
    return report


def parse_args():
    ap = argparse.ArgumentParser(description="Labeled sim evaluation for segmentation")
    ap.add_argument("--model", required=True, help="Path to model checkpoint (state_dict)")
    ap.add_argument("--dataset", required=True, help="Dataset root with rgb/<cam>/ and semseg_raw/<cam>/")
    ap.add_argument("--camera", default="front_left_camera", help="Camera subdirectory name")
    ap.add_argument("--out-json", default="sim_labeled_eval.json", help="Output JSON path")
    ap.add_argument("--num-classes", type=int, default=CARLA_SEMANTIC_NUM_CLASSES)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--limit", type=int, default=0, help="Max frames to evaluate (0=all)")
    ap.add_argument(
        "--min-frames",
        type=int,
        default=1,
        help="NEW-240: minimum paired frames required for a valid evaluation (0 = accept any)",
    )
    ap.add_argument(
        "--allow-partial-load",
        action="store_true",
        help="NEW-245: accept a checkpoint whose parameters do not fully match (recorded, not silent)",
    )
    ap.add_argument(
        "--require-manifest",
        action="store_true",
        help="NEW-243: require and verify a companion model_manifest.json next to the checkpoint",
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()

    result = evaluate_model(
        model_path=Path(args.model),
        dataset_root=Path(args.dataset),
        camera=args.camera,
        num_classes=args.num_classes,
        device=args.device,
        limit=args.limit,
        allow_partial_load=args.allow_partial_load,
        require_manifest=args.require_manifest,
        min_frames=args.min_frames,
    )

    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"Wrote labeled sim eval: {out_path}")
    if result["status"] != STATUS_OK:
        # NEW-240: a failed evaluation is reported as a failure, and the report
        # is still written so the evidence of the failure is durable.
        for message in result.get("errors", []):
            print(f"[FAIL] {message}")
        return EXIT_MISSING_EVIDENCE

    print(
        f"mIoU={result['mIoU']:.6f} "
        f"pixel_accuracy={result['pixel_accuracy']:.6f} "
        f"frames={result['frames_count']}"
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
