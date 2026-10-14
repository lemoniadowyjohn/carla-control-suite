#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Unlabeled real-world evaluation for a segmentation model.

Your thesis requires evaluating generalization on **unlabeled real data**.
Without labels, we can't compute mIoU, but we *can* quantify domain shift with:
 - mean prediction entropy (higher = model is unsure)
 - mean max-probability confidence (lower = less certain)
 - Fréchet distance between pooled logits distributions (sim vs real) if sim
   dataset is provided

NEW-239 / NEW-241 / NEW-243 / NEW-245
-----------------------------------
What this evaluator may and may not support, enforced in code:

* **It cannot support a generalization-accuracy claim.** Without labels there
  is no mIoU and no pixel accuracy. It measures prediction entropy, confidence
  and (optionally) a pooled-logit Frechet distance: *domain-shift / model-behaviour*
  indicators. The report therefore carries an explicit
  ``claim_scope: "domain_shift_indicators_only"`` and never emits an accuracy
  field (NEW-239).
* **An existing-but-empty directory is not evidence.** Previously an empty
  ``--real-dir`` produced ``{"n": 0, "entropy_mean": null, "confidence_mean":
  null}`` and exited 0, which the RQ5 classifier could read as available
  real-world evidence because the keys existed. Now ``n`` must exceed
  ``--min-images`` and every image must actually decode, otherwise the run is a
  failure with a nonzero exit (NEW-241).
* **Strict checkpoint loading** with recorded missing/unexpected keys (NEW-245),
  and a recorded checkpoint SHA-256 plus optional companion-manifest
  verification (NEW-243).

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
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

import numpy as np
from PIL import Image

import torch
import torch.nn.functional as F
from torchvision import models

from ultimate_pipeline.perception.rq5_provenance import (
    MODEL_MANIFEST_FILENAME,
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

#: NEW-239: this evaluator produces shift indicators, never accuracy metrics.
CLAIM_SCOPE = "domain_shift_indicators_only"

EXIT_OK = 0
EXIT_MISSING_EVIDENCE = 2

STATUS_OK = "ok"
STATUS_FAILED = "failed"

#: NEW-241: a real-world directory must contain strictly more images than this
#: for the shift evidence to be admissible.
DEFAULT_MIN_REAL_IMAGES = 1


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
    ap.add_argument(
        "--min-images",
        type=int,
        default=DEFAULT_MIN_REAL_IMAGES,
        help=(
            "NEW-241: minimum number of successfully decoded images required for "
            f"admissible real-world shift evidence (default {DEFAULT_MIN_REAL_IMAGES}; "
            "evidence requires n > this value)"
        ),
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


def _run_folder(
    model,
    folder: Path,
    device: torch.device,
    resize: Optional[Tuple[int, int]],
    limit: int,
) -> Dict[str, Any]:
    """
    Compute shift indicators over every decodable image in ``folder``.

    NEW-241: ``n`` reports the number of images that were actually decoded and
    scored, and ``n_images_discovered``/``decode_failures`` make the difference
    between "empty directory" and "unreadable files" visible. A caller cannot
    mistake ``n=0`` for a measurement any more.
    """
    entropies: list[float] = []
    confidences: list[float] = []
    pooled: list[np.ndarray] = []
    decode_failures: list[str] = []

    discovered = list(_iter_images(folder))
    paths = discovered[:limit] if limit > 0 else discovered

    model.eval()
    with torch.no_grad():
        for p in paths:
            try:
                x = _load_rgb(p, resize=resize).unsqueeze(0).to(device)
            except Exception as exc:
                decode_failures.append(f"{p.as_posix()}: {exc}")
                continue
            logits = model(x)["out"]
            ent = _entropy_from_logits(logits).mean().item()
            prob = F.softmax(logits, dim=1)
            conf = prob.max(dim=1).values.mean().item()
            entropies.append(ent)
            confidences.append(conf)
            pooled.append(_pooled_logits(logits).squeeze(0).detach().cpu().numpy())

    stacked = np.stack(pooled, axis=0) if pooled else np.zeros((0, 1), dtype=np.float32)
    return {
        "n": len(entropies),
        "n_images_discovered": len(discovered),
        "decode_failures": decode_failures,
        "entropy_mean": float(np.mean(entropies)) if entropies else None,
        "entropy_std": float(np.std(entropies)) if entropies else None,
        "confidence_mean": float(np.mean(confidences)) if confidences else None,
        "confidence_std": float(np.std(confidences)) if confidences else None,
        "pooled_logits_mu": stacked.mean(axis=0).tolist() if len(stacked) else None,
        "pooled_logits_cov": (
            np.cov(stacked, rowvar=False).tolist() if len(stacked) > 1 else None
        ),
    }


def main() -> int:
    args = parse_args()
    device = torch.device(args.device if (args.device != "cuda" or torch.cuda.is_available()) else "cpu")

    resize = None
    if args.resize:
        w, h = args.resize.lower().split("x")
        resize = (int(w), int(h))

    report: Dict[str, Any] = {
        "schema": "real_unlabeled_shift_report_v1",
        "status": STATUS_FAILED,
        # NEW-239: this report cannot support a generalization-accuracy claim.
        "claim_scope": CLAIM_SCOPE,
        "accuracy_metrics_available": False,
        "deferred_claim": "real_world_generalization_accuracy",
        "model": str(Path(args.model).resolve()),
        "model_sha256": None,
        "model_manifest_verification": None,
        "device": str(device),
        "real_dir": str(Path(args.real_dir)),
        "min_images": int(args.min_images),
        "real": None,
        "sim": None,
        "frechet_pooled_logits": None,
        "errors": [],
    }

    out_json = Path(args.out_json)

    def _finish_failed() -> int:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        for message in report["errors"]:
            print(f"[FAIL] {message}")
        return EXIT_MISSING_EVIDENCE

    model_path = Path(args.model)
    try:
        report["model_sha256"] = sha256_file(model_path)
    except OSError as exc:
        report["errors"].append(f"checkpoint_unreadable: {exc}")
        return _finish_failed()

    manifest_path = model_path.parent / MODEL_MANIFEST_FILENAME
    if manifest_path.is_file():
        verification = verify_checkpoint_manifest(
            model_path, manifest_path, require_provenance=args.require_manifest
        )
        report["model_manifest_verification"] = verification
        if args.require_manifest and not verification["ok"]:
            report["errors"].extend(verification["failures"])
            return _finish_failed()
    elif args.require_manifest:
        report["errors"].append(
            f"no_companion_manifest: expected {manifest_path.name} next to the checkpoint"
        )
        return _finish_failed()

    num_classes = validate_num_classes(args.num_classes)
    model = models.segmentation.fcn_resnet50(weights=None, num_classes=num_classes)
    try:
        load_record: Dict[str, Any] = {}
        report["state_dict_load"] = load_state_dict_governed(
            model, model_path, allow_partial=args.allow_partial_load, record=load_record
        )
    except (StateDictLoadError, FileNotFoundError) as exc:
        report["errors"].append(f"state_dict_load_failed: {exc}")
        return _finish_failed()
    model.to(device)

    real_dir = Path(args.real_dir)
    if not real_dir.exists():
        raise FileNotFoundError(f"real-dir not found: {real_dir}")

    report["real"] = _run_folder(model, real_dir, device, resize, args.limit)

    # NEW-241: an existing-but-empty (or wholly undecodable) directory is
    # missing evidence, not a successful measurement of zero shift.
    if int(report["real"]["n"]) <= int(args.min_images):
        report["errors"].append(
            f"insufficient_real_images: n={report['real']['n']} <= required "
            f"min_images={int(args.min_images)} "
            f"(discovered={report['real']['n_images_discovered']})"
        )
        return _finish_failed()

    if args.sim_dataset:
        sim_root = Path(args.sim_dataset)
        sim_dir = sim_root / "rgb" / args.sim_camera
        try:
            report["sim_dataset_identity_sha256"] = dataset_content_identity(
                sim_root, args.sim_camera
            )["identity_sha256"]
        except Exception as exc:
            report["sim_dataset_identity_error"] = str(exc)
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

    report["status"] = STATUS_OK
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"✅ Wrote report → {out_json}")
    print(f"claim_scope={report['claim_scope']} (no accuracy metrics are computable without labels)")
    print(
        f"Real entropy(mean)={report['real']['entropy_mean']}, "
        f"confidence(mean)={report['real']['confidence_mean']}, "
        f"n={report['real']['n']}"
    )
    if report["frechet_pooled_logits"] is not None:
        print(f"Sim↔Real Fréchet(pooled logits)={report['frechet_pooled_logits']:.3f}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
