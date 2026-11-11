#!/usr/bin/env python3
"""Run RQ1B once and write a complete ``rq1_run_receipt/v1`` receipt.

The receipt is written only after the pipeline has produced an accepted final
XODR and acceptance payload.  Failed or incomplete runs cannot leave a new
success-shaped receipt behind.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WORKTREE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKTREE))
os.chdir(str(WORKTREE))

from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map
from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.core.terminal_authority import compute_settings_digest
from ultimate_pipeline.main_pipeline import MainPipeline
from ultimate_pipeline.tools.xodr_structural_summary import summarize_xodr
from tools.rq1_receipt_assembler import _sha256_file
from tools.rq1b_full_pipeline import (
    _extract_feature_counts,
    _extract_tileset_digest,
    _extract_topology_counts,
)

SCHEMA = "rq1_run_receipt/v1"


def _git_commit_hash(worktree: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(worktree), capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value.lower())


def _structural_geometry_signature(xodr_path: Path) -> tuple[str, dict[str, Any]]:
    """Return normalized byte identity separately from geometric structure."""
    summary = summarize_xodr(xodr_path)
    normalized_sha256 = summary.get("xodr_sha256")
    if not _is_sha256(normalized_sha256):
        raise RuntimeError("XODR structural summary did not provide a valid normalized SHA-256")
    # This key is byte identity after line-ending normalization, not geometry.
    return normalized_sha256, {key: value for key, value in summary.items() if key != "xodr_sha256"}


def _require_complete_outputs(
    pipeline: Any, returned_out_dir: str | os.PathLike[str] | None
) -> tuple[Path, Path, dict[str, Any]]:
    """Fail closed unless the pipeline supplied the outputs a receipt needs."""
    if not returned_out_dir:
        raise RuntimeError("missing required pipeline output directory")
    out_dir = Path(returned_out_dir)
    if not out_dir.is_dir():
        raise RuntimeError(f"missing required pipeline output directory: {out_dir}")

    map_acceptance = getattr(pipeline, "map_acceptance", None)
    if not isinstance(map_acceptance, dict):
        raise RuntimeError("missing required accepted map_acceptance payload")
    if map_acceptance.get("valid_for_experiments") is not True:
        raise RuntimeError("map acceptance is not valid_for_experiments")

    final_xodr_value = map_acceptance.get("final_xodr_path")
    final_xodr = Path(final_xodr_value) if isinstance(final_xodr_value, str) else None
    if final_xodr is None or not final_xodr.is_file():
        raise RuntimeError("missing required final XODR")
    if not _is_sha256(map_acceptance.get("payload_sha256")):
        raise RuntimeError("missing or invalid required map acceptance payload SHA-256")
    return out_dir, final_xodr, map_acceptance


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomically create a new receipt without replacing historical evidence."""
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing receipt: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def _receipt_digest(receipt: dict[str, Any]) -> str:
    canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run_receipt(run_index: int, base: Path) -> tuple[dict[str, Any], Path]:
    """Execute one RQ1B run and return the completed receipt and its path."""
    pinned = verify_pinned_map("auto_map_of_record")
    if pinned.get("verification_status") != "VERIFIED":
        raise RuntimeError(f"pinned map verification failed: {pinned}")

    input_xodr = Path(pinned.get("resolved_path", ""))
    if not input_xodr.is_file():
        raise FileNotFoundError(f"verified map path is not a file: {input_xodr}")
    input_sha256 = _sha256_file(input_xodr)
    pinned_sha256 = pinned.get("sha256_actual")
    if pinned_sha256 and input_sha256 != pinned_sha256:
        raise RuntimeError("pinned map SHA-256 does not match its resolved input bytes")

    out_base = base / f"run_{run_index:02d}"
    receipt_path = out_base / "rq1_run_receipt.json"
    if receipt_path.exists():
        raise FileExistsError(f"refusing to overwrite existing receipt: {receipt_path}")
    out_base.mkdir(parents=True, exist_ok=True)

    # This exact object is passed to MainPipeline and hashed below.  SETTINGS
    # does not contain the pinned input or this trial's output root.
    effective_settings = copy.copy(SETTINGS)
    effective_settings.INPUT_XODR = str(input_xodr)
    effective_settings.BASE_OUTPUT_DIR = str(out_base)
    effective_settings.QA_AUTOVIS = False

    started = time.time()
    pipeline = MainPipeline(settings=effective_settings)
    returned_out_dir = pipeline.run()
    out_dir, final_xodr, map_acceptance = _require_complete_outputs(pipeline, returned_out_dir)

    xodr_sha256 = _sha256_file(final_xodr)
    recorded_xodr_sha256 = map_acceptance.get("final_xodr_sha256")
    if recorded_xodr_sha256 and recorded_xodr_sha256 != xodr_sha256:
        raise RuntimeError("map acceptance final_xodr_sha256 does not match final XODR bytes")

    normalized_xodr_sha256, structural_signature = _structural_geometry_signature(final_xodr)
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "run": run_index,
        "mode": "B",
        "status": "ok",
        "error": "",
        "duration_s": round(time.time() - started, 1),
        "input_xodr": str(input_xodr),
        "input_sha256": input_sha256,
        "out_dir": str(out_dir),
        "xodr_sha256": xodr_sha256,
        "normalized_xodr_sha256": normalized_xodr_sha256,
        "structural_signature": structural_signature,
        "feature_counts": _extract_feature_counts(map_acceptance),
        "topology_counts": _extract_topology_counts(map_acceptance),
        "output_path": str(final_xodr),
        "tileset_digest": _extract_tileset_digest(map_acceptance),
        "map_acceptance_digest": map_acceptance["payload_sha256"],
        "final_receipt_digest": "",
        "per_stage_hashes": {},
        "per_stage_durations": {"total": round(time.time() - started, 1)},
        "per_stage_status": {"pipeline": "ok"},
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit_hash(WORKTREE),
        "settings_hash": compute_settings_digest(effective_settings),
        "map_acceptance": map_acceptance,
    }
    if not _is_sha256(receipt["settings_hash"]):
        raise RuntimeError("effective settings digest was not produced")
    receipt["final_receipt_digest"] = _receipt_digest(receipt)
    _atomic_write_json(receipt_path, receipt)
    return receipt, receipt_path


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_index", type=int, help="Non-negative RQ1 run index")
    parser.add_argument("output_base_dir", nargs="?", type=Path, default=Path("reports/rq1_trial_runs"))
    args = parser.parse_args(argv)
    if args.run_index < 0:
        parser.error("run_index must be non-negative")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        receipt, receipt_path = run_receipt(args.run_index, args.output_base_dir)
    except Exception as exc:
        print(
            json.dumps({"run": args.run_index, "status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True),
            file=sys.stderr,
        )
        return 2

    print(
        json.dumps(
            {
                "run": receipt["run"],
                "status": receipt["status"],
                "input_sha256": receipt["input_sha256"],
                "xodr_sha256": receipt["xodr_sha256"],
                "normalized_xodr_sha256": receipt["normalized_xodr_sha256"],
                "receipt_path": str(receipt_path),
                "receipt_sha256": receipt["final_receipt_digest"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
