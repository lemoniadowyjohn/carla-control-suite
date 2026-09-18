from __future__ import annotations

import argparse
import glob
import importlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Sequence


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _count_tiles(tiles_dir: Path) -> int:
    if not tiles_dir.is_dir():
        return 0
    return len(sorted(p for p in tiles_dir.glob("*.xodr") if p.is_file()))


def _check_import(module_name: str) -> tuple[bool, str]:
    try:
        importlib.import_module(module_name)
        return True, ""
    except Exception as exc:
        return False, repr(exc)


def _parse_loss(stdout_text: str) -> float:
    matches = re.findall(r"loss\s*=\s*([0-9]+(?:\.[0-9]+)?)", stdout_text)
    if not matches:
        return -1.0
    try:
        return float(matches[-1])
    except Exception:
        return -1.0


def _parse_epochs(stdout_text: str) -> int:
    matches = re.findall(r"\[epoch\s+(\d+)\s*/\s*(\d+)\]", stdout_text)
    if not matches:
        return 0
    try:
        return int(matches[-1][0])
    except Exception:
        return 0


def _resolve_checkpoint(checkpoint_dir: Path) -> Path | None:
    candidates = sorted(glob.glob(str(checkpoint_dir / "*.pt")))
    if not candidates:
        return None
    return Path(candidates[-1])


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Train map-encoder GNN and optionally compute whole-map latent gap."
    )
    ap.add_argument("--tiles-dir", required=True, type=Path)
    ap.add_argument("--manual-xodr", default="cities/ingolstadt/manual_grid0821.xodr")
    ap.add_argument("--auto-xodr", default="cities/ingolstadt/auto_full_aligned.xodr")
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--out-dir", type=Path, default=Path("thesis_results") / "gnn_v1")
    ap.add_argument("--dry-run", action="store_true")
    return ap.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    tiles_dir = Path(args.tiles_dir).expanduser()
    out_dir = Path(args.out_dir).expanduser()
    if not out_dir.is_absolute():
        out_dir = Path.cwd() / out_dir
    checkpoints_dir = out_dir / "checkpoints"
    out_dir.mkdir(parents=True, exist_ok=True)

    torch_ok, torch_error = _check_import("torch")
    pyg_ok, pyg_error = _check_import("torch_geometric")

    timestamp = datetime.now(timezone.utc).isoformat()
    tile_count = _count_tiles(tiles_dir)
    report_path = out_dir / "gnn_training_report.json"

    if (not torch_ok) or (not pyg_ok):
        report = {
            "tiles_dir": str(tiles_dir),
            "tile_count": int(tile_count),
            "torch_available": bool(torch_ok),
            "pyg_available": bool(pyg_ok),
            "status": "DEFERRED_MISSING_PYTORCH",
            "fallback_action": "structural_gap_only",
            "timestamp": timestamp,
            "import_errors": {
                "torch": torch_error,
                "torch_geometric": pyg_error,
            },
        }
        _write_json(report_path, report)
        print("GNN TRAINING: DEFERRED (PyTorch not available)")
        return 0

    train_cmd = [
        sys.executable,
        "-m",
        "ultimate_pipeline.domain_gap_gnn.train_map_encoder",
        "--tiles_dir",
        str(tiles_dir),
        "--epochs",
        str(int(args.epochs)),
        "--batch_size",
        str(int(args.batch_size)),
        "--lr",
        str(float(args.lr)),
        "--out_dir",
        str(checkpoints_dir),
        "--seed",
        "42",
    ]

    if args.dry_run:
        report = {
            "tiles_dir": str(tiles_dir),
            "tile_count": int(tile_count),
            "epochs_completed": 0,
            "final_loss": -1.0,
            "checkpoint": "",
            "torch_available": True,
            "pyg_available": True,
            "latent_gap": {"status": "skipped", "reason": "dry_run"},
            "status": "DRY_RUN",
            "timestamp": timestamp,
            "training_command": train_cmd,
        }
        _write_json(report_path, report)
        print("CMD:", subprocess.list2cmdline(train_cmd))
        return 0

    result = subprocess.run(train_cmd, text=True, capture_output=True, check=False)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)

    epochs_completed = _parse_epochs(result.stdout or "")
    final_loss = _parse_loss(result.stdout or "")

    checkpoint_path = _resolve_checkpoint(checkpoints_dir)
    manual_xodr = Path(args.manual_xodr).expanduser()
    auto_xodr = Path(args.auto_xodr).expanduser()

    latent_gap: Dict[str, Any]
    if checkpoint_path is None:
        latent_gap = {"status": "skipped", "reason": "checkpoint_missing"}
    elif not auto_xodr.exists():
        latent_gap = {"status": "skipped", "reason": "auto_xodr_missing"}
    elif not manual_xodr.exists():
        latent_gap = {"status": "skipped", "reason": "manual_xodr_missing"}
    else:
        try:
            from ultimate_pipeline.domain_gap_gnn.latent_gap_runner import (
                compute_whole_map_latent_gap,
            )

            latent_gap = compute_whole_map_latent_gap(
                str(manual_xodr),
                str(auto_xodr),
                str(checkpoint_path),
            )
        except Exception as exc:
            latent_gap = {"status": "failed", "error": repr(exc)}

    status = "COMPLETE"
    if int(result.returncode) != 0:
        status = "PARTIAL"
    elif latent_gap.get("status") == "failed":
        status = "PARTIAL"
    elif latent_gap.get("status") == "skipped":
        status = "PARTIAL"

    report = {
        "tiles_dir": str(tiles_dir),
        "tile_count": int(tile_count),
        "epochs_completed": int(epochs_completed),
        "final_loss": float(final_loss),
        "checkpoint": str(checkpoint_path) if checkpoint_path is not None else "",
        "torch_available": True,
        "pyg_available": True,
        "latent_gap": latent_gap,
        "status": status,
        "timestamp": timestamp,
        "train_returncode": int(result.returncode),
    }
    _write_json(report_path, report)

    return 0 if int(result.returncode) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
