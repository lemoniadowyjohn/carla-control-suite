#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal thesis experiment batch runner (offline first, CARLA optional).

Additions for quick debugging:
- Writes a per-run perception log file (captured subprocess output).
- Validates perception artifacts via `recording_summary.json` (frames_recorded + status).
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from ultimate_pipeline.tools.perception_artifacts import validate_perception_output
from ultimate_pipeline.tools.artifact_locator import find_final_xodr
from ultimate_pipeline.experiments.thesis.manual_refs import resolve_manual_town, assert_manual_auto_distinct, sha256_file



def _write_json(path: Path, data: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True), encoding="utf-8")


def _expand_runs(tokens: Sequence[str]) -> List[Path]:
    runs: List[Path] = []
    for token in tokens:
        if any(ch in token for ch in ("*", "?")):
            runs.extend([Path(p) for p in sorted(Path(".").glob(token))])
        else:
            runs.append(Path(token))
    return runs


def _select_xodr(run_dir: Path, mode: str) -> Tuple[Optional[Path], str]:
    """Select the XODR artifact for a run directory.

    Modes:
      - final: prefer 08_final*.xodr (canonical)
      - tile: prefer tiles/tile_0_0.xodr, else fall back to final
      - latest: newest *.xodr by mtime (does not prefer tile unless mode=tile)
    """
    mode = (mode or "final").lower().strip()
    if mode not in ("final", "tile", "latest"):
        mode = "final"

    if mode == "tile":
        tile = run_dir / "tiles" / "tile_0_0.xodr"
        if tile.exists():
            return tile, "tile_0_0"
        x, src = find_final_xodr(run_dir)
        return x, f"final_fallback:{src}"

    if mode == "latest":
        xodrs = [p for p in run_dir.rglob("*.xodr") if p.is_file()]
        if not xodrs:
            return None, "not_found"
        xodrs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return xodrs[0], "latest_mtime"

    x, src = find_final_xodr(run_dir)
    return x, f"final:{src}"




def _read_map_statistics(run_dir: Path) -> Dict[str, object]:
    path = run_dir / "map_statistics.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_csv(path: Path, rows: List[Dict[str, object]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _run_subprocess(cmd: List[str], timeout_s: float) -> Tuple[int, str]:
    """Run a subprocess and return (returncode, combined_output_tail)."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        out = (result.stdout or "") + ("\n" if result.stdout and result.stderr else "") + (result.stderr or "")
        out = out.strip()
        # Keep tail so logs stay small even if something is noisy
        return int(result.returncode), out[-8000:]
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as exc:
        return 1, str(exc)


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Thesis batch runner (offline + optional CARLA).")
    ap.add_argument("--auto-runs", nargs="+", required=True, help="Run directories or glob patterns")
    ap.add_argument("--manual-town", required=True, help="Manual town label (e.g., Grid0828)")
    ap.add_argument("--out", required=True, type=Path, help="Output directory for aggregates")
    ap.add_argument("--xodr-mode", choices=["final","tile","latest"], default="final",
                    help="Which XODR to use from each auto run (default: final)")

    # Debug/diagnose helpers
    ap.add_argument("--log-dir", type=Path, default=None, help="Directory for per-run subprocess logs (default: <out>/logs)")
    ap.add_argument("--perception-min-frames", type=int, default=1, help="Minimum frames required for perception to count as OK")

    ap.add_argument("--carla-importability", action="store_true", help="Run CARLA importability smoke test")
    ap.add_argument("--perception-safe", action="store_true", help="Run safe perception capture")
    ap.add_argument("--strict-perception-artifacts", action="store_true", help="Forward --strict-artifacts to run_perception_safe for quick diagnose")
    ap.add_argument("--frames", type=int, default=200, help="Perception frames (default 200)")
    ap.add_argument("--fps", type=float, default=10.0, help="Perception FPS (default 10)")
    ap.add_argument("--host", default="127.0.0.1", help="CARLA host")
    ap.add_argument("--port", type=int, default=2000, help="CARLA port")
    return ap.parse_args()


def main() -> int:
    args = _parse_args()
    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir = (args.log_dir.resolve() if args.log_dir else (out_dir / "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    runs = _expand_runs(args.auto_runs)
    timestamp = datetime.now(timezone.utc).isoformat()

    structural_rows: List[Dict[str, object]] = []
    import_rows: List[Dict[str, object]] = []
    perception_rows: List[Dict[str, object]] = []

    manual_ref = resolve_manual_town(args.manual_town)
    manual_xodr_path = Path(manual_ref["manual_xodr_path"])
    if not manual_xodr_path.is_file():
        raise SystemExit(f"Manual XODR not found: {manual_xodr_path}")

    for run_dir in runs:
        run_dir = run_dir.resolve()
        row_base: Dict[str, object] = {"run_dir": str(run_dir)}

        xodr_path, xodr_source = _select_xodr(run_dir, args.xodr_mode)
        row_base["xodr_path"] = str(xodr_path) if xodr_path else ""
        row_base["xodr_source"] = xodr_source

        stats = _read_map_statistics(run_dir)
        structural_rows.append(
            {
                **row_base,
                "roads": stats.get("roads") or stats.get("num_roads"),
                "junctions": stats.get("junctions") or stats.get("num_junctions"),
                "status": "ok" if stats else "missing",
            }
        )

        # Importability smoke test (optional)
        if args.carla_importability and xodr_path:
            smoke_out = run_dir / "qa_importability"
            cmd = [
                sys.executable,
                "-m",
                "ultimate_pipeline.tools.smoke_load_xodr",
                "--xodr",
                str(xodr_path),
                "--out",
                str(smoke_out),
                "--host",
                args.host,
                "--port",
                str(args.port),
                "--no-screenshot",
            ]
            code, out = _run_subprocess(cmd, timeout_s=120.0)
            import_rows.append({**row_base, "status": "ok" if code == 0 else "fail", "error": out})
        else:
            import_rows.append({**row_base, "status": "skipped", "error": "disabled_or_missing_xodr"})

        # Perception capture (optional)
        if args.perception_safe and xodr_path:
            perc_out = run_dir / "perception_safe"
            cmd = [
                sys.executable,
                "-m",
                "ultimate_pipeline.tools.run_perception_safe",
                "--manual-town",
                manual_ref["cooked_town"],
                "--xodr-in",
                str(xodr_path),
                "--out",
                str(perc_out),
                "--frames",
                str(args.frames),
                "--fps",
                str(args.fps),
                "--host",
                args.host,
                "--port",
                str(args.port),
            ]
            if args.strict_perception_artifacts:
                cmd += ["--strict-artifacts"]
            code, out = _run_subprocess(cmd, timeout_s=180.0)

            log_path = log_dir / f"perception_{run_dir.name}.log"
            try:
                log_path.write_text(out + "\n", encoding="utf-8")
            except Exception:
                pass

            v = validate_perception_output(perc_out, min_frames=int(args.perception_min_frames))
            perception_rows.append(
                {
                    **row_base,
                    "status": "ok" if (code == 0 and v.ok) else ("skipped" if v.recording_status in ("SKIP", "SKIPPED") else "fail"),
                    "recording_status": v.recording_status,
                    "frames_recorded": v.frames_recorded,
                    "frames_requested": v.frames_requested,
                    "reason": v.reason,
                    "log": str(log_path),
                }
            )
        else:
            perception_rows.append(
                {
                    **row_base,
                    "status": "skipped",
                    "recording_status": "SKIP",
                    "frames_recorded": 0,
                    "frames_requested": 0,
                    "reason": "disabled_or_missing_xodr",
                    "log": "",
                }
            )

    _write_csv(out_dir / "structural_summary.csv", structural_rows, ["run_dir", "xodr_path", "xodr_source", "roads", "junctions", "status"])
    _write_csv(out_dir / "importability_summary.csv", import_rows, ["run_dir", "xodr_path", "xodr_source", "status", "error"])
    _write_csv(
        out_dir / "perception_summary.csv",
        perception_rows,
        ["run_dir", "xodr_path", "xodr_source", "status", "recording_status", "frames_recorded", "frames_requested", "reason", "log"],
    )
    _write_json(
        out_dir / "batch_summary.json",
        {
            "generated_at_utc": timestamp,
            "runs": [str(r) for r in runs],
            "manual_xodr": str(manual_xodr_path.resolve()),
            "structural_csv": str(out_dir / "structural_summary.csv"),
            "importability_csv": str(out_dir / "importability_summary.csv"),
            "perception_csv": str(out_dir / "perception_summary.csv"),
        },
    )
    # Add sanity row with manual/auto hashes (auto hash per run where available)
    sanity_rows = []
    for r in structural_rows:
        auto_path = Path(str(r.get("xodr_path") or ""))
        if auto_path.is_file():
            hashes = assert_manual_auto_distinct(manual_xodr_path, auto_path)
            status = "FAIL_IDENTICAL" if hashes["manual_xodr_sha256"] == hashes["auto_xodr_sha256"] else "OK"
            sanity_rows.append({
                "run_dir": r.get("run_dir"),
                "manual_xodr_sha256": hashes["manual_xodr_sha256"],
                "auto_xodr_sha256": hashes["auto_xodr_sha256"],
                "status": status,
            })
    if sanity_rows:
        _write_csv(out_dir / "sanity_hashes.csv", sanity_rows, ["run_dir", "manual_xodr_sha256", "auto_xodr_sha256", "status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
