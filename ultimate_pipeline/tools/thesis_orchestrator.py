#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Thesis Orchestrator (CARLA-safe, end-to-end plan generator).

This is deliberately *non-destructive by default*:
- Default mode is DRY-RUN: prints the planned commands and writes documentation stubs.
- With --execute, it will run commands (pipeline/domain-gap/perception) that may
  start CARLA, spawn actors, and write large outputs.

Primary purpose:
- Provide the missing orchestration/index layer called out in ARCHITECTURE_STATUS.md
- Produce stable, thesis-citable artifacts:
  - settings snapshot (delegated to underlying tools)
  - MANIFEST.json / MANIFEST.txt (via write_manifest)
  - hashes.sha256.json (via hash_tree)
  - README_RUN.md (human-readable summary)

Dependencies:
- Uses existing repo tools: ultimate_pipeline.tools.hash_tree, write_manifest, run_pipeline, run_full_domain_gap.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ultimate_pipeline.tools.hash_tree import hash_tree
from ultimate_pipeline.tools.write_manifest import write_run_manifest


DEFAULT_BBOX = "48.74935649548228,11.422268084715878,48.77444431571603,11.47882091528412"


@dataclass
class ThesisRunPlan:
    out_dir: str
    bbox: str
    manual_xodr: Optional[str]
    execute: bool
    commands: List[List[str]]


def _run(cmd: List[str], execute: bool) -> int:
    if not execute:
        print("[thesis_orchestrator][dry-run] " + " ".join(cmd))
        return 0
    return int(subprocess.run(cmd).returncode)


def _write_text(path: Path, s: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(s, encoding="utf-8")


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def build_plan(args: argparse.Namespace) -> ThesisRunPlan:
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    cmds: List[List[str]] = []

    # 1) Run pipeline (OSM->XODR->hardening->final xodr)
    # run_pipeline currently exposes no argparse surface for bbox/out flags,
    # so emit the executable module call only.
    cmds.append([sys.executable, "-m", "ultimate_pipeline.run_pipeline"])

    # 2) Repeat conversion determinism check (thesis experiment)
    if args.osm_path:
        cmds.append([
            sys.executable, "-m", "ultimate_pipeline.experiments.thesis.exp_osm_to_xodr_determinism",
            "--osm", str(Path(args.osm_path)),
            "--out-dir", str(out_dir / "osm2xodr_determinism"),
            "--runs", str(int(args.repeat_runs)),
        ])

    # 3) Domain gap (manual vs auto) if manual_xodr provided
    if args.manual_xodr:
        cmds.append([
            sys.executable, "-m", "ultimate_pipeline.run_full_domain_gap",
            "--manual_xodr", str(Path(args.manual_xodr)),
            "--output_dir", str(out_dir / "domain_gap"),
        ])

    return ThesisRunPlan(
        out_dir=str(out_dir),
        bbox=args.bbox,
        manual_xodr=args.manual_xodr,
        execute=bool(args.execute),
        commands=cmds,
    )


def finalize_artifacts(out_dir: Path, bbox: str, note: str = "thesis_run") -> None:
    # Hash tree
    hashes = hash_tree(str(out_dir), algo="sha256")
    _write_json(out_dir / "hashes.sha256.json", hashes)

    # Manifest (best-effort required file list)
    required = [
        "run_manifest.json",
        "run_summary.json",
        "settings_snapshot.json",
        "hashes.sha256.json",
    ]
    write_run_manifest(
        run_dir=str(out_dir),
        fields={"kind": note, "bbox": bbox},
        required_files=required,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Thesis orchestrator (dry-run by default).")
    ap.add_argument("--out", required=True, help="Output directory for this thesis run")
    ap.add_argument("--bbox", default=DEFAULT_BBOX, help="OSM bbox lat_min,lon_min,lat_max,lon_max")
    ap.add_argument("--osm-path", default=None, help="Optional OSM input path for determinism experiment")
    ap.add_argument("--manual-xodr", default=None, help="Optional manual XODR to compare in domain-gap")
    ap.add_argument("--repeat-runs", type=int, default=3, help="Repeat runs for OSM->XODR determinism experiment")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="Actually execute commands (high-impact)")
    mode.add_argument("--dry-run", action="store_true", help="Explicit dry-run mode (default)")
    ap.add_argument("--emit-readme", action="store_true", help="Write README_RUN.md with plan and metadata")

    args = ap.parse_args()

    plan = build_plan(args)

    meta = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "plan": asdict(plan),
    }
    _write_json(Path(plan.out_dir) / "thesis_plan.json", meta)

    if args.emit_readme:
        _write_text(
            Path(plan.out_dir) / "README_RUN.md",
            "# Thesis Run\n\n"
            f"- created_utc: {meta['created_utc']}\n"
            f"- bbox: `{plan.bbox}`\n"
            f"- manual_xodr: `{plan.manual_xodr}`\n\n"
            "## Planned commands\n\n"
            + "\n".join([("```\n" + " ".join(c) + "\n```") for c in plan.commands])
            + "\n",
        )

    # Execute plan (or dry-run)
    for cmd in plan.commands:
        rc = _run(cmd, execute=plan.execute)
        if rc != 0:
            print(f"[thesis_orchestrator] command failed rc={rc}: {' '.join(cmd)}")
            if plan.execute:
                return rc

    # Finalize reproducibility artifacts regardless
    finalize_artifacts(Path(plan.out_dir), bbox=plan.bbox, note="thesis_run")

    print("[thesis_orchestrator] success")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
