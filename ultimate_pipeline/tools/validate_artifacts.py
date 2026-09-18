#!/usr/bin/env python3
"""
Validate presence of key artifacts for the latest auto run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from ultimate_pipeline.tools.path_utils import repo_root, resolve_latest_run, norm_path_str


def _print_table(rows: List[tuple[str, str, str]]) -> None:
    name_w = max(len("Artifact"), max((len(r[0]) for r in rows), default=0))
    status_w = max(len("Status"), max((len(r[1]) for r in rows), default=0))
    header = f"{'Artifact':<{name_w}} | {'Status':<{status_w}} | Detail"
    divider = f"{'-' * name_w}-+-{'-' * status_w}-+{'-' * max(6, 50)}"
    print(header)
    print(divider)
    for name, status, detail in rows:
        print(f"{name:<{name_w}} | {status:<{status_w}} | {detail}")


def main() -> int:
    try:
        root = repo_root()
    except Exception as e:
        print(f"FAIL: unable to locate repo root ({e})")
        return 2

    out_root = root / "ultimate_pipeline_out"
    if not out_root.is_dir():
        print(f"FAIL: output root not found: {norm_path_str(out_root)}")
        return 2

    try:
        run_dir = resolve_latest_run(out_root, skip_names=["manual_baselines"])
    except Exception as e:
        print(f"FAIL: could not find latest run under {norm_path_str(out_root)}: {e}")
        return 2

    rows: List[tuple[str, str, str]] = []
    required_ok = True

    def add(name: str, ok: bool, detail: str, required: bool) -> None:
        nonlocal required_ok
        status = "PASS" if ok else ("FAIL" if required else "MISSING")
        if required and not ok:
            required_ok = False
        rows.append((name, status, detail))

    tile_meta = run_dir / "tile_metadata.json"
    add("tile_metadata.json", tile_meta.is_file(), norm_path_str(tile_meta), True)

    tiles_dir = run_dir / "tiles"
    tiles_have_xodr = tiles_dir.is_dir() and any(tiles_dir.glob("*.xodr"))
    tiles_detail = norm_path_str(tiles_dir) if tiles_dir.exists() else f"missing: {norm_path_str(tiles_dir)}"
    if tiles_dir.is_dir() and not tiles_have_xodr:
        tiles_detail = f"no .xodr files in {norm_path_str(tiles_dir)}"
    add("tiles/ with .xodr", tiles_have_xodr, tiles_detail, True)

    finals = list(run_dir.glob("08_final*.xodr"))
    finals_detail = norm_path_str(run_dir) if finals else f"no 08_final*.xodr in {norm_path_str(run_dir)}"
    add("08_final*.xodr", bool(finals), finals_detail, True)

    domain_full = run_dir / "domain_gap" / "full_report.json"
    add("domain_gap/full_report.json", domain_full.is_file(), norm_path_str(domain_full), True)

    per_tile_status = None
    per_tile_status_note = ""
    if domain_full.is_file():
        try:
            data = json.loads(domain_full.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                per_tile_status = data.get("per_tile_status")
            else:
                per_tile_status_note = "full_report.json is not a JSON object"
        except Exception as e:
            per_tile_status_note = f"full_report.json read error: {e}"

    per_tile_required = per_tile_status == "computed"
    per_tile_context = (
        f"per_tile_status={per_tile_status}" if per_tile_status is not None else "per_tile_status unknown"
    )

    tile_metrics = domain_full.parent / "tile_metrics.csv"
    tm_detail = norm_path_str(tile_metrics) if tile_metrics.is_file() else f"missing: {norm_path_str(tile_metrics)}"
    if per_tile_status_note:
        tm_detail = f"{tm_detail} ({per_tile_status_note})"
    add("domain_gap/tile_metrics.csv", tile_metrics.is_file(), f"{tm_detail} [{per_tile_context}]", per_tile_required)

    worst_tiles = domain_full.parent / "worst_tiles.csv"
    wt_detail = norm_path_str(worst_tiles) if worst_tiles.is_file() else f"missing: {norm_path_str(worst_tiles)}"
    if per_tile_status_note:
        wt_detail = f"{wt_detail} ({per_tile_status_note})"
    add("domain_gap/worst_tiles.csv", worst_tiles.is_file(), f"{wt_detail} [{per_tile_context}]", per_tile_required)

    eval_root = root / "eval_out"
    corr_files = sorted(eval_root.glob("*/correspondence.csv")) if eval_root.is_dir() else []
    if corr_files:
        extra = len(corr_files) - 1
        detail = norm_path_str(corr_files[0]) + (f" (+{extra} more)" if extra > 0 else "")
    else:
        detail = f"none found under {norm_path_str(eval_root)}"
    add("eval_out/*/correspondence.csv", bool(corr_files), detail, False)

    det_reports = []
    if run_dir.is_dir():
        det_reports = [p for p in run_dir.rglob("determinism_report.*") if p.suffix.lower() in {".json", ".csv"}]
    if det_reports:
        extra = len(det_reports) - 1
        detail = norm_path_str(det_reports[0]) + (f" (+{extra} more)" if extra > 0 else "")
    else:
        detail = f"none found under {norm_path_str(run_dir)}"
    add("determinism_report.(json|csv)", bool(det_reports), detail, False)

    print(f"Repo root : {norm_path_str(root)}")
    print(f"Latest run: {norm_path_str(run_dir)}")
    print()
    _print_table(rows)

    return 0 if required_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
