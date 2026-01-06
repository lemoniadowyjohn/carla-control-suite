#!/usr/bin/env python
"""
Robust CARLA tile QA batch runner.

Why this exists:
- On Windows, CARLA OpenDRIVE generation can trigger native crashes (e.g. 0xC0000409).
- Even when you isolate each tile in a worker subprocess, the *controller* can still die
  if it imports/uses carla in-process.
- This runner keeps the main pipeline safe by moving the entire tile QA orchestration
  into a separate process.

Behavior:
- Restarts CARLA once at the beginning (optional).
- Validates tiles by calling ultimate_pipeline.tools.tile_worker in a subprocess.
- Forces worker-safe mode (UP_NO_CARLA_AUTOSTART=1) so workers never restart CARLA.
- If a tile fails (timeout / CARLA crash / unreachable), it can restart CARLA and retry.
- Writes:
  - tile_validation_summary.json
  - tile_failure_taxonomy.json

Exit codes:
- 0: completed (even if tiles failed)
- 2: bad arguments / missing inputs
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
# ----------------------------
# CARLA-safety OpenDRIVE gate
# ----------------------------
# CARLA can hard-crash on some *valid* OpenDRIVE files (e.g., Lane::ComputeTransform).
# We run a conservative sanitizer before loading tiles to:
#   - apply known-safe fixes (e.g., clamp laneOffset on junction connector roads)
#   - otherwise classify and skip unsafe tiles (instead of killing the whole batch)
#
# If the dedicated module is not present, we fall back to a no-op gate.
try:
    from ultimate_pipeline.opendrive.carla_safety import carla_safety_sanitize_xodr  # type: ignore
except Exception:
    # Minimal built-in fallback sanitizer (keeps this script usable even if the module is missing).
    # Implements only the safest/highest-impact fix:
    #   - if road is a junction connector (junction != -1 or name starts with ':'),
    #     clamp laneOffset (a,b,c,d) to 0 when |a| is above threshold.
    def carla_safety_sanitize_xodr(xodr_path: str, out_path: str | None = None, **kwargs):
        import os
        import re
        import xml.etree.ElementTree as ET

        mode = str(kwargs.get("mode", os.getenv("CARLA_SAFETY_MODE", "auto_fix_and_warn"))).strip().lower()
        try:
            laneoffset_max = float(kwargs.get("junction_laneoffset_abs_max", os.getenv("CARLA_SAFETY_JUNCTION_LANEOFFSET_MAX", "2.0")))
        except Exception:
            laneoffset_max = 2.0

        class _Res:
            ok: bool = True
            modified: bool = False
            findings: list[dict] = []
            out_path: str = xodr_path

        # Quick NaN/Inf guard
        try:
            txt = open(xodr_path, "r", encoding="utf-8", errors="ignore").read()
            if re.search(r"\b(nan|inf|-inf)\b", txt, flags=re.IGNORECASE):
                _Res.ok = False
                _Res.findings.append({"code": "NAN_INF_DETECTED", "severity": "error", "message": "NaN/Inf tokens detected"})
                return _Res
        except Exception:
            pass

        try:
            tree = ET.parse(xodr_path)
            root = tree.getroot()
        except Exception as e:
            _Res.ok = (mode != "fail_fast")
            _Res.findings.append({"code": "XML_PARSE_FAIL", "severity": "error", "message": str(e)})
            if mode == "fail_fast":
                raise
            return _Res

        modified = False
        for road in root.findall("road"):
            junction = road.get("junction", "-1")
            name = road.get("name", "")
            is_junction = (junction is not None and junction != "-1") or (name.startswith(":") if isinstance(name, str) else False)
            if not is_junction:
                continue
            lanes = road.find("lanes")
            if lanes is None:
                continue
            for lo in lanes.findall("laneOffset"):
                try:
                    a = float(lo.get("a", "0.0"))
                except Exception:
                    a = 0.0
                if abs(a) > laneoffset_max:
                    lo.set("a", "0.00000000")
                    lo.set("b", "0.00000000")
                    lo.set("c", "0.00000000")
                    lo.set("d", "0.00000000")
                    modified = True
                    _Res.findings.append({
                        "code": "JUNCTION_LANEOFFSET_CLAMP",
                        "severity": "warn",
                        "message": f"Clamped junction laneOffset a={a:.3f} to 0.0 (max={laneoffset_max})",
                        "junction": junction,
                        "road_name": name,
                    })

        if modified:
            _Res.modified = True
            if out_path is None:
                base, ext = os.path.splitext(xodr_path)
                out_path = base + ".carla_safe" + ext
            tree.write(out_path, encoding="utf-8", xml_declaration=True)
            _Res.out_path = out_path
        return _Res


import sys

def _force_utf8_console() -> None:
    """Best-effort: avoid UnicodeEncodeError on Windows consoles/subprocess logs."""
    for s in (sys.stdout, sys.stderr):
        try:
            if hasattr(s, "reconfigure"):
                s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

_force_utf8_console()

def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")

def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")

def _tiles_from_metadata(meta: Any) -> List[str]:
    """
    Extract tile filenames from many possible tile_metadata.json formats.

    Supported patterns (best-effort):
      A) {"tiles":[{"file":"tile_0_0.xodr"}, ...]}
      B) {"tiles":["tile_0_0.xodr", ...]}
      C) [{"file":"tile_0_0.xodr"}, ...]
      D) {"tiles": {"tile_0_0.xodr": {...}, ...}}          (dict mapping)
      E) {"tile_files": [...]} / {"tile_paths": [...]}     (alt keys)
      F) {"tile_0_0.xodr": {...}, "tile_0_1.xodr": {...}}  (top-level mapping)

    Returns a list of *filenames* (not full paths).
    """
    def _norm_name(s: str) -> str:
        try:
            return Path(s).name
        except Exception:
            return s

    # Common alternate keys
    if isinstance(meta, dict):
        for k in ("tile_files", "tile_paths", "files", "paths"):
            if k in meta:
                meta = meta[k]
                break

    # If dict has "tiles" key, unwrap
    if isinstance(meta, dict) and "tiles" in meta:
        meta = meta["tiles"]

    # Case: list of strings/dicts
    if isinstance(meta, list):
        out: List[str] = []
        for t in meta:
            if isinstance(t, str):
                out.append(_norm_name(t))
            elif isinstance(t, dict):
                for k in ("file", "path", "name", "xodr", "xodr_path", "xodrFile", "filename", "tile"):
                    if k in t and isinstance(t[k], str):
                        out.append(_norm_name(t[k]))
                        break
        return out

    # Case: dict mapping tile_name -> metadata
    if isinstance(meta, dict):
        keys = list(meta.keys())
        xodr_keys = [k for k in keys if isinstance(k, str) and k.lower().endswith(".xodr")]
        if xodr_keys:
            return [_norm_name(k) for k in xodr_keys]

        # If values contain path-like fields
        out: List[str] = []
        for v in meta.values():
            if isinstance(v, dict):
                for k in ("file", "path", "name", "xodr", "xodr_path", "filename"):
                    if k in v and isinstance(v[k], str) and v[k].lower().endswith(".xodr"):
                        out.append(_norm_name(v[k]))
                        break
        if out:
            return out

    return []

def _run_tile_worker(
    python_exe: str,
    tile_xodr: Path,
    report_path: Path,
    log_path: Path,
    timeout_s: float,
    retries: int,
    fix_s: bool,
    no_spawn: bool,
) -> int:
    cmd = [
        python_exe, "-m", "ultimate_pipeline.tools.tile_worker",
        "--xodr", str(tile_xodr),
        "--report_path", str(report_path),
        "--timeout_s", str(timeout_s),
        "--retries", str(retries),
    ]
    if fix_s:
        cmd.append("--fix_s")
    if no_spawn:
        cmd.append("--no_spawn")

    env = os.environ.copy()
    env["UP_NO_CARLA_AUTOSTART"] = "1"  # critical: workers never restart CARLA

    with log_path.open("w", encoding="utf-8") as f:
        try:
            # Add a safety timeout slightly above the worker’s own timeout
            return subprocess.run(
                cmd,
                stdout=f,
                stderr=subprocess.STDOUT,
                env=env,
                timeout=timeout_s + 15.0,  # grace period
            ).returncode
        except subprocess.TimeoutExpired:
            f.write(f"\n[tile_qa_batch] worker timed out after {timeout_s} s\n")
            f.flush()
            return 124  # conventional timeout exit code


def run_tile_qa_batch(
    *,
    tiles_dir: str,
    out_dir: str,
    tile_metadata: str | None = None,
    tile_metadata_path: str | None = None,
    timeout_s: float = 300.0,
    retries: int = 2,
    max_tile_attempts: int = 2,
    restart_every_n: int = 10,
    fix_s: bool = True,
    no_spawn: bool = True,
    python_exe: str | None = None,
) -> Dict[str, Any]:
    """
    Library wrapper used by the pipeline.

    IMPORTANT: This runs the batch runner in a *subprocess* to keep the main
    pipeline process safe from CARLA / UE native crashes on Windows (e.g. 0xC0000409).

    Returns a dict with returncode + paths to summary/taxonomy/log.
    """
    out_dir_p = Path(out_dir)
    out_dir_p.mkdir(parents=True, exist_ok=True)

    # Support both the old API (tile_metadata=...) and the new one used by main_pipeline
    # (tile_metadata_path=...). Prefer tile_metadata_path if provided.
    meta = tile_metadata_path or tile_metadata
    if not meta:
        raise ValueError('run_tile_qa_batch requires tile_metadata or tile_metadata_path')

    # Ensure the subprocess can import `ultimate_pipeline` even if cwd differs.
    project_root = Path(__file__).resolve().parents[2]  # .../carla_-main
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    log_path = out_dir_p / "logs" / "tile_qa_batch.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    exe = python_exe or sys.executable
    cmd = [
        exe, "-m", "ultimate_pipeline.tools.tile_qa_batch",
        "--tile_metadata", str(meta),
        "--tiles_dir", str(tiles_dir),
        "--out_dir", str(out_dir),
        "--timeout_s", str(timeout_s),
        "--retries", str(int(retries)),
        "--max_tile_attempts", str(int(max_tile_attempts)),
        "--restart_every_n", str(int(restart_every_n)),
    ]
    if fix_s:
        cmd.append("--fix_s")
    if no_spawn:
        cmd.append("--no_spawn")

    with log_path.open("a", encoding="utf-8") as f:
        f.write("\n" + "=" * 72 + "\n")
        f.write(f"[run_tile_qa_batch] cmd: {' '.join(cmd)}\n")
        rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env=env, cwd=str(project_root)).returncode

    summary_path = out_dir_p / "tile_validation_summary.json"
    taxonomy_path = out_dir_p / "tile_failure_taxonomy.json"

    return {
        "returncode": rc,
        "log_path": str(log_path),
        "summary_path": str(summary_path) if summary_path.exists() else None,
        "taxonomy_path": str(taxonomy_path) if taxonomy_path.exists() else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tile_metadata", required=True)
    ap.add_argument("--tiles_dir", required=True)
    ap.add_argument("--out_dir", required=True)
    ap.add_argument("--timeout_s", type=float, default=300.0)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--max_tile_attempts", type=int, default=2)
    ap.add_argument("--restart_every_n", type=int, default=10)
    ap.add_argument("--fix_s", action="store_true")
    ap.add_argument("--no_spawn", action="store_true")
    args = ap.parse_args()

    tile_metadata = Path(args.tile_metadata)
    tiles_dir = Path(args.tiles_dir)
    out_dir = Path(args.out_dir)

    # ----------------------------
    # Robust path resolution (Windows-safe)
    # ----------------------------
    # main_pipeline may launch this module from a different working directory and/or pass
    # relative paths. Resolve them against likely bases to avoid false rc=2 failures.
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parents[1]  # .../ultimate_pipeline
    repo_root = script_dir.parents[2]     # .../carla_-main

    candidate_bases = [
        Path.cwd(),
        repo_root,
        project_root,
        out_dir,
        out_dir.parent,
        out_dir.parent.parent if out_dir.parent != out_dir else out_dir,
    ]

    def _resolve_existing(p: Path) -> Path:
        if p.exists():
            return p.resolve()
        if p.is_absolute():
            return p
        for b in candidate_bases:
            try:
                cand = (b / p).resolve()
            except Exception:
                continue
            if cand.exists():
                return cand
        return p

    tile_metadata = _resolve_existing(tile_metadata)
    tiles_dir = _resolve_existing(tiles_dir)

    # Common fallbacks: if this process is run inside e.g. .../tile_qa_subprocess/
    # and paths were passed relative to the parent output folder.
    if not tiles_dir.exists():
        fallback_tiles = (out_dir.parent / "tiles").resolve()
        if fallback_tiles.exists():
            tiles_dir = fallback_tiles

    if not tile_metadata.exists():
        fallback_meta = (out_dir.parent / "tile_metadata.json").resolve()
        if fallback_meta.exists():
            tile_metadata = fallback_meta

    print(f"[tile_qa_batch] resolved tile_metadata: {tile_metadata}")
    print(f"[tile_qa_batch] resolved tiles_dir:     {tiles_dir}")
    print(f"[tile_qa_batch] out_dir:                {out_dir.resolve()}")

    if not tile_metadata.exists():
        print(f"[tile_qa_batch] missing tile_metadata: {tile_metadata}")
        return 2
    if not tiles_dir.exists():
        print(f"[tile_qa_batch] missing tiles_dir: {tiles_dir}")
        return 2

    meta = _read_json(tile_metadata)
    tiles = _tiles_from_metadata(meta)

    # If metadata format is unexpected, fall back to listing tile files directly.
    if not tiles:
        print("[tile_qa_batch] no tiles found in metadata (format mismatch). Falling back to tiles_dir/*.xodr")
        try:
            tiles = sorted([p.name for p in tiles_dir.glob("*.xodr")])
            print(f"[tile_qa_batch] discovered {len(tiles)} tiles via filesystem scan")
        except Exception as e:
            print(f"[tile_qa_batch] filesystem scan failed: {e}")
            tiles = []

    if not tiles:
        print("[tile_qa_batch] still no tiles available after fallback. (Check tile_metadata.json and tiles_dir.)")
        try:
            if isinstance(meta, dict):
                print(f"[tile_qa_batch] metadata keys (sample): {list(meta.keys())[:20]}")
        except Exception:
            pass
        return 2

    reports_dir = out_dir / "tile_reports"
    logs_dir = out_dir / "logs" / "tile_workers"
    reports_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    # CARLA lifecycle utilities (kept inside this subprocess).
    try:
        from ultimate_pipeline.carla_tools.carla_recovery import restart_carla
    except Exception as e:
        restart_carla = None  # type: ignore
        print(f"[tile_qa_batch] warning: could not import carla_recovery.restart_carla: {e}")

    def _restart(tag: str) -> None:
        if restart_carla is None:
            return
        print(f"[{_now()}] [RESTART] Restarting CARLA server ({tag})...")
        try:
            restart_carla()
        except Exception as e:
            print(f"[{_now()}] [WARN] restart_carla failed: {e}")
        # Give UE a moment to become responsive after port-open.
        time.sleep(5.0)

    _restart("batch_start")

    python_exe = sys.executable

    taxonomy: List[Dict[str, Any]] = []
    passed = 0

    for i, tile_name in enumerate(tiles):
        tile_path = tiles_dir / tile_name
        if not tile_path.exists():
            taxonomy.append({
                "tile": tile_name,
                "status": "missing_tile_file",
                "tile_path": str(tile_path),
            })
            continue

        if args.restart_every_n > 0 and i > 0 and (i % args.restart_every_n) == 0:
            _restart(f"periodic_{i}")

        
        # ----------------------------
        # CARLA-safety gate (pre-load)
        # ----------------------------
        # Run once per tile (not per attempt). If the tile is unsafe for CARLA ingestion,
        # classify it and continue without crashing the whole batch.
        safety_mode = os.getenv("CARLA_SAFETY_MODE", "auto_fix_and_warn").strip().lower()
        try:
            laneoffset_max = float(os.getenv("CARLA_SAFETY_JUNCTION_LANEOFFSET_MAX", "2.0"))
        except Exception:
            laneoffset_max = 2.0

        safe_tiles_dir = out_dir / "carla_safe_tiles"
        safe_tiles_dir.mkdir(parents=True, exist_ok=True)

        safe_res = carla_safety_sanitize_xodr(
            str(tile_path),
            out_path=str(safe_tiles_dir / tile_name),
            mode=safety_mode,
            junction_laneoffset_abs_max=laneoffset_max,
        )

        if not getattr(safe_res, "ok", True):
            taxonomy.append({
                "tile": tile_name,
                "status": "carla_unsafe_xodr",
                "error": "CARLA safety gate rejected tile before simulator load",
                "tile_path": str(tile_path),
                "safety_mode": safety_mode,
                "laneoffset_max": laneoffset_max,
                "safety_findings": [
                    getattr(f, "__dict__", f) for f in (getattr(safe_res, "findings", []) or [])
                ],
            })
            continue

        tile_path_for_worker = Path(getattr(safe_res, "out_path", str(tile_path))) if getattr(safe_res, "out_path", None) else tile_path
        if not tile_path_for_worker.exists():
            tile_path_for_worker = tile_path

        report_path = reports_dir / f"{tile_path.stem}.json"
        log_path = logs_dir / f"{tile_path.stem}.log"

        status = "failed"
        error: Optional[str] = None
        rc_final: int = 999

        for attempt in range(1, max(1, args.max_tile_attempts) + 1):
            print(f"[{_now()}] [TILE] {i+1}/{len(tiles)} attempt {attempt}: {tile_name}")
            rc = _run_tile_worker(
                python_exe=python_exe,
                tile_xodr=tile_path_for_worker,
                report_path=report_path,
                log_path=log_path,
                timeout_s=args.timeout_s,
                retries=args.retries,
                fix_s=args.fix_s,
                no_spawn=args.no_spawn,
            )
            rc_final = rc

            tile_report: Dict[str, Any] = {}
            if report_path.exists():
                try:
                    tile_report = _read_json(report_path)
                except Exception:
                    tile_report = {"status": "invalid_report"}

            ok = (rc == 0) and (tile_report.get("status") == "ok")
            if ok:
                status = "passed"
                passed += 1
                break

            # classify error (best-effort)
            error = None
            if isinstance(tile_report, dict):
                carla_err = (tile_report.get("carla") or {}).get("error")
                if isinstance(carla_err, str):
                    error = carla_err
            if error is None:
                error = f"worker_rc_{rc}"

            # restart+retry on CARLA-related failure
            if attempt < args.max_tile_attempts:
                _restart(f"retry_{tile_path.stem}_attempt{attempt}")

        taxonomy.append({
            "tile": tile_name,
            "status": status,
            "error": error,
            "worker_returncode": rc_final,
            "report_path": str(report_path),
            "log_path": str(log_path),
            "carla_safety": {
                "mode": safety_mode,
                "junction_laneoffset_abs_max": laneoffset_max,
                "modified": bool(getattr(safe_res, "modified", False)),
                "out_path": str(getattr(safe_res, "out_path", "")),
                "findings": [getattr(f, "__dict__", f) for f in (getattr(safe_res, "findings", []) or [])],
            },
        })
    summary = {
        "generated_at": _now(),
        "tiles_total": len(tiles),
        "tiles_passed": passed,
        "tiles_failed": len(tiles) - passed,
        "timeout_s": args.timeout_s,
        "retries": args.retries,
        "max_tile_attempts": args.max_tile_attempts,
        "restart_every_n": args.restart_every_n,
        "reports_dir": str(reports_dir),
        "logs_dir": str(logs_dir),
    }

    _write_json(out_dir / "tile_validation_summary.json", summary)
    _write_json(out_dir / "tile_failure_taxonomy.json", taxonomy)

    print(f"[{_now()}] [SUMMARY] Tile QA summary: passed {passed}/{len(tiles)} (details in tile_failure_taxonomy.json)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
