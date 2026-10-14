#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generalization Experiments Runner (RQ5)

Canonical entrypoint for training and evaluating semantic segmentation models
across different K values (number of generated maps used for training).

NEW-234 / NEW-235 / NEW-236 / NEW-237 / NEW-242 / NEW-246
-------------------------------------------------------
This runner previously produced *research-integrity* defects rather than merely
missing features. Each is now a hard, recorded behaviour:

NEW-234 -- the K-sweep actually trains on K datasets
    The runner recorded ``k_datasets`` in ``training_manifest.json`` but passed
    only ``dataset_roots[0]`` to ``train_launcher``, which accepts a single
    ``--dataset``. K=1/K=3/K=5 could therefore all train on the same first
    dataset while claiming 1/3/5 roots. The runner now passes ``--datasets`` with
    *every* root, so ``train_launcher`` trains on a true union, and it refuses to
    proceed if the training manifest it wrote disagrees with the roots actually
    handed to the trainer.

NEW-235 -- training failure stops the condition
    ``train_model()``'s boolean return was discarded and the runner proceeded
    straight to ``_find_checkpoint()``, so a failed training run could fall
    through to a *pre-existing* checkpoint and have it evaluated as if it came
    from the current experiment. A failed training run now marks the condition
    failed and skips evaluation, unless checkpoint reuse was explicitly requested
    via ``--allow_checkpoint_reuse`` and the reused checkpoint is bound to a
    verified manifest.

NEW-236 -- run-specific checkpoint identity
    ``_ensure_model_last()`` returned early when ``model_last.pt`` already
    existed, and ``_find_checkpoint()`` prioritised it, so a successful retrain
    could still evaluate the *previous* model. Each condition now gets its own
    checkpoint directory keyed by a run id, stale ``model_last.pt`` files are
    removed before training, and the selected checkpoint must match the manifest
    written by this run.

NEW-237 -- explicit, disjoint, content-identified evaluation splits
    The evaluation dataset used to fall back to ``manual_datasets[0]`` and then
    to ``gen_datasets[0]`` -- i.e. train on A, evaluate on A, or evaluate
    generated training data under a field still named ``simulated_manual_eval``.
    A governed run now *requires* an explicit ``--eval_dataset``, computes a
    content identity for every split, and refuses to run when the evaluation
    split shares content identity with any training split.

NEW-242 -- experiment-level exit semantics
    The runner returned 0 unconditionally, even with skipped K values, failed
    training, missing checkpoints and failed evaluations. It now returns a
    nonzero exit code whenever any requested condition did not complete, and
    records an explicit per-condition ``status``.

NEW-246 -- missing results are never exported as 0.0
    ``r.get("mIoU", 0.0)`` conflated "not measured" with "measured zero". CSV
    cells for absent evidence are now empty (``N/A``) and a status column
    accompanies every row.

Usage:
    python -m ultimate_pipeline.run_generalization_experiments \\
        --train_gen_datasets /path/to/gen_run_001 /path/to/gen_run_002 ... \\
        --train_manual_datasets /path/to/manual_capture \\
        --eval_dataset /path/to/manual_eval_capture \\
        --real_u_dir /path/to/real_unlabeled_images \\
        --k_values 1 3 5 \\
        --out_dir ./generalization_output

Outputs:
    generalization/
        generalization_results.csv      # Main results table (N/A for missing)
        generalization_results.json     # Full results with metadata + status
        gen_many_curve.csv              # Structural metrics per K
        experiment_status.json          # NEW-242: per-condition outcome + exit code
        models/<condition>/<run_id>/
            seg_fcn_epoch###.pt
            model_manifest.json
        eval/<condition>/
            sim_labeled_eval.json
            real_u_eval_report.json
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
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ultimate_pipeline.config.thesis_contract import (
    GENERALIZATION_RQ5A,
    GENERALIZATION_RQ5B_ACCURACY,
    GENERALIZATION_RQ5B_SHIFT,
    infer_generalization_claim_status,
    infer_generalization_component_statuses,
)
from ultimate_pipeline.perception.rq5_provenance import (
    MULTI_ROOT_TRAIN,
    DatasetIdentityError,
    assert_disjoint_splits,
    combine_dataset_identities,
    dataset_content_identity,
    seed_contract,
    verify_checkpoint_manifest,
)

#: Exit codes (NEW-242).
EXIT_OK = 0
EXIT_EXPERIMENT_INCOMPLETE = 1
EXIT_USAGE = 2

#: Per-condition statuses.
STATUS_TRAINED_AND_EVALUATED = "trained_and_evaluated"
STATUS_TRAINED_NOT_EVALUATED = "trained_not_evaluated"
STATUS_TRAIN_FAILED = "train_failed"
STATUS_CHECKPOINT_MISSING = "checkpoint_missing"
STATUS_CHECKPOINT_REUSED = "checkpoint_reused"
STATUS_EVAL_FAILED = "eval_failed"
STATUS_SKIPPED = "skipped"

#: CSV sentinel for absent evidence (NEW-246). Never a numeric zero.
NA = "N/A"

DEFAULT_SEED = 1337


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


# ---------------------------------------------------------------------------
# NEW-236: run-specific checkpoint identity
# ---------------------------------------------------------------------------


def _purge_stale_checkpoints(model_dir: Path) -> List[str]:
    """
    Remove checkpoints left by a previous run so they can never be mistaken for
    this run's output (NEW-236).

    Returns the list of removed paths, for the condition's audit record.
    """
    removed: List[str] = []
    if not model_dir.exists():
        return removed
    ckpt_dir = model_dir / "checkpoints"
    for path in (ckpt_dir / "model_last.pt",):
        if path.is_file():
            path.unlink()
            removed.append(path.as_posix())
    for path in model_dir.glob("seg_fcn_epoch*.pt"):
        if path.is_file():
            path.unlink()
            removed.append(path.as_posix())
    for path in model_dir.glob("model_manifest.json"):
        if path.is_file():
            path.unlink()
            removed.append(path.as_posix())
    return removed


def _ensure_model_last(model_dir: Path) -> Optional[Path]:
    """
    Create ``checkpoints/model_last.pt`` from the latest epoch checkpoint.

    NEW-236: this no longer early-returns when ``model_last.pt`` already exists.
    It is deliberately *overwriting*: in a run-specific model directory the only
    correct content for ``model_last.pt`` is the last epoch of the run that owns
    that directory, and :func:`_purge_stale_checkpoints` guarantees no other run's
    file is present.
    """
    ckpt_dir = model_dir / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    epoch_ckpts = sorted(model_dir.glob("seg_fcn_epoch*.pt"))
    if not epoch_ckpts:
        return None

    import shutil

    last_pt = ckpt_dir / "model_last.pt"
    shutil.copy2(epoch_ckpts[-1], last_pt)
    return last_pt


def _find_checkpoint(model_dir: Path) -> Optional[Path]:
    """
    Find the checkpoint for a run-specific model directory.

    NEW-236: ``checkpoints/model_last.pt`` is preferred, but only because the
    directory is purged and run-scoped first -- not because it is assumed to be
    current.
    """
    ckpt_dir = model_dir / "checkpoints"
    if ckpt_dir.exists():
        last_pt = ckpt_dir / "model_last.pt"
        if last_pt.exists():
            return last_pt

    epoch_ckpts = sorted(model_dir.glob("seg_fcn_epoch*.pt"))
    if epoch_ckpts:
        return epoch_ckpts[-1]

    return None


def _verify_run_checkpoint(
    model_path: Path,
    model_dir: Path,
    require_manifest: bool,
) -> Dict[str, Any]:
    """
    NEW-236: confirm the selected checkpoint is bound to *this* run's manifest.

    A checkpoint with no companion manifest, or one whose recorded SHA-256 does
    not match the file, is not usable as this run's evidence.
    """
    manifest_path = model_dir / "model_manifest.json"
    if not manifest_path.is_file():
        return {
            "ok": not require_manifest,
            "failures": (
                []
                if not require_manifest
                else [f"no companion manifest for this run at {manifest_path}"]
            ),
            "manifest_path": str(manifest_path),
            "manifest_present": False,
        }
    verification = verify_checkpoint_manifest(
        model_path, manifest_path, require_provenance=require_manifest
    )
    verification["manifest_path"] = str(manifest_path)
    verification["manifest_present"] = True
    return verification


# ---------------------------------------------------------------------------
# NEW-234: pass every K root to the trainer
# ---------------------------------------------------------------------------


def _dataset_identity_block(
    roots: Sequence[Path],
    camera: str,
    *,
    role: str,
    max_files: Optional[int] = None,
) -> Dict[str, Any]:
    """Compute (and record) the content identity of a governed split."""
    per_root: List[Dict[str, Any]] = []
    errors: List[str] = []
    for root in roots:
        try:
            per_root.append(dataset_content_identity(root, camera, max_files=max_files))
        except DatasetIdentityError as exc:
            per_root.append(
                {
                    "root": str(root),
                    "camera": camera,
                    "identity_sha256": None,
                    "complete": False,
                    "error": str(exc),
                }
            )
            errors.append(str(exc))
    if len(per_root) == 1:
        combined = dict(per_root[0])
        combined.setdefault("strategy", "single_root")
    else:
        combined = combine_dataset_identities(per_root, strategy=MULTI_ROOT_TRAIN)
    combined["role"] = role
    if errors:
        combined["errors"] = errors
    return combined


def train_model(
    condition_name: str,
    dataset_roots: List[Path],
    camera: str,
    out_dir: Path,
    epochs: int,
    batch_size: int,
    device: str,
    log_dir: Path,
    *,
    seed: int = DEFAULT_SEED,
    model_subdir: Optional[Path] = None,
    min_root_files: int = 1,
) -> Tuple[bool, Optional[Path], Dict[str, Any]]:
    """
    Train a single model condition on *every* supplied dataset root (NEW-234).

    Returns ``(ok, model_path, record)`` where ``record`` is the training manifest
    actually written for this run. The caller must consult ``ok`` -- discarding it
    is precisely the NEW-235 defect.
    """
    model_dir = model_subdir if model_subdir is not None else (out_dir / "models" / condition_name)
    model_dir.mkdir(parents=True, exist_ok=True)

    # NEW-236: this directory belongs to this run alone. Anything already in it is
    # from a previous run and must not survive into the new evidence.
    removed = _purge_stale_checkpoints(model_dir)

    log_file = log_dir / f"train_{condition_name}.log"

    # NEW-234: hand EVERY root to the trainer, via the multi-root flag.
    cmd = [
        sys.executable, "-m", "ultimate_pipeline.perception.train_launcher",
        "--datasets", *[str(p) for p in dataset_roots],
        "--camera", camera,
        "--out-dir", str(model_dir),
        "--epochs", str(epochs),
        "--batch", str(batch_size),
        "--device", device,
        "--seed", str(int(seed)),
    ]

    print(
        f"[TRAIN] {condition_name}: {len(dataset_roots)} dataset(s) "
        f"({', '.join(p.name for p in dataset_roots)}), epochs={epochs}, seed={seed}"
    )

    identities = [
        _dataset_identity_block([root], camera, role="generated_train", max_files=None)
        for root in dataset_roots
    ]
    train_identity = (
        combine_dataset_identities(identities, strategy=MULTI_ROOT_TRAIN)
        if len(identities) > 1
        else identities[0]
    )

    manifest = {
        "condition": condition_name,
        # NEW-234: the manifest must state exactly what the trainer received.
        "dataset_roots": [str(p) for p in dataset_roots],
        "dataset_root_count": len(dataset_roots),
        "trainer_dataset_argv": ["--datasets", *[str(p) for p in dataset_roots]],
        "train_dataset_identity": train_identity,
        "camera": camera,
        "epochs": epochs,
        "batch_size": batch_size,
        "device": device,
        "seed": int(seed),
        "seed_contract": seed_contract(seed),
        "model_dir": str(model_dir),
        "purged_stale_checkpoints": removed,
        "timestamp": datetime.now().isoformat(),
    }
    (model_dir / "training_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    ret = _run_subprocess(cmd, log_file=log_file)

    if ret != 0:
        record = dict(manifest)
        record["train_exit_code"] = int(ret)
        record["ok"] = False
        print(f"[TRAIN] {condition_name}: FAILED (exit={ret})")
        return False, None, record

    # NEW-234 self-check: the manifest and the trainer must agree on the roots.
    produced_manifest = model_dir / "model_manifest.json"
    if produced_manifest.is_file():
        try:
            trained = json.loads(produced_manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            trained = {}
        trained_roots = [str(p) for p in ((trained.get("dataset") or {}).get("train_roots") or [])]
        if trained_roots and trained_roots != manifest["dataset_roots"]:
            record = dict(manifest)
            record["train_exit_code"] = 0
            record["ok"] = False
            record["error"] = (
                "trainer consumed a different dataset root set than the runner requested: "
                f"requested={manifest['dataset_roots']} trained={trained_roots}"
            )
            print(f"[TRAIN] {condition_name}: FAILED (root mismatch: {record['error']})")
            return False, None, record
        manifest["trainer_reported_roots"] = trained_roots or None
        manifest["trainer_train_identity_sha256"] = (
            (trained.get("dataset") or {}).get("train_identity_sha256")
        )
    else:
        record = dict(manifest)
        record["train_exit_code"] = 0
        record["ok"] = False
        record["error"] = "trainer wrote no model_manifest.json; refusing to trust its checkpoints"
        print(f"[TRAIN] {condition_name}: FAILED (no model manifest produced)")
        return False, None, record

    _ensure_model_last(model_dir)
    model_path = _find_checkpoint(model_dir)
    if model_path is None:
        record = dict(manifest)
        record["train_exit_code"] = 0
        record["ok"] = False
        record["error"] = "training exited 0 but produced no checkpoint"
        print(f"[TRAIN] {condition_name}: FAILED (no checkpoint produced)")
        return False, None, record

    record = dict(manifest)
    record["train_exit_code"] = 0
    record["ok"] = True
    record["checkpoint"] = str(model_path)
    print(f"[TRAIN] {condition_name}: DONE -> {model_path}")
    return True, model_path, record


# ---------------------------------------------------------------------------
# evaluation wrappers
# ---------------------------------------------------------------------------


def eval_sim_labeled(
    condition_name: str,
    model_path: Path,
    eval_dataset: Path,
    camera: str,
    out_dir: Path,
    device: str,
    log_dir: Path,
    *,
    eval_dataset_identity: Optional[Dict[str, Any]] = None,
    model_identity: Optional[Dict[str, Any]] = None,
    min_frames: int = 1,
) -> Dict[str, Any]:
    """Run labeled sim evaluation against an explicitly identified split."""
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
        "--min-frames", str(int(min_frames)),
    ]

    print(f"[EVAL_SIM] {condition_name}: evaluating on {eval_dataset}")
    ret = _run_subprocess(cmd, log_file=log_file)

    # NEW-240: read the report, never guess from the exit code alone.
    payload: Dict[str, Any] = {}
    if out_json.exists():
        try:
            loaded = json.loads(out_json.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
        except (OSError, json.JSONDecodeError):
            payload = {}

    result: Dict[str, Any] = {
        "condition": condition_name,
        "ok": ret == 0 and payload.get("status") == "ok",
        "exit_code": int(ret),
        "status": payload.get("status") or ("missing_report" if not payload else "unknown"),
        "errors": list(payload.get("errors") or []),
    }
    if payload.get("error"):
        result["error"] = payload["error"]
    result.update(
        {
            "mIoU": payload.get("mIoU"),
            "pixel_accuracy": payload.get("pixel_accuracy"),
            "frames_count": payload.get("frames_count"),
            "model": payload.get("model"),
            "model_sha256": payload.get("model_sha256"),
            "dataset": payload.get("dataset"),
            "dataset_identity_sha256": payload.get("dataset_identity_sha256"),
            "state_dict_load": payload.get("state_dict_load"),
        }
    )
    if eval_dataset_identity is not None:
        result["expected_dataset_identity_sha256"] = eval_dataset_identity.get(
            "identity_sha256"
        )
        expected = eval_dataset_identity.get("identity_sha256")
        actual = result.get("dataset_identity_sha256")
        result["dataset_identity_matches_request"] = bool(expected) and expected == actual
    if model_identity is not None:
        expected_model = model_identity.get("sha256")
        result["expected_model_sha256"] = expected_model
        result["model_identity_matches_request"] = bool(expected_model) and expected_model == result.get(
            "model_sha256"
        )
    return result


def eval_real_unlabeled(
    condition_name: str,
    model_path: Path,
    real_u_dir: Path,
    out_dir: Path,
    device: str,
    log_dir: Path,
    *,
    sim_dataset: Optional[Path] = None,
    camera: str = "front_left_camera",
    min_images: int = 1,
) -> Dict[str, Any]:
    """Run unlabeled real-world shift evaluation."""
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
        # NEW-241: evidence requires strictly more than this many decoded images.
        "--min-images", str(int(min_images)),
    ]

    if sim_dataset:
        cmd.extend(["--sim-dataset", str(sim_dataset), "--sim-camera", camera])

    print(f"[EVAL_REAL_U] {condition_name}: evaluating on {real_u_dir}")
    ret = _run_subprocess(cmd, log_file=log_file)

    payload: Dict[str, Any] = {}
    if out_json.exists():
        try:
            loaded = json.loads(out_json.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
        except (OSError, json.JSONDecodeError):
            payload = {}

    real_block = payload.get("real") if isinstance(payload.get("real"), dict) else {}
    result: Dict[str, Any] = {
        "condition": condition_name,
        "ok": ret == 0 and payload.get("status") == "ok",
        "exit_code": int(ret),
        "status": payload.get("status") or ("missing_report" if not payload else "unknown"),
        "errors": list(payload.get("errors") or []),
        # NEW-239: the claim scope travels with the result so no downstream
        # consumer can read shift indicators as accuracy metrics.
        "claim_scope": payload.get("claim_scope", "domain_shift_indicators_only"),
        "accuracy_metrics_available": False,
        "n": real_block.get("n"),
        "n_images_discovered": real_block.get("n_images_discovered"),
        "entropy_mean": real_block.get("entropy_mean"),
        "confidence_mean": real_block.get("confidence_mean"),
        "frechet_pooled_logits": payload.get("frechet_pooled_logits"),
        "model_sha256": payload.get("model_sha256"),
        "dataset_identity_sha256": payload.get("sim_dataset_identity_sha256"),
    }
    if payload.get("error"):
        result["error"] = payload["error"]
    return result


# ---------------------------------------------------------------------------
# NEW-246: missing evidence is never 0.0
# ---------------------------------------------------------------------------


def _metric_cell(value: Any) -> Any:
    """
    Return a CSV-safe cell for a metric.

    NEW-246: absent or non-numeric evidence becomes ``N/A``. A measured zero
    stays a measured zero -- the two must never collapse into the same cell.
    """
    if value is None:
        return NA
    if isinstance(value, bool):
        return NA
    if isinstance(value, (int, float)):
        return value
    return NA


def write_results_csv(results: List[Dict], out_path: Path) -> None:
    """Write generalization_results.csv with explicit statuses and N/A cells."""
    if not results:
        return

    columns = [
        "condition", "K", "status", "ok",
        "mIoU", "pixel_accuracy", "frames_count",
        "real_claim_scope", "real_entropy_mean", "real_confidence_mean", "real_n",
        "errors",
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            sim = r.get("sim") if isinstance(r.get("sim"), dict) else {}
            real = r.get("real") if isinstance(r.get("real"), dict) else {}
            writer.writerow(
                {
                    "condition": r.get("condition", ""),
                    "K": r.get("k") if r.get("k") is not None else NA,
                    "status": r.get("status", ""),
                    "ok": r.get("ok"),
                    "mIoU": _metric_cell(sim.get("mIoU")),
                    "pixel_accuracy": _metric_cell(sim.get("pixel_accuracy")),
                    "frames_count": _metric_cell(sim.get("frames_count")),
                    "real_claim_scope": real.get("claim_scope", NA),
                    "real_entropy_mean": _metric_cell(real.get("entropy_mean")),
                    "real_confidence_mean": _metric_cell(real.get("confidence_mean")),
                    "real_n": _metric_cell(real.get("n")),
                    "errors": "; ".join(str(e) for e in (r.get("errors") or [])) or NA,
                }
            )


def write_gen_many_curve_csv(results: List[Dict], out_path: Path) -> None:
    """Write gen_many_curve.csv for K-sweep analysis (N/A for missing evidence)."""
    if not results:
        return

    columns = ["K", "condition", "status", "train_dataset_root_count", "sim_mIoU", "real_claim_scope", "real_entropy_mean", "real_confidence_mean"]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            if not str(r.get("condition", "")).startswith("generated_k_"):
                continue
            sim = r.get("sim") if isinstance(r.get("sim"), dict) else {}
            real = r.get("real") if isinstance(r.get("real"), dict) else {}
            writer.writerow(
                {
                    "K": r.get("k") if r.get("k") is not None else NA,
                    "condition": r.get("condition", ""),
                    "status": r.get("status", ""),
                    "train_dataset_root_count": _metric_cell(
                        r.get("train_dataset_root_count")
                    ),
                    "sim_mIoU": _metric_cell(sim.get("mIoU")),
                    "real_claim_scope": real.get("claim_scope", NA),
                    "real_entropy_mean": _metric_cell(real.get("entropy_mean")),
                    "real_confidence_mean": _metric_cell(real.get("confidence_mean")),
                }
            )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Generalization experiments: train and evaluate models across K values"
    )
    ap.add_argument(
        "--train_gen_datasets", nargs="+", default=[],
        help="Generated dataset roots (from pipeline runs)",
    )
    ap.add_argument(
        "--train_manual_datasets", nargs="+", default=[],
        help="Manual capture dataset roots (for baseline)",
    )
    ap.add_argument(
        "--eval_dataset",
        default="",
        help=(
            "NEW-237: the labeled evaluation split. Required for a governed run; "
            "it is never inferred from a training directory. Must be disjoint "
            "(by content identity) from every training split."
        ),
    )
    ap.add_argument(
        "--real_u_dir",
        default="",
        help="Directory with unlabeled real-world images (supports domain-shift claims only)",
    )
    ap.add_argument(
        "--k_values", nargs="+", type=int, default=[1, 3, 5],
        help="K values for generated-data sweep",
    )
    ap.add_argument(
        "--out_dir", default="./generalization_output",
        help="Output directory",
    )
    ap.add_argument(
        "--camera", default="front_left_camera",
        help="Camera name for dataset subdirs",
    )
    ap.add_argument(
        "--epochs", type=int, default=3,
        help="Training epochs per model",
    )
    ap.add_argument(
        "--batch", type=int, default=2,
        help="Training batch size",
    )
    ap.add_argument(
        "--device", default="cuda" if "torch" in sys.modules and __import__("torch").cuda.is_available() else "cpu",
        help="Training/eval device",
    )
    ap.add_argument(
        "--seed", type=int, default=DEFAULT_SEED,
        help=f"NEW-244: governed experiment seed (default {DEFAULT_SEED})",
    )
    ap.add_argument(
        "--run_id", default="",
        help="NEW-236: run identifier used to scope checkpoint directories (default: timestamp)",
    )
    ap.add_argument(
        "--min_eval_frames", type=int, default=1,
        help="NEW-240: minimum paired frames required for valid labeled evaluation",
    )
    ap.add_argument(
        "--min_real_images", type=int, default=1,
        help="NEW-241: real-world shift evidence requires strictly more decoded images than this",
    )
    ap.add_argument(
        "--require_manifest", action="store_true",
        help="NEW-243: require a verified companion model_manifest.json for every evaluated checkpoint",
    )
    ap.add_argument(
        "--allow_checkpoint_reuse", action="store_true",
        help=(
            "NEW-235: permit evaluation of a pre-existing checkpoint when this run's "
            "training did not produce one. Off by default: a failed training run must "
            "never fall through to a stale model."
        ),
    )
    ap.add_argument(
        "--skip_training", action="store_true",
        help="Evaluate existing checkpoints only. Requires --allow_checkpoint_reuse.",
    )
    ap.add_argument(
        "--allow_incomplete", action="store_true",
        help=(
            "NEW-242: return exit 0 even when conditions failed or were skipped. "
            "Off by default: an incomplete experiment exits nonzero."
        ),
    )
    return ap.parse_args(argv)


def _preflight(
    args: argparse.Namespace,
    gen_datasets: List[Path],
    manual_datasets: List[Path],
    camera: str,
) -> Tuple[Optional[Dict[str, Any]], List[Path]]:
    """
    NEW-237: validate split configuration before any training happens.

    Returns ``(splits_or_None, errors)``. When ``errors`` is non-empty the caller
    must refuse to run.
    """
    errors: List[str] = []
    splits: Dict[str, Any] = {
        "camera": camera,
        "generated_train": [],
        "generated_validation": [],
        "generated_test": [],
        "manual_train": [],
        "eval": None,
        "real_unlabeled": None,
    }

    if not args.eval_dataset:
        errors.append(
            "NEW-237: --eval_dataset is required. The evaluation split is never inferred "
            "from a training directory (that was train/eval leakage, or evaluation of "
            "generated training data under a 'manual' status field)."
        )

    eval_path = Path(args.eval_dataset) if args.eval_dataset else None
    train_roots = list(gen_datasets) + list(manual_datasets)
    train_identities: List[Dict[str, Any]] = []
    for root in train_roots:
        block = _dataset_identity_block([root], camera, role="train", max_files=None)
        train_identities.append(block)
        if block.get("identity_sha256") is None:
            errors.append(f"train split could not be content-identified: {root}")

    eval_identity: Optional[Dict[str, Any]] = None
    if eval_path is not None:
        if not eval_path.exists():
            errors.append(f"evaluation split does not exist: {eval_path}")
        else:
            eval_identity = _dataset_identity_block(
                [eval_path], camera, role="eval", max_files=None
            )
            if eval_identity.get("identity_sha256") is None:
                errors.append(
                    f"evaluation split could not be content-identified: {eval_path}"
                )
            else:
                # NEW-237: overlap is decided by content digest, not by path.
                overlaps = assert_disjoint_splits(train_identities, [eval_identity])
                errors.extend(overlaps)

    splits["train_identities"] = train_identities
    splits["eval_identity"] = eval_identity
    splits["eval_path"] = eval_path
    splits["real_unlabeled"] = str(args.real_u_dir) if args.real_u_dir else None
    splits["disjoint_verified"] = not any(
        "shares content identity" in e for e in errors
    )
    return splits, errors


def _run_condition(
    *,
    condition: str,
    k: Optional[int],
    dataset_roots: List[Path],
    camera: str,
    out_dir: Path,
    args: argparse.Namespace,
    log_dir: Path,
    run_id: str,
    splits: Dict[str, Any],
    real_u_dir: Optional[Path],
    real_u_min_images: int,
    eval_min_frames: int,
    sim_reference_dataset: Optional[Path],
) -> Dict[str, Any]:
    """Train (unless skipping) and evaluate one experimental condition."""
    result: Dict[str, Any] = {
        "condition": condition,
        "k": k,
        "dataset_roots": [str(p) for p in dataset_roots],
        "train_dataset_root_count": len(dataset_roots),
        "seed": int(args.seed),
        "status": STATUS_TRAINED_NOT_EVALUATED,
        "ok": False,
        "sim": {},
        "real": {},
        "errors": [],
        "run_id": run_id,
    }

    model_dir = out_dir / "models" / condition / run_id
    trained = False
    model_path: Optional[Path] = None

    if not args.skip_training:
        trained, model_path, train_record = train_model(
            condition_name=condition,
            dataset_roots=dataset_roots,
            camera=camera,
            out_dir=out_dir,
            epochs=args.epochs,
            batch_size=args.batch,
            device=args.device,
            log_dir=log_dir,
            seed=args.seed,
            model_subdir=model_dir,
        )
        result["training"] = train_record
        if not trained:
            # NEW-235: a failed training run MUST NOT fall through to a stale
            # checkpoint. It can only be evaluated under an explicit reuse mode.
            result["status"] = STATUS_TRAIN_FAILED
            result["ok"] = False
            result["errors"].append(
                train_record.get("error") or "training failed; no checkpoint evaluated"
            )
            if not args.allow_checkpoint_reuse:
                result["errors"].append(
                    "checkpoint reuse was not requested, so no existing model was evaluated"
                )
                return result
    else:
        result["errors"].append("--skip_training was requested")

    if model_path is None:
        model_path = _find_checkpoint(model_dir)

    if model_path is None:
        result["status"] = STATUS_CHECKPOINT_MISSING
        result["ok"] = False
        result["errors"].append(
            f"no checkpoint available in {model_dir} for run {run_id}"
        )
        return result

    result["checkpoint"] = str(model_path)
    if not trained:
        result["status"] = STATUS_CHECKPOINT_REUSED
        result["errors"].append(
            "this condition was NOT trained by the current run; the evaluated checkpoint "
            "is a pre-existing artifact and its metrics do not describe this experiment"
        )

    # NEW-236: the evaluated checkpoint must be bound to this run's manifest.
    verification = _verify_run_checkpoint(
        model_path, model_dir, require_manifest=args.require_manifest or not trained
    )
    result["checkpoint_verification"] = verification
    if not verification["ok"]:
        result["status"] = STATUS_CHECKPOINT_MISSING
        result["ok"] = False
        result["errors"].extend(verification["failures"])
        return result

    model_identity = {
        "sha256": verification.get("checkpoint_sha256"),
        "manifest": verification.get("manifest_path"),
    }

    eval_dataset = splits.get("eval_path")
    if eval_dataset is not None and Path(eval_dataset).exists():
        result["sim"] = eval_sim_labeled(
            condition_name=condition,
            model_path=model_path,
            eval_dataset=Path(eval_dataset),
            camera=camera,
            out_dir=out_dir,
            device=args.device,
            log_dir=log_dir,
            eval_dataset_identity=splits.get("eval_identity"),
            model_identity=model_identity,
            min_frames=eval_min_frames,
        )
        if not result["sim"].get("ok"):
            result["errors"].append(
                f"labeled evaluation did not produce admissible evidence: "
                f"{result['sim'].get('errors') or result['sim'].get('error')}"
            )
            if not (result["sim"].get("dataset_identity_matches_request", True) and result["sim"].get("model_identity_matches_request", True)):
                result["errors"].append(
                    "evaluation dataset or model identity did not match the requested split/checkpoint"
                )
    else:
        result["errors"].append("no admissible evaluation split was evaluated")

    if real_u_dir is not None and real_u_dir.exists():
        result["real"] = eval_real_unlabeled(
            condition_name=condition,
            model_path=model_path,
            real_u_dir=real_u_dir,
            out_dir=out_dir,
            device=args.device,
            log_dir=log_dir,
            sim_dataset=sim_reference_dataset,
            camera=camera,
            min_images=real_u_min_images,
        )
        if not result["real"].get("ok"):
            result["errors"].append(
                f"real-unlabeled evaluation did not produce admissible evidence: "
                f"{result['real'].get('errors') or result['real'].get('error')}"
            )
    else:
        result["errors"].append("no admissible real-unlabeled directory was evaluated")

    result["ok"] = bool(result["sim"].get("ok")) and bool(result["real"].get("ok"))
    result["status"] = (
        STATUS_TRAINED_AND_EVALUATED if result["ok"] else STATUS_EVAL_FAILED
    )
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    log_dir = out_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    gen_datasets = [Path(p) for p in args.train_gen_datasets]
    manual_datasets = [Path(p) for p in args.train_manual_datasets]
    real_u_dir = Path(args.real_u_dir) if args.real_u_dir else None

    # NEW-242: the runner's own outcome is a governed result, not a formality.
    exit_code = EXIT_OK
    preflight_errors: List[str] = []
    skipped_conditions: List[Dict[str, Any]] = []

    if args.skip_training and not args.allow_checkpoint_reuse:
        preflight_errors.append(
            "--skip_training requires --allow_checkpoint_reuse: evaluating a checkpoint that "
            "this run did not train must be an explicit, recorded decision (NEW-235)"
        )

    splits, split_errors = _preflight(args, gen_datasets, manual_datasets, args.camera)
    preflight_errors.extend(split_errors)

    run_id = args.run_id or datetime.now().strftime("run_%Y%m%dT%H%M%S")

    all_results: List[Dict[str, Any]] = []

    if preflight_errors:
        # NEW-237: refuse to produce evidence from an unverified split layout.
        print("[PREFLIGHT] refusing to run:")
        for message in preflight_errors:
            print(f"  - {message}")
        gen_dir = out_dir / "generalization"
        gen_dir.mkdir(parents=True, exist_ok=True)
        (gen_dir / "experiment_status.json").write_text(
            json.dumps(
                {
                    "timestamp": datetime.now().isoformat(),
                    "status": "preflight_failed",
                    "exit_code": EXIT_USAGE,
                    "preflight_errors": preflight_errors,
                    "splits": {k: v for k, v in splits.items() if k != "train_identities"},
                    "results_count": 0,
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        return EXIT_USAGE

    # --- Manual baseline (if manual training datasets provided) ---
    if manual_datasets:
        all_results.append(
            _run_condition(
                condition="manual_baseline_k000",
                k=0,
                dataset_roots=manual_datasets,
                camera=args.camera,
                out_dir=out_dir,
                args=args,
                log_dir=log_dir,
                run_id=run_id,
                splits=splits,
                real_u_dir=real_u_dir,
                real_u_min_images=args.min_real_images,
                eval_min_frames=args.min_eval_frames,
                sim_reference_dataset=splits.get("eval_path"),
            )
        )

    # --- Generated K-sweep ---
    for k in args.k_values:
        if k > len(gen_datasets):
            print(
                f"[SKIP] K={k} requested but only {len(gen_datasets)} generated datasets available"
            )
            # NEW-242: a skipped requested condition is an incomplete experiment.
            skipped_conditions.append(
                {
                    "condition": f"generated_k_k{k:03d}",
                    "k": k,
                    "status": STATUS_SKIPPED,
                    "ok": False,
                    "reason": (
                        f"K={k} requested but only {len(gen_datasets)} generated "
                        "dataset(s) available"
                    ),
                    "sim": {},
                    "real": {},
                    "errors": ["insufficient_generated_datasets_for_requested_k"],
                }
            )
            continue

        condition = f"generated_k_k{k:03d}"
        # NEW-234: all K roots, handed to the trainer as a true union.
        k_datasets = gen_datasets[:k]

        all_results.append(
            _run_condition(
                condition=condition,
                k=k,
                dataset_roots=k_datasets,
                camera=args.camera,
                out_dir=out_dir,
                args=args,
                log_dir=log_dir,
                run_id=run_id,
                splits=splits,
                real_u_dir=real_u_dir,
                real_u_min_images=args.min_real_images,
                eval_min_frames=args.min_eval_frames,
                sim_reference_dataset=k_datasets[0] if k_datasets else None,
            )
        )

    all_results.extend(skipped_conditions)

    # --- Write outputs ---
    gen_dir = out_dir / "generalization"
    gen_dir.mkdir(parents=True, exist_ok=True)

    # NEW-246: a condition that produced no evidence still gets a row, with N/A
    # metric cells and an explicit status, so "missing" is visible in the table
    # instead of silently vanishing from it.
    write_results_csv(all_results, gen_dir / "generalization_results.csv")
    write_gen_many_curve_csv(all_results, gen_dir / "gen_many_curve.csv")

    # NEW-239: the claim status now names the two independent claim families.
    claim_status = infer_generalization_claim_status(
        results=all_results,
        train_gen_datasets=gen_datasets,
        train_manual_datasets=manual_datasets,
        eval_manual_dataset=splits.get("eval_path"),
        real_u_dir=real_u_dir,
    )
    component_statuses = infer_generalization_component_statuses(
        results=all_results,
        eval_manual_dataset=splits.get("eval_path"),
        real_u_dir=real_u_dir,
    )
    simulated_status = component_statuses["simulated_manual_eval"]
    real_status = component_statuses["real_unlabeled_eval"]
    real_accuracy_status = component_statuses["real_world_generalization_accuracy"]
    paired_ingolstadt_status = component_statuses["paired_ingolstadt_generalization"]

    # NEW-242: derive the experiment exit code from what actually happened.
    completed = [r for r in all_results if r.get("status") == STATUS_TRAINED_AND_EVALUATED]
    failed = [r for r in all_results if r.get("status") != STATUS_TRAINED_AND_EVALUATED]
    if failed:
        exit_code = EXIT_EXPERIMENT_INCOMPLETE

    status_payload = {
        "schema": "generalization_experiment_status_v2",
        "timestamp": datetime.now().isoformat(),
        "run_id": run_id,
        "seed": int(args.seed),
        "seed_contract": seed_contract(args.seed),
        "exit_code": exit_code,
        "experiment_status": "complete" if exit_code == EXIT_OK else "incomplete",
        "generalization_claim_status": claim_status.value,
        "generalization_claim_reason": claim_status.reason,
        "rq5a_simulated_transfer": {
            "claim_family": GENERALIZATION_RQ5A,
            "status": simulated_status.value,
            "reason": simulated_status.reason,
        },
        "rq5b_real_unlabeled_shift": {
            "claim_family": GENERALIZATION_RQ5B_SHIFT,
            "status": real_status.value,
            "reason": real_status.reason,
        },
        "rq5b_real_generalization_accuracy": {
            "claim_family": GENERALIZATION_RQ5B_ACCURACY,
            "status": real_accuracy_status.value,
            "reason": real_accuracy_status.reason,
        },
        "paired_ingolstadt_generalization": {
            "status": paired_ingolstadt_status.value,
            "reason": paired_ingolstadt_status.reason,
        },
        "split_layout": {
            "eval_dataset": str(splits.get("eval_path")) if splits.get("eval_path") else None,
            "eval_dataset_identity_sha256": (splits.get("eval_identity") or {}).get(
                "identity_sha256"
            ),
            "disjoint_verified": splits.get("disjoint_verified"),
            "train_dataset_root_count": len(gen_datasets) + len(manual_datasets),
        },
        "results_count": len(all_results),
        "conditions_completed": [r["condition"] for r in completed],
        "conditions_not_completed": [
            {"condition": r["condition"], "status": r.get("status"), "errors": r.get("errors")}
            for r in failed
        ],
        "claim_boundary": (
            f"Claim {GENERALIZATION_RQ5A} only from simulated_manual_eval_status. Claim "
            f"{GENERALIZATION_RQ5B_SHIFT} only from real_unlabeled_eval_status. "
            f"{GENERALIZATION_RQ5B_ACCURACY} cannot be claimed: unlabeled real-world data "
            "carries no labels, so no mIoU or pixel accuracy exists for it."
        ),
    }
    (gen_dir / "experiment_status.json").write_text(
        json.dumps(status_payload, indent=2, default=str), encoding="utf-8"
    )
    # Retain the historical filename so existing consumers keep working.
    (gen_dir / "generalization_status.json").write_text(
        json.dumps(
            {
                "timestamp": status_payload["timestamp"],
                "generalization_claim_status": claim_status.value,
                "generalization_claim_reason": claim_status.reason,
                "simulated_manual_eval_status": simulated_status.value,
                "simulated_manual_eval_reason": simulated_status.reason,
                "real_unlabeled_eval_status": real_status.value,
                "real_unlabeled_eval_reason": real_status.reason,
                "real_world_generalization_accuracy_status": real_accuracy_status.value,
                "real_world_generalization_accuracy_reason": real_accuracy_status.reason,
                "paired_ingolstadt_generalization_status": paired_ingolstadt_status.value,
                "paired_ingolstadt_generalization_reason": paired_ingolstadt_status.reason,
                "experiment_status": status_payload["experiment_status"],
                "exit_code": exit_code,
                "results_count": len(all_results),
                "claim_boundary": status_payload["claim_boundary"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    full_report = {
        "schema": "generalization_results_v2",
        "timestamp": datetime.now().isoformat(),
        "run_id": run_id,
        "k_values": args.k_values,
        "seed": int(args.seed),
        "train_gen_datasets": [str(p) for p in gen_datasets],
        "train_manual_datasets": [str(p) for p in manual_datasets],
        "eval_manual_dataset": str(splits.get("eval_path")) if splits.get("eval_path") else None,
        "eval_dataset_identity_sha256": (splits.get("eval_identity") or {}).get(
            "identity_sha256"
        ),
        "split_disjoint_verified": splits.get("disjoint_verified"),
        "real_u_dir": str(real_u_dir) if real_u_dir else None,
        "real_u_conditioned_on_k": len(all_results) > 1,
        "generalization_claim_status": claim_status.value,
        "generalization_claim_reason": claim_status.reason,
        "experiment_status": status_payload["experiment_status"],
        "exit_code": exit_code,
        "conditions_not_completed": status_payload["conditions_not_completed"],
        "claim_boundary": status_payload["claim_boundary"],
        "experiment_status_path": str(gen_dir / "experiment_status.json"),
        "results": all_results,
    }
    (gen_dir / "generalization_results.json").write_text(
        json.dumps(full_report, indent=2, default=str), encoding="utf-8"
    )

    print(f"\n[DONE] Results written to {gen_dir}")
    print(f"  - generalization_results.csv")
    print(f"  - generalization_results.json")
    print(f"  - gen_many_curve.csv")
    print(f"  - experiment_status.json")
    print(
        f"[EXIT] experiment_status={status_payload['experiment_status']} "
        f"completed={len(completed)} not_completed={len(failed)} code={exit_code}"
    )

    if exit_code == EXIT_EXPERIMENT_INCOMPLETE and not args.allow_incomplete:
        return EXIT_EXPERIMENT_INCOMPLETE
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
