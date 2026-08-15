#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Unlabeled real-world evaluation for a segmentation model.

Your thesis requires evaluating generalization on **unlabeled real data**.
Without labels, we can't compute mIoU, but we *can* quantify domain shift with:
 - mean prediction entropy (higher = model is unsure)
 - mean max-probability confidence (lower = less certain)
 - Fréchet distance between pooled logits distributions (sim vs real) if sim
   dataset is provided

Inputs:
 - `--model`: path to a `torchvision.models.segmentation.fcn_resnet50` state_dict
 - `--real-dir`: directory containing real RGB images (.png/.jpg)
 - optional `--sim-dataset`: a recorded simulator dataset root with `rgb/<cam>`

Outputs:
 - JSON report written to `--out-json`
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, Optional, Tuple

import numpy as np
from PIL import Image

import torch
import torch.nn.functional as F
from torchvision import models

from ultimate_pipeline.perception.semantic_classes import (
    CARLA_SEMANTIC_NUM_CLASSES,
    validate_num_classes,
)


def _iter_images(folder: Path) -> Iterable[Path]:
    exts = {".png", ".jpg", ".jpeg", ".bmp"}
    for p in sorted(folder.rglob("*")):
        if p.suffix.lower() in exts:
            yield p


def _load_rgb(path: Path, resize: Optional[Tuple[int, int]] = None) -> torch.Tensor:
    img = Image.open(path).convert("RGB")
    if resize is not None:
        img = img.resize(resize, resample=Image.BILINEAR)
    arr = np.asarray(img, dtype=np.float32) / 255.0
    x = torch.from_numpy(arr).permute(2, 0, 1)  # C,H,W
    return x


def _entropy_from_logits(logits: torch.Tensor) -> torch.Tensor:
    # logits: [N,C,H,W]
    p = F.softmax(logits, dim=1)
    ent = -(p * torch.log(torch.clamp(p, min=1e-8))).sum(dim=1)  # [N,H,W]
    return ent


def _pooled_logits(logits: torch.Tensor) -> torch.Tensor:
    # Mean pool per-class logit over space -> [N,C]
    return logits.mean(dim=(2, 3))


def _frechet_distance(mu1, cov1, mu2, cov2) -> float:
    # Minimal Fréchet distance for Gaussians.
    # We keep it simple and robust; if sqrtm fails, we fall back to diagonal.
    from scipy.linalg import sqrtm  # type: ignore

    mu1 = np.asarray(mu1)
    mu2 = np.asarray(mu2)
    cov1 = np.asarray(cov1)
    cov2 = np.asarray(cov2)
    diff = mu1 - mu2
    try:
        covmean = sqrtm(cov1.dot(cov2))
        if np.iscomplexobj(covmean):
            covmean = covmean.real
        return float(diff.dot(diff) + np.trace(cov1 + cov2 - 2.0 * covmean))
    except Exception:
        # diagonal fallback
        d1 = np.diag(np.diag(cov1))
        d2 = np.diag(np.diag(cov2))
        covmean = np.sqrt(np.diag(d1) * np.diag(d2))
        return float(diff.dot(diff) + np.trace(d1 + d2 - 2.0 * np.diag(covmean)))


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="path to model checkpoint (state_dict)")
    ap.add_argument("--real-dir", required=True, help="folder with real RGB images")
    ap.add_argument("--out-json", default="real_eval_report.json")
    ap.add_argument("--num-classes", type=int, default=CARLA_SEMANTIC_NUM_CLASSES)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--resize", default="", help="e.g. 1024x512 to match simulator")
    ap.add_argument("--sim-dataset", default="", help="optional simulator dataset root (for FID-like distance)")
    ap.add_argument("--sim-camera", default="front_left_camera")
    ap.add_argument("--limit", type=int, default=500)
    return ap.parse_args()


def _run_folder(model, folder: Path, device: torch.device, resize: Optional[Tuple[int, int]], limit: int) -> dict:
    entropies = []
    confidences = []
    pooled = []

    paths = list(_iter_images(folder))
    if limit > 0:
        paths = paths[:limit]

    model.eval()
    with torch.no_grad():
        for p in paths:
            x = _load_rgb(p, resize=resize).unsqueeze(0).to(device)
            logits = model(x)["out"]
            ent = _entropy_from_logits(logits).mean().item()
            prob = F.softmax(logits, dim=1)
            conf = prob.max(dim=1).values.mean().item()
            entropies.append(ent)
            confidences.append(conf)
            pooled.append(_pooled_logits(logits).squeeze(0).detach().cpu().numpy())

    pooled = np.stack(pooled, axis=0) if pooled else np.zeros((0, 1), dtype=np.float32)
    return {
        "n": len(paths),
        "entropy_mean": float(np.mean(entropies)) if entropies else None,
        "entropy_std": float(np.std(entropies)) if entropies else None,
        "confidence_mean": float(np.mean(confidences)) if confidences else None,
        "confidence_std": float(np.std(confidences)) if confidences else None,
        "pooled_logits_mu": pooled.mean(axis=0).tolist() if len(pooled) else None,
        "pooled_logits_cov": np.cov(pooled, rowvar=False).tolist() if len(pooled) > 1 else None,
    }


def main() -> None:
    args = parse_args()
    device = torch.device(args.device if (args.device != "cuda" or torch.cuda.is_available()) else "cpu")

    resize = None
    if args.resize:
        w, h = args.resize.lower().split("x")
        resize = (int(w), int(h))

    num_classes = validate_num_classes(args.num_classes)
    model = models.segmentation.fcn_resnet50(weights=None, num_classes=num_classes)
    sd = torch.load(args.model, map_location="cpu")
    model.load_state_dict(sd, strict=False)
    model.to(device)

    real_dir = Path(args.real_dir)
    if not real_dir.exists():
        raise FileNotFoundError(f"real-dir not found: {real_dir}")

    report = {
        "model": str(Path(args.model).resolve()),
        "device": str(device),
        "real": _run_folder(model, real_dir, device, resize, args.limit),
        "sim": None,
        "frechet_pooled_logits": None,
    }

    if args.sim_dataset:
        sim_root = Path(args.sim_dataset)
        sim_dir = sim_root / "rgb" / args.sim_camera
        if sim_dir.exists():
            report["sim"] = _run_folder(model, sim_dir, device, resize, args.limit)
            try:
                mu1 = report["sim"]["pooled_logits_mu"]
                cov1 = report["sim"]["pooled_logits_cov"]
                mu2 = report["real"]["pooled_logits_mu"]
                cov2 = report["real"]["pooled_logits_cov"]
                if mu1 is not None and cov1 is not None and mu2 is not None and cov2 is not None:
                    report["frechet_pooled_logits"] = _frechet_distance(mu1, cov1, mu2, cov2)
            except Exception:
                # SciPy may not be installed; we keep the rest of the report.
                report["frechet_pooled_logits"] = None

    out_json = Path(args.out_json)
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"✅ Wrote report → {out_json}")
    print(f"Real entropy(mean)={report['real']['entropy_mean']}, confidence(mean)={report['real']['confidence_mean']}")
    if report["frechet_pooled_logits"] is not None:
        print(f"Sim↔Real Fréchet(pooled logits)={report['frechet_pooled_logits']:.3f}")


if __name__ == "__main__":
    main()
