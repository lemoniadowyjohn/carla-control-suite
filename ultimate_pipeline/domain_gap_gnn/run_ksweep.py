#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

from .latent_gap_runner import compute_whole_map_latent_gap


K_VALUES: List[int] = [10, 20, 30, 40, 50, 60, 72]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run K-sweep GNN training over sampled tile subsets."
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
    return parser.parse_args(list(argv))


def _require_file(path: Path, name: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{name} not found: {path}")


def _list_tiles(tiles_dir: Path) -> List[Path]:
    if not tiles_dir.is_dir():
        raise FileNotFoundError(f"tiles_dir not found: {tiles_dir}")
    tiles = sorted(p for p in tiles_dir.glob("*.xodr") if p.is_file())
    if not tiles:
        raise RuntimeError(f"No .xodr tiles found in: {tiles_dir}")
    if len(tiles) < max(K_VALUES):
        raise RuntimeError(
            f"Need at least {max(K_VALUES)} tiles for K-sweep, found {len(tiles)}"
        )
    return tiles


def _resolve_checkpoint(checkpoint_dir: Path) -> Path:
    candidates = sorted(checkpoint_dir.glob("map_encoder_epoch*.pt"))
    if not candidates:
        raise RuntimeError(f"No checkpoint generated in: {checkpoint_dir}")
    return candidates[-1]


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
    ]
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


def _checkpoint_final_epoch_path(train_out_dir: Path) -> Path:
    return train_out_dir / "map_encoder_epoch50.pt"


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
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "ksweep_report.json"
    csv_path = out_dir / "generalization_results.csv"

    max_k = max(K_VALUES)
    max_k_row = next(r for r in results if int(r["k"]) == int(max_k))
    convergence_k = next(
        (int(r["k"]) for r in results if float(r["cosine_similarity"]) > 0.99),
        None,
    )

    report = {
        "k_values": list(K_VALUES),
        "results": results,
        "max_k": int(max_k),
        "max_k_cosine_similarity": float(max_k_row["cosine_similarity"]),
        "convergence_k": convergence_k,
        "status": "COMPLETE",
        "timestamp": datetime.now(timezone.utc).isoformat(),
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
                    "cosine_similarity": float(row["cosine_similarity"]),
                    "l2": float(row["l2"]),
                    "final_loss": float(row["final_loss"]),
                }
            )

    print("")
    print("K-sweep summary")
    print("k\tcosine_similarity\tl2\tfinal_loss")
    for row in results:
        print(
            f"{int(row['k'])}\t"
            f"{float(row['cosine_similarity']):.6f}\t"
            f"{float(row['l2']):.6f}\t"
            f"{float(row['final_loss']):.6f}"
        )
    print(f"\nSaved: {report_path}")
    print(f"Saved: {csv_path}")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    tiles_dir = args.tiles_dir.expanduser()
    out_dir = args.out_dir.expanduser()
    manual_xodr = args.manual_xodr.expanduser()
    auto_xodr = args.auto_xodr.expanduser()

    _require_file(manual_xodr, "manual_xodr")
    _require_file(auto_xodr, "auto_xodr")
    all_tiles = _list_tiles(tiles_dir)
    existing_final_losses = _load_existing_final_losses(out_dir)

    run_root = out_dir / "ksweep_runs"
    run_root.mkdir(parents=True, exist_ok=True)
    results: List[Dict[str, Any]] = []

    for k in K_VALUES:
        seed = int(42 + k)
        rng = random.Random(seed)
        chosen = sorted(rng.sample(all_tiles, int(k)), key=lambda p: p.name)

        temp_dir = Path(tempfile.mkdtemp(prefix=f"ksweep_k{k}_"))
        try:
            for src in chosen:
                shutil.copy2(src, temp_dir / src.name)

            train_out_dir = run_root / f"k_{int(k)}"
            if _checkpoint_final_epoch_path(train_out_dir).is_file():
                checkpoint = _resolve_checkpoint(train_out_dir)
                training = {
                    "checkpoint": checkpoint,
                    "final_loss": float(existing_final_losses.get(int(k), float("nan"))),
                }
                print(f"[ksweep] K={int(k)} checkpoint exists; skipping retrain: {checkpoint}")
            else:
                training = _run_training(
                    tiles_dir=temp_dir,
                    out_dir=train_out_dir,
                    seed=seed,
                    epochs=int(args.epochs),
                    batch_size=int(args.batch_size),
                    lr=float(args.lr),
                )
            metrics = _compute_metrics(
                manual_xodr=manual_xodr,
                auto_xodr=auto_xodr,
                checkpoint=Path(training["checkpoint"]),
            )
            results.append(
                {
                    "k": int(k),
                    "cosine_similarity": float(metrics["cosine_similarity"]),
                    "l2": float(metrics["l2"]),
                    "final_loss": float(training["final_loss"]),
                    "seed": int(seed),
                }
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    _write_outputs(out_dir=out_dir, results=results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
