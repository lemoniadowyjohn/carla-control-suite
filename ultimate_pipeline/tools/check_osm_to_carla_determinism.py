#!/usr/bin/env python3
"""
Determinism checker for OSM->OpenDRIVE->CARLA pipeline runs.

Features:
- Accept two or more run directories, or --out-root + --latest N newest runs.
- Hashes tile_metadata.json, 08_final*.xodr, and tiles/tile_*.xodr (MD5 + SHA256).
- Summarizes tile count, total XODR bytes, and regex counts of <junction>/<road>.
- Reports if runs are identical and lists the first K differing files.
- Writes determinism_report.json (ASCII-friendly).
- Exports determinism_summary.csv with thesis-ready scalar columns.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from ultimate_pipeline.utils.bootstrap import bootstrap_console

bootstrap_console()

TAG_RE_JUNCTION = re.compile(r"<junction\b")
TAG_RE_ROAD = re.compile(r"<road\b")


def _select_final_xodr(run_dir: Path) -> Tuple[Path | None, List[Path]]:
    finals = sorted(run_dir.glob("08_final*.xodr"), key=lambda p: p.name.lower())
    if not finals:
        return None, finals

    semantic_candidates = [fx for fx in finals if "semantic" in fx.name.lower()]
    if semantic_candidates:
        return semantic_candidates[0], finals

    # If the semantic copy is missing (e.g. that copy step failed) but the
    # laneSection-successor repair still produced its output, prefer that
    # over the plain pre-repair file -- same "AUTHORITATIVE MAP SWITCH"
    # semantics stage_08_integrity.py itself uses, and the same defect
    # class already fixed in artifact_locator.py::find_final_xodr().
    fixed_candidates = [fx for fx in finals if "lanesectionfixed" in fx.name.lower()]
    if fixed_candidates:
        return fixed_candidates[0], finals

    return finals[0], finals


def _file_hashes(path: Path) -> Tuple[str, str]:
    md5 = hashlib.md5()
    sha = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            md5.update(chunk)
            sha.update(chunk)
    return md5.hexdigest(), sha.hexdigest()


def _count_tags(path: Path) -> Tuple[int, int]:
    """Return (junction_count, road_count) using regex; tolerate decode errors."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return 0, 0
    return len(TAG_RE_JUNCTION.findall(text)), len(TAG_RE_ROAD.findall(text))


def _safe_relpath(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve())).replace("\\", "/")
    except Exception:
        return str(path)


def _extract_osm_hint(payload: Dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return ""
    direct_keys = (
        "osm_file",
        "osm_path",
        "input_osm_path",
        "source_osm",
        "source_osm_path",
        "OSM_FILE",
        "OSM_XML_PATH",
    )
    for key in direct_keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    nested = payload.get("settings")
    if isinstance(nested, dict):
        for key in direct_keys:
            value = nested.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _read_json_dict(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _resolve_source_osm_hint(run_dir: Path) -> str:
    hint_files = (
        run_dir / "run_metadata.json",
        run_dir / "settings_snapshot.json",
        run_dir / "domain_gap_settings_snapshot.json",
    )
    for p in hint_files:
        if not p.is_file():
            continue
        hint = _extract_osm_hint(_read_json_dict(p))
        if hint:
            return hint
    return ""


def _find_source_osm_file(run_dir: Path, hint: str) -> Path | None:
    candidates: List[Path] = [
        run_dir / "osm" / "extract.osm",
        run_dir / "osm" / "extract.osm.pbf",
        run_dir / "osm_extract.osm",
        run_dir / "osm_extract.osm.pbf",
        run_dir / "artifacts" / "osm_extract.osm",
        run_dir / "artifacts" / "osm_extract.osm.pbf",
    ]

    hint_path = Path(hint) if hint else None
    if hint_path:
        if hint_path.is_absolute():
            candidates.insert(0, hint_path)
        else:
            candidates.insert(0, run_dir / hint_path)

    for c in candidates:
        if c.is_file():
            return c

    osm_files = sorted(run_dir.rglob("*.osm")) + sorted(run_dir.rglob("*.osm.pbf"))
    if not osm_files:
        return None
    osm_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return osm_files[0]


def _capture_source_osm_provenance(run_dir: Path) -> Dict[str, Any]:
    hint = _resolve_source_osm_hint(run_dir)
    source_file = _find_source_osm_file(run_dir, hint=hint)
    if source_file and source_file.is_file():
        _md5, sha = _file_hashes(source_file)
        return {
            "source_osm_identity": _safe_relpath(source_file, run_dir),
            "source_osm_sha256": sha,
            "source_osm_origin": "artifact",
        }
    if hint:
        return {
            "source_osm_identity": hint,
            "source_osm_sha256": "",
            "source_osm_origin": "metadata",
        }
    return {
        "source_osm_identity": "",
        "source_osm_sha256": "",
        "source_osm_origin": "missing",
    }


def _add_file(files: Dict[str, Dict[str, object]], rel: str, path: Path) -> int:
    """Add file metadata and return size added to XODR totals (only for XODR files)."""
    if path.is_file():
        md5, sha = _file_hashes(path)
        size = path.stat().st_size
        files[rel] = {"exists": True, "size_bytes": size, "md5": md5, "sha256": sha}
        return size
    files[rel] = {"exists": False}
    return 0


def _collect_run(run_dir: Path) -> Dict[str, object]:
    run_dir = run_dir.resolve()
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    tile_meta = run_dir / "tile_metadata.json"
    chosen_final, final_xodr = _select_final_xodr(run_dir)
    tiles_dir = run_dir / "tiles"
    tile_xodr = sorted(tiles_dir.glob("tile_*.xodr"), key=lambda p: p.name.lower()) if tiles_dir.is_dir() else []

    files: Dict[str, Dict[str, object]] = {}
    xodr_bytes = 0
    junctions = 0
    roads = 0
    missing_files: List[str] = []

    if not tile_meta.is_file():
        missing_files.append("tile_metadata.json")
    _add_file(files, "tile_metadata.json", tile_meta)

    if not final_xodr:
        missing_files.append("08_final*.xodr")

    for fx in final_xodr:
        rel = fx.name
        xodr_bytes += _add_file(files, rel, fx)
        j, r = _count_tags(fx)
        junctions += j
        roads += r

    if not tile_xodr:
        missing_files.append("tiles/tile_*.xodr")

    for tx in tile_xodr:
        rel = str(Path("tiles") / tx.name)
        xodr_bytes += _add_file(files, rel, tx)
        j, r = _count_tags(tx)
        junctions += j
        roads += r

    manifest = {k: v["sha256"] for k, v in files.items() if v.get("exists")}

    summary = {
        "tile_count": len(tile_xodr),
        "final_count": len(final_xodr),
        "xodr_total_bytes": xodr_bytes,
        "junction_count": junctions,
        "road_count": roads,
    }

    osm_source = _capture_source_osm_provenance(run_dir)

    return {
        "name": run_dir.name,
        "files": files,
        "summary": summary,
        "manifest": manifest,
        "chosen_final_xodr": chosen_final.name if chosen_final else None,
        "missing_files": sorted(missing_files),
        "source_osm_identity": osm_source.get("source_osm_identity", ""),
        "source_osm_sha256": osm_source.get("source_osm_sha256", ""),
        "source_osm_origin": osm_source.get("source_osm_origin", "missing"),
    }


def _valid_run_dir(run_dir: Path) -> bool:
    if not run_dir.is_dir():
        return False
    has_meta = (run_dir / "tile_metadata.json").is_file()
    has_final = any(run_dir.glob("08_final*.xodr"))
    tiles_dir = run_dir / "tiles"
    has_tiles = tiles_dir.is_dir() and any(tiles_dir.glob("tile_*.xodr"))
    return has_meta or has_final or has_tiles


def _pick_latest_runs(out_root: Path, latest: int) -> List[Path]:
    entries: List[Tuple[float, Path]] = []
    for child in sorted(out_root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        if not _valid_run_dir(child):
            continue
        mtimes: List[float] = [child.stat().st_mtime]
        for p in [child / "tile_metadata.json", child / "tiles"]:
            if p.exists():
                mtimes.append(p.stat().st_mtime)
        for fx in sorted(child.glob("08_final*.xodr"), key=lambda p: p.name.lower()):
            mtimes.append(fx.stat().st_mtime)
        tiles_dir = child / "tiles"
        if tiles_dir.is_dir():
            for tx in sorted(tiles_dir.glob("tile_*.xodr"), key=lambda p: p.name.lower()):
                mtimes.append(tx.stat().st_mtime)
        entries.append((max(mtimes), child))
    entries.sort(key=lambda t: (t[0], t[1].name.lower()), reverse=True)
    return [p for _, p in entries[:latest]]


def _compare_manifests(baseline: Dict[str, str], other: Dict[str, str], diff_limit: int) -> Tuple[bool, List[Dict[str, object]]]:
    diff: List[Dict[str, object]] = []
    keys = sorted(set(baseline.keys()) | set(other.keys()))
    if len(keys) == 0:
        return False, [{"file": "__empty_manifest__", "reason": "no_comparable_artifacts"}]
    for rel in keys:
        a = baseline.get(rel)
        b = other.get(rel)
        if a != b:
            diff.append({"file": rel, "baseline_sha256": a, "other_sha256": b})
            if len(diff) >= diff_limit:
                break
    return len(diff) == 0, diff


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Check determinism of pipeline outputs (hashes + summary stats).")
    ap.add_argument("runs", nargs="*", type=Path, help="Run directories to compare (need at least two).")
    ap.add_argument("--out-root", type=Path, help="Root directory containing multiple runs.")
    ap.add_argument("--latest", type=int, default=0, help="If set with --out-root, take the N newest runs under that root.")
    ap.add_argument("--diff-limit", type=int, default=20, help="Max differing files to record per comparison.")
    ap.add_argument("--report", type=Path, default=Path("determinism_report.json"), help="Path to write determinism_report.json")
    ap.add_argument("--csv", type=Path, default=None, help="Path to write determinism_summary.csv (default: alongside report)")
    ap.add_argument("--include-timestamp", action="store_true", help="Include UTC timestamp in report (omit by default for determinism).")
    return ap.parse_args()


def _export_csv(
    run_infos: List[Dict[str, Any]],
    comparisons: List[Dict[str, Any]],
    all_identical: bool,
    csv_path: Path,
) -> None:
    """Export thesis-ready CSV with scalar columns."""
    fieldnames = [
        "run_id",
        "tile_count",
        "final_count",
        "xodr_total_bytes",
        "junction_count",
        "road_count",
        "chosen_final_xodr",
        "final_sha256",
        "source_osm_identity",
        "source_osm_sha256",
        "source_osm_origin",
        "identical_to_baseline",
        "conclusion",
    ]

    baseline_manifest = run_infos[0].get("manifest", {}) if run_infos else {}
    baseline_final = run_infos[0].get("chosen_final_xodr") if run_infos else None
    baseline_sha = baseline_manifest.get(baseline_final, "") if baseline_final else ""

    rows = []
    comparison_by_other = {
        str(c.get("other", "")): c for c in comparisons if isinstance(c, dict)
    }
    for i, info in enumerate(run_infos):
        summary = info.get("summary", {})
        manifest = info.get("manifest", {})
        chosen_final = info.get("chosen_final_xodr")
        final_sha = manifest.get(chosen_final, "") if chosen_final else ""
        row_conclusion = "IDENTICAL" if all_identical else "DIFFER"

        # Determine if identical to baseline
        if i == 0:
            identical_to_baseline = "baseline"
        else:
            # Find comparison for this run
            comp = comparison_by_other.get(str(info.get("name", "")))
            if comp:
                identical_to_baseline = "yes" if comp.get("identical") else "no"
                checked_files = int(comp.get("checked_files", 0) or 0)
                if checked_files == 0:
                    row_conclusion = "EMPTY"
            else:
                identical_to_baseline = "unknown"

        rows.append({
            "run_id": info.get("name", ""),
            "tile_count": summary.get("tile_count", ""),
            "final_count": summary.get("final_count", ""),
            "xodr_total_bytes": summary.get("xodr_total_bytes", ""),
            "junction_count": summary.get("junction_count", ""),
            "road_count": summary.get("road_count", ""),
            "chosen_final_xodr": chosen_final or "",
            "final_sha256": final_sha[:16] + "..." if final_sha else "",
            "source_osm_identity": info.get("source_osm_identity", ""),
            "source_osm_sha256": info.get("source_osm_sha256", ""),
            "source_osm_origin": info.get("source_osm_origin", ""),
            "identical_to_baseline": identical_to_baseline,
            "conclusion": row_conclusion,
        })

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _gather_runs(args: argparse.Namespace) -> List[Path]:
    run_dirs: List[Path] = []
    if args.runs:
        run_dirs.extend(args.runs)
    if args.out_root and args.latest:
        latest = _pick_latest_runs(args.out_root, args.latest)
        run_dirs.extend(latest)
    dedup: List[Path] = []
    seen = set()
    for r in run_dirs:
        rp = r.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        dedup.append(rp)
    return sorted(dedup, key=lambda p: p.name.lower())


def main() -> int:
    args = _parse_args()
    run_dirs = _gather_runs(args)

    if len(run_dirs) < 2:
        print("Need at least two runs. Provide run directories or --out-root with --latest N.")
        return 2

    print(f"Comparing {len(run_dirs)} runs...")
    for rd in run_dirs:
        print(f"  - {rd}")

    run_infos = [_collect_run(rd) for rd in run_dirs]

    baseline = run_infos[0]
    comparisons = []
    all_identical = True

    for info in run_infos[1:]:
        ok, diffs = _compare_manifests(baseline["manifest"], info["manifest"], args.diff_limit)
        comparisons.append(
            {
                "baseline": baseline["name"],
                "other": info["name"],
                "identical": ok,
                "differing_files": diffs,
                "diff_limit": args.diff_limit,
                "checked_files": len(set(baseline["manifest"].keys()) | set(info["manifest"].keys())),
            }
        )
        all_identical = all_identical and ok

    report = {
        "runs": [{k: v for k, v in info.items() if k != "manifest"} for info in run_infos],
        "comparisons": comparisons,
        "identical": all_identical,
        "note": "Hashes cover tile_metadata.json, 08_final*.xodr, and tiles/tile_*.xodr",
        "source_osm_provenance": {
            "identities": sorted(
                {
                    str(info.get("source_osm_identity", "")).strip()
                    for info in run_infos
                    if str(info.get("source_osm_identity", "")).strip()
                }
            ),
            "hashes": sorted(
                {
                    str(info.get("source_osm_sha256", "")).strip()
                    for info in run_infos
                    if str(info.get("source_osm_sha256", "")).strip()
                }
            ),
        },
    }
    if args.include_timestamp:
        report["generated_at"] = datetime.utcnow().isoformat() + "Z"

    report_path: Path = args.report
    if report_path.is_dir():
        report_path = report_path / "determinism_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True), encoding="utf-8")

    # Export CSV
    csv_path = args.csv
    if csv_path is None:
        csv_path = report_path.with_suffix(".csv").with_name(
            report_path.stem.replace("_report", "_summary") + ".csv"
        )
    _export_csv(run_infos, comparisons, all_identical, csv_path)

    print(f"\nReport written to {report_path}")
    print(f"CSV written to {csv_path}")
    for comp in comparisons:
        status = "IDENTICAL" if comp["identical"] else "DIFFER"
        print(f"{baseline['name']} vs {comp['other']}: {status}")
        if comp["differing_files"]:
            for entry in comp["differing_files"]:
                print(f"  * {entry['file']}")
            remaining = comp["checked_files"] - len(comp["differing_files"])
            if len(comp["differing_files"]) >= args.diff_limit and remaining > 0:
                print(f"  ... truncated at diff_limit={args.diff_limit}")

    return 0 if all_identical else 1


if __name__ == "__main__":
    raise SystemExit(main())
