#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Post-run thesis protocol adapter.

Generates standardized artifacts in a run directory based on existing pipeline outputs:
- determinism_fingerprint.json
- pipeline_health_summary.json
- map_content_fingerprint.json
- quarantine_stub.json (schema-valid stub unless quarantine is implemented)

Designed for tile-based outputs (prefers tiles/tile_0_0.xodr).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")


def safe_git_commit(repo_root: Path) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (commit_hash, error_reason). If not available, commit_hash=None and error_reason set.
    """
    try:
        # Avoid hanging if git isn't installed; keep it quick.
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=2,
        )
        if r.returncode == 0:
            return r.stdout.strip(), None
        return None, (r.stderr.strip() or f"git rev-parse failed with code {r.returncode}")
    except FileNotFoundError:
        return None, "git not found"
    except subprocess.TimeoutExpired:
        return None, "git command timed out"
    except Exception as e:
        return None, f"git error: {e}"


def collect_up_env() -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in os.environ.items():
        if k.startswith("UP_"):
            out[k] = v
    return dict(sorted(out.items(), key=lambda kv: kv[0]))


def find_canonical_xodr(run_dir: Path) -> Tuple[Optional[Path], str]:
    tile = run_dir / "tiles" / "tile_0_0.xodr"
    if tile.exists():
        return tile, "tiles/tile_0_0.xodr"
    xodrs = sorted(run_dir.rglob("*.xodr"), key=lambda p: p.stat().st_mtime, reverse=True)
    if xodrs:
        return xodrs[0], "newest *.xodr"
    return None, "none found"


def summarize_gate_from_debug(debug: Optional[Dict[str, Any]], key_hint: str) -> Dict[str, Any]:
    """
    Very defensive: tries to find counts/ok from arbitrary debug json.
    """
    if not debug:
        return {"ok": None, "issues": None, "source": None}

    # Common patterns
    for k in ("ok", "passed", "success"):
        if k in debug and isinstance(debug[k], bool):
            ok = debug[k]
            break
    else:
        ok = None

    issues = None
    for k in ("issues", "errors", "failures", "problems"):
        if k in debug and isinstance(debug[k], list):
            issues = len(debug[k])
            break
        if k in debug and isinstance(debug[k], int):
            issues = debug[k]
            break

    # Heuristic: if there's an obvious list of discontinuities etc.
    if issues is None:
        for k in debug.keys():
            if "discontinu" in k.lower() and isinstance(debug[k], list):
                issues = len(debug[k])
                break

    return {"ok": ok, "issues": issues, "source": key_hint}


def merge_gate_summaries(
    primary: Optional[Dict[str, Any]],
    primary_name: str,
    secondary: Optional[Dict[str, Any]],
    secondary_name: str,
) -> Dict[str, Any]:
    primary_summary = summarize_gate_from_debug(primary, primary_name) if primary else None
    secondary_summary = summarize_gate_from_debug(secondary, secondary_name) if secondary else None

    ok = None
    issues = None
    sources: List[str] = []

    if primary_summary:
        ok = primary_summary.get("ok")
        issues = primary_summary.get("issues")
        sources.append(primary_name)
    if secondary_summary:
        if ok is None:
            ok = secondary_summary.get("ok")
        if issues is None:
            issues = secondary_summary.get("issues")
        sources.append(secondary_name)

    return {"ok": ok, "issues": issues, "sources": sources or None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True, help="Path to a single ultimate_pipeline_out run directory")
    ap.add_argument("--repo-root", default=None, help="Repo root for git commit lookup (default: parent of run-dir parent)")
    ap.add_argument("--enable-quarantine-stub", action="store_true", help="Write quarantine_report.json schema-valid stub")
    args = ap.parse_args()

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.exists():
        print(f"[adapter] run-dir not found: {run_dir}", file=sys.stderr)
        return 2

    # Infer repo root if not provided: <repo>/ultimate_pipeline_out/<run>
    if args.repo_root:
        repo_root = Path(args.repo_root).resolve()
    else:
        repo_root = run_dir.parent.parent if run_dir.parent.name == "ultimate_pipeline_out" else run_dir.parent

    generated_at = utc_now_iso()

    # Inputs
    settings_path = run_dir / "settings_snapshot.json"
    manifest_path = run_dir / "run_manifest.json"
    map_stats_path = run_dir / "map_statistics.json"
    continuity_debug_path = run_dir / "continuity_debug.json"
    stability_path = run_dir / "continuity_stability.json"
    geom_debug_path = run_dir / "geometry_validator_debug.json"

    settings = read_json(settings_path) or {}
    manifest = read_json(manifest_path) or {}
    map_stats = read_json(map_stats_path) or {}
    continuity_debug = read_json(continuity_debug_path)
    stability = read_json(stability_path)
    geom_debug = read_json(geom_debug_path)

    # Canonical XODR + hashes
    xodr_path, xodr_pick_reason = find_canonical_xodr(run_dir)
    final_xodr_sha256 = None
    final_xodr_rel = None
    if xodr_path and xodr_path.exists():
        final_xodr_sha256 = sha256_file(xodr_path)
        try:
            final_xodr_rel = str(xodr_path.relative_to(run_dir))
        except Exception:
            final_xodr_rel = str(xodr_path)

    settings_sha256 = sha256_file(settings_path) if settings_path.exists() else None
    map_stats_sha256 = sha256_file(map_stats_path) if map_stats_path.exists() else None

    git_commit, git_err = safe_git_commit(repo_root)

    # determinism_fingerprint.json
    deterministic_seed = (
        settings.get("deterministic_seed")
        or settings.get("seed")
        or manifest.get("deterministic_seed")
        or manifest.get("seed")
    )
    det = {
        "generated_at_utc": generated_at,
        "git_commit": git_commit,
        "git_commit_error": git_err,
        "python_version": sys.version.replace("\n", " "),
        "os_info": {
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "env": {
            "UP_*": collect_up_env(),
        },
        "seeds": {
            "deterministic_seed": deterministic_seed,
            "python_hash_seed": os.environ.get("PYTHONHASHSEED"),
        },
        "inputs": {
            "bbox": settings.get("bbox") or settings.get("coordinates") or manifest.get("bbox"),
            "osm_source": manifest.get("osm_source"),
            "dem_path": settings.get("dem_path") or manifest.get("dem_path"),
        },
        "hashes": {
            "settings_snapshot_sha256": settings_sha256,
            "final_xodr_sha256": final_xodr_sha256,
            "map_statistics_sha256": map_stats_sha256,
        },
    }
    write_json(run_dir / "determinism_fingerprint.json", det)

    # map_content_fingerprint.json
    mcf = {
        "generated_at_utc": generated_at,
        "final_xodr_path": final_xodr_rel,
        "final_xodr_sha256": final_xodr_sha256,
        "map_statistics_sha256": map_stats_sha256,
    }
    write_json(run_dir / "map_content_fingerprint.json", mcf)

    # pipeline_health_summary.json (lightweight aggregation)
    gates = {
        "geometric_continuity": merge_gate_summaries(
            continuity_debug,
            "continuity_debug.json",
            geom_debug,
            "geometry_validator_debug.json",
        ),
        "continuity_stability": summarize_gate_from_debug(stability, "continuity_stability.json"),
        "geometry_validator": summarize_gate_from_debug(geom_debug, "geometry_validator_debug.json"),
    }

    # overall_ok: conservative. If we can't tell, keep None.
    overall_ok = None
    # If any gate explicitly says ok False -> overall False; if all explicit True -> True.
    oks = [g.get("ok") for g in gates.values() if g.get("ok") is not None]
    if oks:
        overall_ok = all(bool(x) for x in oks)

    phs = {
        "generated_at_utc": generated_at,
        "overall_ok": overall_ok,
        "run_metadata": {
            "map_name": manifest.get("map_name") or settings.get("map_name"),
            "roads": map_stats.get("roads") or map_stats.get("num_roads"),
            "junctions": map_stats.get("junctions") or map_stats.get("num_junctions"),
            "tiles": (read_json(run_dir / "tile_metadata.json") or {}).get("tiles_count"),
        },
        "gates": gates,
        "sources": {
            "files": [
                name
                for name, path in (
                    ("settings_snapshot.json", settings_path),
                    ("run_manifest.json", manifest_path),
                    ("map_statistics.json", map_stats_path),
                    ("continuity_debug.json", continuity_debug_path),
                    ("continuity_stability.json", stability_path),
                    ("geometry_validator_debug.json", geom_debug_path),
                )
                if path.exists()
            ]
        },
    }
    write_json(run_dir / "pipeline_health_summary.json", phs)

    # quarantine_stub.json (stub but schema-valid)
    q = {
        "generated_at_utc": generated_at,
        "enabled": False,
        "status": "not_implemented",
        "road_ids_quarantined": [],
        "count_removed": 0,
        "fraction_removed": 0.0,
        "thresholds": None,
        "input_xodr_sha256": final_xodr_sha256,
        "output_xodr_sha256": final_xodr_sha256,
    }
    write_json(run_dir / "quarantine_stub.json", q)

    print(f"[adapter] Wrote standardized artifacts into: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
