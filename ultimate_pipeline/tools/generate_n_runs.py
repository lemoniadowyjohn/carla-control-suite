#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_n_runs.py - Generate N pipeline runs from identical inputs for determinism analysis.

This script:
1. Runs the main_pipeline N times with identical settings
2. Calls check_osm_to_carla_determinism.py to produce determinism_report.json
3. Exports a thesis-ready CSV with scalar columns

Usage:
    python -m ultimate_pipeline.tools.generate_n_runs --n 5 --out-root ./thesis_runs --city ingolstadt

Outputs:
    <out-root>/
        run_001/...
        run_002/...
        ...
        determinism_report.json
        determinism_summary.csv
        batch_manifest.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _sha256_file(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {}


def _first_successful_sha256(runs: List[Dict[str, Any]]) -> str:
    for r in runs:
        sha = r.get("final_xodr_sha256")
        if isinstance(sha, str) and sha.strip():
            return sha.strip()
    return ""


def _count_xodr_tags(xodr_path: Path) -> Dict[str, int]:
    """Count road/junction tags in XODR file."""
    if not xodr_path.exists():
        return {"roads": 0, "junctions": 0}
    try:
        import re
        text = xodr_path.read_text(encoding="utf-8", errors="ignore")
        return {
            "roads": len(re.findall(r"<road\b", text)),
            "junctions": len(re.findall(r"<junction\b", text)),
        }
    except Exception:
        return {"roads": 0, "junctions": 0}


def _find_final_xodr(run_dir: Path) -> Optional[Path]:
    """Find the final XODR in a run directory."""
    candidates = sorted(run_dir.glob("08_final*.xodr"))
    if candidates:
        # Prefer semantic version
        semantic = [c for c in candidates if "semantic" in c.name.lower()]
        return semantic[0] if semantic else candidates[-1]
    # Fallback: any xodr
    candidates = sorted(run_dir.glob("*.xodr"))
    return candidates[-1] if candidates else None


def _tail_text(path: Path, max_chars: int = 2000) -> str:
    try:
        if not path.exists():
            return ""
        txt = path.read_text(encoding="utf-8", errors="replace")
        return txt[-max_chars:]
    except Exception:
        return ""


def _tail_lines(path: Path, max_lines: int = 200) -> str:
    try:
        if not path.exists():
            return ""
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-max_lines:])
    except Exception:
        return ""


def _apply_profile(profile: str, extra_env: Dict[str, str]) -> None:
    prof = str(profile or "").strip().lower()
    if prof not in ("fast_offline", "full_evidence"):
        return
    if prof == "fast_offline":
        extra_env.setdefault("UP_DISABLE_CARLA", "1")
        extra_env.setdefault("UP_SKIP_STEP10_TILE_QA", "1")
        extra_env.setdefault("UP_SKIP_TILE_QA", "1")
        extra_env.setdefault("UP_SKIP_STEP10_WHEN_CARLA_DOWN", "1")
        extra_env.setdefault("UP_ENABLE_OSM2WORLD", "0")
        extra_env.setdefault("ENABLE_OSM2WORLD", "0")
        extra_env.setdefault("ENABLE_BLENDER_FBX", "0")
        extra_env.setdefault("UP_ENABLE_DOMAIN_GAP", "0")
        extra_env.setdefault("ENABLE_DOMAIN_GAP", "0")
        extra_env.setdefault("UP_ENABLE_THESIS_PERCEPTION_CAPTURE", "0")
        extra_env.setdefault("UP_ENABLE_SCENARIORUNNER", "0")
    else:
        extra_env.setdefault("UP_DISABLE_CARLA", "0")
        extra_env.setdefault("UP_ENABLE_DOMAIN_GAP", "1")
        extra_env.setdefault("ENABLE_DOMAIN_GAP", "1")
        extra_env.setdefault("UP_ENABLE_THESIS_PERCEPTION_CAPTURE", "1")
        extra_env.setdefault("UP_ENABLE_SCENARIORUNNER", "1")


def _parse_output_dir_from_log(log_path: Path) -> Optional[Path]:
    if not log_path.exists():
        return None
    try:
        txt = log_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    import re
    m = re.search(r"Output dir:\s*(?P<path>[A-Za-z]:\\[^\r\n]+)", txt)
    if not m:
        return None
    p = Path(m.group("path").strip())
    return p if p.exists() else None


def _run_pipeline_once(
    run_id: str,
    out_dir: Path,
    city: str,
    extra_env: Dict[str, str],
    timeout_s: int,
    dry_run: bool,
    profile: str,
) -> Dict[str, Any]:
    """Run main_pipeline once and return result metadata."""
    result = {
        "run_id": run_id,
        "run_dir": str(out_dir),
        "status": "pending",
        "return_code": None,
        "elapsed_s": 0.0,
        "final_xodr": None,
        "final_xodr_sha256": None,
        "error": None,
    }

    env = os.environ.copy()
    env.update(extra_env)
    env["UP_RUN_TAG"] = run_id
    env["UP_CITY"] = city
    # Force output to specific directory
    env["UP_OUTPUT_DIR"] = str(out_dir)

    cmd = [sys.executable, "-m", "ultimate_pipeline.main_pipeline"]

    if dry_run:
        result["status"] = "dry_run"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "run_dir.txt").write_text(str(out_dir), encoding="utf-8")
        (out_dir / "pipeline.log").write_text("[dry-run] " + " ".join(cmd) + "\n", encoding="utf-8")
        return result

    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "pipeline.log"
    (out_dir / "run_dir.txt").write_text(str(out_dir), encoding="utf-8")

    t0 = time.monotonic()
    try:
        with log_path.open("w", encoding="utf-8", errors="replace") as lf:
            proc = subprocess.run(
                cmd,
                stdout=lf,
                stderr=subprocess.STDOUT,
                env=env,
                timeout=timeout_s,
                cwd=str(Path(__file__).resolve().parents[2]),  # repo root
            )
        result["return_code"] = proc.returncode
        result["status"] = "failed" if proc.returncode != 0 else "pending_artifact_validation"
    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
        result["error"] = f"timeout after {timeout_s}s"
        timeout_payload = {
            "status": "timeout",
            "timeout_s": int(timeout_s),
            "log_tail": _tail_lines(log_path, max_lines=200),
            "profile": profile,
            "env_snapshot": extra_env,
            "hint": "check pipeline.log tail for stuck stage",
        }
        (out_dir / "timeout.json").write_text(json.dumps(timeout_payload, indent=2), encoding="utf-8")
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    result["elapsed_s"] = round(time.monotonic() - t0, 2)
    if timeout_s > 0 and result["elapsed_s"] > (timeout_s * 2):
        result["elapsed_note"] = "system suspend / clock jump suspected"

    resolved_out = _parse_output_dir_from_log(log_path)
    if resolved_out:
        (out_dir / "run_dir.txt").write_text(str(resolved_out), encoding="utf-8")

    # Find final XODR
    final_xodr = _find_final_xodr(out_dir)
    has_valid_final_xodr = False
    if final_xodr and final_xodr.is_file():
        result["final_xodr"] = str(final_xodr)
        has_valid_final_xodr = final_xodr.stat().st_size > 0
        if has_valid_final_xodr:
            result["final_xodr_sha256"] = _sha256_file(final_xodr)
            tags = _count_xodr_tags(final_xodr)
            result["roads_count"] = tags["roads"]
            result["junctions_count"] = tags["junctions"]

    # Count tiles
    tiles_dir = out_dir / "tiles"
    if tiles_dir.is_dir():
        result["tile_count"] = len(list(tiles_dir.glob("tile_*.xodr")))
    else:
        result["tile_count"] = 0

    if result.get("return_code") == 0:
        if has_valid_final_xodr:
            result["status"] = "ok"
        else:
            result["status"] = "incomplete"
            if not result.get("error"):
                result["error"] = "return_code=0 but no valid final XODR produced"

    return result


def _run_determinism_check(
    run_dirs: List[Path],
    report_path: Path,
) -> Dict[str, Any]:
    """Run check_osm_to_carla_determinism.py and return result."""
    cmd = [
        sys.executable, "-m", "ultimate_pipeline.tools.check_osm_to_carla_determinism",
        *[str(rd) for rd in run_dirs],
        "--report", str(report_path),
        "--include-timestamp",
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        return {
            "ok": proc.returncode == 0,
            "return_code": proc.returncode,
            "report_path": str(report_path),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _export_csv(
    runs: List[Dict[str, Any]],
    determinism_report: Dict[str, Any],
    csv_path: Path,
) -> None:
    """Export thesis-ready CSV with scalar columns."""
    # Determine identical/differ/skip conclusion
    status = str(determinism_report.get("status", "")).upper()
    skip_mode = status == "SKIP"
    all_identical = determinism_report.get("identical", False)

    fieldnames = [
        "run_id",
        "status",
        "return_code",
        "elapsed_s",
        "final_xodr_sha256",
        "roads_count",
        "junctions_count",
        "tile_count",
        "identical_to_baseline",
        "conclusion",
    ]

    baseline_sha = _first_successful_sha256(runs)

    rows = []
    for i, run in enumerate(runs):
        sha = run.get("final_xodr_sha256", "")
        identical_to_baseline = (sha == baseline_sha) if (sha and baseline_sha) else None

        if skip_mode:
            conclusion = "SKIP"
        else:
            conclusion = "IDENTICAL" if all_identical else "DIFFER"

        rows.append({
            "run_id": run.get("run_id", ""),
            "status": run.get("status", ""),
            "return_code": run.get("return_code", ""),
            "elapsed_s": run.get("elapsed_s", ""),
            "final_xodr_sha256": sha[:16] + "..." if sha else "",  # Truncate for readability
            "roads_count": run.get("roads_count", ""),
            "junctions_count": run.get("junctions_count", ""),
            "tile_count": run.get("tile_count", ""),
            "identical_to_baseline": "yes" if identical_to_baseline else ("no" if identical_to_baseline is False else ""),
            "conclusion": conclusion,
        })

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate N pipeline runs for determinism analysis")
    ap.add_argument("--n", type=int, default=3, help="Number of runs to generate")
    ap.add_argument("--out-root", type=Path, required=True, help="Root directory for all runs")
    ap.add_argument("--city", default=os.getenv("UP_CITY", "ingolstadt"))
    ap.add_argument("--timeout", type=int, default=3600, help="Timeout per run in seconds")
    ap.add_argument("--timeout-s", dest="timeout", type=int, default=None, help="Timeout per run in seconds")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-pipeline", action="store_true", help="Skip pipeline runs, only do determinism check on existing runs")
    ap.add_argument("--env", nargs="*", default=[], help="Extra env vars as KEY=VALUE")
    ap.add_argument("--profile", choices=["fast_offline", "full_evidence"], default="fast_offline")
    args = ap.parse_args()
    if args.timeout is None:
        args.timeout = 3600

    out_root = args.out_root.resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    # Parse extra env vars
    extra_env: Dict[str, str] = {}
    for kv in args.env:
        if "=" in kv:
            k, v = kv.split("=", 1)
            extra_env[k] = v
    _apply_profile(args.profile, extra_env)

    # Add thesis bbox from environment if set
    for bbox_var in ["UP_LAT_MIN", "UP_LON_MIN", "UP_LAT_MAX", "UP_LON_MAX"]:
        if bbox_var in os.environ and bbox_var not in extra_env:
            extra_env[bbox_var] = os.environ[bbox_var]

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    runs: List[Dict[str, Any]] = []

    # Generate N runs
    if not args.skip_pipeline:
        print(f"Generating {args.n} runs under {out_root}...")
        for i in range(1, args.n + 1):
            run_id = f"run_{i:03d}_{timestamp}"
            run_dir = out_root / f"run_{i:03d}"
            print(f"\n[{i}/{args.n}] {run_id}")

            result = _run_pipeline_once(
                run_id=run_id,
                out_dir=run_dir,
                city=args.city,
                extra_env=extra_env,
                timeout_s=args.timeout,
                dry_run=args.dry_run,
                profile=args.profile,
            )
            runs.append(result)
            note = f" ({result.get('elapsed_note')})" if result.get("elapsed_note") else ""
            print(f"  -> {result['status']} (elapsed: {result['elapsed_s']}s){note}")
    else:
        # Collect existing runs
        print(f"Collecting existing runs from {out_root}...")
        for run_dir in sorted(out_root.iterdir()):
            if run_dir.is_dir() and run_dir.name.startswith("run_"):
                final_xodr = _find_final_xodr(run_dir)
                runs.append({
                    "run_id": run_dir.name,
                    "run_dir": str(run_dir),
                    "status": "existing",
                    "return_code": None,
                    "elapsed_s": 0,
                    "final_xodr": str(final_xodr) if final_xodr else None,
                    "final_xodr_sha256": _sha256_file(final_xodr) if final_xodr else None,
                    **(_count_xodr_tags(final_xodr) if final_xodr else {}),
                    "tile_count": len(list((run_dir / "tiles").glob("tile_*.xodr"))) if (run_dir / "tiles").is_dir() else 0,
                })
        print(f"  Found {len(runs)} existing runs")

    # Write batch manifest
    manifest_path = out_root / "batch_manifest.json"
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "n_runs": len(runs),
        "city": args.city,
        "extra_env": extra_env,
        "runs": runs,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(f"\nBatch manifest -> {manifest_path}")

    if len(runs) < 2:
        print("Need at least 2 runs for determinism check. Writing SKIP report.")
        report_path = out_root / "determinism_report.json"
        det_report = {
            "status": "SKIP",
            "reason": "need_at_least_2_runs",
            "n_runs": len(runs),
            "runs": [r.get("run_id") for r in runs],
        }
        report_path.write_text(json.dumps(det_report, indent=2, default=str), encoding="utf-8")
        csv_path = out_root / "determinism_summary.csv"
        _export_csv(runs, det_report, csv_path)
        return 0

    # Run determinism check
    if not args.dry_run:
        print("\nRunning determinism check...")
        run_dirs = [Path(r["run_dir"]) for r in runs if r.get("run_dir")]
        report_path = out_root / "determinism_report.json"

        det_result = _run_determinism_check(run_dirs, report_path)
        det_report = _read_json(report_path)
        if not det_result.get("ok"):
            print("  -> UNKNOWN (determinism tool failed)")
        else:
            print(f"  -> {'IDENTICAL' if det_report.get('identical') else 'DIFFER'}")

        # Load report for CSV export

        # Export CSV
        csv_path = out_root / "determinism_summary.csv"
        _export_csv(runs, det_report, csv_path)
        print(f"  CSV -> {csv_path}")

        # Print summary
        print("\n" + "=" * 60)
        print("DETERMINISM SUMMARY")
        print("=" * 60)
        n_timeouts = sum(
            1 for r in runs
            if r.get("status") in {"timeout", "failed", "error"} or not r.get("final_xodr_sha256")
        )
        n_participating = sum(1 for r in runs if r.get("final_xodr_sha256"))
        if det_report.get("identical") and n_timeouts > 0:
            print(f"Conclusion: IDENTICAL among successful runs (timeouts present: {n_timeouts})")
        else:
            conclusion = "IDENTICAL" if det_report.get("identical") else "DIFFER"
            print(f"Conclusion: {conclusion}")
        print(f"Runs compared: {len(runs)}")
        baseline_sha = _first_successful_sha256(runs)
        if baseline_sha:
            print(f"Baseline SHA256: {baseline_sha[:32]}...")
        else:
            print("Baseline SHA256: N/A (no successful final_xodr_sha256)")
        print(f"Report: {report_path}")
        print(f"CSV: {csv_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
