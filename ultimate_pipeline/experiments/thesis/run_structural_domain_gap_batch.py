#!/usr/bin/env python3
"""Batch runner for structural domain-gap experiments (manual vs auto maps).

This script shells out to `ultimate_pipeline.run_full_domain_gap` multiple times,
passing `--manual_map` and an explicit `--output_dir` for each run. It does not
change any pipeline computations; it only orchestrates repeated runs and tracks
their locations in an index CSV.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import subprocess
import sys
from pathlib import Path
import os
from typing import Any, Dict, List, Optional

from ultimate_pipeline.utils.run_provenance import collect_provenance, write_provenance


DEFAULT_OUTPUT_ROOT = "ultimate_pipeline/artifacts/experiments/domain_gap_structural"
DEFAULT_MANUAL_MAPS = "Grid0821,Grid0828"


def _load_and_validate_protocol(protocol_path: str) -> dict:
    """Load and validate a protocol file, raising on error."""
    from ultimate_pipeline.experiments.thesis.protocol import (
        load_protocol,
        validate_protocol,
    )
    protocol = load_protocol(protocol_path)
    protocol["_source_path"] = str(Path(protocol_path).resolve())
    validate_protocol(protocol)
    return protocol


def _write_protocol_snapshot_with_provenance(
    out_dir: Path,
    protocol: dict,
) -> None:
    """Write protocol snapshot and provenance to output directory."""
    from ultimate_pipeline.experiments.thesis.protocol import write_protocol_snapshot

    provenance = collect_provenance(extra={
        "run_type": "structural_domain_gap_batch",
    })
    write_protocol_snapshot(str(out_dir), protocol, provenance)


EXPECTED_FIELDNAMES = [
    "run_id",
    "manual_map",
    "k_index",
    "start_ts",
    "end_ts",
    "return_code",
    "command",
    "output_dir",
    "stray_outputs_detected",
    "stray_outputs",
]


def parse_manual_maps(raw: str) -> List[str]:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise ValueError("manual_maps must include at least one entry")
    return parts


def _write_index_header(index_path: Path) -> None:
    with index_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EXPECTED_FIELDNAMES)
        writer.writeheader()


def ensure_index_file(index_path: Path) -> None:
    if not index_path.exists():
        _write_index_header(index_path)
        return

    existing: List[str]
    with index_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        try:
            existing = next(reader)
        except StopIteration:
            existing = []

    if existing == EXPECTED_FIELDNAMES:
        return

    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    legacy_path = index_path.with_name(f"index.legacy_{timestamp}.csv")
    index_path.rename(legacy_path)
    _write_index_header(index_path)


def build_run_id(manual_map: str, run_index: int) -> str:
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    return f"{timestamp}_{manual_map}_run{run_index + 1}"


def run_single(
    manual_map: str,
    run_index: int,
    output_root: Path,
    repo_root: Path,
) -> Dict[str, str]:
    run_id = build_run_id(manual_map, run_index)
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"

    cmd = [
        sys.executable,
        "-m",
        "ultimate_pipeline.run_full_domain_gap",
        "--manual_map",
        manual_map,
        "--output_dir",
        str(run_dir),
    ]

    started = datetime.datetime.utcnow().isoformat() + "Z"
    start_ts = datetime.datetime.utcnow().timestamp()
    env = os.environ.copy()
    env.setdefault("UP_DISABLE_CARLA", "1")
    try:
        with stdout_path.open("w", encoding="utf-8") as stdout_f, stderr_path.open("w", encoding="utf-8") as stderr_f:
            result = subprocess.run(cmd, cwd=str(repo_root), stdout=stdout_f, stderr=stderr_f, env=env)
        returncode = str(result.returncode)
    except Exception as e:
        returncode = f"exception:{e}"

    finished = datetime.datetime.utcnow().isoformat() + "Z"

    stray_outputs: List[str] = []
    default_root = repo_root / "ultimate_pipeline_out"
    if default_root.exists():
        try:
            for candidate in default_root.rglob("domain_gap"):
                if not candidate.is_dir():
                    continue
                try:
                    if candidate.stat().st_mtime >= start_ts and not str(candidate).startswith(str(run_dir)):
                        stray_outputs.append(str(candidate))
                except Exception:
                    continue
        except Exception:
            pass

    if stray_outputs:
        stray_msg = f"WARNING: stray domain-gap outputs detected under default root: {stray_outputs}"
        try:
            with (run_dir / "stray_outputs.log").open("w", encoding="utf-8") as f:
                f.write(stray_msg)
        except Exception:
            pass

    return {
        "run_id": run_id,
        "manual_map": manual_map,
        "k_index": str(run_index),
        "start_ts": started,
        "end_ts": finished,
        "return_code": returncode,
        "command": " ".join(cmd),
        "output_dir": str(run_dir),
        "stray_outputs_detected": "yes" if stray_outputs else "no",
        "stray_outputs": "|".join(stray_outputs),
    }


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Batch structural domain-gap runner.")
    ap.add_argument("--k", type=int, default=5, help="Number of runs per manual map.")
    ap.add_argument(
        "--output_root",
        default=DEFAULT_OUTPUT_ROOT,
        help="Root directory where per-run folders are created.",
    )
    ap.add_argument(
        "--manual_maps",
        default=DEFAULT_MANUAL_MAPS,
        help="Comma-separated list of manual map choices for run_full_domain_gap.",
    )
    ap.add_argument(
        "--protocol",
        default="",
        help="Path to thesis protocol YAML for snapshot + validation",
    )
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    if args.k < 1:
        raise SystemExit("--k must be >= 1")

    repo_root = Path(__file__).resolve().parents[3]
    output_root = Path(args.output_root)
    if not output_root.is_absolute():
        output_root = (repo_root / output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    # Handle protocol if provided
    if args.protocol:
        print(f"Loading thesis protocol: {args.protocol}")
        protocol = _load_and_validate_protocol(args.protocol)
        _write_protocol_snapshot_with_provenance(output_root, protocol)
        print(f"Protocol snapshot written to: {output_root}")

    manual_maps = parse_manual_maps(args.manual_maps)

    index_path = output_root / "index.csv"
    ensure_index_file(index_path)

    with index_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EXPECTED_FIELDNAMES)

        for manual_map in manual_maps:
            for run_index in range(args.k):
                row = run_single(
                    manual_map=manual_map,
                    run_index=run_index,
                    output_root=output_root,
                    repo_root=repo_root,
                )
                writer.writerow(row)
                f.flush()


if __name__ == "__main__":
    main()
