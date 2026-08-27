#!/usr/bin/env python3
"""C19 assembly orchestrator — runs all 4 evidence-bundle steps together, in order.

Previously each step (export_thesis_tables, audit_thesis_topic_contract,
validate_thesis_claim_provenance, pack_thesis_run) was only ever run by hand,
individually. That is exactly how the committed evidence bundle went stale after the C29
pin promotion: the registry and rq_tables.json were updated, but the other 3 steps were
never re-run, so contract_audit.json / provenance_validation.json / thesis_run_bundle.json
silently kept citing pre-promotion state until caught by chance (see
reports/post_audit_hardening/FRECHET_ROW_WIRED_AND_PROVENANCE_VALIDATOR_REGRESSION_FIXED.md).

Usage:
    python tools/run_c19_assembly.py --out-dir reports/post_audit_hardening/C19_THESIS_ASSEMBLY

Fail-closed: stops at the first step that exits nonzero (in particular, step 3's honesty
gate) rather than building the remaining steps on top of a known-bad intermediate state.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent


def build_step_commands(out_dir: Path, repo_root: Path) -> List[Tuple[str, List[str]]]:
    """[(step_name, argv), ...] in the required order. Pure -- no subprocess calls."""
    py = sys.executable
    return [
        (
            "export_thesis_tables",
            [py, str(repo_root / "tools" / "export_thesis_tables.py"), "--out", str(out_dir)],
        ),
        (
            "audit_thesis_topic_contract",
            [
                py, "-m", "ultimate_pipeline.tools.audit_thesis_topic_contract",
                "--out", str(out_dir / "contract_audit.json"),
            ],
        ),
        (
            "validate_thesis_claim_provenance",
            [
                py, str(repo_root / "tools" / "validate_thesis_claim_provenance.py"),
                "--out", str(out_dir / "provenance_validation.json"),
            ],
        ),
        (
            "pack_thesis_run",
            [py, str(repo_root / "tools" / "pack_thesis_run.py"), "--out", str(out_dir)],
        ),
    ]


def run_steps(
    steps: List[Tuple[str, List[str]]],
    run_fn: Callable[[List[str]], "subprocess.CompletedProcess"],
) -> Dict[str, Any]:
    """Run `steps` in order via `run_fn`, stopping at the first nonzero return code."""
    results: List[Dict[str, Any]] = []
    for name, argv in steps:
        proc = run_fn(argv)
        results.append({"step": name, "returncode": proc.returncode})
        if proc.returncode != 0:
            return {"ok": False, "steps": results, "failed_at": name}
    return {"ok": True, "steps": results, "failed_at": None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir", type=Path,
        default=REPO_ROOT / "reports" / "post_audit_hardening" / "C19_THESIS_ASSEMBLY",
    )
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    steps = build_step_commands(args.out_dir, REPO_ROOT)

    def _run(argv: List[str]) -> "subprocess.CompletedProcess":
        print(f"[run_c19_assembly] $ {' '.join(argv)}")
        return subprocess.run(argv, cwd=str(REPO_ROOT))

    result = run_steps(steps, _run)
    if result["ok"]:
        print(f"[run_c19_assembly] all {len(result['steps'])} steps passed -> {args.out_dir}")
        return 0
    print(f"[run_c19_assembly] FAILED at step {result['failed_at']!r} -- later steps not run")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
