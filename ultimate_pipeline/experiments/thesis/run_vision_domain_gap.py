from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".npy"}


_TOPOLOGY_METRICS_SCOPE_TEMPLATE: Dict[str, Any] = {
    "road_length_valid": True,
    "junction_count_valid": True,
    "curvature_kl_valid": True,
    "requires_spatial_alignment": False,
    "crs_independence_reason": (
        "aggregate statistics computed within each map's native coordinate frame; "
        "curvature is a distribution comparison over road shapes, not absolute position"
    ),
}


def topology_metrics_scope_template() -> Dict[str, Any]:
    """Canonical thesis-facing scope statement for CRS-independent topology metrics."""
    return dict(_TOPOLOGY_METRICS_SCOPE_TEMPLATE)

try:  # pragma: no cover - optional dependency branch
    import numpy as np
except Exception:  # pragma: no cover
    np = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency branch
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]


@dataclass(frozen=True)
class PairMetrics:
    relative_path: str
    mse: float
    mae: float
    psnr_db: Optional[float]
    histogram_l1: Optional[float]


def _iter_candidate_files(root: Path) -> Dict[str, Path]:
    if not root.exists():
        return {}
    out: Dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            out[str(path.relative_to(root)).replace("\\", "/")] = path
    return out


def _load_array(path: Path):
    if np is None:
        raise RuntimeError("numpy unavailable")
    suffix = path.suffix.lower()
    if suffix == ".npy":
        arr = np.asarray(np.load(path), dtype=np.float32)
    elif Image is not None:
        with Image.open(path) as im:
            arr = np.asarray(im.convert("RGB"), dtype=np.float32)
    else:
        raise RuntimeError("Pillow unavailable")
    if arr.ndim == 2:
        arr = arr[..., None]
    return arr


def _align_shapes(a, b):
    if np is None:
        raise RuntimeError("numpy unavailable")
    min_h = int(min(a.shape[0], b.shape[0]))
    min_w = int(min(a.shape[1], b.shape[1]))
    min_c = int(min(a.shape[2], b.shape[2]))
    return a[:min_h, :min_w, :min_c], b[:min_h, :min_w, :min_c]


def _histogram_l1(a, b) -> Optional[float]:
    if np is None:
        return None
    bins = 32
    total = 0.0
    for channel in range(a.shape[2]):
        hist_a, _ = np.histogram(a[..., channel], bins=bins, range=(0.0, 255.0), density=True)
        hist_b, _ = np.histogram(b[..., channel], bins=bins, range=(0.0, 255.0), density=True)
        total += float(np.abs(hist_a - hist_b).sum())
    return total / float(a.shape[2])


def _compute_pair_metrics(relative_path: str, auto_path: Path, manual_path: Path) -> PairMetrics:
    if np is None:
        raise RuntimeError("numpy unavailable")
    auto_arr = _load_array(auto_path)
    manual_arr = _load_array(manual_path)
    auto_arr, manual_arr = _align_shapes(auto_arr, manual_arr)
    diff = auto_arr - manual_arr
    mse = float(np.mean(np.square(diff)))
    mae = float(np.mean(np.abs(diff)))
    psnr = None if mse <= 0.0 else float(20.0 * math.log10(255.0 / math.sqrt(mse)))
    hist = _histogram_l1(auto_arr, manual_arr)
    return PairMetrics(
        relative_path=relative_path,
        mse=mse,
        mae=mae,
        psnr_db=psnr,
        histogram_l1=hist,
    )


def _aggregate_metrics(metrics: list[PairMetrics]) -> dict[str, float | int | None]:
    if not metrics:
        return {
            "paired_files": 0,
            "mse_mean": None,
            "mae_mean": None,
            "psnr_db_mean": None,
            "histogram_l1_mean": None,
        }
    psnr_values = [m.psnr_db for m in metrics if m.psnr_db is not None]
    hist_values = [m.histogram_l1 for m in metrics if m.histogram_l1 is not None]
    return {
        "paired_files": len(metrics),
        "mse_mean": sum(m.mse for m in metrics) / len(metrics),
        "mae_mean": sum(m.mae for m in metrics) / len(metrics),
        "psnr_db_mean": (sum(psnr_values) / len(psnr_values)) if psnr_values else None,
        "histogram_l1_mean": (sum(hist_values) / len(hist_values)) if hist_values else None,
    }


def _count_modality_files(root: Path) -> Dict[str, int]:
    rgb_files = 0
    semseg_files = 0
    lidar_files = 0
    if root.is_dir():
        rgb_dir = root / "rgb"
        semseg_dir = root / "semseg_raw"
        lidar_dir = root / "lidar"
        if rgb_dir.is_dir():
            rgb_files = len(list(rgb_dir.rglob("*.png")))
        if semseg_dir.is_dir():
            semseg_files = len(list(semseg_dir.rglob("*.png")))
        if lidar_dir.is_dir():
            lidar_files = len(list(lidar_dir.rglob("*.ply"))) + len(list(lidar_dir.rglob("*.npz")))
    return {
        "rgb_files": int(rgb_files),
        "semseg_files": int(semseg_files),
        "lidar_files": int(lidar_files),
    }


def run_vision_domain_gap(auto_dir, manual_dir, out_dir):
    auto_root = Path(auto_dir)
    manual_root = Path(manual_dir)
    output_root = Path(out_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    auto_files = _iter_candidate_files(auto_root)
    manual_files = _iter_candidate_files(manual_root)
    shared = sorted(set(auto_files) & set(manual_files))

    metrics: list[PairMetrics] = []
    errors: list[dict[str, str]] = []

    quantitative_available = np is not None and Image is not None
    if quantitative_available:
        for relative_path in shared:
            try:
                metrics.append(_compute_pair_metrics(relative_path, auto_files[relative_path], manual_files[relative_path]))
            except Exception as exc:
                errors.append({"relative_path": relative_path, "error": f"{type(exc).__name__}: {exc}"})

    summary = {
        "status": "ok" if metrics else ("no_pairs" if not shared else "metric_unavailable"),
        "auto_dir": str(auto_root),
        "manual_dir": str(manual_root),
        "auto_candidate_files": len(auto_files),
        "manual_candidate_files": len(manual_files),
        "shared_relative_files": len(shared),
        # Backward-compatible keys retained for existing lightweight consumers.
        "auto_images": len(list(auto_root.rglob("*.png"))),
        "manual_images": len(list(manual_root.rglob("*.png"))),
        "modality_counts": {
            "auto": _count_modality_files(auto_root),
            "manual": _count_modality_files(manual_root),
        },
        "quantitative_metrics": _aggregate_metrics(metrics),
        "pair_metrics": [m.__dict__ for m in metrics],
        "metric_errors": errors,
        "metric_contract": {
            "implemented": True,
            "available": bool(quantitative_available),
            "metrics": ["mse", "mae", "psnr_db", "histogram_l1"],
            "note": "Quantitative metrics require numpy and Pillow, and matching relative paths.",
        },
        "rq3_plumbing": {
            "paired_relative_files": int(len(shared)),
            "quantitative_pairs": int(len(metrics)),
            "ready_for_comparison": bool(len(metrics) > 0),
            "status": (
                "ready"
                if len(metrics) > 0
                else ("missing_pairs" if len(shared) == 0 else "metrics_unavailable")
            ),
            "claim_boundary": (
                "Diagnostic perceptual metrics only; this output alone does not close "
                "RQ3/RQ4/RQ5."
            ),
        },
    }
    out_path = output_root / "vision_domain_gap_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Compute quantitative metrics for generated vs manual captures.")
    ap.add_argument("--auto", required=True)
    ap.add_argument("--manual", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    run_vision_domain_gap(a.auto, a.manual, a.out)
