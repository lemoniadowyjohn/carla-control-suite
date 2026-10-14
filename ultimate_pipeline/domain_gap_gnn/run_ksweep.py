#!/usr/bin/env python3
"""OC-51 (RQ4): K-sweep with nested subsets, separated seeds and checkpoint identity.

Experimental design (§2-§5):
- ONE deterministic permutation per selection seed; subset(K) = P[:K], so
  K=10 ⊂ K=20 ⊂ ... — varying K no longer confounds sample size with
  subset composition or training seed.
- ``selection_seed`` (which tiles) is independent of ``training_seed``
  (shuffling/init/noise) and ``torch_seed``.
- Each K trains a seed ensemble (K × TRAINING_SEEDS); per-K aggregates
  (n/mean/std/median/min/max/CI) are reported with raw per-run rows kept.

Checkpoint reuse (§7): an existing checkpoint is reused ONLY when its
sidecar manifest matches the expected identity exactly (schema, dataset
manifest, tile selection, seeds, model/training config, code revision).
Legacy checkpoints without manifests are never silently reused.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import gnn_provenance as prov
from .graph_builder import MapGraphBuilder, graph_schema_hash, node_feature_dim
from .latent_gap_runner import compute_whole_map_latent_gap


K_VALUES: List[int] = [10, 20, 30, 40, 50, 60, 72]

DEFAULT_SELECTION_SEED = 1234
DEFAULT_TRAINING_SEEDS: List[int] = [42, 43, 44]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run K-sweep GNN training over nested tile subsets."
    )
    parser.add_argument(
        "--tiles_dir",
        type=Path,
        default=Path("domain_gap_results") / "auto_tiles_aligned",
        help="Directory containing .xodr tiles for K-sweep training.",
    )
    parser.add_argument(
        "--out_dir",
        type=Path,
        default=Path("thesis_results") / "gnn_v1",
        help="Output directory for K-sweep artifacts.",
    )
    parser.add_argument(
        "--manual_xodr",
        type=Path,
        default=Path("cities") / "ingolstadt" / "manual_grid0828.xodr",
        help="Manual reference XODR used for latent gap inference.",
    )
    parser.add_argument(
        "--auto_xodr",
        type=Path,
        default=Path("domain_gap_results") / "auto_aligned.xodr",
        help="Auto-generated XODR used for latent gap inference.",
    )
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument(
        "--selection_seed",
        type=int,
        default=DEFAULT_SELECTION_SEED,
        help="Dataset-selection seed: fixes the deterministic tile "
             "permutation (which tiles per K). Independent of training seeds.",
    )
    parser.add_argument(
        "--training_seeds",
        type=int,
        nargs="+",
        default=list(DEFAULT_TRAINING_SEEDS),
        help="Training seeds: one run per (K, seed).",
    )
    parser.add_argument(
        "--k_values",
        type=int,
        nargs="+",
        default=list(K_VALUES),
        help="K values for the sweep (must be increasing positive ints).",
    )
    parser.add_argument("--width_mode", type=str, default="legacy",
                        choices=("legacy", "polynomial"))
    parser.add_argument("--strict_dataset", action="store_true")
    parser.add_argument("--noise_std", type=float, default=0.01)
    parser.add_argument("--temperature", type=float, default=0.5)
    parser.add_argument(
        "--on_checkpoint_mismatch",
        type=str,
        default="retrain",
        choices=("retrain", "fail"),
        help="What to do when an existing checkpoint's manifest does not "
             "match the expected identity: retrain, or fail closed.",
    )
    parser.add_argument(
        "--exclude_source_xodr",
        type=Path,
        nargs="*",
        default=[],
        help="GAP-010 source-identity exclusion contract: additional "
             "known eval/reference XODR paths (beyond --manual_xodr and "
             "--auto_xodr, which are ALWAYS excluded automatically) whose "
             "content must never enter the K-sweep tile pool -- e.g. "
             "cities/ingolstadt/manual_grid0821.xodr if distinct from the "
             "--manual_xodr used for this run.",
    )
    return parser.parse_args(list(argv))


def _require_file(path: Path, name: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{name} not found: {path}")


def _list_tiles(
    tiles_dir: Path,
    *,
    min_tiles: int = max(K_VALUES),
    exclude_hashes: Optional[set] = None,
) -> List[Path]:
    if not tiles_dir.is_dir():
        raise FileNotFoundError(f"tiles_dir not found: {tiles_dir}")
    tiles = sorted(p for p in tiles_dir.glob("*.xodr") if p.is_file())
    if exclude_hashes:
        excluded_names: List[str] = []
        kept: List[Path] = []
        for p in tiles:
            if prov.sha256_file(p) in exclude_hashes:
                excluded_names.append(p.name)
            else:
                kept.append(p)
        if excluded_names:
            print(
                f"[ksweep] source-SHA exclusion (GAP-010): dropped "
                f"{len(excluded_names)} tile(s) whose content matches a "
                f"protected eval/reference file: {excluded_names}"
            )
        tiles = kept
    if not tiles:
        raise RuntimeError(f"No .xodr tiles found in: {tiles_dir}")
    if len(tiles) < int(min_tiles):
        raise RuntimeError(
            f"Need at least {int(min_tiles)} tiles for K-sweep, found {len(tiles)}"
        )
    return tiles


def _checkpoint_epoch_number(path: Path) -> int:
    match = re.search(r"map_encoder_epoch(\d+)\.pt$", path.name)
    return int(match.group(1)) if match else -1


def _resolve_checkpoint(checkpoint_dir: Path) -> Path:
    candidates = list(checkpoint_dir.glob("map_encoder_epoch*.pt"))
    if not candidates:
        raise RuntimeError(f"No checkpoint generated in: {checkpoint_dir}")
    # Sort numerically by epoch number, not lexicographically by filename --
    # "epoch100.pt" < "epoch90.pt" as strings, which would silently pick a
    # less-trained checkpoint as the "latest" one once epoch counts cross a
    # digit-width boundary.
    return max(candidates, key=_checkpoint_epoch_number)


def _parse_final_loss(stdout_text: str) -> float:
    matches = re.findall(r"loss\s*=\s*([0-9]+(?:\.[0-9]+)?)", stdout_text)
    if not matches:
        raise RuntimeError("Could not parse final loss from training stdout")
    return float(matches[-1])


def _run_training(
    tiles_dir: Path,
    out_dir: Path,
    *,
    seed: int,
    epochs: int,
    batch_size: int,
    lr: float,
    selection_seed: int | None = None,
    width_mode: str = "legacy",
    strict_dataset: bool = False,
    noise_std: float = 0.01,
    temperature: float = 0.5,
    exclude_source_xodr: Optional[Sequence[Path]] = None,
) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "ultimate_pipeline.domain_gap_gnn.train_map_encoder",
        "--tiles_dir",
        str(tiles_dir),
        "--epochs",
        str(int(epochs)),
        "--batch_size",
        str(int(batch_size)),
        "--lr",
        str(float(lr)),
        "--out_dir",
        str(out_dir),
        "--seed",
        str(int(seed)),
        "--width_mode",
        str(width_mode),
        "--noise_std",
        str(float(noise_std)),
        "--temperature",
        str(float(temperature)),
    ]
    if selection_seed is not None and int(selection_seed) >= 0:
        cmd += ["--selection_seed", str(int(selection_seed))]
    if strict_dataset:
        cmd += ["--strict_dataset"]
    if exclude_source_xodr:
        # GAP-010: forward the same protected-reference paths so the
        # trainer subprocess independently re-enforces the exclusion
        # contract on the actual dataset it builds (defense in depth --
        # the tile pool passed to it was already filtered by the caller).
        cmd += ["--exclude_source_xodr"] + [str(p) for p in exclude_source_xodr]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    if int(proc.returncode) != 0:
        raise RuntimeError(
            "Training failed with return code "
            f"{int(proc.returncode)} for command: {' '.join(cmd)}"
        )
    checkpoint = _resolve_checkpoint(out_dir)
    final_loss = _parse_final_loss(proc.stdout or "")
    return {
        "checkpoint": checkpoint,
        "final_loss": float(final_loss),
    }


def _compute_metrics(
    *,
    manual_xodr: Path,
    auto_xodr: Path,
    checkpoint: Path,
) -> Dict[str, float]:
    latent = compute_whole_map_latent_gap(
        manual_xodr=str(manual_xodr),
        auto_xodr=str(auto_xodr),
        checkpoint=str(checkpoint),
    )
    if not bool(latent.get("enabled")):
        raise RuntimeError(f"Latent gap inference failed: {latent}")
    metrics = latent.get("metrics", {})
    return {
        "cosine_similarity": float(metrics.get("cosine_similarity", 0.0)),
        "l2": float(metrics.get("l2", 0.0)),
    }


def _checkpoint_final_epoch_path(train_out_dir: Path, epochs: int) -> Path:
    return train_out_dir / f"map_encoder_epoch{int(epochs)}.pt"


def _manifest_sidecar(checkpoint: Path) -> Path:
    return checkpoint.with_suffix(checkpoint.suffix + ".manifest.json")


def _expected_manifest_for_subset(
    *,
    subset_dir: Path,
    subset_names: List[str],
    all_tile_hashes: Dict[str, str],
    selection_seed: int,
    training_seed: int,
    epochs: int,
    batch_size: int,
    lr: float,
    noise_std: float,
    temperature: float,
    width_mode: str,
    strict_dataset: bool,
    hidden_dim: int = 128,
    exclude_source_hashes: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Expected checkpoint identity for one (K, training_seed) run.

    The dataset manifest is built with the SAME helper the trainer uses
    (prov.build_training_dataset_manifest over the staged subset dir), so
    a matching checkpoint verifies byte-identically. ``exclude_source_hashes``
    (GAP-010) MUST be the same set passed to the trainer subprocess via
    --exclude_source_xodr, or the two sides' manifests can never match.
    """
    versions = prov.get_torch_versions()
    _, dataset_manifest_sha, _ = prov.build_training_dataset_manifest(
        subset_dir, width_mode=width_mode, strict=strict_dataset,
        exclude_source_hashes=exclude_source_hashes,
    )
    selection_sha = prov.tile_selection_hash(subset_names, all_tile_hashes)
    node_dim = _detect_node_dim(subset_dir, width_mode)
    return {
        "graph_schema_sha256": graph_schema_hash(width_mode=width_mode),
        "training_dataset_manifest_sha256": dataset_manifest_sha,
        "tile_selection_sha256": selection_sha,
        "selection_seed": int(selection_seed),
        "training_seed": int(training_seed),
        "model_config": prov.build_model_config(
            node_dim=int(node_dim), hidden_dim=int(hidden_dim)
        ),
        "training_config": prov.build_training_config(
            epochs=int(epochs),
            batch_size=int(batch_size),
            lr=float(lr),
            noise_std=float(noise_std),
            temperature=float(temperature),
            width_mode=str(width_mode),
            strict_dataset=bool(strict_dataset),
        ),
        "git_sha": prov.get_git_sha(),
        "torch_version": str(versions["torch_version"]),
        "torch_geometric_version": str(versions["torch_geometric_version"]),
    }


def _try_reuse_checkpoint(
    train_out_dir: Path,
    epochs: int,
    expected: Dict[str, Any],
    *,
    on_mismatch: str,
) -> Path | None:
    """Return a reusable checkpoint path, or None when retraining is needed.

    Reuse requires the final-epoch file AND a sidecar manifest whose
    identity fields match exactly. Legacy checkpoints without manifests
    are never silently reused (§7).
    """
    final_ckpt = _checkpoint_final_epoch_path(train_out_dir, epochs)
    if not final_ckpt.is_file():
        return None
    sidecar = _manifest_sidecar(final_ckpt)
    if not sidecar.is_file():
        msg = f"[ksweep] {final_ckpt} has no manifest sidecar (legacy); not reusing"
        print(msg)
        if on_mismatch == "fail":
            raise RuntimeError(msg + " (on_checkpoint_mismatch=fail)")
        return None
    try:
        found = json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception as exc:
        msg = f"[ksweep] unreadable manifest sidecar {sidecar}: {exc!r}"
        print(msg)
        if on_mismatch == "fail":
            raise RuntimeError(msg)
        return None
    # node_dim is data-dependent (auto-detected); compare only when the
    # stored manifest carries it AND we can compute the same value.
    ok, reasons = prov.checkpoints_compatible(expected, found)
    if reasons:
        detail = ", ".join(reasons)
        msg = (f"[ksweep] checkpoint identity mismatch for {final_ckpt} "
               f"({detail}); not reusing")
        print(msg)
        if on_mismatch == "fail":
            raise RuntimeError(msg + " (on_checkpoint_mismatch=fail)")
        return None
    print(f"[ksweep] checkpoint identity verified; reusing: {final_ckpt}")
    return final_ckpt


def _load_existing_final_losses(out_dir: Path) -> Dict[int, float]:
    csv_path = out_dir / "generalization_results.csv"
    if not csv_path.is_file():
        return {}
    results: Dict[int, float] = {}
    try:
        with csv_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                k = int(row.get("k", 0) or 0)
                if k <= 0:
                    continue
                results[k] = float(row.get("final_loss", "nan"))
    except Exception:
        return {}
    return results


def _write_outputs(
    *,
    out_dir: Path,
    results: List[Dict[str, Any]],
    per_run_rows: List[Dict[str, Any]],
    k_values: List[int],
    selection_seed: int,
    training_seeds: List[int],
    eval_pair_hashes: Dict[str, str],
    exclude_source_hashes: Optional[Sequence[str]] = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "ksweep_report.json"
    csv_path = out_dir / "generalization_results.csv"
    per_run_csv = out_dir / "ksweep_per_run_rows.csv"
    protocol_path = out_dir / "K_SWEEP_PROTOCOL.json"

    max_k = max(k_values)
    max_k_row = next(r for r in results if int(r["k"]) == int(max_k))
    convergence_k = next(
        (int(r["k"]) for r in results if float(r["cosine_similarity_mean"]) > 0.99),
        None,
    )

    report = {
        "k_values": list(k_values),
        "selection_seed": int(selection_seed),
        "training_seeds": [int(s) for s in training_seeds],
        "nested_subsets": True,
        "results": results,
        "per_run_rows": per_run_rows,
        "max_k": int(max_k),
        "max_k_cosine_similarity": float(max_k_row["cosine_similarity_mean"]),
        "convergence_k": convergence_k,
        "status": "COMPLETE",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "eval_pair_sha256": eval_pair_hashes,
        "source_sha_exclusion_contract": {
            "note": "GAP-010: hashes excluded from the training tile pool "
                    "and from every dataset manifest built for this run "
                    "(always includes manual_xodr/auto_xodr).",
            "excluded_hashes": sorted(exclude_source_hashes or []),
        },
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["k", "cosine_similarity", "l2", "final_loss"],
        )
        writer.writeheader()
        for row in results:
            writer.writerow(
                {
                    "k": int(row["k"]),
                    # Legacy-compatible columns carry per-K means.
                    "cosine_similarity": float(row["cosine_similarity_mean"]),
                    "l2": float(row["l2_mean"]),
                    "final_loss": float(row["final_loss_mean"]),
                }
            )

    if per_run_rows:
        with per_run_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=sorted(per_run_rows[0].keys()))
            writer.writeheader()
            for row in per_run_rows:
                writer.writerow({k: row.get(k, "") for k in sorted(row.keys())})

    protocol = {
        "design": "nested_subsets",
        "subset_rule": "subset(K) = P[:K] with P = deterministic permutation "
                       "of eligible tiles from selection_seed",
        "seed_separation": {
            "selection_seed": "fixes WHICH tiles per K (subset composition)",
            "training_seed": "fixes shuffling/init/noise per run",
            "torch_seed": "equals training_seed unless overridden",
        },
        "stages": {
            prov.DESCRIPTIVE_K_SWEEP: (
                "This sweep. Describes how latent metrics vary with K on the "
                "fixed manual-vs-auto whole-map pair. NOT an independent "
                "generalization claim."
            ),
            prov.MODEL_SELECTION: (
                "If any K (or checkpoint) is chosen using the whole-map "
                "manual-vs-auto pair, that decision MUST be recorded here "
                "with the selection criterion."
            ),
            prov.FINAL_EVALUATION: (
                "Requires a held-out map/pair never used for sweeps or "
                "selection. Re-using the sweep pair as the final test is "
                "leakage by design and must be labelled as such."
            ),
        },
        "evaluation_pair_reuse_warning": (
            "The manual-vs-auto whole-map pair used for per-run metrics is "
            "reused across every (K, seed). It is therefore NOT an untouched "
            "test set: K-selection on these numbers is MODEL_SELECTION on a "
            "DESCRIPTIVE sweep, and any 'best K' claim must say so."
        ),
        "eval_pair_sha256": eval_pair_hashes,
        "selection_seed": int(selection_seed),
        "training_seeds": [int(s) for s in training_seeds],
    }
    protocol_path.write_text(json.dumps(protocol, indent=2) + "\n", encoding="utf-8")

    print("")
    print("K-sweep summary (per-K means over training seeds)")
    print("k\tn\tcos_mean\tl2_mean\tfinal_loss_mean")
    for row in results:
        print(
            f"{int(row['k'])}\t"
            f"{int(row['n_seeds'])}\t"
            f"{float(row['cosine_similarity_mean']):.6f}\t"
            f"{float(row['l2_mean']):.6f}\t"
            f"{float(row['final_loss_mean']):.6f}"
        )
    print(f"\nSaved: {report_path}")
    print(f"Saved: {csv_path}")
    print(f"Saved: {per_run_csv}")
    print(f"Saved: {protocol_path}")


def _detect_node_dim(tiles_dir: Path, width_mode: str) -> int:
    first = sorted(tiles_dir.glob("*.xodr"))
    if not first:
        return int(node_feature_dim())
    g = MapGraphBuilder.build_from_xodr(str(first[0]), width_mode=width_mode)
    if g is None or getattr(g, "x", None) is None:
        return int(node_feature_dim())
    return int(g.x.shape[1])


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    tiles_dir = args.tiles_dir.expanduser()
    out_dir = args.out_dir.expanduser()
    manual_xodr = args.manual_xodr.expanduser()
    auto_xodr = args.auto_xodr.expanduser()

    _require_file(manual_xodr, "manual_xodr")
    _require_file(auto_xodr, "auto_xodr")
    k_values = sorted(int(k) for k in args.k_values)
    if k_values != sorted(set(k_values)) or any(k <= 0 for k in k_values):
        raise ValueError(f"k_values must be distinct positive ints, got {k_values}")
    training_seeds = [int(s) for s in args.training_seeds]
    selection_seed = int(args.selection_seed)

    eval_pair_hashes = {
        "manual_xodr": prov.sha256_file(manual_xodr),
        "auto_xodr": prov.sha256_file(auto_xodr),
    }

    # GAP-010 source-identity exclusion contract: the run's own eval pair
    # (manual_xodr/auto_xodr) is ALWAYS protected -- its content must never
    # silently exist inside the K-sweep training pool. --exclude_source_xodr
    # adds any further known reference maps (e.g. a distinct historical
    # manual_grid0821.xodr) to the same protected set.
    extra_protected = [Path(p).expanduser() for p in args.exclude_source_xodr]
    exclude_source_paths = [manual_xodr, auto_xodr] + extra_protected
    exclude_hashes = set(prov.exclusion_hashes_for(exclude_source_paths))
    print(
        f"[ksweep] source-SHA exclusion active: {len(exclude_hashes)} "
        f"protected hash(es) from {len(exclude_source_paths)} path(s)"
    )

    all_tiles = _list_tiles(
        tiles_dir, min_tiles=max(k_values), exclude_hashes=exclude_hashes,
    )

    # ONE deterministic permutation per selection seed; nested prefixes.
    tile_names = [p.name for p in all_tiles]
    subsets = prov.nested_subsets(tile_names, k_values, selection_seed)
    tile_by_name = {p.name: p for p in all_tiles}
    all_hashes = {p.name: prov.sha256_file(p) for p in all_tiles}

    run_root = out_dir / "ksweep_runs"
    run_root.mkdir(parents=True, exist_ok=True)
    results: List[Dict[str, Any]] = []
    per_run_rows: List[Dict[str, Any]] = []
    subset_records: Dict[int, Dict[str, Any]] = {}

    for k in k_values:
        chosen_names = subsets[int(k)]
        subset_records[int(k)] = {
            "tile_names": list(chosen_names),
            "tile_selection_sha256": prov.tile_selection_hash(chosen_names, all_hashes),
        }
        cos_vals: List[float] = []
        l2_vals: List[float] = []
        loss_vals: List[float] = []
        for tseed in training_seeds:
            temp_dir = Path(tempfile.mkdtemp(prefix=f"ksweep_k{k}_s{tseed}_"))
            try:
                for name in chosen_names:
                    shutil.copy2(tile_by_name[name], temp_dir / name)
                # Content-derived identity of this exact (K, seed) run.
                expected = _expected_manifest_for_subset(
                    subset_dir=temp_dir,
                    subset_names=chosen_names,
                    all_tile_hashes=all_hashes,
                    selection_seed=selection_seed,
                    training_seed=int(tseed),
                    epochs=int(args.epochs),
                    batch_size=int(args.batch_size),
                    lr=float(args.lr),
                    noise_std=float(args.noise_std),
                    temperature=float(args.temperature),
                    width_mode=str(args.width_mode),
                    strict_dataset=bool(args.strict_dataset),
                    exclude_source_hashes=sorted(exclude_hashes),
                )

                train_out_dir = run_root / f"k_{int(k)}" / f"seed_{int(tseed)}"
                reused = _try_reuse_checkpoint(
                    train_out_dir, int(args.epochs), expected,
                    on_mismatch=str(args.on_checkpoint_mismatch),
                )
                if reused is not None:
                    checkpoint = reused
                    # Final loss for a reused checkpoint: recompute cheaply
                    # from the stored manifest when available, else NaN
                    # (never silently invent a number).
                    sidecar = _manifest_sidecar(reused)
                    try:
                        meta = json.loads(sidecar.read_text(encoding="utf-8"))
                        final_loss = float(
                            meta.get("final_loss", float("nan"))
                        )
                    except Exception:
                        final_loss = float("nan")
                    print(f"[ksweep] K={int(k)} seed={int(tseed)} reusing {checkpoint}")
                else:
                    training = _run_training(
                        tiles_dir=temp_dir,
                        out_dir=train_out_dir,
                        seed=int(tseed),
                        epochs=int(args.epochs),
                        batch_size=int(args.batch_size),
                        lr=float(args.lr),
                        selection_seed=selection_seed,
                        width_mode=str(args.width_mode),
                        strict_dataset=bool(args.strict_dataset),
                        noise_std=float(args.noise_std),
                        temperature=float(args.temperature),
                        exclude_source_xodr=exclude_source_paths,
                    )
                    checkpoint = Path(training["checkpoint"])
                    final_loss = float(training["final_loss"])
                    # Record the observed final loss in the sidecar so a
                    # future reuse does not need stdout archaeology.
                    sidecar = _manifest_sidecar(checkpoint)
                    if sidecar.is_file():
                        try:
                            meta = json.loads(sidecar.read_text(encoding="utf-8"))
                            meta["final_loss"] = final_loss
                            sidecar.write_text(
                                json.dumps(meta, indent=2, sort_keys=True) + "\n",
                                encoding="utf-8",
                            )
                        except Exception:
                            pass
                metrics = _compute_metrics(
                    manual_xodr=manual_xodr,
                    auto_xodr=auto_xodr,
                    checkpoint=checkpoint,
                )
                cos_vals.append(float(metrics["cosine_similarity"]))
                l2_vals.append(float(metrics["l2"]))
                loss_vals.append(float(final_loss))
                per_run_rows.append(
                    {
                        "k": int(k),
                        "training_seed": int(tseed),
                        "selection_seed": int(selection_seed),
                        "cosine_similarity": float(metrics["cosine_similarity"]),
                        "l2": float(metrics["l2"]),
                        "final_loss": float(final_loss),
                        "checkpoint": str(checkpoint),
                        "tile_selection_sha256": subset_records[int(k)][
                            "tile_selection_sha256"
                        ],
                    }
                )
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

        cos_stats = prov.summarize_runs(cos_vals)
        l2_stats = prov.summarize_runs(l2_vals)
        loss_stats = prov.summarize_runs(loss_vals)
        results.append(
            {
                "k": int(k),
                "n_seeds": int(len(training_seeds)),
                "training_seeds": [int(s) for s in training_seeds],
                "selection_seed": int(selection_seed),
                "tile_selection_sha256": subset_records[int(k)][
                    "tile_selection_sha256"
                ],
                "cosine_similarity_mean": cos_stats["mean"],
                "cosine_similarity_std": cos_stats["std"],
                "cosine_similarity_median": cos_stats["median"],
                "cosine_similarity_min": cos_stats["min"],
                "cosine_similarity_max": cos_stats["max"],
                "cosine_similarity_ci95": [cos_stats["ci95_low"], cos_stats["ci95_high"]],
                "cosine_similarity_bootstrap_ci95": [
                    cos_stats["bootstrap_ci95_low"], cos_stats["bootstrap_ci95_high"]
                ],
                "l2_mean": l2_stats["mean"],
                "l2_std": l2_stats["std"],
                "l2_median": l2_stats["median"],
                "l2_min": l2_stats["min"],
                "l2_max": l2_stats["max"],
                "l2_ci95": [l2_stats["ci95_low"], l2_stats["ci95_high"]],
                "final_loss_mean": loss_stats["mean"],
                "final_loss_std": loss_stats["std"],
                "final_loss_median": loss_stats["median"],
                "final_loss_min": loss_stats["min"],
                "final_loss_max": loss_stats["max"],
            }
        )

    _write_outputs(
        out_dir=out_dir,
        results=results,
        per_run_rows=per_run_rows,
        k_values=k_values,
        selection_seed=selection_seed,
        training_seeds=training_seeds,
        eval_pair_hashes=eval_pair_hashes,
        exclude_source_hashes=sorted(exclude_hashes),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
