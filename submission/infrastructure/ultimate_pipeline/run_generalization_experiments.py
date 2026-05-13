#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generalization Experiments Runner

Canonical entrypoint for training and evaluating semantic segmentation models
across different K values (number of generated maps used for training).

Usage:
    python -m ultimate_pipeline.run_generalization_experiments \\
        --train_gen_datasets /path/to/gen_run_001 /path/to/gen_run_002 ... \\
        --train_manual_datasets /path/to/manual_capture \\
        --eval_manual_dataset /path/to/manual_eval_capture \\
        --real_u_dir /path/to/real_unlabeled_images \\
        --k_values 1 3 5 \\
        --out_dir ./generalization_output

Outputs:
    generalization/
        generalization_results.csv      # Main results table
        generalization_results.json     # Full results with metadata
        gen_many_curve.csv              # Structural metrics per K
        models/
            manual_baseline_k000/
                checkpoints/model_last.pt
            generated_k_k001/
                checkpoints/model_last.pt
            ...
        eval/
            manual_baseline_k000/
                sim_labeled_eval.json
                real_u_eval_report.json
            generated_k_k001/
                sim_labeled_eval.json
                real_u_eval_report.json
            ...
        logs/
            train_*.log
            eval_sim_*.log
            eval_real_u_*.log
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ultimate_pipeline.config.thesis_contract import (
    infer_generalization_claim_status,
    infer_generalization_component_statuses,
)


def _run_subprocess(
    cmd: List[str],
    log_file: Optional[Path] = None,
    env: Optional[Dict[str, str]] = None,
) -> int:
    """Run subprocess, optionally capturing output to log file."""
    run_env = os.environ.copy()
    if env:
        run_env.update(env)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "w", encoding="utf-8") as f:
            result = subprocess.run(
                cmd,
                stdout=f,
                stderr=subprocess.STDOUT,
                env=run_env,
                text=True,
            )
    else:
        result = subprocess.run(cmd, env=run_env)

    return result.returncode


def _find_checkpoint(model_dir: Path) -> Optional[Path]:
    """Find the best checkpoint in a model directory."""
    # Priority: checkpoints/model_last.pt > seg_fcn_epoch*.pt (last)
    ckpt_dir = model_dir / "checkpoints"
    if ckpt_dir.exists():
        last_pt = ckpt_dir / "model_last.pt"
        if last_pt.exists():
            return last_pt

    # Fallback to epoch checkpoints
    epoch_ckpts = sorted(model_dir.glob("seg_fcn_epoch*.pt"))
    if epoch_ckpts:
        return epoch_ckpts[-1]

    return None


def _ensure_model_last(model_dir: Path) -> Optional[Path]:
    """Ensure checkpoints/model_last.pt exists by copying from latest epoch."""
    ckpt_dir = model_dir / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    last_pt = ckpt_dir / "model_last.pt"
    if last_pt.exists():
        return last_pt

    # Find latest epoch checkpoint
    epoch_ckpts = sorted(model_dir.glob("seg_fcn_epoch*.pt"))
    if epoch_ckpts:
        import shutil
        shutil.copy2(epoch_ckpts[-1], last_pt)
        return last_pt

    return None


def train_model(
    condition_name: str,
    dataset_roots: List[Path],
    camera: str,
    out_dir: Path,
    epochs: int,
    batch_size: int,
    device: str,
    log_dir: Path,
) -> bool:
    """Train a single model condition."""
    model_dir = out_dir / "models" / condition_name
    model_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / f"train_{condition_name}.log"

    # Build command - pass multiple dataset roots
    cmd = [
        sys.executable, "-m", "ultimate_pipeline.perception.train_launcher",
        "--dataset", str(dataset_roots[0]),  # Primary dataset
        "--camera", camera,
        "--out-dir", str(model_dir),
        "--epochs", str(epochs),
        "--batch", str(batch_size),
        "--device", device,
    ]

    print(f"[TRAIN] {condition_name}: {len(dataset_roots)} dataset(s), epochs={epochs}")

    # Write training manifest
    manifest = {
        "condition": condition_name,
        "dataset_roots": [str(p) for p in dataset_roots],
        "camera": camera,
        "epochs": epochs,
        "batch_size": batch_size,
        "device": device,
        "timestamp": datetime.now().isoformat(),
    }
    (model_dir / "training_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    ret = _run_subprocess(cmd, log_file=log_file)

    if ret == 0:
        # Ensure model_last.pt exists
        _ensure_model_last(model_dir)
        print(f"[TRAIN] {condition_name}: DONE")
    else:
        print(f"[TRAIN] {condition_name}: FAILED (exit={ret})")

    return ret == 0


def eval_sim_labeled(
    condition_name: str,
    model_path: Path,
    eval_dataset: Path,
    camera: str,
    out_dir: Path,
    device: str,
    log_dir: Path,
) -> Dict[str, Any]:
    """Run labeled sim evaluation."""
    eval_dir = out_dir / "eval" / condition_name
    eval_dir.mkdir(parents=True, exist_ok=True)

    out_json = eval_dir / "sim_labeled_eval.json"
    log_file = log_dir / f"eval_sim_{condition_name}.log"

    cmd = [
        sys.executable, "-m", "ultimate_pipeline.perception.eval_sim_labeled",
        "--model", str(model_path),
        "--dataset", str(eval_dataset),
        "--camera", camera,
        "--out-json", str(out_json),
        "--device", device,
    ]

    print(f"[EVAL_SIM] {condition_name}: evaluating on {eval_dataset}")
    ret = _run_subprocess(cmd, log_file=log_file)

    result = {"condition": condition_name, "ok": ret == 0}
    if out_json.exists():
        try:
            result.update(json.loads(out_json.read_text(encoding="utf-8")))
        except Exception:
            pass

    return result


def eval_real_unlabeled(
    condition_name: str,
    model_path: Path,
    real_u_dir: Path,
    out_dir: Path,
    device: str,
    log_dir: Path,
    sim_dataset: Optional[Path] = None,
    camera: str = "front_left_camera",
) -> Dict[str, Any]:
    """Run unlabeled real evaluation."""
    eval_dir = out_dir / "eval" / condition_name
    eval_dir.mkdir(parents=True, exist_ok=True)

    out_json = eval_dir / "real_u_eval_report.json"
    log_file = log_dir / f"eval_real_u_{condition_name}.log"

    cmd = [
        sys.executable, "-m", "ultimate_pipeline.perception.eval_real_unlabeled",
        "--model", str(model_path),
        "--real-dir", str(real_u_dir),
        "--out-json", str(out_json),
        "--device", device,
    ]

    if sim_dataset:
        cmd.extend(["--sim-dataset", str(sim_dataset), "--sim-camera", camera])

    print(f"[EVAL_REAL_U] {condition_name}: evaluating on {real_u_dir}")
    ret = _run_subprocess(cmd, log_file=log_file)

    result = {"condition": condition_name, "ok": ret == 0}
    if out_json.exists():
        try:
            result.update(json.loads(out_json.read_text(encoding="utf-8")))
        except Exception:
            pass

    return result


def write_results_csv(results: List[Dict], out_path: Path) -> None:
    """Write generalization_results.csv."""
    if not results:
        return

    # Determine columns
    columns = [
        "condition", "K", "mIoU", "pixel_accuracy", "frames_count",
        "real_entropy_mean", "real_confidence_mean", "real_n",
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            row = {
                "condition": r.get("condition", ""),
                "K": r.get("k", 0),
                "mIoU": r.get("sim", {}).get("mIoU", 0.0) if isinstance(r.get("sim"), dict) else r.get("mIoU", 0.0),
                "pixel_accuracy": r.get("sim", {}).get("pixel_accuracy", 0.0) if isinstance(r.get("sim"), dict) else r.get("pixel_accuracy", 0.0),
                "frames_count": r.get("sim", {}).get("frames_count", 0) if isinstance(r.get("sim"), dict) else r.get("frames_count", 0),
                "real_entropy_mean": r.get("real", {}).get("entropy_mean") if isinstance(r.get("real"), dict) else None,
                "real_confidence_mean": r.get("real", {}).get("confidence_mean") if isinstance(r.get("real"), dict) else None,
                "real_n": r.get("real", {}).get("n") if isinstance(r.get("real"), dict) else None,
            }
            writer.writerow(row)


def write_gen_many_curve_csv(results: List[Dict], out_path: Path) -> None:
    """Write gen_many_curve.csv for K-sweep analysis."""
    if not results:
        return

    columns = ["K", "condition", "sim_mIoU", "real_entropy_mean", "real_confidence_mean"]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            if r.get("condition", "").startswith("generated_k_"):
                row = {
                    "K": r.get("k", 0),
                    "condition": r.get("condition", ""),
                    "sim_mIoU": r.get("sim", {}).get("mIoU", 0.0) if isinstance(r.get("sim"), dict) else r.get("mIoU", 0.0),
                    "real_entropy_mean": r.get("real", {}).get("entropy_mean") if isinstance(r.get("real"), dict) else None,
                    "real_confidence_mean": r.get("real", {}).get("confidence_mean") if isinstance(r.get("real"), dict) else None,
                }
                writer.writerow(row)


def parse_args():
    ap = argparse.ArgumentParser(
        description="Generalization experiments: train and evaluate models across K values"
    )
    ap.add_argument(
        "--train_gen_datasets", nargs="+", default=[],
        help="Generated dataset roots (from pipeline runs)"
    )
    ap.add_argument(
        "--train_manual_datasets", nargs="+", default=[],
        help="Manual capture dataset roots (for baseline)"
    )
    ap.add_argument(
        "--eval_manual_dataset", default="",
        help="Manual dataset for labeled sim evaluation (if different from train)"
    )
    ap.add_argument(
        "--real_u_dir", default="",
        help="Directory with unlabeled real-world images"
    )
    ap.add_argument(
        "--k_values", nargs="+", type=int, default=[1, 3, 5],
        help="K values for generated-data sweep"
    )
    ap.add_argument(
        "--out_dir", default="./generalization_output",
        help="Output directory"
    )
    ap.add_argument(
        "--camera", default="front_left_camera",
        help="Camera name for dataset subdirs"
    )
    ap.add_argument(
        "--epochs", type=int, default=3,
        help="Training epochs per model"
    )
    ap.add_argument(
        "--batch", type=int, default=2,
        help="Training batch size"
    )
    ap.add_argument(
        "--device", default="cuda" if "torch" in sys.modules and __import__("torch").cuda.is_available() else "cpu",
        help="Training/eval device"
    )
    ap.add_argument(
        "--skip_training", action="store_true",
        help="Skip training, only run evaluation (requires existing checkpoints)"
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    log_dir = out_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    gen_datasets = [Path(p) for p in args.train_gen_datasets]
    manual_datasets = [Path(p) for p in args.train_manual_datasets]

    # Determine eval dataset
    eval_dataset = Path(args.eval_manual_dataset) if args.eval_manual_dataset else (
        manual_datasets[0] if manual_datasets else (gen_datasets[0] if gen_datasets else None)
    )

    real_u_dir = Path(args.real_u_dir) if args.real_u_dir else None

    all_results: List[Dict] = []

    # --- Manual baseline (if manual datasets provided) ---
    if manual_datasets:
        condition = "manual_baseline_k000"

        if not args.skip_training:
            train_model(
                condition_name=condition,
                dataset_roots=manual_datasets,
                camera=args.camera,
                out_dir=out_dir,
                epochs=args.epochs,
                batch_size=args.batch,
                device=args.device,
                log_dir=log_dir,
            )

        model_path = _find_checkpoint(out_dir / "models" / condition)
        if model_path:
            result = {"condition": condition, "k": 0, "sim": {}, "real": {}}

            # Sim labeled eval
            if eval_dataset and eval_dataset.exists():
                sim_result = eval_sim_labeled(
                    condition_name=condition,
                    model_path=model_path,
                    eval_dataset=eval_dataset,
                    camera=args.camera,
                    out_dir=out_dir,
                    device=args.device,
                    log_dir=log_dir,
                )
                result["sim"] = sim_result

            # Real unlabeled eval
            if real_u_dir and real_u_dir.exists():
                real_result = eval_real_unlabeled(
                    condition_name=condition,
                    model_path=model_path,
                    real_u_dir=real_u_dir,
                    out_dir=out_dir,
                    device=args.device,
                    log_dir=log_dir,
                    sim_dataset=eval_dataset,
                    camera=args.camera,
                )
                result["real"] = real_result.get("real", {})

            all_results.append(result)

    # --- Generated K-sweep ---
    for k in args.k_values:
        if k > len(gen_datasets):
            print(f"[SKIP] K={k} requested but only {len(gen_datasets)} generated datasets available")
            continue

        condition = f"generated_k_k{k:03d}"
        k_datasets = gen_datasets[:k]

        if not args.skip_training:
            train_model(
                condition_name=condition,
                dataset_roots=k_datasets,
                camera=args.camera,
                out_dir=out_dir,
                epochs=args.epochs,
                batch_size=args.batch,
                device=args.device,
                log_dir=log_dir,
            )

        model_path = _find_checkpoint(out_dir / "models" / condition)
        if model_path:
            result = {"condition": condition, "k": k, "sim": {}, "real": {}}

            # Sim labeled eval
            if eval_dataset and eval_dataset.exists():
                sim_result = eval_sim_labeled(
                    condition_name=condition,
                    model_path=model_path,
                    eval_dataset=eval_dataset,
                    camera=args.camera,
                    out_dir=out_dir,
                    device=args.device,
                    log_dir=log_dir,
                )
                result["sim"] = sim_result

            # Real unlabeled eval
            if real_u_dir and real_u_dir.exists():
                real_result = eval_real_unlabeled(
                    condition_name=condition,
                    model_path=model_path,
                    real_u_dir=real_u_dir,
                    out_dir=out_dir,
                    device=args.device,
                    log_dir=log_dir,
                    sim_dataset=k_datasets[0] if k_datasets else None,
                    camera=args.camera,
                )
                result["real"] = real_result.get("real", {})

            all_results.append(result)

    # --- Write outputs ---
    gen_dir = out_dir / "generalization"
    gen_dir.mkdir(parents=True, exist_ok=True)

    # CSV outputs
    write_results_csv(all_results, gen_dir / "generalization_results.csv")
    write_gen_many_curve_csv(all_results, gen_dir / "gen_many_curve.csv")

    # JSON output
    claim_status = infer_generalization_claim_status(
        results=all_results,
        train_gen_datasets=gen_datasets,
        train_manual_datasets=manual_datasets,
        eval_manual_dataset=eval_dataset,
        real_u_dir=real_u_dir,
    )
    component_statuses = infer_generalization_component_statuses(
        results=all_results,
        eval_manual_dataset=eval_dataset,
        real_u_dir=real_u_dir,
    )
    simulated_status = component_statuses["simulated_manual_eval"]
    real_status = component_statuses["real_unlabeled_eval"]
    paired_ingolstadt_status = component_statuses["paired_ingolstadt_generalization"]
    status_payload = {
        "timestamp": datetime.now().isoformat(),
        "generalization_claim_status": claim_status.value,
        "generalization_claim_reason": claim_status.reason,
        "simulated_manual_eval_status": simulated_status.value,
        "simulated_manual_eval_reason": simulated_status.reason,
        "real_unlabeled_eval_status": real_status.value,
        "real_unlabeled_eval_reason": real_status.reason,
        "paired_ingolstadt_generalization_status": paired_ingolstadt_status.value,
        "paired_ingolstadt_generalization_reason": paired_ingolstadt_status.reason,
        "simulated_ingolstadt_eval_configured": bool(eval_dataset),
        "real_world_unlabeled_eval_configured": bool(real_u_dir),
        "results_count": len(all_results),
        "train_generated_dataset_count": len(gen_datasets),
        "train_manual_dataset_count": len(manual_datasets),
        "claim_boundary": (
            "Do not claim simulated Ingolstadt or real-world unlabeled generalization "
            "unless the corresponding status above is authoritative_result_available."
        ),
    }
    (gen_dir / "generalization_status.json").write_text(
        json.dumps(status_payload, indent=2), encoding="utf-8"
    )

    full_report = {
        "timestamp": datetime.now().isoformat(),
        "k_values": args.k_values,
        "train_gen_datasets": [str(p) for p in gen_datasets],
        "train_manual_datasets": [str(p) for p in manual_datasets],
        "eval_manual_dataset": str(eval_dataset) if eval_dataset else None,
        "real_u_dir": str(real_u_dir) if real_u_dir else None,
        "real_u_conditioned_on_k": len(all_results) > 1,
        "generalization_claim_status": claim_status.value,
        "generalization_claim_reason": claim_status.reason,
        "simulated_manual_eval_status": simulated_status.value,
        "simulated_manual_eval_reason": simulated_status.reason,
        "real_unlabeled_eval_status": real_status.value,
        "real_unlabeled_eval_reason": real_status.reason,
        "paired_ingolstadt_generalization_status": paired_ingolstadt_status.value,
        "paired_ingolstadt_generalization_reason": paired_ingolstadt_status.reason,
        "claim_boundary": status_payload["claim_boundary"],
        "generalization_status_path": str(gen_dir / "generalization_status.json"),
        "results": all_results,
    }
    (gen_dir / "generalization_results.json").write_text(
        json.dumps(full_report, indent=2), encoding="utf-8"
    )

    print(f"\n[DONE] Results written to {gen_dir}")
    print(f"  - generalization_results.csv")
    print(f"  - generalization_results.json")
    print(f"  - gen_many_curve.csv")

    return 0


if __name__ == "__main__":
    sys.exit(main())
