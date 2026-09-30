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


def _assert_contiguous_generated_sequence(dataset_roots: List[Path]) -> Dict[str, Any]:
    """NEW-242: K-sweep data must be a contiguous, spatially adjacent prefix.

    `gen_datasets[:k]` is only a meaningful nested K-series when each added
    run is spatially adjacent to the ones already in the set. Arbitrary
    ordering of unrelated generated runs makes "K=3 beats K=1" meaningless.
    Returns the adjacency report (raises on clear violations when a manifest
    records neighbour information).
    """
    report: Dict[str, Any] = {
        "schema": "GEN_DATASET_SEQUENCE/v1",
        "roots": [str(p) for p in dataset_roots],
        "count": len(dataset_roots),
        "duplicates": [],
        "adjacency_declared": False,
        "chain_violations": [],
        "contiguous": True,
    }
    seen: Dict[str, int] = {}
    for i, p in enumerate(dataset_roots):
        key = str(p)
        if key in seen:
            report["duplicates"].append({"root": key, "positions": [seen[key], i]})
        seen[key] = i
    if report["duplicates"]:
        report["contiguous"] = False
        raise ValueError(
            "NEW-242: generated dataset sequence contains duplicate roots: "
            + json.dumps(report["duplicates"])
        )

    # Best-effort neighbour declaration from each run's manifest, if present.
    neighbours: List[Optional[List[str]]] = []
    for p in dataset_roots:
        manifest_path = Path(p) / "map_composition_manifest.json"
        entry: Optional[List[str]] = None
        if manifest_path.exists():
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                raw = payload.get("neighbour_runs") or payload.get("adjacent_runs")
                if isinstance(raw, list):
                    entry = [str(x) for x in raw]
            except Exception:
                entry = None
        neighbours.append(entry)
    if any(n is not None for n in neighbours):
        report["adjacency_declared"] = True
        for i in range(1, len(neighbours)):
            prev_root, cur_root = dataset_roots[i - 1], dataset_roots[i]
            prev_n, cur_n = neighbours[i - 1], neighbours[i]
            ok = False
            if cur_n is not None:
                ok = any(Path(str(x)) == prev_root or str(x) == str(prev_root) for x in cur_n)
            if not ok and prev_n is not None:
                ok = any(Path(str(x)) == cur_root or str(x) == str(cur_root) for x in prev_n)
            if not ok:
                report["chain_violations"].append(
                    {"index": i, "from": str(prev_root), "to": str(cur_root)}
                )
        if report["chain_violations"]:
            report["contiguous"] = False
            raise ValueError(
                "NEW-242: generated dataset sequence is not a contiguous spatially "
                "adjacent chain: "
                + json.dumps(report["chain_violations"][:5])
            )
    return report


def train_model(
    condition_name: str,
    dataset_roots: List[Path],
    camera: str,
    out_dir: Path,
    epochs: int,
    batch_size: int,
    device: str,
    log_dir: Path,
    seed: int = 0,
    split_manifest: str = "",
) -> bool:
    """Train a single model condition."""
    model_dir = out_dir / "models" / condition_name
    model_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / f"train_{condition_name}.log"

    # Build command - pass EVERY dataset root (NEW-234: previously only
    # dataset_roots[0] was forwarded, so k>1 conditions trained on k=1 data).
    cmd = [sys.executable, "-m", "ultimate_pipeline.perception.train_launcher"]
    for root in dataset_roots:
        cmd.extend(["--dataset", str(root)])
    cmd.extend([
        "--camera", camera,
        "--out-dir", str(model_dir),
        "--epochs", str(epochs),
        "--batch", str(batch_size),
        "--device", device,
        "--seed", str(seed),
    ])
    if split_manifest:
        cmd.extend(["--split-manifest", str(split_manifest)])

    print(f"[TRAIN] {condition_name}: {len(dataset_roots)} dataset(s), epochs={epochs}, seed={seed}")

    # Write training manifest
    manifest = {
        "condition": condition_name,
        "dataset_roots": [str(p) for p in dataset_roots],
        "dataset_root_count": len(dataset_roots),
        "camera": camera,
        "epochs": epochs,
        "batch_size": batch_size,
        "device": device,
        "seed": int(seed),
        "split_manifest": split_manifest or None,
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
    ap.add_argument(
        "--seed", type=int, default=0,
        help="Global training seed, forwarded to train_launcher and recorded in "
        "training_provenance.json (NEW-239).",
    )
    ap.add_argument(
        "--split_manifest", default="",
        help="Governed split manifest (generated_train/generated_validation/"
        "generated_test/manual_test, disjoint). Required to claim a "
        "held-out manual test result (NEW-240).",
    )
    ap.add_argument(
        "--hyperparameter_suite", default="",
        help="Name of the hyperparameter suite actually used (NEW-244: a "
        "single fixed pair of epochs/batch cannot support 'not one "
        "hyperparameter choice' claims).",
    )
    ap.add_argument(
        "--require_both_eval_sets", action="store_true",
        help="NEW-243: fail (nonzero exit) unless BOTH the labeled sim eval set "
        "and the unlabeled real eval set are configured and complete.",
    )
    ap.add_argument(
        "--real_u_is_train_split", action="store_true",
        help="NEW-241: declare that --real_u_dir is drawn from the TRAIN split. "
        "Such results must not be reported as `manual_test`.",
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

    # NEW-242: the K-series must be a contiguous, adjacent, duplicate-free
    # sequence -- otherwise `gen_datasets[:k]` is not a nested K-sweep.
    gen_sequence_report = (
        _assert_contiguous_generated_sequence(gen_datasets) if len(gen_datasets) > 1 else None
    )

    # Determine eval dataset. NEW-243: NO silent fallback. Previously an
    # unset --eval_manual_dataset silently evaluated on generated TRAIN data
    # and the result was reported as a manual-test score.
    eval_dataset = Path(args.eval_manual_dataset) if args.eval_manual_dataset else None
    eval_dataset_fallback_used = False
    if eval_dataset is None and manual_datasets:
        eval_dataset = manual_datasets[0]
        eval_dataset_fallback_used = True
    if eval_dataset is None and gen_datasets:
        raise ValueError(
            "NEW-243: no labeled evaluation dataset configured. Pass "
            "--eval_manual_dataset explicitly; evaluating on --train_gen_datasets "
            "would report training data as a manual-test score."
        )
    if eval_dataset is not None and not eval_dataset.exists():
        raise FileNotFoundError(
            f"NEW-243: configured eval dataset does not exist: {eval_dataset}"
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
                seed=int(args.seed),
                split_manifest=args.split_manifest,
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
                seed=int(args.seed),
                split_manifest=args.split_manifest,
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

    # --- NEW-243 / NEW-245: completion accounting -------------------------
    # Claiming both evaluation sets while only running one is silent
    # incomplete execution. Every condition must have produced both reports,
    # otherwise `summary_complete` stays False and the gap is named.
    def _has_sim(row: Dict) -> bool:
        sim = row.get("sim")
        return isinstance(sim, dict) and sim.get("mIoU") is not None

    def _has_real(row: Dict) -> bool:
        real = row.get("real")
        return isinstance(real, dict) and real.get("entropy_mean") is not None

    conditions_total = len(all_results)
    missing_sim = [r.get("condition") for r in all_results if not _has_sim(r)]
    missing_real = [r.get("condition") for r in all_results if not _has_real(r)]
    claimed_sim = bool(eval_dataset)
    claimed_real = bool(real_u_dir)
    ran_sim = conditions_total > 0 and not missing_sim
    ran_real = conditions_total > 0 and not missing_real

    summary_complete = bool(
        conditions_total
        and claimed_sim and claimed_real
        and ran_sim and ran_real
        and eval_dataset is not None and eval_dataset.exists()
        and real_u_dir is not None and real_u_dir.exists()
        and (gen_sequence_report is None or gen_sequence_report.get("contiguous", False))
    )
    incomplete_reasons: List[str] = []
    if not claimed_sim:
        incomplete_reasons.append("simulated_manual_eval_not_configured")
    elif not ran_sim:
        incomplete_reasons.append(f"simulated_manual_eval_missing_for:{missing_sim}")
    if not claimed_real:
        incomplete_reasons.append("real_unlabeled_eval_not_configured")
    elif not ran_real:
        incomplete_reasons.append(f"real_unlabeled_eval_missing_for:{missing_real}")
    if real_u_dir is not None and not real_u_dir.exists():
        incomplete_reasons.append("real_unlabeled_eval_dir_missing")
    if gen_sequence_report is not None and not gen_sequence_report.get("contiguous", False):
        incomplete_reasons.append("generated_dataset_sequence_not_contiguous")

    if args.require_both_eval_sets and not summary_complete:
        raise RuntimeError(
            "NEW-243: both evaluation sets were required but this run is "
            f"incomplete: {incomplete_reasons}"
        )

    # --- NEW-241: name the real eval split honestly -----------------------
    # The unlabeled real directory was previously reported under the
    # `manual_test` heading while actually being the TRAIN split.
    if real_u_dir is None:
        real_u_split_classification = "not_configured"
    elif args.real_u_is_train_split:
        real_u_split_classification = "train_split"
    else:
        real_u_split_classification = "unlabeled_external_not_manual_test"

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
        # NEW-243/NEW-245: the honest completion flag.
        "summary_complete": bool(summary_complete),
        "incomplete_reasons": incomplete_reasons,
        "missing_simulated_eval_conditions": missing_sim,
        "missing_real_eval_conditions": missing_real,
        "eval_dataset_fallback_used": bool(eval_dataset_fallback_used),
        "real_u_split_classification": real_u_split_classification,
        "seed": int(args.seed),
        "split_manifest": args.split_manifest or None,
        "hyperparameter_suite": args.hyperparameter_suite or None,
        "generated_dataset_sequence": gen_sequence_report,
        "claim_boundary": (
            "Do not claim simulated Ingolstadt or real-world unlabeled generalization "
            "unless the corresponding status above is authoritative_result_available, "
            "and do not claim a complete summary while summary_complete is false."
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
        "summary_complete": bool(summary_complete),
        "incomplete_reasons": incomplete_reasons,
        "real_u_split_classification": real_u_split_classification,
        "eval_dataset_fallback_used": bool(eval_dataset_fallback_used),
        "generated_dataset_sequence": gen_sequence_report,
        "seed": int(args.seed),
        "split_manifest": args.split_manifest or None,
        "hyperparameter_suite": args.hyperparameter_suite or None,
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
