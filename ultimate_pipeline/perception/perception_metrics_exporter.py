#!/usr/bin/env python3
"""
ultimate_pipeline/perception/perception_metrics_exporter.py

Goal: produce a *reliable* perception metrics JSON from whatever images your run produced,
so run_full_domain_gap.py can compute a perceptual gap (even if PerceptionGap schema differs).

Design principles:
- No CARLA required (post-run artifact processing).
- Tolerant image discovery: searches common folders under the run output directory.
- Two feature modes:
  1) Torch/torchvision available -> ResNet18 embeddings (fast, decent).
  2) Otherwise -> simple RGB histogram features (always works).

Outputs:
- <run_out>/<out_name>   (default: perception_metrics_auto.json)
JSON contains:
  - n_images, feature_dim, feature_mean, method, sample_files
  - optionally: per_folder counts
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

import numpy as np


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp"}


def _discover_images(run_out: str, max_images: int = 4000) -> List[Path]:
    root = Path(run_out)

    # Common places your pipeline tends to write images
    candidates = [
        root / "perception",
        root / "perception" / "images",
        root / "screenshots",
        root / "road_perception",
        root / "qa",
        root / "viz",
    ]

    files: List[Path] = []
    seen = set()

    def add_from_dir(d: Path):
        if not d.is_dir():
            return
        for p in d.rglob("*"):
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                s = str(p.resolve())
                if s not in seen:
                    seen.add(s)
                    files.append(p)
                    if len(files) >= max_images:
                        return

    for d in candidates:
        add_from_dir(d)
        if len(files) >= max_images:
            break

    # Fallback: scan shallowly under run_out
    if not files:
        add_from_dir(root)

    return files[:max_images]


def _rgb_histogram_features(img_paths: List[Path], bins: int = 32) -> np.ndarray:
    """
    Fast, dependency-light features: concatenated RGB hist (3*bins).
    Uses Pillow if available; otherwise uses matplotlib.image as fallback.
    """
    try:
        from PIL import Image  # type: ignore
        loader = "pillow"
    except Exception:
        Image = None
        loader = "matplotlib"

    feats = []
    for p in img_paths:
        try:
            if loader == "pillow" and Image is not None:
                im = Image.open(p).convert("RGB")
                arr = np.asarray(im, dtype=np.uint8)
            else:
                import matplotlib.image as mpimg  # type: ignore
                arr = mpimg.imread(str(p))
                if arr.dtype != np.uint8:
                    arr = (np.clip(arr, 0, 1) * 255).astype(np.uint8)
                if arr.ndim == 2:  # grayscale
                    arr = np.stack([arr, arr, arr], axis=-1)
                if arr.shape[-1] == 4:  # RGBA
                    arr = arr[..., :3]
        except Exception:
            continue

        # histogram per channel
        f = []
        for c in range(3):
            h, _ = np.histogram(arr[..., c], bins=bins, range=(0, 255), density=True)
            f.append(h.astype(np.float32))
        feat = np.concatenate(f, axis=0)
        feats.append(feat)

    if not feats:
        return np.zeros((0, 3 * bins), dtype=np.float32)

    return np.stack(feats, axis=0)


def _resnet18_embeddings(img_paths: List[Path], batch_size: int = 32, max_images: int = 2000) -> Tuple[np.ndarray, str]:
    """
    ResNet18 penultimate-layer embeddings via torchvision.
    Uses ImageNet weights if available in local cache (no internet required, but may download if your environment allows).
    """
    import torch  # type: ignore
    from torchvision import models, transforms  # type: ignore
    from PIL import Image  # type: ignore

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    try:
        # New API
        weights = models.ResNet18_Weights.DEFAULT  # type: ignore
        model = models.resnet18(weights=weights)  # type: ignore
        preprocess = weights.transforms()
        method = "resnet18(weights=DEFAULT)"
    except Exception:
        # Old API
        model = models.resnet18(pretrained=True)  # type: ignore
        preprocess = transforms.Compose([
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])
        method = "resnet18(pretrained=True)"

    model.fc = torch.nn.Identity()  # 512-d
    model.eval().to(device)

    imgs = img_paths[:max_images]
    feats = []

    def load_img(p: Path):
        im = Image.open(p).convert("RGB")
        return preprocess(im)

    with torch.no_grad():
        for i in range(0, len(imgs), batch_size):
            batch_paths = imgs[i:i+batch_size]
            batch = []
            for p in batch_paths:
                try:
                    batch.append(load_img(p))
                except Exception:
                    continue
            if not batch:
                continue
            x = torch.stack(batch, dim=0).to(device)
            y = model(x).detach().cpu().numpy().astype(np.float32)
            feats.append(y)

    if not feats:
        return np.zeros((0, 512), dtype=np.float32), method

    return np.concatenate(feats, axis=0), method


def export_perception_metrics(run_out: str, out_name: str = "perception_metrics_auto.json", max_images: int = 2000) -> str:
    """
    Create a perception metrics JSON inside run_out.

    Returns absolute path to the written JSON.
    """
    run_out = str(Path(run_out).resolve())
    img_paths = _discover_images(run_out, max_images=max_images)

    payload: Dict[str, Any] = {
        "run_out": run_out,
        "n_images_discovered": int(len(img_paths)),
        "method": None,
        "feature_dim": None,
        "feature_mean": None,
        "sample_files": [str(p) for p in img_paths[:20]],
    }

    if len(img_paths) == 0:
        payload["method"] = "none"
        payload["n_images_used"] = 0
        payload["error"] = "No images discovered under run_out."
        out_path = Path(run_out) / out_name
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return str(out_path)

    # Try torch embedding mode
    feats = None
    method = None
    try:
        import torch  # type: ignore
        _ = torch.__version__
        feats, method = _resnet18_embeddings(img_paths, max_images=max_images)
    except Exception:
        feats = _rgb_histogram_features(img_paths, bins=32)
        method = "rgb_histogram(bins=32)"

    if feats is None:
        feats = np.zeros((0, 1), dtype=np.float32)

    if feats.shape[0] == 0:
        payload["method"] = method
        payload["n_images_used"] = int(feats.shape[0])
        payload["error"] = "Images found, but feature extraction failed for all images."
    else:
        mu = feats.mean(axis=0)
        # Diagonal variance is a lightweight stand-in for full covariance.
        # It supports simple Fréchet-style distances without writing huge JSON files.
        var = feats.var(axis=0)

        # Keep a small sample of feature vectors so downstream can compute
        # MMD/Wasserstein/mean-gap without needing the full dataset.
        max_samples = 256
        if feats.shape[0] <= max_samples:
            sample_idx = None
            samples = feats
        else:
            import numpy as _np
            _rng = _np.random.default_rng(0)
            sample_idx = _rng.choice(feats.shape[0], size=max_samples, replace=False)
            samples = feats[sample_idx]

        payload["method"] = method
        payload["feature_dim"] = int(mu.shape[0])
        payload["feature_mean"] = [float(x) for x in mu.tolist()]
        payload["feature_var_diag"] = [float(x) for x in var.tolist()]
        payload["n_images_used"] = int(feats.shape[0])
        payload["feature_samples"] = [[float(x) for x in row.tolist()] for row in samples]
        if sample_idx is not None:
            payload["feature_samples_seed"] = 0


    out_path = Path(run_out) / out_name
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(out_path)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-out", required=True, help="ultimate_pipeline_out/<timestamp> folder")
    ap.add_argument("--out-name", default="perception_metrics_auto.json")
    ap.add_argument("--max-images", type=int, default=2000)
    args = ap.parse_args()
    p = export_perception_metrics(args.run_out, args.out_name, args.max_images)
    print("Wrote:", p)
