#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compute deterministic OSM statistics (offline, no CARLA).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class OSMStatsResult:
    ok: bool
    message: str
    stats: Dict[str, Any]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_commit(repo_root: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip(), None
        return None, (result.stderr.strip() or f"git rev-parse failed with code {result.returncode}")
    except FileNotFoundError:
        return None, "git not found"
    except subprocess.TimeoutExpired:
        return None, "git command timed out"
    except Exception as exc:  # noqa: BLE001
        return None, f"git error: {exc}"


def _output_root_from_settings() -> Path:
    try:
        from ultimate_pipeline.config.settings import SETTINGS

        return Path(getattr(SETTINGS, "PIPELINE_OUTPUT_ROOT", "ultimate_pipeline_out"))
    except Exception:
        return Path("ultimate_pipeline_out")


def _resolve_run_dir(run_dir_arg: Optional[str], output_root: Optional[Path] = None) -> Path:
    if run_dir_arg:
        return Path(run_dir_arg)
    root = output_root or _output_root_from_settings()
    if not root.exists():
        return Path(".")
    candidates = [p for p in root.iterdir() if p.is_dir()]
    if not candidates:
        return Path(".")
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _find_osm_in_run(run_dir: Path) -> Tuple[Optional[Path], str]:
    candidates = [
        run_dir / "osm" / "extract.osm",
        run_dir / "osm" / "extract.osm.pbf",
        run_dir / "osm_extract.osm",
        run_dir / "osm_extract.osm.pbf",
        run_dir / "artifacts" / "osm_extract.osm",
        run_dir / "artifacts" / "osm_extract.osm.pbf",
    ]
    for c in candidates:
        if c.exists():
            return c, str(c)
    osm_files = sorted(run_dir.rglob("*.osm")) + sorted(run_dir.rglob("*.osm.pbf"))
    if osm_files:
        osm_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return osm_files[0], str(osm_files[0])
    return None, "not_found"


def _bbox_update(bbox: Dict[str, float], lat: float, lon: float) -> None:
    bbox["lat_min"] = min(bbox["lat_min"], lat)
    bbox["lat_max"] = max(bbox["lat_max"], lat)
    bbox["lon_min"] = min(bbox["lon_min"], lon)
    bbox["lon_max"] = max(bbox["lon_max"], lon)


def _compute_stats_from_osm_xml(path: Path) -> OSMStatsResult:
    stats: Dict[str, Any] = {
        "nodes": 0,
        "ways": 0,
        "relations": 0,
        "highway_counts": {},
        "building_ways": 0,
        "building_relations": 0,
        "junction_relations": 0,
        "bbox": None,
        "bbox_ok": False,
    }
    bbox = {"lat_min": float("inf"), "lat_max": float("-inf"), "lon_min": float("inf"), "lon_max": float("-inf")}
    try:
        for _event, elem in ET.iterparse(path, events=("end",)):
            if elem.tag == "node":
                stats["nodes"] += 1
                lat = elem.attrib.get("lat")
                lon = elem.attrib.get("lon")
                if lat is not None and lon is not None:
                    _bbox_update(bbox, float(lat), float(lon))
            elif elem.tag == "way":
                stats["ways"] += 1
                highway = None
                has_building = False
                for tag in elem.findall("tag"):
                    k = tag.attrib.get("k")
                    v = tag.attrib.get("v")
                    if k == "highway":
                        highway = v
                    if k == "building":
                        has_building = True
                if highway:
                    counts = stats["highway_counts"]
                    counts[highway] = counts.get(highway, 0) + 1
                if has_building:
                    stats["building_ways"] += 1
            elif elem.tag == "relation":
                stats["relations"] += 1
                has_building = False
                has_junction = False
                for tag in elem.findall("tag"):
                    k = tag.attrib.get("k")
                    v = tag.attrib.get("v")
                    if k == "building":
                        has_building = True
                    if k == "junction" or (k == "type" and v == "junction"):
                        has_junction = True
                if has_building:
                    stats["building_relations"] += 1
                if has_junction:
                    stats["junction_relations"] += 1
            elem.clear()
        if bbox["lat_min"] != float("inf"):
            stats["bbox"] = bbox
            stats["bbox_ok"] = bbox["lat_min"] <= bbox["lat_max"] and bbox["lon_min"] <= bbox["lon_max"]
        return OSMStatsResult(True, "ok", stats)
    except Exception as exc:  # noqa: BLE001
        return OSMStatsResult(False, f"parse_error: {exc}", stats)


def _compute_stats(path: Path) -> OSMStatsResult:
    if path.suffix.lower() == ".pbf":
        try:
            import osmium  # type: ignore
        except Exception as exc:  # noqa: BLE001
            return OSMStatsResult(False, f"pbf_not_supported: {exc}", {"nodes": 0, "ways": 0, "relations": 0})

        class _Handler(osmium.SimpleHandler):
            def __init__(self) -> None:
                super().__init__()
                self.stats = {
                    "nodes": 0,
                    "ways": 0,
                    "relations": 0,
                    "highway_counts": {},
                    "building_ways": 0,
                    "building_relations": 0,
                    "junction_relations": 0,
                    "bbox": None,
                    "bbox_ok": False,
                }
                self._bbox = {
                    "lat_min": float("inf"),
                    "lat_max": float("-inf"),
                    "lon_min": float("inf"),
                    "lon_max": float("-inf"),
                }

            def node(self, n) -> None:  # type: ignore[override]
                self.stats["nodes"] += 1
                if n.location.valid():
                    _bbox_update(self._bbox, n.location.lat, n.location.lon)

            def way(self, w) -> None:  # type: ignore[override]
                self.stats["ways"] += 1
                if "highway" in w.tags:
                    tag = w.tags["highway"]
                    counts = self.stats["highway_counts"]
                    counts[tag] = counts.get(tag, 0) + 1
                if "building" in w.tags:
                    self.stats["building_ways"] += 1

            def relation(self, r) -> None:  # type: ignore[override]
                self.stats["relations"] += 1
                if "building" in r.tags:
                    self.stats["building_relations"] += 1
                if r.tags.get("junction") or r.tags.get("type") == "junction":
                    self.stats["junction_relations"] += 1

            def finish(self) -> None:
                if self._bbox["lat_min"] != float("inf"):
                    self.stats["bbox"] = self._bbox
                    self.stats["bbox_ok"] = (
                        self._bbox["lat_min"] <= self._bbox["lat_max"]
                        and self._bbox["lon_min"] <= self._bbox["lon_max"]
                    )

        handler = _Handler()
        try:
            handler.apply_file(str(path), locations=True)
            handler.finish()
            return OSMStatsResult(True, "ok", handler.stats)
        except Exception as exc:  # noqa: BLE001
            return OSMStatsResult(False, f"parse_error: {exc}", handler.stats)

    return _compute_stats_from_osm_xml(path)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)
    path.write_text(text + ("\n" if not text.endswith("\n") else ""), encoding="utf-8", newline="\n")


def _build_manifest(input_path: Optional[Path]) -> Dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[2]
    git_commit, git_err = _git_commit(repo_root)
    inputs = {}
    if input_path and input_path.exists():
        inputs["osm_path"] = str(input_path)
        inputs["osm_sha256"] = _sha256(input_path)
    return {
        "generated_at_utc": _utc_now(),
        "python_version": sys.version.replace("\n", " "),
        "git_commit": git_commit,
        "git_commit_error": git_err,
        "inputs": inputs,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Compute OSM statistics for a run or file.")
    group = p.add_mutually_exclusive_group(required=False)
    group.add_argument("--osm", type=Path, help="Input .osm or .osm.pbf file")
    group.add_argument("--run-dir", type=Path, help="Run directory to locate OSM artifact")
    p.add_argument("--out", type=Path, default=Path("."), help="Output directory (default: current directory)")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    run_dir = _resolve_run_dir(str(args.run_dir) if args.run_dir else None)
    if args.osm:
        osm_path = args.osm
    else:
        osm_path, _reason = _find_osm_in_run(run_dir)

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "osm_statistics.json"
    manifest_path = out_dir / "osm_statistics_manifest.json"

    if not osm_path or not osm_path.exists():
        payload = {
            "ok": False,
            "error": "osm_missing",
            "run_dir": str(run_dir),
            "osm_path": str(osm_path) if osm_path else "",
        }
        _write_json(report_path, payload)
        _write_json(manifest_path, _build_manifest(osm_path if osm_path else None))
        return 2

    result = _compute_stats(osm_path)
    payload = {
        "ok": result.ok,
        "error": None if result.ok else result.message,
        "run_dir": str(run_dir),
        "osm_path": str(osm_path),
        "stats": result.stats,
    }
    _write_json(report_path, payload)
    _write_json(manifest_path, _build_manifest(osm_path))
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
