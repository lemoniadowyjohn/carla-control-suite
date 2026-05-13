#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_experiments.py — thesis-end-to-end runner (fixpack).

This restores thesis-grade batch mode:
- For each run directory:
  - locate final XODR (08_final*.xodr)
  - compute SHA256 hashes for key files
  - optionally run CARLA importability smoke load (gated)
  - optionally run perception capture (gated) and validate outputs
  - optionally compute domain gap (offline) if manual map is provided
  - optionally generate a thesis figure pack (offline)

Outputs:
- structural_summary.csv
- importability_summary.csv (if enabled)
- perception_summary.csv (if enabled)
- domain_gap_summary.csv (if enabled)
- batch_index.json (full metadata)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _sha256_file(path: Path) -> str:
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


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str), encoding="utf-8")


def _write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def _expand_runs(tokens: Sequence[str]) -> List[Path]:
    runs: List[Path] = []
    for t in tokens:
        if any(ch in t for ch in ("*", "?")):
            runs.extend([Path(p) for p in sorted(Path(".").glob(t))])
        else:
            runs.append(Path(t))
    return runs


def _pick_final_xodr(run_dir: Path) -> Optional[Path]:
    cands = sorted(run_dir.glob("08_final*.xodr"))
    if cands:
        return cands[-1]
    # fallback: any xodr
    cands = sorted(run_dir.glob("*.xodr"))
    return cands[-1] if cands else None


def _stats_roads_count(stats: Dict[str, Any]) -> Any:
    # supports multiple schemas
    if "roads" in stats and isinstance(stats["roads"], dict) and "count" in stats["roads"]:
        return stats["roads"]["count"]
    if "total_roads" in stats:
        return stats["total_roads"]
    return ""


def _read_map_statistics(path: Path) -> Dict[str, Any]:
    """Read map statistics from JSON (helper for tests)."""
    if path.is_dir():
        path = path / "map_statistics.json"
    return _read_json(path)


def _run(cmd: List[str], dry_run: bool) -> Tuple[int, str]:
    if dry_run:
        return 0, "[dry-run] " + " ".join(cmd)
    cp = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (cp.stdout or "") + "\n" + (cp.stderr or "")
    return int(cp.returncode), out[-4000:]


def _carla_preflight_guard(out_dir: Path, host: str, port: int) -> Dict[str, Any]:
    from ultimate_pipeline.tools.carla_preflight import run_preflight
    out_dir.mkdir(parents=True, exist_ok=True)
    if os.getenv("UP_DISABLE_CARLA", "").strip().lower() in ("1", "true", "yes", "on"):
        return {"ok": False, "tick_ok": False, "reason": "carla_disabled_env"}
    autostart = os.getenv("UP_CARLA_AUTOSTART", "").strip().lower() in ("1", "true", "yes", "on")
    force_restart = os.getenv("UP_CARLA_FORCE_RESTART", "").strip().lower() in ("1", "true", "yes", "on")
    return run_preflight(
        host=host,
        port=int(port),
        out_dir=str(out_dir),
        autostart=autostart,
        force_restart=force_restart,
    )


def _carla_smoke_importability(xodr: Path, out_dir: Path, host: str, port: int, timeout_s: int, dry_run: bool) -> Dict[str, Any]:
    # Uses the existing smoke suite tool used by main_pipeline. Gated: only runs when enabled.
    smoke_out = out_dir / "carla_importability"
    smoke_out.mkdir(parents=True, exist_ok=True)
    preflight = _carla_preflight_guard(smoke_out, host=str(host), port=int(port))
    if not preflight.get("ok"):
        return {"ok": False, "returncode": None, "stdout_tail": "", "out_dir": str(smoke_out), "reason": "carla_not_ready", "carla_reachability": preflight}
    cmd = [
        sys.executable, "-m", "ultimate_pipeline.tools.carla_smoke_suite",
        "--xodr", str(xodr),
        "--host", str(host),
        "--port", str(int(port)),
        "--timeout", str(float(timeout_s)),
        "--out", str(smoke_out),
    ]
    rc, tail = _run(cmd, dry_run=dry_run)
    rep = {"ok": (rc == 0), "returncode": rc, "stdout_tail": tail, "out_dir": str(smoke_out)}
    # If smoke_suite.json exists, merge it
    payload = smoke_out / "smoke_suite.json"
    if payload.exists():
        rep["payload"] = _read_json(payload)
        # Normalize ok
        if isinstance(rep["payload"], dict) and "load_ok" in rep["payload"]:
            rep["ok"] = bool(rep["payload"].get("load_ok"))
    return rep


def _run_perception_safe(xodr: Path, out_dir: Path, manual_town: str, host: str, port: int, frames: int, fps: float, rig: str,
                         calib: Optional[str], use_current_world: bool, min_frames: int, dry_run: bool) -> Dict[str, Any]:
    per_out = out_dir / "perception_safe"
    per_out.mkdir(parents=True, exist_ok=True)
    preflight = _carla_preflight_guard(per_out, host=str(host), port=int(port))
    if not preflight.get("ok"):
        return {"ok": False, "returncode": None, "stdout_tail": "", "out_dir": str(per_out), "reason": "carla_not_ready", "carla_reachability": preflight}
    cmd = [
        sys.executable, "-m", "ultimate_pipeline.tools.run_perception_safe",
        "--manual-town", manual_town,
        "--xodr-in", str(xodr),
        "--out", str(per_out),
        "--frames", str(int(frames)),
        "--fps", str(float(fps)),
        "--host", str(host),
        "--port", str(int(port)),
        "--rig", str(rig),
        "--min-frames", str(int(min_frames)),
    ]
    if calib:
        cmd += ["--calib", str(calib)]
    if use_current_world:
        cmd.append("--use-current-world")

    rc, tail = _run(cmd, dry_run=dry_run)
    rep = {"ok": (rc == 0), "returncode": rc, "stdout_tail": tail, "out_dir": str(per_out)}
    # attach metrics/status if present
    rep["carla_status"] = _read_json(per_out / "carla_status.json")
    rep["recording_summary"] = _read_json(per_out / "recording_summary.json")
    # Normalize ok using carla_status.ok when present
    if isinstance(rep["carla_status"], dict) and "ok" in rep["carla_status"]:
        rep["ok"] = bool(rep["carla_status"].get("ok"))
    return rep


def _domain_gap_offline(manual_xodr: Path, auto_xodr: Path, out_dir: Path, manual_tiles: Optional[Path], auto_tiles: Optional[Path],
                        perception_manual_json: Optional[Path], perception_auto_json: Optional[Path]) -> Dict[str, Any]:
    # Uses the in-repo function used by main_pipeline: avoids CLI uncertainty.
    from ultimate_pipeline.run_full_domain_gap import run_full_domain_gap
    out_dir.mkdir(parents=True, exist_ok=True)
    result = run_full_domain_gap(
        manual_xodr=str(manual_xodr),
        auto_xodr=str(auto_xodr),
        manual_tiles=str(manual_tiles) if manual_tiles else "",
        auto_tiles=str(auto_tiles) if auto_tiles else "",
        perception_manual_json=str(perception_manual_json) if perception_manual_json else None,
        perception_auto_json=str(perception_auto_json) if perception_auto_json else None,
        output_dir=str(out_dir),
    )
    # result is expected dict-like
    return result if isinstance(result, dict) else {"status": "unknown_result_type"}


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    # ARM: keep as a thin wrapper
    arm = sub.add_parser("arm", help="Run a single perception capture on a given XODR or cooked town")
    arm.add_argument("--manual-town", required=True)
    src = arm.add_mutually_exclusive_group(required=True)
    src.add_argument("--xodr", type=Path)
    src.add_argument("--town")
    arm.add_argument("--use-current-world", action="store_true")
    arm.add_argument("--out", required=True, type=Path)
    arm.add_argument("--frames", type=int, default=200)
    arm.add_argument("--fps", type=float, default=10.0)
    arm.add_argument("--host", default=os.getenv("UP_CARLA_HOST", "127.0.0.1"))
    arm.add_argument("--port", type=int, default=int(os.getenv("UP_CARLA_PORT", "2000")))
    arm.add_argument("--rig", choices=["dominik", "thesis"], default="thesis")
    arm.add_argument("--calib", type=Path, default=None)
    arm.add_argument("--dry-run", action="store_true")

    # BATCH: thesis-grade
    batch = sub.add_parser("batch", help="Batch experiments over many run directories (thesis-grade)")
    batch.add_argument("--auto-runs", nargs="+", required=True, help="List/globs of run directories")
    batch.add_argument("--out", required=True, type=Path, help="Output directory for summaries")
    batch.add_argument("--dry-run", action="store_true")
    batch.add_argument("--host", default=os.getenv("UP_CARLA_HOST", "127.0.0.1"))
    batch.add_argument("--port", type=int, default=int(os.getenv("UP_CARLA_PORT", "2000")))
    batch.add_argument(
        "--manual-town",
        default=os.getenv("UP_MANUAL_TOWN", "Grid0828"),
        help="Manual town label forwarded to run_perception_safe (e.g., Grid0828, Grid0821).",
    )
    batch.add_argument(
        "--use-current-world",
        action="store_true",
        help="Forward --use-current-world to run_perception_safe in batch perception runs.",
    )
    batch.add_argument("--frames", type=int, default=200)
    batch.add_argument("--fps", type=float, default=10.0)
    batch.add_argument("--rig", choices=["dominik", "thesis"], default="thesis")
    batch.add_argument("--calib", default=None, help="Optional calib_data.json path for perception")
    batch.add_argument("--min-rgb-frames", type=int, default=1)
    batch.add_argument("--min-lidar-frames", type=int, default=0)
    batch.add_argument("--require-lidar", action="store_true")

    # Gates
    batch.add_argument("--run-importability", action="store_true", help="Run CARLA smoke importability per run")
    batch.add_argument("--importability-timeout-s", type=int, default=180)
    batch.add_argument("--run-perception", action="store_true", help="Run run_perception_safe per run")
    batch.add_argument("--run-domain-gap", action="store_true", help="Run offline domain gap per run (requires --manual-xodr)")
    batch.add_argument("--manual-xodr", type=Path, default=None)
    batch.add_argument("--manual-tiles", type=Path, default=None)
    batch.add_argument("--auto-tiles-subdir", default="tiles", help="Where to find auto tiles inside each run dir")
    batch.add_argument("--perception-manual-json", type=Path, default=None)
    batch.add_argument("--make-figures", action="store_true", help="Generate figure pack per run (offline)")

    args = ap.parse_args()

    if args.cmd == "arm":
        out_dir = Path(args.out).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, "-m", "ultimate_pipeline.tools.run_perception_safe",
               "--manual-town", args.manual_town,
               "--out", str(out_dir),
               "--frames", str(int(args.frames)),
               "--fps", str(float(args.fps)),
               "--host", str(args.host),
               "--port", str(int(args.port)),
               "--rig", str(args.rig)]
        if args.town:
            cmd += ["--town", str(args.town)]
            if args.use_current_world:
                cmd.append("--use-current-world")
        else:
            cmd += ["--xodr-in", str(Path(args.xodr).resolve())]
        if args.calib:
            cmd += ["--calib", str(Path(args.calib).resolve())]
        if args.dry_run:
            print("[dry-run] " + " ".join(cmd))
            return 0
        return int(subprocess.run(cmd).returncode)

    # batch
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    runs = _expand_runs(args.auto_runs)

    created_utc = datetime.now(timezone.utc).isoformat()
    batch_index: Dict[str, Any] = {"created_utc": created_utc, "runs": []}

    structural_rows: List[Dict[str, Any]] = []
    import_rows: List[Dict[str, Any]] = []
    perception_rows: List[Dict[str, Any]] = []
    domain_rows: List[Dict[str, Any]] = []

    for run_dir in runs:
        run_dir = run_dir.resolve()
        row_base: Dict[str, Any] = {"run_dir": str(run_dir), "run_name": run_dir.name}

        xodr = _pick_final_xodr(run_dir)
        row_base["final_xodr"] = str(xodr) if xodr else ""
        if xodr and xodr.exists():
            row_base["final_xodr_sha256"] = _sha256_file(xodr)
        else:
            row_base["final_xodr_sha256"] = ""

        settings_snap = run_dir / "settings_snapshot.json"
        row_base["settings_snapshot_sha256"] = _sha256_file(settings_snap) if settings_snap.exists() else ""

        stats = _read_json(run_dir / "map_statistics.json")
        row_base["roads_count"] = _stats_roads_count(stats)
        structural_rows.append(dict(row_base))

        run_out_dir = out_dir / "runs" / run_dir.name
        run_out_dir.mkdir(parents=True, exist_ok=True)

        import_rep = None
        if args.run_importability and xodr:
            import_rep = _carla_smoke_importability(
                xodr=xodr,
                out_dir=run_out_dir,
                host=str(args.host),
                port=int(args.port),
                timeout_s=int(args.importability_timeout_s),
                dry_run=bool(args.dry_run),
            )
            import_rows.append({
                **row_base,
                "import_ok": bool(import_rep.get("ok")),
                "import_returncode": import_rep.get("returncode", ""),
                "import_out_dir": import_rep.get("out_dir", ""),
            })
            _write_json(run_out_dir / "importability.json", import_rep)

        per_rep = None
        if args.run_perception and xodr:
            lock_path = run_dir / "perception.lock"
            try:
                lock_path.write_text(json.dumps({"pid": os.getpid(), "timestamp": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
            except Exception:
                pass
            try:
                per_rep = _run_perception_safe(
                    xodr=xodr,
                    out_dir=run_out_dir,
                    manual_town=str(args.manual_town),
                    host=str(args.host),
                    port=int(args.port),
                    frames=int(args.frames),
                    fps=float(args.fps),
                    rig=str(args.rig),
                    calib=str(args.calib) if args.calib else None,
                    use_current_world=bool(args.use_current_world),
                    min_frames=int(args.min_rgb_frames),
                    dry_run=bool(args.dry_run),
                )
            finally:
                try:
                    if lock_path.exists():
                        lock_path.unlink()
                except Exception:
                    pass
            # Extract frame counts for min-frame validation
            metrics = per_rep.get("recording_summary", {}) or {}
            rgb_frames = metrics.get("frames_recorded", 0)
            lidar_frames = metrics.get("lidar_frames", 0)

            # Validate minimum frames: reject 0-frame "success" as FAIL
            min_rgb = int(args.min_rgb_frames)
            min_lidar = int(args.min_lidar_frames) if args.require_lidar else 0
            frames_ok = (rgb_frames >= min_rgb) and (lidar_frames >= min_lidar)
            perception_truly_ok = bool(per_rep.get("ok")) and frames_ok

            # Override ok status if frames don't meet minimum
            if per_rep.get("ok") and not frames_ok:
                per_rep["ok"] = False
                per_rep["failure_reason"] = f"min_frames_not_met: rgb={rgb_frames}<{min_rgb} or lidar={lidar_frames}<{min_lidar}"

            perception_rows.append({
                **row_base,
                "perception_ok": perception_truly_ok,
                "perception_returncode": per_rep.get("returncode", ""),
                "perception_out_dir": per_rep.get("out_dir", ""),
                "rgb_frames": rgb_frames,
                "lidar_frames": lidar_frames,
                "min_frames_met": "yes" if frames_ok else "no",
            })
            _write_json(run_out_dir / "perception.json", per_rep)

        dg_rep = None
        if args.run_domain_gap and args.manual_xodr and xodr:
            auto_tiles = (run_dir / args.auto_tiles_subdir)
            auto_tiles = auto_tiles if auto_tiles.exists() else None
            # Discover perception metrics from the run output if generated
            auto_perc = None
            if per_rep and isinstance(per_rep.get("out_dir"), str):
                pm = Path(per_rep["out_dir"]) / "perception_metrics.json"
                if pm.exists():
                    auto_perc = pm
            dg_out = run_out_dir / "domain_gap"
            if args.dry_run:
                dg_rep = {"status": "dry_run", "manual_xodr": str(args.manual_xodr), "auto_xodr": str(xodr)}
            else:
                dg_rep = _domain_gap_offline(
                    manual_xodr=args.manual_xodr.resolve(),
                    auto_xodr=xodr.resolve(),
                    out_dir=dg_out,
                    manual_tiles=args.manual_tiles.resolve() if args.manual_tiles and args.manual_tiles.exists() else None,
                    auto_tiles=auto_tiles.resolve() if auto_tiles else None,
                    perception_manual_json=args.perception_manual_json.resolve() if args.perception_manual_json and args.perception_manual_json.exists() else None,
                    perception_auto_json=auto_perc.resolve() if auto_perc else None,
                )
            _write_json(run_out_dir / "domain_gap.json", dg_rep)
            domain_rows.append({**row_base, "domain_gap_out_dir": str(dg_out), "domain_gap_ok": (dg_out / "domain_gap_status.json").exists()})

        if args.make_figures:
            fig_cmd = [sys.executable, "-m", "ultimate_pipeline.thesis.make_figure_pack", "--run-dir", str(run_dir), "--out", str(run_out_dir / "figure_pack")]
            rc, tail = _run(fig_cmd, dry_run=bool(args.dry_run))
            _write_json(run_out_dir / "figure_pack_status.json", {"ok": rc == 0, "returncode": rc, "stdout_tail": tail})

        batch_index["runs"].append({
            **row_base,
            "importability": import_rep,
            "perception": per_rep,
            "domain_gap": {"enabled": bool(args.run_domain_gap), "out_dir": str((run_out_dir/"domain_gap")) if args.run_domain_gap else ""},
        })

    # write outputs
    _write_csv(out_dir / "structural_summary.csv", structural_rows,
               ["run_name", "run_dir", "final_xodr", "final_xodr_sha256", "settings_snapshot_sha256", "roads_count"])
    if import_rows:
        _write_csv(out_dir / "importability_summary.csv", import_rows,
                   ["run_name","run_dir","final_xodr","final_xodr_sha256","import_ok","import_returncode","import_out_dir"])
    if perception_rows:
        _write_csv(out_dir / "perception_summary.csv", perception_rows,
                   ["run_name","run_dir","final_xodr","final_xodr_sha256","perception_ok","perception_returncode","perception_out_dir","rgb_frames","lidar_frames","min_frames_met"])
    if domain_rows:
        _write_csv(out_dir / "domain_gap_summary.csv", domain_rows,
                   ["run_name","run_dir","final_xodr","final_xodr_sha256","domain_gap_ok","domain_gap_out_dir"])

    _write_json(out_dir / "batch_index.json", batch_index)
    print(f"[batch] wrote summaries to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
