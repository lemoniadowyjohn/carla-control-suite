
#!/usr/bin/env python3
# ultimate_pipeline/run_full_domain_gap.py

from __future__ import annotations

import os
import csv
import json
import re
import sys
import time
import glob
import hashlib
import shutil
import argparse
import statistics
import atexit
import traceback
from pathlib import Path
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import numpy as np
from typing import Dict, Any, Optional, List, Tuple

from ultimate_pipeline.tools.path_utils import resolve_latest_run, repo_root, norm_path_str, timestamp_dirname, ensure_dir as ensure_dir_util
from ultimate_pipeline.tools.write_manifest import write_run_manifest

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.domain_gap_gnn import TORCH_GEOMETRIC_AVAILABLE

from ultimate_pipeline.domain_gap.geo_alignment import GeoAligner, identity_transform
from ultimate_pipeline.domain_gap.tile_grid_meta import load_grid_spec_from_meta_or_tiles
from ultimate_pipeline.domain_gap.deterministic_alignment import (
    deterministic_promote_and_align,
    compute_auto_bbox_and_centroid,
    BBox,
)
from ultimate_pipeline.core.georef_utils import normalize_georeference, parse_georeference
from ultimate_pipeline.utils.finalize_run_pack import write_signature_json, write_success_txt
from ultimate_pipeline.tools.coordinate_system_artifact import write_coordinate_system_json
from ultimate_pipeline.core.run_manifest import update_run_manifest
from ultimate_pipeline.tools.xodr_structural_summary import summarize_xodr
# Lazy-safe imports (none of these depend on CARLA)
from ultimate_pipeline.domain_gap.tile_matcher import TileMatcher
from ultimate_pipeline.domain_gap.tile_gap_evaluator import TileGapEvaluator
from ultimate_pipeline.domain_gap.geometry_gap import GeometryGap
from ultimate_pipeline.domain_gap.curvature_gap import CurvatureGap
from ultimate_pipeline.domain_gap.elevation_gap import ElevationGap
from ultimate_pipeline.domain_gap.intersection_gap import IntersectionGap
from ultimate_pipeline.domain_gap.semantic_gap import SemanticGap
from ultimate_pipeline.domain_gap.connectivity_gap import ConnectivityGap
from ultimate_pipeline.domain_gap.perception_gap import PerceptionEvaluator, PerceptionGap

from ultimate_pipeline.visualization.map_diff import overlay_maps
from ultimate_pipeline.visualization.heatmap_plotter import TileHeatmapPlotter
from ultimate_pipeline.quality.road_classification_gap import RoadClassificationGap


# CLI manual map choices (only when --manual_map is used)
# NOTE: Do not hardcode machine-specific absolute paths here.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_AUTO_GEOREFERENCE_WARNING = (
    "Coordinates may be in local frame; verify alignment quality"
)
_AUTO_GEOREFERENCE_IOU_MIN = 0.05

def _env_path(name: str) -> Path | None:
    v = os.getenv(name, "").strip()
    return Path(v) if v else None


def _flatten_numeric(obj, prefix: str = "") -> Dict[str, float]:
    """Flatten numeric scalars inside nested dicts into dotted keys."""
    out: Dict[str, float] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            out.update(_flatten_numeric(v, p))
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        out[prefix] = float(obj)
    return out


def _normalized_l1_over2(a_dist: Dict[str, float], b_dist: Dict[str, float]) -> Optional[float]:
    keys = set(a_dist) | set(b_dist)
    if not keys:
        return None
    total_a = sum(float(a_dist.get(k, 0.0)) for k in keys)
    total_b = sum(float(b_dist.get(k, 0.0)) for k in keys)
    if total_a <= 0 or total_b <= 0:
        return None
    l1 = 0.0
    for k in keys:
        pa = float(a_dist.get(k, 0.0)) / total_a
        pb = float(b_dist.get(k, 0.0)) / total_b
        l1 += abs(pa - pb)
    return l1 / 2.0


def _safe_dict(d: Any) -> Dict[str, Any]:
    return d if isinstance(d, dict) else {}


_REQUIRED_DOMAIN_GAP_METRICS = (
    "road_length_delta_m",
    "junction_count_delta",
    "intersection_iou",
)


def _finite_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        out = float(value)
        if not np.isfinite(out):
            return None
        return float(out)
    except Exception:
        return None


def _extract_intersection_iou(intersection_gap: Dict[str, Any]) -> Optional[float]:
    if not isinstance(intersection_gap, dict):
        return None

    for key in ("intersection_iou", "iou", "iou_score", "jaccard"):
        val = _finite_float(intersection_gap.get(key))
        if val is not None:
            return val

    gap_val = None
    for key in ("normalized_gap", "gap"):
        gap_val = _finite_float(intersection_gap.get(key))
        if gap_val is not None:
            break
    if gap_val is None:
        return None

    # Contract maps this to an IoU-style similarity signal.
    iou = 1.0 - gap_val
    if iou < 0.0:
        iou = 0.0
    if iou > 1.0:
        iou = 1.0
    return iou


def _compute_required_domain_gap_metrics(
    reference_xodr: str,
    aligned_auto: str,
    whole_inter_gap: Dict[str, Any],
) -> Dict[str, Any]:
    manual_summary = summarize_xodr(Path(reference_xodr))
    auto_summary = summarize_xodr(Path(aligned_auto))

    road_length_delta_m = None
    manual_len = _finite_float(manual_summary.get("total_road_length_m"))
    auto_len = _finite_float(auto_summary.get("total_road_length_m"))
    if manual_len is not None and auto_len is not None:
        road_length_delta_m = float(auto_len - manual_len)

    junction_count_delta = None
    try:
        junction_count_delta = int(auto_summary.get("junction_count")) - int(manual_summary.get("junction_count"))
    except Exception:
        junction_count_delta = None

    intersection_iou = _extract_intersection_iou(whole_inter_gap)

    road_count_delta = None
    try:
        road_count_delta = int(auto_summary.get("road_count")) - int(manual_summary.get("road_count"))
    except Exception:
        road_count_delta = None

    lane_count_delta = None
    try:
        lane_count_delta = int(auto_summary.get("lane_count_total")) - int(manual_summary.get("lane_count_total"))
    except Exception:
        lane_count_delta = None

    return {
        "road_length_delta_m": road_length_delta_m,
        "junction_count_delta": junction_count_delta,
        "intersection_iou": intersection_iou,
        "road_count_delta": road_count_delta,
        "lane_count_delta": lane_count_delta,
    }


def _enforce_required_domain_gap_metrics(metrics: Dict[str, Any], *, context: str) -> None:
    missing: list[str] = []
    for key in _REQUIRED_DOMAIN_GAP_METRICS:
        val = metrics.get(key) if isinstance(metrics, dict) else None
        if key == "junction_count_delta":
            try:
                int(val)
            except Exception:
                missing.append(key)
        else:
            if _finite_float(val) is None:
                missing.append(key)
    if missing:
        raise RuntimeError(
            f"{context}: required domain-gap metrics unavailable ({', '.join(sorted(set(missing)))})"
        )


def _acquire_output_lock(output_dir: str, log: logging.Logger) -> None:
    """Acquire an output-directory lock to prevent concurrent runs clobbering artifacts.

    Observed failure mode: launcher starts two interpreters (venv + system python) concurrently
    writing into the same output_dir. This lock must be race-free.

    Behavior:
      - First process to atomically create the lock file wins.
      - If the lock already exists, we fail closed unless UP_IGNORE_OUTPUT_LOCK=1.
      - Lock content is JSON for traceability; legacy digit-only locks are tolerated.
    """
    lock_path = Path(output_dir) / ".run_full_domain_gap.lock"
    pid = int(os.getpid())

    def _parse_lock(text: str) -> Optional[int]:
        t = (text or "").strip()
        if not t:
            return None
        if t.isdigit():
            try:
                return int(t)
            except Exception:
                return None
        try:
            obj = json.loads(t)
            if isinstance(obj, dict) and isinstance(obj.get("pid"), int):
                return int(obj["pid"])
        except Exception:
            return None
        return None

    ignore_lock = str(os.getenv("UP_IGNORE_OUTPUT_LOCK", "0") or "0").strip().lower() in ("1", "true", "yes", "on")

    payload = {"pid": pid, "python": str(sys.executable), "utc": float(time.time())}
    flags = getattr(os, "O_CREAT", 0) | getattr(os, "O_EXCL", 0) | getattr(os, "O_WRONLY", 0)

    def _atomic_write() -> None:
        fd = os.open(str(lock_path), flags)
        try:
            os.write(fd, (json.dumps(payload) + "\n").encode("utf-8", errors="replace"))
        finally:
            try:
                os.close(fd)
            except Exception:
                pass

    try:
        _atomic_write()
    except FileExistsError:
        if not ignore_lock:
            other_pid = None
            try:
                other_pid = _parse_lock(lock_path.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                other_pid = None
            raise RuntimeError(
                f"Output dir lock exists (pid={other_pid}). Refusing to run. "
                f"Delete {lock_path.name} to rerun, or set UP_IGNORE_OUTPUT_LOCK=1 to override."
            )
        log.warning("Output lock exists; proceeding due to UP_IGNORE_OUTPUT_LOCK=1")
    except Exception as exc:
        log.warning("Failed to acquire output lock (%s).", exc)

    def _cleanup() -> None:
        try:
            if not lock_path.exists():
                return
            txt = lock_path.read_text(encoding="utf-8", errors="replace")
            owner = _parse_lock(txt)
            if owner is not None and owner == pid:
                lock_path.unlink()
            elif owner is None and txt.strip() == str(pid):
                lock_path.unlink()
        except Exception:
            pass

    atexit.register(_cleanup)



def _ensure_pairing_schema(report: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure tile_pairing_report.json matches AGENT_SYNC §5.A schema (thesis_final strict)."""
    if not isinstance(report, dict):
        return report

    # Normalize pairs field
    pairs = report.get("pairs") or report.get("matches") or []
    report["pairs"] = list(pairs)
    report["num_pairs"] = len(pairs)

    # Add provenance
    if "pairing_provenance" not in report:
        try:
            import scipy  # noqa: F401
            scipy_ok = True
        except ImportError:
            scipy_ok = False
        report["pairing_provenance"] = {
            "scipy_available": scipy_ok,
            "fallback_reason": None if report.get("pairing_method") == "hungarian" else "scipy_unavailable"
        }

    # Ensure one_to_one block exists
    if "one_to_one" not in report:
        report["one_to_one"] = {"ok": True, "duplicate_manual": [], "duplicate_auto": []}

    return report


def _dump_pairing_report_early(output_dir: str, report: Optional[Dict[str, Any]]) -> None:
    if not isinstance(report, dict):
        return
    try:
        report = _ensure_pairing_schema(report)
        _safe_dump_json(os.path.join(output_dir, "tile_pairing_report.json"), report)
    except Exception:
        pass


def _ensure_canonical_domain_gap_outputs(run_root: Path, output_dir: Path) -> None:
    """Ensure canonical artifacts exist under <run_root>/domain_gap (best-effort copy)."""
    try:
        canonical_dir = run_root / "domain_gap"
        canonical_dir.mkdir(parents=True, exist_ok=True)
        output_dir = Path(output_dir)
        required = [
            "full_report.json",
            "summary.csv",
            "reproducibility_hash.json",
            "tile_pairing_report.json",
            "domain_gap_status.json",
            "coordinate_system.json",
            "crs_comparability.json",
            "audit_summary.json",
        ]
        for name in required:
            src = output_dir / name
            dst = canonical_dir / name
            try:
                if src.resolve() == dst.resolve():
                    continue
            except Exception:
                pass
            if src.is_file():
                try:
                    if src.stat().st_size > 0:
                        shutil.copy2(src, dst)
                except Exception:
                    pass
    except Exception:
        pass


def _write_domain_gap_status(canonical_dir: Path, payload: Dict[str, Any]) -> None:
    canonical_dir.mkdir(parents=True, exist_ok=True)
    _safe_dump_json(str(canonical_dir / "domain_gap_status.json"), payload)


def _thesis_scope_fields() -> Dict[str, Any]:
    return {
        "rq2_scope": "structural_domain_gap",
        "elevation_included": False,
        "scenario_boundary": (
            "scenario_b_structural_only_generated_vs_manual_reference; "
            "no cooked/manual perception equivalence claim"
        ),
    }


def _default_georef_info() -> Dict[str, Any]:
    return {"norm": "", "valid": False, "params_complete": False, "raw": ""}


def _build_crs_comparability_report(
    manual_xodr: Optional[str],
    auto_xodr: Optional[str],
) -> Dict[str, Any]:
    manual_path = str(manual_xodr or "").strip()
    auto_path = str(auto_xodr or "").strip()
    manual_present = bool(manual_path and Path(manual_path).is_file())
    auto_present = bool(auto_path and Path(auto_path).is_file())

    manual_info = _read_georef_info(manual_path) if manual_present else _default_georef_info()
    auto_info = _read_georef_info(auto_path) if auto_present else _default_georef_info()
    manual_norm = str(manual_info.get("norm") or "")
    auto_norm = str(auto_info.get("norm") or "")

    status = "crs_match"
    reason = "manual_and_auto_georeference_match"
    if not manual_present:
        status = "manual_missing"
        reason = "manual_xodr_missing"
    elif not auto_present:
        status = "auto_missing"
        reason = "auto_xodr_missing"
    elif not manual_info.get("valid"):
        status = "manual_georef_invalid"
        reason = "manual_georeference_invalid_or_unparseable"
    elif not auto_info.get("valid"):
        status = "auto_georef_invalid"
        reason = "auto_georeference_invalid_or_unparseable"
    elif not manual_norm:
        status = "manual_georef_missing"
        reason = "manual_georeference_missing"
    elif not auto_norm:
        status = "auto_georef_missing"
        reason = "auto_georeference_missing"
    elif manual_norm != auto_norm:
        status = "crs_mismatch"
        reason = "manual_and_auto_georeference_do_not_match"

    crs_match = status == "crs_match"
    return {
        "schema_version": "1.0",
        **_thesis_scope_fields(),
        "manual": {
            "xodr_path": manual_path or None,
            "present": manual_present,
            "xodr_sha256": _hash_file_sha256(manual_path) if manual_present else None,
            "geoReference_norm": manual_norm or None,
            "params_complete": bool(manual_info.get("params_complete")) if manual_present else None,
            "valid": bool(manual_info.get("valid")) if manual_present else None,
        },
        "auto": {
            "xodr_path": auto_path or None,
            "present": auto_present,
            "xodr_sha256": _hash_file_sha256(auto_path) if auto_present else None,
            "geoReference_norm": auto_norm or None,
            "params_complete": bool(auto_info.get("params_complete")) if auto_present else None,
            "valid": bool(auto_info.get("valid")) if auto_present else None,
        },
        "comparability": {
            "status": status,
            "reason": reason,
            "crs_match": crs_match,
            "auto_proj4_matches_manual": crs_match,
            "manual_file_unchanged": True,
        },
    }


def _write_crs_comparability(
    run_dir: Path,
    manual_xodr: Optional[str],
    auto_xodr: Optional[str],
) -> Dict[str, Any]:
    report = _build_crs_comparability_report(manual_xodr, auto_xodr)
    _safe_dump_json(str(Path(run_dir) / "crs_comparability.json"), report)
    return report


def _write_domain_gap_audit_summary(
    run_dir: Path,
    *,
    crs_report: Dict[str, Any],
    status_payload: Dict[str, Any],
) -> None:
    comparability = crs_report.get("comparability", {}) if isinstance(crs_report, dict) else {}
    summary = {
        "schema_version": "1.0",
        **_thesis_scope_fields(),
        "run_dir": str(run_dir),
        "domain_gap_status": {
            "status": status_payload.get("status"),
            "success": status_payload.get("success"),
            "failure_reason": status_payload.get("failure_reason"),
            "reason": status_payload.get("reason"),
        },
        "crs_comparability": {
            "status": comparability.get("status"),
            "reason": comparability.get("reason"),
            "crs_match": comparability.get("crs_match"),
        },
        "artifacts": {
            "full_report_json": str((Path(run_dir) / "full_report.json")),
            "domain_gap_status_json": str((Path(run_dir) / "domain_gap_status.json")),
            "crs_comparability_json": str((Path(run_dir) / "crs_comparability.json")),
            "coordinate_system_json": str((Path(run_dir) / "coordinate_system.json")),
        },
        "note": "Direct run_full_domain_gap thesis parity audit summary.",
    }
    _safe_dump_json(str(Path(run_dir) / "audit_summary.json"), summary)


def _classify_domain_gap_failure_reason(error: Optional[str], tb: Optional[str]) -> str:
    """Return a stable failure code for status artifacts."""
    haystack = f"{error or ''}\n{tb or ''}".lower()
    if "timed out after" in haystack and "tile_manual_xodr_windows" in haystack:
        return "tiling_timeout"
    if "timeout" in haystack and "manual tiling" in haystack:
        return "tiling_timeout"
    return "domain_gap_failed"


def _compute_pairing_stats(pairs: list[Any], min_iou: float) -> tuple[int, list[float], Optional[float], Optional[float]]:
    """Compute match count and IoU stats from pairing dicts."""
    ious: list[float] = []
    for p in pairs:
        iou = None
        if isinstance(p, dict):
            if "iou" in p:
                iou = p["iou"]
            elif "IoU" in p:
                iou = p["IoU"]
        if isinstance(iou, (int, float)) and not isinstance(iou, bool):
            if float(iou) >= float(min_iou):
                ious.append(float(iou))
    if not ious:
        return 0, [], None, None
    return len(ious), ious, float(sum(ious) / len(ious)), float(statistics.median(ious))


def _collect_unique_tile_pairs(
    tile_pairing_report: Optional[Dict[str, Any]],
    tile_match_info: Dict[str, Dict[str, Any]],
) -> list[Any]:
    pairs: list[Any] = []
    seen: set[tuple[Any, ...]] = set()

    def _row_key(row: Any) -> Optional[tuple[Any, ...]]:
        if not isinstance(row, dict):
            return None
        manual_id = (
            row.get("manual")
            or row.get("manual_tile")
            or row.get("manual_tile_id")
            or row.get("a_id")
            or row.get("a_tile_id")
        )
        auto_id = (
            row.get("auto")
            or row.get("auto_tile")
            or row.get("auto_tile_id")
            or row.get("b_id")
            or row.get("b_tile_id")
        )
        return (
            str(manual_id or ""),
            str(auto_id or ""),
            _try_float(row.get("iou") if "iou" in row else row.get("IoU")),
            _try_float(row.get("cost")),
        )

    if isinstance(tile_pairing_report, dict):
        for field in ("matches", "candidates"):
            seq = tile_pairing_report.get(field)
            if not isinstance(seq, list):
                continue
            for row in seq:
                key = _row_key(row)
                if key is not None:
                    if key in seen:
                        continue
                    seen.add(key)
                pairs.append(row)

    if not pairs and isinstance(tile_match_info, dict):
        pairs = [v for v in tile_match_info.values() if isinstance(v, dict)]
    return pairs


def _enforced_confidence(
    num_matches: int,
    median_iou: Optional[float],
    min_matches_high: int = 10,
    min_median_iou_high: float = 0.5,
    min_matches_med: int = 5,
    min_median_iou_med: float = 0.3,
) -> str:
    """Enforce thesis rule: HIGH requires both match count + median IoU threshold."""
    if num_matches >= int(min_matches_high) and median_iou is not None and median_iou >= float(min_median_iou_high):
        return "HIGH"
    if num_matches >= int(min_matches_med) and median_iou is not None and median_iou >= float(min_median_iou_med):
        return "MEDIUM"
    return "LOW"


def _enforce_r5_run_root(auto_meta_path: Path, auto_xodr_path: Path) -> None:
    run_root = auto_meta_path.parent
    auto_xodr_resolved = auto_xodr_path.resolve()
    run_root_resolved = run_root.resolve()
    if hasattr(auto_xodr_resolved, "is_relative_to"):
        inside = auto_xodr_resolved.is_relative_to(run_root_resolved)
    else:
        inside = str(auto_xodr_resolved).startswith(str(run_root_resolved))
    if not inside:
        raise RuntimeError(
            f"R5 violation: auto_xodr is not inside run_root. auto_xodr={auto_xodr_resolved} run_root={run_root_resolved}"
        )


def _is_intermediate_dir(path: Path) -> bool:
    """Check if path is an intermediate directory (not the real run_root).

    Intermediate directories that should NOT be treated as run_root:
    - domain_gap/* (output artifacts)
    - auto_tiles_* (tiling outputs)
    - manual_tiles_* (manual tiling outputs)
    - tiles (raw tiles directory)
    """
    name = path.name.lower()
    # Check direct name matches
    if name in ("domain_gap", "tiles"):
        return True
    # Check prefixes for generated directories
    if name.startswith("auto_tiles_") or name.startswith("manual_tiles_"):
        return True
    # Check if any parent is domain_gap (e.g., domain_gap/auto_tiles_promoted_aligned)
    for parent in path.parents:
        if parent.name.lower() == "domain_gap":
            return True
    return False


def _resolve_run_root_from_auto_meta(auto_meta_path: Path, max_levels: int = 6) -> Path:
    """Resolve run_root from a tile_metadata.json path (run_root or tileset).

    Run root detection rules:
    1. Directory containing 08_final*.xodr is ALWAYS the run_root (strongest signal)
    2. Directory containing settings_snapshot.json is run_root ONLY IF:
       - It's not under domain_gap/
       - It's not named auto_tiles_* or manual_tiles_*
       - It's not just "tiles/"

    This prevents intermediate output directories from being mistaken for run_root.
    """
    start = auto_meta_path.parent
    candidates = [start] + list(start.parents)

    for idx, parent in enumerate(candidates):
        if idx > max_levels:
            break
        try:
            # 08_final*.xodr is the strongest indicator of run_root
            if list(parent.glob("08_final*.xodr")):
                return parent

            # settings_snapshot.json is only valid if NOT in an intermediate directory
            if (parent / "settings_snapshot.json").is_file():
                if not _is_intermediate_dir(parent):
                    return parent
                # Otherwise, skip this candidate and keep climbing
        except Exception:
            continue

    raise RuntimeError(
        "Could not resolve run_root from auto_meta. "
        "Pass --auto_xodr or use run_root/tile_metadata.json. "
        f"Searched from: {start}"
    )


def _walk_find_files(root: Path, names: list[str], max_depth: int = 6) -> list[Path]:
    """Find candidate meta files under a directory (depth-limited, deterministic ordering)."""
    out: list[Path] = []
    root = root.resolve()
    try:
        root_parts = len(root.parts)
    except Exception:
        root_parts = None
    for dirpath, dirnames, filenames in os.walk(str(root)):
        p = Path(dirpath)
        if root_parts is not None:
            try:
                depth = len(p.resolve().parts) - root_parts
            except Exception:
                depth = 0
            if depth > max_depth:
                dirnames[:] = []
                continue
        for fn in filenames:
            if fn in names:
                out.append(p / fn)
    out = sorted(set(out), key=lambda x: str(x).lower())
    return out


def _pick_best_auto_meta(candidates: list[Path]) -> Path | None:
    """Prefer auto tiles meta and avoid domain_gap/manual tiles if possible."""
    if not candidates:
        return None

    def score(p: Path) -> tuple[int, float, str]:
        s = 0
        lp = str(p).replace("\\", "/").lower()
        if "/auto_tiles" in lp or "auto_tiles_" in lp:
            s += 50
        if "/tiles/" in lp:
            s += 10
        if "/domain_gap" in lp:
            s -= 30
        if "/manual_tiles" in lp or "manual_tiles_" in lp:
            s -= 40
        name = p.name.lower()
        # Prefer tile_metadata.json over tile_manifest.json for --auto_meta
        if name == "tile_metadata.json":
            s += 10
        elif name == "tile_manifest.json":
            s += 5
        try:
            mt = p.stat().st_mtime
        except Exception:
            mt = 0.0
        return (s, mt, str(p).lower())

    return max(candidates, key=score)


def _resolve_auto_meta_path(arg: Path) -> Path:
    """Resolve --auto_meta. Accepts file or directory (run_root).

    If a directory is given, we search for tile_metadata.json (preferred) or tile_manifest.json.
    """
    try:
        if arg.is_file():
            return arg
    except Exception:
        pass
    try:
        if arg.is_dir():
            names = ["tile_metadata.json", "tile_manifest.json", "tiling_meta.json", "meta.json", "tile_meta.json"]
            candidates = _walk_find_files(arg, names, max_depth=7)
            best = _pick_best_auto_meta(candidates)
            if best:
                return best
    except Exception:
        pass
    raise FileNotFoundError(f"Auto tile metadata not found/resolvable: {arg}")

def resolve_manual_xodr(manual_map_name: str) -> Path:
    """Resolve manual reference XODR for a given manual town name.

    Priority:
      1) UP_MANUAL_XODR_<TOWN> env var (e.g., UP_MANUAL_XODR_GRID0828)
      2) repo-relative manual_maps/* fallbacks (bounded, governed order)
      3) UP_MANUAL_XODR fallback (generic)
    """
    key = f"UP_MANUAL_XODR_{manual_map_name.upper()}"
    p = _env_path(key)
    if p and p.exists():
        return p

    # Bounded repo-local fallback set only (no prior-run/per-session directories).
    fallbacks: dict[str, list[Path]] = {
        "GRID0828": [
            _REPO_ROOT / "cities" / "ingolstadt" / "manual_grid0828.xodr",
            _REPO_ROOT / "manual_maps" / "manual_ingolstadt_grid0828.xodr",
            _REPO_ROOT / "manual_maps" / "Grid0828.xodr",
            _REPO_ROOT / "manual_maps" / "GRID0828.xodr",
            _REPO_ROOT / "manual_maps" / "Grid0828" / "Grid0828.xodr",
        ],
        "GRID0821": [
            _REPO_ROOT / "cities" / "ingolstadt" / "manual_grid0821.xodr",
            _REPO_ROOT / "manual_maps" / "Grid0821.xodr",
            _REPO_ROOT / "manual_maps" / "GRID0821.xodr",
            _REPO_ROOT / "manual_maps" / "Grid0821" / "Grid0821.xodr",
            # NOTE: do NOT fall back to Grid0828 here — wrong map, silent misalignment
        ],
    }
    # Generic bounded fallback for ad-hoc named manual maps.
    if manual_map_name.upper() not in fallbacks:
        fallbacks[manual_map_name.upper()] = [
            _REPO_ROOT / "manual_maps" / f"{manual_map_name}.xodr",
            _REPO_ROOT / "manual_maps" / f"{manual_map_name.upper()}.xodr",
            _REPO_ROOT / "manual_maps" / manual_map_name / f"{manual_map_name}.xodr",
            _REPO_ROOT / "manual_maps" / "manual_ingolstadt_grid0828.xodr",
            _REPO_ROOT / "manual_maps" / "Grid0821.xodr",
            _REPO_ROOT / "manual_maps" / "Grid0828.xodr",
        ]
    for cand in fallbacks.get(manual_map_name.upper(), []):
        try:
            if cand.exists():
                return cand
        except Exception:
            continue

    generic = _env_path("UP_MANUAL_XODR")
    if generic and generic.exists():
        return generic

    searched = [key] + [str(p) for p in fallbacks.get(manual_map_name.upper(), [])] + ["UP_MANUAL_XODR"]
    raise FileNotFoundError(
        f"Manual XODR not found for {manual_map_name}. Searched: {', '.join([s for s in searched if s])}. "
        f"Set env {key} to an existing .xodr path (recommended)."
    )


def _resolve_reported_artifact_path(raw_path: str, report_json_path: Path) -> Path:
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate
    report_relative = (report_json_path.parent / candidate).expanduser()
    if report_relative.exists():
        return report_relative
    repo_relative = (repo_root() / candidate).expanduser()
    if repo_relative.exists():
        return repo_relative
    return report_relative


def validate_reproducibility_preconditions(report_json_path: Path) -> list[str]:
    report_json_path = Path(report_json_path).expanduser()
    if not report_json_path.is_file():
        return [f"Reproducibility warning: full_report.json not found: {report_json_path}"]

    try:
        report = json.loads(report_json_path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return [f"Reproducibility warning: could not read {report_json_path}: {exc}"]

    warnings: list[str] = []
    for key in ("manual_xodr", "auto_xodr"):
        raw_value = str(report.get(key) or "").strip()
        if not raw_value:
            warnings.append(
                f"Reproducibility warning: {key} missing or empty in {report_json_path}"
            )
            continue
        resolved = _resolve_reported_artifact_path(raw_value, report_json_path)
        if not resolved.exists():
            warnings.append(
                f"Reproducibility warning: {key} path does not exist: {raw_value} "
                f"(checked: {resolved})"
            )
    return warnings


DEFAULT_MANUAL_MAPS = {
    "Grid0828": _REPO_ROOT / "manual_maps" / "manual_ingolstadt_grid0828.xodr",
    "Grid0821": _REPO_ROOT / "manual_maps" / "Grid0821.xodr",
}
# Optional aggregator/metrics (lazy-loaded to avoid import-time failures on HPC)
DomainGapAggregator = None  # type: ignore
JunctionComplexityGap = None  # type: ignore
TopologyGap = None  # type: ignore


log = logging.getLogger("run_full_domain_gap")

_CARLA_TILE_QA_SKIPPED = "SKIPPED_CARLA_NOT_INVOKED"
_CARLA_DRIVABILITY_NOTE = (
    "CARLA not invoked; drivability is inferred from offline structural gates only"
)

# Provenance defaults (updated in __main__ when CLI is used)
manual_map_choice: Optional[str] = None
manual_xodr_resolved: str = ""
manual_xodr_source: str = "none"


# ---------------------------------------------------------------------------
# Tile-level fallback alignment: translation-only
# GeoAligner can fail on very sparse tiles (too few points to sample).
# When that happens, we align tiles by centroid translation of <planView><geometry> start points.
# ---------------------------------------------------------------------------
def _planview_centroid(xodr_path: str):
    try:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
        xs, ys = [], []
        for geom in root.findall(".//road/planView/geometry"):
            x = geom.get("x"); y = geom.get("y")
            if x is None or y is None:
                continue
            try:
                xs.append(float(x)); ys.append(float(y))
            except Exception:
                pass
        if not xs:
            return None
        return sum(xs) / len(xs), sum(ys) / len(ys)
    except Exception:
        return None

def _translate_planview_geometry(
    in_path: str,
    out_path: str,
    dx: float,
    dy: float,
    *,
    zero_header_offset: bool = False,
) -> bool:
    try:
        tree = ET.parse(in_path)
        root = tree.getroot()
        n = 0
        for geom in root.findall(".//road/planView/geometry"):
            x = geom.get("x"); y = geom.get("y")
            if x is None or y is None:
                continue
            try:
                geom.set("x", str(float(x) + dx))
                geom.set("y", str(float(y) + dy))
                n += 1
            except Exception:
                continue
        if zero_header_offset:
            header = root.find("header")
            if header is not None:
                off = header.find("offset")
                if off is not None:
                    off.set("x", "0.0")
                    off.set("y", "0.0")
        try:
            header = root.find("header")
            if header is not None:
                geo = header.find("geoReference")
                if geo is not None and geo.text:
                    geo.text = normalize_georeference(geo.text)
        except Exception:
            pass
        if n == 0:
            return False
        Path(os.path.dirname(out_path)).mkdir(parents=True, exist_ok=True)
        tree.write(out_path, encoding="utf-8", xml_declaration=True)
        return True
    except Exception:
        return False


def _read_georef_norm(xodr_path: str) -> str:
    try:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
        header = root.find("header")
        if header is None:
            return ""
        geo = header.find("geoReference")
        return normalize_georeference(geo.text if geo is not None else None)
    except Exception:
        return ""


def _read_georef_info(xodr_path: str) -> dict:
    try:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
        header = root.find("header")
        if header is None:
            return {"norm": "", "valid": False, "params_complete": False, "raw": ""}
        geo = header.find("geoReference")
        raw = geo.text if geo is not None else None
        valid, params_complete, norm = parse_georeference(raw)
        return {"norm": norm, "valid": valid, "params_complete": params_complete, "raw": raw or ""}
    except Exception:
        return {"norm": "", "valid": False, "params_complete": False, "raw": ""}


def _read_header_offset(xodr_path: str) -> Optional[dict]:
    try:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
        header = root.find("header")
        if header is None:
            return None
        off = header.find("offset")
        if off is None:
            return None
        return {
            "x": float(off.get("x", "0.0")),
            "y": float(off.get("y", "0.0")),
            "z": float(off.get("z", "0.0")),
            "hdg": float(off.get("hdg", "0.0")),
        }
    except Exception:
        return None


def _offset_large(offset: Optional[dict], threshold: float = 1e5) -> bool:
    if not isinstance(offset, dict):
        return False
    try:
        x = float(offset.get("x", 0.0))
        y = float(offset.get("y", 0.0))
        z = float(offset.get("z", 0.0))
    except Exception:
        return False
    return max(abs(x), abs(y), abs(z)) >= threshold


def _canonical_ingolstadt_auto_georeference(auto_xodr: str) -> str:
    if not auto_xodr:
        return ""
    try:
        resolved = Path(auto_xodr).resolve()
    except Exception:
        resolved = Path(auto_xodr)
    canonical_auto_xodr = (
        _REPO_ROOT / "cities" / "ingolstadt" / "ingolstadt_osm_auto.xodr"
    )
    try:
        canonical_resolved = canonical_auto_xodr.resolve()
    except Exception:
        canonical_resolved = canonical_auto_xodr
    if resolved != canonical_resolved:
        return ""
    bbox = getattr(SETTINGS, "DEFAULT_GPS_BOUNDS", {}) or {}
    lat_min = bbox.get("lat_min")
    lon_min = bbox.get("lon_min")
    if lat_min is None or lon_min is None:
        return ""
    return normalize_georeference(
        f"+proj=tmerc +lat_0={lat_min} +lon_0={lon_min} "
        "+k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
    )


def _extract_alignment_bbox_iou_after(transform: Any) -> Optional[float]:
    if not isinstance(transform, dict):
        return None
    crs_meta = transform.get("crs_reprojection")
    if isinstance(crs_meta, dict):
        for key in ("bbox_iou_after_reprojection", "bbox_iou_after"):
            value = _finite_float(crs_meta.get(key))
            if value is not None:
                return value
    diagnostics = transform.get("diagnostics")
    if isinstance(diagnostics, dict):
        for key in ("bbox_iou_after_reprojection", "bbox_iou_after"):
            value = _finite_float(diagnostics.get(key))
            if value is not None:
                return value
    return None


def _update_run_meta_auto_georef(
    run_meta: Dict[str, Any],
    georef_override: Optional[Dict[str, Any]],
) -> None:
    if not isinstance(run_meta, dict) or not isinstance(georef_override, dict):
        return
    if not georef_override.get("auto_georeference_injected"):
        return
    run_meta["auto_georeference_injected"] = True
    run_meta["auto_georeference_warning"] = str(
        georef_override.get("auto_georeference_warning")
        or _AUTO_GEOREFERENCE_WARNING
    )
    run_meta["auto_georeference_override_reason"] = str(
        georef_override.get("reason") or ""
    )
    run_meta["auto_georeference_override_path"] = str(
        georef_override.get("auto_xodr_path_after") or ""
    )


def _attach_auto_georef_metadata(
    full_report: Dict[str, Any],
    run_meta: Optional[Dict[str, Any]],
) -> None:
    if not isinstance(full_report, dict) or not isinstance(run_meta, dict):
        return
    if not bool(run_meta.get("auto_georeference_injected")):
        return
    full_report["auto_georeference_injected"] = True
    full_report["auto_georeference_warning"] = str(
        run_meta.get("auto_georeference_warning") or _AUTO_GEOREFERENCE_WARNING
    )


def _raise_on_invalid_auto_georef_alignment(
    transform: Any,
    georef_override: Optional[Dict[str, Any]],
) -> None:
    if not isinstance(georef_override, dict):
        return
    if not georef_override.get("auto_georeference_injected"):
        return
    bbox_iou_after = _extract_alignment_bbox_iou_after(transform)
    if bbox_iou_after is None or bbox_iou_after >= float(_AUTO_GEOREFERENCE_IOU_MIN):
        return
    raise RuntimeError(
        "CRS fallback produced near-zero bbox overlap "
        f"(IoU={float(bbox_iou_after):.4f}). The auto XODR coordinates are "
        "likely in a local frame and cannot be compared against the manual "
        "reference without pipeline preprocessing. Use the full-pipeline "
        "contract XODR from "
        "artifacts/final_runs/scenario_b_audit/contract_run/08_final_structural_gap.xodr "
        "instead of the raw cities/ingolstadt/ingolstadt_osm_auto.xodr."
    )


def _promote_auto_georef_if_needed(
    auto_xodr: str,
    manual_xodr: str,
    output_dir: str,
    log: logging.Logger,
) -> tuple[str, Optional[dict]]:
    if not auto_xodr or not Path(auto_xodr).is_file():
        return auto_xodr, None
    if not manual_xodr or not Path(manual_xodr).is_file():
        return auto_xodr, None
    manual_info = _read_georef_info(manual_xodr)
    auto_info = _read_georef_info(auto_xodr)
    offset = _read_header_offset(auto_xodr)
    canonical_auto_georef = _canonical_ingolstadt_auto_georeference(auto_xodr)
    if canonical_auto_georef and not auto_info.get("params_complete"):
        out_path = os.path.join(output_dir, "auto_georef_override.xodr")
        auto_hash_before = _hash_file_sha256(auto_xodr)
        manual_hash = _hash_file_sha256(manual_xodr)
        try:
            tree = ET.parse(auto_xodr)
            root = tree.getroot()
            header = root.find("header")
            if header is None:
                header = ET.SubElement(root, "header")
            geo = header.find("geoReference")
            if geo is None:
                geo = ET.SubElement(header, "geoReference")
            geo.text = canonical_auto_georef
            Path(os.path.dirname(out_path)).mkdir(parents=True, exist_ok=True)
            tree.write(out_path, encoding="utf-8", xml_declaration=True)
        except Exception as exc:
            log.warning(
                "Canonical Ingolstadt geoReference override failed (%s); using original auto_xodr",
                exc,
            )
            return auto_xodr, None
        auto_hash_after = _hash_file_sha256(out_path)
        override = {
            "reason": "auto_incomplete_promoted_to_canonical_ingolstadt_bbox",
            "auto_georeference_injected": True,
            "auto_georeference_warning": _AUTO_GEOREFERENCE_WARNING,
            "auto_xodr_path_before": str(Path(auto_xodr)),
            "auto_xodr_path_after": str(Path(out_path)),
            "manual_xodr_path": str(Path(manual_xodr)),
            "auto_georef_before": auto_info.get("norm") or "",
            "auto_georef_after": canonical_auto_georef,
            "manual_georef": manual_info.get("norm") or "",
            "auto_xodr_sha256_before": auto_hash_before,
            "auto_xodr_sha256_after": auto_hash_after,
            "manual_xodr_sha256": manual_hash,
            "offset": offset,
        }
        try:
            _safe_dump_json(os.path.join(output_dir, "georef_override.json"), override)
        except Exception:
            pass
        log.warning(
            "Auto geoReference incomplete; injected canonical Ingolstadt CRS only "
            "to attempt alignment. Coordinates may still be in a local frame and "
            "must pass the alignment IoU quality gate."
        )
        return out_path, override
    apply_override = (
        bool(manual_info.get("params_complete"))
        and bool(manual_info.get("norm"))
        and (not auto_info.get("params_complete"))
        and _offset_large(offset)
    )
    if not apply_override:
        return auto_xodr, None
    out_path = os.path.join(output_dir, "auto_georef_override.xodr")
    auto_hash_before = _hash_file_sha256(auto_xodr)
    manual_hash = _hash_file_sha256(manual_xodr)
    try:
        tree = ET.parse(auto_xodr)
        root = tree.getroot()
        header = root.find("header")
        if header is None:
            header = ET.SubElement(root, "header")
        geo = header.find("geoReference")
        if geo is None:
            geo = ET.SubElement(header, "geoReference")
        geo.text = normalize_georeference(manual_info.get("norm"))
        Path(os.path.dirname(out_path)).mkdir(parents=True, exist_ok=True)
        tree.write(out_path, encoding="utf-8", xml_declaration=True)
    except Exception as exc:
        log.warning("GeoReference override failed (%s); using original auto_xodr", exc)
        return auto_xodr, None
    auto_hash_after = _hash_file_sha256(out_path)
    override = {
        "reason": "auto_incomplete_large_offset_promoted_to_manual",
        "auto_georeference_injected": True,
        "auto_georeference_warning": _AUTO_GEOREFERENCE_WARNING,
        "auto_xodr_path_before": str(Path(auto_xodr)),
        "auto_xodr_path_after": str(Path(out_path)),
        "manual_xodr_path": str(Path(manual_xodr)),
        "auto_georef_before": auto_info.get("norm") or "",
        "auto_georef_after": normalize_georeference(manual_info.get("norm")),
        "manual_georef": manual_info.get("norm") or "",
        "auto_xodr_sha256_before": auto_hash_before,
        "auto_xodr_sha256_after": auto_hash_after,
        "manual_xodr_sha256": manual_hash,
        "offset": offset,
    }
    try:
        _safe_dump_json(os.path.join(output_dir, "georef_override.json"), override)
    except Exception:
        pass
    log.warning("Auto geoReference incomplete + large offset; promoted to manual CRS.")
    return out_path, override

def _offset_bake_applicable(offset: Optional[dict], tol: float = 1e-6) -> bool:
    if not isinstance(offset, dict):
        return False
    try:
        x = float(offset.get("x", 0.0))
        y = float(offset.get("y", 0.0))
        hdg = float(offset.get("hdg", 0.0))
    except Exception:
        return False
    if abs(hdg) > tol:
        return False
    return abs(x) > tol or abs(y) > tol


def _offset_matches_transform(offset: dict, transform: dict, tol: float = 1e-3) -> bool:
    try:
        x = float(offset.get("x", 0.0))
        y = float(offset.get("y", 0.0))
        scale = float(transform.get("scale", 1.0))
        c = float(transform.get("cos", 1.0))
        sn = float(transform.get("sin", 0.0))
        tx = float(transform.get("tx", 0.0))
        ty = float(transform.get("ty", 0.0))
    except Exception:
        return False
    if abs(scale - 1.0) > tol:
        return False
    if abs(c - 1.0) > tol or abs(sn) > tol:
        return False
    return abs(tx - x) <= tol and abs(ty - y) <= tol
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# ===================================================================
# Helpers
# ===================================================================
def _ensure_dir(p: str) -> str:
    os.makedirs(p, exist_ok=True)
    return p

def _hash_file_md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_file_sha256(path: str) -> str:
    """Return SHA-256 hex digest for a file (stable provenance fingerprint)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_signature(output_dir: str, rel_files: List[str]) -> None:
    sig: Dict[str, Any] = {
        "hash_algorithm": "sha256",
        "files": {},
    }
    for rel in rel_files:
        path = os.path.join(output_dir, rel)
        if os.path.isfile(path):
            try:
                sig["files"][rel] = _hash_file_sha256(path)
            except Exception:
                sig["files"][rel] = None
    _safe_dump_json(os.path.join(output_dir, "signature.json"), sig)

def _file_fingerprint(path: str) -> dict:
    """Stable, thesis-friendly fingerprint of a file (identity proof)."""
    try:
        st = os.stat(path)
        return {
            "path": os.path.abspath(path),
            "size_bytes": int(st.st_size),
            "mtime_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime)),
            "md5": _hash_file_md5(path),
            "sha256": _hash_file_sha256(path),
        }
    except Exception as e:
        return {"path": str(path), "error": str(e)}


def _find_tile_manifest(tiles_dir: str) -> Optional[Path]:
    if not tiles_dir:
        return None
    candidates = [
        Path(tiles_dir) / "tile_manifest.json",
        Path(tiles_dir).parent / "tile_manifest.json",
    ]
    for cand in candidates:
        try:
            if cand.is_file():
                return cand
        except Exception:
            continue
    return None


def _read_tile_manifest_proj4(path: Optional[Path]) -> str:
    if path is None or not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return str(data.get("proj4_norm") or "")
    except Exception:
        return ""


def _read_tile_manifest(path: Optional[Path]) -> Optional[dict]:
    if path is None or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _read_tiles_dir_proj4(tiles_dir: str) -> str:
    if not tiles_dir:
        return ""
    try:
        tile_paths = sorted(Path(tiles_dir).glob("tile_*.xodr"))
    except Exception:
        return ""
    for tile_path in tile_paths:
        info = _read_georef_info(str(tile_path))
        norm = str((info or {}).get("norm") or "").strip()
        if norm:
            return norm
    return ""


def _grid_info_from_manifest(manifest: Optional[dict]) -> Optional[dict]:
    if not isinstance(manifest, dict):
        return None
    return {
        "proj4_norm": manifest.get("proj4_norm"),
        "proj4_params_complete": manifest.get("proj4_params_complete"),
        "origin_x": manifest.get("origin_x"),
        "origin_y": manifest.get("origin_y"),
        "tile_size_m": manifest.get("tile_size_m"),
        "buffer_m": manifest.get("buffer_m"),
        "frame_method": manifest.get("frame_method"),
        "transform": manifest.get("transform"),
        "tiles_dir": manifest.get("tiles_dir"),
    }


def _tile_bounds_from_xodr(xodr_path: str) -> Optional[Tuple[float, float, float, float]]:
    try:
        tree = ET.parse(xodr_path)
        root = tree.getroot()
    except Exception:
        return None

    xs, ys = [], []
    for geom in root.findall(".//planView/geometry"):
        x = geom.get("x")
        y = geom.get("y")
        if x is None or y is None:
            continue
        try:
            xs.append(float(x))
            ys.append(float(y))
        except Exception:
            continue
    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _load_tile_bounds(tiles_dir: str) -> Dict[str, Tuple[float, float, float, float]]:
    meta_path = _find_tile_metadata(tiles_dir)
    manifest_path = _find_tile_manifest(tiles_dir)
    if manifest_path and manifest_path.is_file():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8", errors="replace"))
            tiles = data.get("tiles", [])
            out: Dict[str, Tuple[float, float, float, float]] = {}
            if isinstance(tiles, list) and tiles:
                for t in tiles:
                    if not isinstance(t, dict):
                        continue
                    name = t.get("id") or t.get("file")
                    bbox = t.get("bbox") or {}
                    if not name or not isinstance(bbox, dict):
                        continue
                    try:
                        out[name] = (
                            float(bbox["min_x"]),
                            float(bbox["min_y"]),
                            float(bbox["max_x"]),
                            float(bbox["max_y"]),
                        )
                    except Exception:
                        continue
                if out:
                    return out
        except Exception:
            pass

    if meta_path and meta_path.is_file():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8", errors="replace"))
            out: Dict[str, Tuple[float, float, float, float]] = {}
            for k, v in data.items():
                if not isinstance(k, str) or k.startswith("_") or not isinstance(v, dict):
                    continue
                b = v.get("bounds")
                if isinstance(b, (list, tuple)) and len(b) == 4:
                    try:
                        out[k] = (float(b[0]), float(b[1]), float(b[2]), float(b[3]))
                        continue
                    except Exception:
                        pass
                bb = v.get("bbox")
                if isinstance(bb, dict):
                    try:
                        out[k] = (
                            float(bb["min_x"]),
                            float(bb["min_y"]),
                            float(bb["max_x"]),
                            float(bb["max_y"]),
                        )
                    except Exception:
                        pass
            return out
        except Exception:
            pass

    # Final fallback: compute bounds from tile_*.xodr
    out: Dict[str, Tuple[float, float, float, float]] = {}
    try:
        if tiles_dir and os.path.isdir(tiles_dir):
            for fn in sorted(os.listdir(tiles_dir)):
                if not fn.lower().endswith(".xodr"):
                    continue
                b = _tile_bounds_from_xodr(os.path.join(tiles_dir, fn))
                if b:
                    out[fn] = b
    except Exception:
        pass
    return out


def _is_degenerate_bbox(b: Tuple[float, float, float, float], eps: float = 1e-6) -> bool:
    try:
        ax1, ay1, ax2, ay2 = b
        if not all(np.isfinite([ax1, ay1, ax2, ay2])):
            return True
        return (ax2 - ax1) <= eps or (ay2 - ay1) <= eps
    except Exception:
        return True


def _bbox_iou(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(ix2 - ix1, 0.0)
    ih = max(iy2 - iy1, 0.0)
    inter = iw * ih
    area_a = max(ax2 - ax1, 0.0) * max(ay2 - ay1, 0.0)
    area_b = max(bx2 - bx1, 0.0) * max(by2 - by1, 0.0)
    union = area_a + area_b - inter
    if union <= 0.0:
        return 0.0
    return float(inter / union)


def _write_tile_correspondence_csv(
    out_path: Path,
    matches: dict,
    *,
    min_iou: float,
) -> None:
    rows = []
    for manual_tile in sorted(matches.keys()):
        v = matches.get(manual_tile) or {}
        match = v.get("match") or v.get("auto_tile")
        iou = v.get("iou")
        status = v.get("status")
        centroid_dist_deg = v.get("centroid_dist_deg")
        match_quality = v.get("match_quality")
        if not match_quality:
            good = bool(match) and isinstance(iou, (int, float)) and float(iou) >= float(min_iou)
            match_quality = "good" if good else "low_iou"
        rows.append({
            "manual_tile": manual_tile,
            "auto_tile": match or "",
            "centroid_dist_deg": centroid_dist_deg,
            "iou": iou,
            "match_quality": match_quality,
            "status": status or "",
        })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        f.write("manual_tile,auto_tile,centroid_dist_deg,iou,match_quality,status\n")
        for r in rows:
            f.write(
                f"{r['manual_tile']},{r['auto_tile']},{r['centroid_dist_deg'] if r['centroid_dist_deg'] is not None else ''},"
                f"{r['iou'] if r['iou'] is not None else ''},{r['match_quality']},{r['status']}\n"
            )

def _find_tile_metadata(tiles_dir: str) -> Optional[Path]:
    """Return tile_metadata.json for a tiles directory (or parent) if present."""
    if not tiles_dir:
        return None
    candidates = [
        Path(tiles_dir) / "tile_metadata.json",
        Path(tiles_dir).parent / "tile_metadata.json",
    ]
    for cand in candidates:
        try:
            if cand.is_file():
                return cand
        except Exception:
            continue
    return None


def _validate_tiler_outputs(out_root: Path) -> Tuple[bool, str, Optional[Path]]:
    tiles_dir = out_root / "tiles"
    meta_path = out_root / "tile_metadata.json"
    manifest_path = out_root / "tile_manifest.json"
    diag_path = out_root / "tiler_diagnostics.json"

    if not tiles_dir.is_dir():
        return False, f"tiles_dir missing: {tiles_dir}", diag_path if diag_path.is_file() else None
    tile_files = sorted(p for p in tiles_dir.glob("tile_*.xodr"))
    if not tile_files:
        return False, f"no tile_*.xodr under {tiles_dir}", diag_path if diag_path.is_file() else None
    if not meta_path.is_file():
        return False, f"tile_metadata.json missing: {meta_path}", diag_path if diag_path.is_file() else None
    if not manifest_path.is_file():
        return False, f"tile_manifest.json missing: {manifest_path}", diag_path if diag_path.is_file() else None
    if not diag_path.is_file():
        return False, f"tiler_diagnostics.json missing: {diag_path}", None

    try:
        data = json.loads(meta_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return False, f"tile_metadata.json unreadable: {meta_path}", diag_path
    if not isinstance(data, dict):
        return False, f"tile_metadata.json invalid: {meta_path}", diag_path
    entries = {k: v for k, v in data.items() if isinstance(k, str) and not k.startswith("_") and isinstance(v, dict)}
    if not entries:
        return False, f"tile_metadata.json has no tile entries: {meta_path}", diag_path
    for k, v in entries.items():
        b = v.get("bounds")
        if not (isinstance(b, (list, tuple)) and len(b) == 4):
            return False, f"tile_metadata.json missing bounds for {k}", diag_path
        try:
            _ = [float(x) for x in b]
        except Exception:
            return False, f"tile_metadata.json invalid bounds for {k}", diag_path
    return True, "ok", diag_path


def _write_aligned_tile_metadata(
    aligned_dir: str,
    *,
    source_manifest: Optional[dict],
    proj4_norm: str,
    out_path: str,
) -> dict:
    tiles_dir = Path(aligned_dir)
    tiles = sorted([p for p in tiles_dir.glob("tile_*.xodr")])
    tile_entries = []
    bounds_list: list[Tuple[float, float, float, float]] = []
    for p in tiles:
        name = p.name
        b = _tile_bounds_from_xodr(str(p))
        if b:
            bounds_list.append(b)
        entry = {
            "id": name,
            "path": str(Path("tiles") / name),
            "bounds": list(b) if b else None,
            "sha256": _hash_file_sha256(str(p)),
        }
        tile_entries.append(entry)
    origin_x = origin_y = None
    if bounds_list:
        origin_x = min(b[0] for b in bounds_list)
        origin_y = min(b[1] for b in bounds_list)
    tile_size_m = source_manifest.get("tile_size_m") if isinstance(source_manifest, dict) else None
    buffer_m = source_manifest.get("buffer_m") if isinstance(source_manifest, dict) else None
    meta = {
        "schema_version": "1",
        "tiles_dir": str(tiles_dir),
        "origin_x": origin_x,
        "origin_y": origin_y,
        "tile_size_m": tile_size_m,
        "buffer_m": buffer_m,
        "proj4_norm": proj4_norm or "",
        "tiles": tile_entries,
    }
    _safe_dump_json(out_path, meta)
    return meta

def _is_dir_with_xodr(dir_path: str) -> bool:
    if not dir_path or not os.path.isdir(dir_path):
        return False
    try:
        return any(fn.lower().endswith(".xodr") for fn in os.listdir(dir_path))
    except Exception:
        return False


def _resolve_tiles_dir(dir_path: str) -> str:
    if not dir_path:
        return ""
    tiles_sub = os.path.join(dir_path, "tiles")
    if _is_dir_with_xodr(tiles_sub):
        return tiles_sub
    if _is_dir_with_xodr(dir_path):
        return dir_path
    return dir_path

def _is_identity_transform(transform: Any, tol: float = 1e-9) -> bool:
    """
    Detect identity / skipped alignment.
    Uses both diagnostics label and numeric tolerance on R/t/scale.
    """
    if not isinstance(transform, dict):
        return False
    diag_method = str(transform.get("diagnostics", {}).get("method", "")).lower()
    if diag_method == "identity":
        return True
    try:
        R = np.asarray(transform.get("R", []), dtype=float)
        t = np.asarray(transform.get("t", []), dtype=float).reshape(-1)
        scale = float(transform.get("scale", 1.0))
    except Exception:
        return False

    r_ok = R.shape == (2, 2) and np.allclose(R, np.eye(2), atol=tol)
    t_ok = t.shape[0] == 2 and np.allclose(t, np.zeros(2), atol=tol)
    s_ok = abs(scale - 1.0) <= tol
    return r_ok and t_ok and s_ok


def _apply_xodr_hardener(aligned_path: Path, hardened_path: Path, report_path: Path, logger: logging.Logger) -> tuple[bool, Dict[str, Any]]:
    """Run deterministic CARLA crash hardener; returns (applied, report)."""
    try:
        from ultimate_pipeline.tools import xodr_carla_hardener as hardener
    except Exception as e:  # pragma: no cover - import guard
        return False, {"error": f"import_failed:{e}"}

    try:
        report = hardener.harden_xodr(
            aligned_path,
            hardened_path,
            report_path=report_path,
        )
        return True, report
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("XODR hardener failed (%s)", e)
        return False, {"error": str(e)}


def _auto_generate_correspondence(manual_meta: Path, auto_meta: Path, out_dir: Path, logger: logging.Logger) -> tuple[Optional[Path], Optional[str]]:
    """Generate a correspondence CSV via evaluate_tiling.py (deterministic parameters)."""
    try:
        from ultimate_pipeline.tools import evaluate_tiling
    except Exception as e:  # pragma: no cover - import guard
        return None, f"import_failed:{e}"

    try:
        args = argparse.Namespace(
            a_meta=str(manual_meta),
            b_meta=str(auto_meta),
            a_metrics=None,
            b_metrics=None,
            out=str(out_dir),
            max_dist_mult=3.0,
            min_iou=0.01,
            estimate_translation=True,
            bootstrap_loose=True,
            min_bootstrap_matches=5,
        )
        evaluate_tiling.evaluate(args)
        corr_path = out_dir / "correspondence.csv"
        if corr_path.is_file():
            return corr_path, None
        return None, "correspondence.csv not produced"
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Auto tile correspondence generation failed (%s)", e)
        return None, str(e)


def _format_cmd(cmd: list[str]) -> str:
    try:
        import shlex
        return shlex.join(cmd)
    except Exception:
        return ' '.join(cmd)


def _read_origin_from_meta(path: Optional[Path]) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    if not path or not Path(path).is_file():
        return None, None, None, None
    try:
        from ultimate_pipeline.tools import tile_manual_xodr_windows as _tmx
        return _tmx._read_origin_from_meta(Path(path))
    except Exception:
        return None, None, None, None


def _write_inferred_tile_origin_meta(tiles_dir: str, out_path: Path) -> Optional[Path]:
    if not tiles_dir or not Path(tiles_dir).is_dir():
        return None

    manifest_path = _find_tile_manifest(tiles_dir)
    if manifest_path and manifest_path.is_file():
        ox, oy, ts, bm = _read_origin_from_meta(manifest_path)
        if ox is not None and oy is not None:
            return manifest_path

    metadata_path = _find_tile_metadata(tiles_dir)
    tile_size_m = 500.0
    buffer_m = 50.0
    entries: list[tuple[int, int, float, float]] = []

    if metadata_path and metadata_path.is_file():
        try:
            data = json.loads(metadata_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            data = {}
        if isinstance(data, dict):
            settings_snapshot = data.get("_settings_snapshot")
            if isinstance(settings_snapshot, dict):
                tile_size_m = float(settings_snapshot.get("TILE_SIZE_M", tile_size_m) or tile_size_m)
                buffer_m = float(settings_snapshot.get("TILE_BUFFER_M", buffer_m) or buffer_m)
            for name, entry in data.items():
                if not isinstance(name, str) or name.startswith("_") or not isinstance(entry, dict):
                    continue
                try:
                    i = int(entry.get("i"))
                    j = int(entry.get("j"))
                    bounds = entry.get("bounds")
                    if isinstance(bounds, (list, tuple)) and len(bounds) == 4:
                        min_x = float(bounds[0])
                        min_y = float(bounds[1])
                        entries.append((i, j, min_x, min_y))
                except Exception:
                    continue

    if not entries:
        for tile_path in sorted(Path(tiles_dir).glob("tile_*.xodr")):
            name = tile_path.name
            match = re.search(r"tile_(\d+)_(\d+)\.xodr$", name)
            if not match:
                continue
            bounds = _tile_bounds_from_xodr(str(tile_path))
            if not bounds:
                continue
            entries.append((int(match.group(1)), int(match.group(2)), float(bounds[0]), float(bounds[1])))
            break

    if not entries:
        return None

    i, j, min_x, min_y = entries[0]
    origin_x = float(min_x - (i * tile_size_m))
    origin_y = float(min_y - (j * tile_size_m))
    payload = {
        "schema_version": "1",
        "origin_x": origin_x,
        "origin_y": origin_y,
        "tile_size_m": float(tile_size_m),
        "buffer_m": float(buffer_m),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def _manual_tiles_fix_command(reference_xodr: str, output_dir: str, auto_meta_path: Optional[Path]) -> str:
    if not reference_xodr or not auto_meta_path:
        return ''
    out_dir = os.path.join(output_dir, 'manual_tiles_aligned')
    cmd = [
        sys.executable,
        '-m',
        'ultimate_pipeline.tools.tile_manual_xodr_windows',
        '--xodr',
        reference_xodr,
        '--out',
        out_dir,
        '--origin-from-meta',
        str(auto_meta_path),
    ]
    return _format_cmd(cmd)


def _auto_generate_aligned_manual_tiles(
    reference_xodr: str,
    auto_meta_path: Optional[Path],
    output_dir: str,
    logger: logging.Logger,
) -> Optional[str]:
    if not reference_xodr or not Path(reference_xodr).is_file():
        return None
    if not auto_meta_path or not Path(auto_meta_path).is_file():
        return None
    out_root = Path(output_dir) / 'manual_tiles_aligned'
    tiles_dir = out_root / 'tiles'
    if _is_dir_with_xodr(str(tiles_dir)):
        ok, reason, diag_path = _validate_tiler_outputs(out_root)
        if ok:
            return str(tiles_dir)
        diag_msg = f" See diagnostics: {diag_path}" if diag_path else ""
        logger.error("Existing manual tiles invalid (%s).%s", reason, diag_msg)
        return None
    try:
        out_root.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None
    log_path = out_root / 'manual_tiles_aligned.log'
    cmd = [
        sys.executable,
        '-m',
        'ultimate_pipeline.tools.tile_manual_xodr_windows',
        '--xodr',
        str(reference_xodr),
        '--out',
        str(out_root),
        '--origin-from-meta',
        str(auto_meta_path),
    ]
    if ".venv" not in (sys.executable or "").lower():
        logger.warning(
            "Auto-retile uses interpreter: %s (expected .venv\\Scripts\\python.exe).",
            sys.executable,
        )
    logger.info('Auto-generating aligned manual tiles via: %s', _format_cmd(cmd))
    try:
        import subprocess
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=300, # Added timeout to prevent indefinite hangs
        )
        try:
            log_path.write_text(result.stdout or '', encoding='utf-8')
        except Exception:
            pass
        if result.returncode != 0:
            logger.error('Manual tiling failed (rc=%s). See %s', result.returncode, log_path)
            return None
    except Exception as exc:
        logger.error('Manual tiling failed (%s)', exc)
        return None
    if _is_dir_with_xodr(str(tiles_dir)):
        ok, reason, diag_path = _validate_tiler_outputs(out_root)
        if ok:
            logger.info('Aligned manual tiles ready: %s', tiles_dir)
            return str(tiles_dir)
        diag_msg = f" See diagnostics: {diag_path}" if diag_path else ""
        logger.error('Manual tiling produced invalid output (%s).%s', reason, diag_msg)
        return None
    logger.error('Manual tiling produced no tiles under %s', tiles_dir)
    return None


def _rewrite_xodr_georef(xodr_path: Path, proj4_norm: str) -> None:
    tree = ET.parse(str(xodr_path))
    root = tree.getroot()
    header = root.find("header")
    if header is None:
        header = ET.SubElement(root, "header")
    geo = header.find("geoReference")
    if geo is None:
        geo = ET.SubElement(header, "geoReference")
    geo.text = normalize_georeference(proj4_norm)
    tree.write(str(xodr_path), encoding="utf-8", xml_declaration=True)


def _rewrite_tiles_crs(output_root: Path, proj4_norm: str) -> None:
    normalized = normalize_georeference(proj4_norm)
    tiles_dir = output_root / "tiles"
    for tile_path in sorted(tiles_dir.glob("tile_*.xodr")):
        _rewrite_xodr_georef(tile_path, normalized)

    manifest_path = output_root / "tile_manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(manifest, dict):
                manifest["proj4_norm"] = normalized
                manifest["proj4_params_complete"] = True
                manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        except Exception:
            pass


def _auto_generate_tiles_from_xodr(
    source_xodr: str,
    output_root: Path,
    logger: logging.Logger,
    *,
    origin_from_meta: Optional[Path] = None,
    proj4_override: Optional[str] = None,
) -> Optional[str]:
    if not source_xodr or not Path(source_xodr).is_file():
        return None
    tiles_dir = output_root / "tiles"
    meta_path = output_root / "tile_metadata.json"
    if _is_dir_with_xodr(str(tiles_dir)) and meta_path.is_file():
        ok, reason, diag_path = _validate_tiler_outputs(output_root)
        if ok:
            if proj4_override:
                try:
                    _rewrite_tiles_crs(output_root, proj4_override)
                except Exception as exc:
                    logger.warning("Failed to rewrite reused auto tiles CRS (%s)", exc)
            return str(output_root)
        diag_msg = f" See diagnostics: {diag_path}" if diag_path else ""
        logger.error("Existing auto tiles invalid (%s).%s", reason, diag_msg)
        return None
    try:
        output_root.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None
    log_path = output_root / "auto_tiles_promoted.log"
    cmd = [
        sys.executable,
        "-m",
        "ultimate_pipeline.tools.tile_manual_xodr_windows",
        "--xodr",
        str(source_xodr),
        "--out",
        str(output_root),
    ]
    if origin_from_meta and origin_from_meta.is_file():
        cmd.extend(["--origin-from-meta", str(origin_from_meta)])
    logger.info("Auto-tiling via: %s", _format_cmd(cmd))
    try:
        import subprocess

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300, # Added timeout to prevent indefinite hangs
        )
        try:
            log_path.write_text(result.stdout or "", encoding="utf-8")
        except Exception:
            pass
        if result.returncode != 0:
            logger.error("Auto-tiling failed (rc=%s). See %s", result.returncode, log_path)
            return None
    except Exception as exc:
        logger.error("Auto-tiling failed (%s)", exc)
        return None
    ok, reason, diag_path = _validate_tiler_outputs(output_root)
    if ok:
        if proj4_override:
            try:
                _rewrite_tiles_crs(output_root, proj4_override)
            except Exception as exc:
                logger.warning("Failed to rewrite generated auto tiles CRS (%s)", exc)
        return str(output_root)
    diag_msg = f" See diagnostics: {diag_path}" if diag_path else ""
    logger.error("Auto-tiling produced invalid output (%s).%s", reason, diag_msg)
    return None


def _grid_bounds_from_tiles_dir(tiles_dir: str) -> dict:
    bounds = _load_tile_bounds(tiles_dir)
    if not bounds:
        return {"min_x": None, "min_y": None, "max_x": None, "max_y": None}
    min_x = min(v[0] for v in bounds.values())
    min_y = min(v[1] for v in bounds.values())
    max_x = max(v[2] for v in bounds.values())
    max_y = max(v[3] for v in bounds.values())
    return {"min_x": float(min_x), "min_y": float(min_y), "max_x": float(max_x), "max_y": float(max_y)}


def _summarize_correspondence_rejections(
    rows: list[dict],
    manual_tiles: str,
    auto_tiles: str,
    min_iou: Optional[float],
    max_rows: int = 5,
) -> list[dict]:
    out: list[dict] = []
    if not rows:
        return out
    manual_bounds = _load_tile_bounds(manual_tiles)
    auto_bounds = _load_tile_bounds(auto_tiles)
    for r in rows[:max_rows]:
        reasons: list[str] = []
        mq = r.get('match_quality')
        if mq and mq != 'good':
            reasons.append(f'match_quality={mq}')
        iou = r.get('iou')
        if iou is None:
            reasons.append('iou_missing')
        elif min_iou is not None and isinstance(iou, (int, float)) and iou < float(min_iou):
            reasons.append(f'iou_below_min_iou({float(iou):.3f}<{float(min_iou):.3f})')
        m_id = _normalize_tile_id(r.get('a_id') or '', manual_tiles)
        a_id = _normalize_tile_id(r.get('b_id') or '', auto_tiles)
        mb = manual_bounds.get(m_id)
        ab = auto_bounds.get(a_id)
        if mb is None and m_id:
            mb = _tile_bounds_from_xodr(os.path.join(manual_tiles, m_id))
        if ab is None and a_id:
            ab = _tile_bounds_from_xodr(os.path.join(auto_tiles, a_id))
        if not mb or not ab:
            reasons.append('bbox_missing')
        else:
            iou_bbox = _bbox_iou(mb, ab)
            if isinstance(iou_bbox, (int, float)) and iou_bbox <= 0.0:
                reasons.append('bbox_no_overlap')
        out.append({
            'a_id': r.get('a_id'),
            'b_id': r.get('b_id'),
            'iou': r.get('iou'),
            'distance': r.get('distance'),
            'match_quality': r.get('match_quality'),
            'reasons': reasons,
        })
    return out


def _one_to_one_from_corr_rows(
    rows: list[dict],
    manual_tiles: str,
    auto_tiles: str,
    *,
    min_iou: float,
) -> Tuple[Dict[str, dict], Dict[str, Any]]:
    manual_bounds = _load_tile_bounds(manual_tiles)
    auto_bounds = _load_tile_bounds(auto_tiles)
    excluded_manual: Dict[str, str] = {}
    excluded_auto: Dict[str, str] = {}

    for m_id, b in manual_bounds.items():
        if b is None or _is_degenerate_bbox(b):
            excluded_manual[m_id] = "bbox_degenerate"
    for a_id, b in auto_bounds.items():
        if b is None or _is_degenerate_bbox(b):
            excluded_auto[a_id] = "bbox_degenerate"

    def _area(b: Tuple[float, float, float, float]) -> float:
        ax1, ay1, ax2, ay2 = b
        return max(ax2 - ax1, 0.0) * max(ay2 - ay1, 0.0)

    def _median(vals: list[float]) -> Optional[float]:
        if not vals:
            return None
        vals = sorted(vals)
        mid = len(vals) // 2
        if len(vals) % 2 == 1:
            return vals[mid]
        return 0.5 * (vals[mid - 1] + vals[mid])

    ratio_thresh = float(getattr(SETTINGS, "TILE_DEGENERATE_AREA_RATIO", 1e3))
    manual_areas = [_area(b) for k, b in manual_bounds.items() if k not in excluded_manual and _area(b) > 0.0]
    auto_areas = [_area(b) for k, b in auto_bounds.items() if k not in excluded_auto and _area(b) > 0.0]
    manual_med = _median(manual_areas)
    auto_med = _median(auto_areas)
    if manual_med:
        for k, b in manual_bounds.items():
            if k in excluded_manual:
                continue
            ratio = _area(b) / float(manual_med) if manual_med else 1.0
            if ratio >= ratio_thresh or ratio <= (1.0 / ratio_thresh):
                excluded_manual[k] = "bbox_area_ratio"
    if auto_med:
        for k, b in auto_bounds.items():
            if k in excluded_auto:
                continue
            ratio = _area(b) / float(auto_med) if auto_med else 1.0
            if ratio >= ratio_thresh or ratio <= (1.0 / ratio_thresh):
                excluded_auto[k] = "bbox_area_ratio"

    candidates: list[tuple[float, str, str]] = []
    candidates_list: list[dict] = []
    for r in rows:
        m_id = _normalize_tile_id(r.get("a_id") or "", manual_tiles)
        a_id = _normalize_tile_id(r.get("b_id") or "", auto_tiles)
        if not m_id or not a_id:
            continue
        if m_id not in manual_bounds:
            excluded_manual.setdefault(m_id, "bbox_missing")
            continue
        if a_id not in auto_bounds:
            excluded_auto.setdefault(a_id, "bbox_missing")
            continue
        if m_id in excluded_manual or a_id in excluded_auto:
            continue
        iou = r.get("iou")
        if not isinstance(iou, (int, float)):
            mb = manual_bounds.get(m_id)
            ab = auto_bounds.get(a_id)
            if mb and ab:
                iou = _bbox_iou(mb, ab)
        if not isinstance(iou, (int, float)):
            continue
        if float(iou) < float(min_iou):
            continue
        candidates.append((float(iou), a_id, m_id))
        candidates_list.append({"manual": m_id, "auto": a_id, "iou": round(float(iou), 6)})

    candidates.sort(key=lambda t: (-t[0], t[1], t[2]))

    used_manual: set[str] = set()
    used_auto: set[str] = set()
    collisions_resolved = 0
    corr_map: Dict[str, dict] = {}
    matches_list: list[dict] = []

    for iou, a_id, m_id in candidates:
        if m_id in used_manual or a_id in used_auto:
            collisions_resolved += 1
            continue
        used_manual.add(m_id)
        used_auto.add(a_id)
        corr_map[m_id] = {
            "auto_tile": a_id,
            "iou": round(float(iou), 4),
            "match_quality": "good",
        }
        matches_list.append({"manual": m_id, "auto": a_id, "iou": round(float(iou), 6), "status": "matched_by_iou"})

    unmatched_manual = len([m for m in manual_bounds.keys() if m not in used_manual and m not in excluded_manual])
    unmatched_auto = len([a for a in auto_bounds.keys() if a not in used_auto and a not in excluded_auto])

    report = {
        "excluded_auto_tiles": sorted(excluded_auto.keys()),
        "excluded_manual_tiles": sorted(excluded_manual.keys()),
        "exclusion_reasons": {**excluded_auto, **excluded_manual},
        "min_iou": float(min_iou),
        "area_ratio_threshold": float(ratio_thresh),
        "pairing_method": "greedy",
        "num_candidates": len(candidates),
        "num_matches": len(used_manual),
        "collisions_resolved": int(collisions_resolved),
        "unmatched": {"manual": int(unmatched_manual), "auto": int(unmatched_auto)},
        "candidates": candidates_list,
        "matches": matches_list,
    }
    return corr_map, report


def _align_tiles_dir(
    auto_tiles_dir: str,
    out_dir: str,
    transform: dict,
    logger: logging.Logger,
    *,
    offset_bake: Optional[dict] = None,
    use_alignment: bool = True,
) -> str:
    """Prepare auto tiles for per-tile comparison (optional offset bake + alignment)."""
    if not auto_tiles_dir or not os.path.isdir(auto_tiles_dir):
        return auto_tiles_dir

    aligned_dir = os.path.join(out_dir, "auto_tiles_aligned")
    os.makedirs(aligned_dir, exist_ok=True)

    # Sorted for deterministic processing across filesystems
    for fn in sorted(f for f in os.listdir(auto_tiles_dir) if f.lower().endswith(".xodr")):
        src = os.path.join(auto_tiles_dir, fn)
        dst = os.path.join(aligned_dir, fn)
        try:
            if offset_bake and _offset_bake_applicable(offset_bake):
                tmp = os.path.join(aligned_dir, f"__offset_tmp__{fn}")
                ok = _translate_planview_geometry(
                    src,
                    tmp,
                    float(offset_bake.get("x", 0.0)),
                    float(offset_bake.get("y", 0.0)),
                    zero_header_offset=True,
                )
                if not ok:
                    raise RuntimeError("offset_bake_failed")
                if use_alignment:
                    GeoAligner.apply_to_xodr(tmp, dst, transform)
                else:
                    shutil.copy2(tmp, dst)
                try:
                    os.remove(tmp)
                except Exception:
                    pass
            elif use_alignment:
                GeoAligner.apply_to_xodr(src, dst, transform)
            else:
                shutil.copy2(src, dst)
        except Exception as e:
            # Keep pipeline robust: fall back to copying the original tile
            try:
                shutil.copy2(src, dst)
            except Exception:
                logger.debug("Failed to copy tile fallback for %s (%s)", fn, e)

    return aligned_dir



def _normalize_tile_matches(tile_matches: Any) -> Dict[str, Dict[str, Any]]:
    """Normalize tile matching output to a *rich* dict.

    We keep IoU and status because per-tile metrics need them.

    Returns: manual_tile_filename -> {"match": <auto_tile_filename|None>, "iou": <float|None>, "status": <str|None>}
    """
    out: Dict[str, Dict[str, Any]] = {}
    if tile_matches is None:
        return out

    def _as_entry(match: Any, iou: Any = None, status: Any = None) -> Dict[str, Any]:
        return {
            "match": match if isinstance(match, str) else None,
            "iou": float(iou) if isinstance(iou, (int, float)) else None,
            "status": str(status) if status is not None else None,
        }

    if isinstance(tile_matches, dict):
        for manual, v in tile_matches.items():
            if isinstance(v, str):
                out[str(manual)] = _as_entry(v, None, "LEGACY_STR")
            elif isinstance(v, dict):
                # TileMatcher.match() style: {"match": "...", "iou": 0.73, "status": "MATCHED"}
                match = v.get("match") or v.get("auto_tile") or v.get("auto") or v.get("best_match")
                iou = v.get("iou") if "iou" in v else v.get("best_iou")
                status = v.get("status") or v.get("reason") or v.get("state")
                out[str(manual)] = _as_entry(match, iou, status)
            else:
                out[str(manual)] = _as_entry(None, None, f"INVALID_TYPE:{type(v).__name__}")
        return out

    if isinstance(tile_matches, list):
        # list[{"manual_tile": "...", "auto_tile": "...", "iou": 0.5, "status": "..."}]
        for item in tile_matches:
            if not isinstance(item, dict):
                continue
            manual = item.get("manual_tile") or item.get("manual") or item.get("m") or item.get("tile")
            match = item.get("match") or item.get("auto_tile") or item.get("auto") or item.get("a")
            iou = item.get("iou")
            status = item.get("status")
            if isinstance(manual, str):
                out[manual] = _as_entry(match, iou, status)
        return out

    return out


def _normalize_tile_match_info(tile_matches: Any) -> Dict[str, Dict[str, Any]]:
    """Normalize TileMatcher output into per-manual-tile info.

    Output:
      manual_tile -> {
        "auto_tile": str | None,
        "iou": float | None,
        "status": "matched" | "unmatched" | "invalid",
        "reason": str | None
      }
    """
    info: Dict[str, Dict[str, Any]] = {}
    if tile_matches is None:
        return info

    def _coerce_iou(v: Any) -> Optional[float]:
        if v is None:
            return None
        try:
            f = float(v)
            if f != f:  # NaN
                return None
            return f
        except Exception:
            return None

    if isinstance(tile_matches, dict):
        for k, v in tile_matches.items():
            if not isinstance(k, str):
                continue
            auto_tile = None
            iou = None
            status = "invalid"
            reason = None

            if isinstance(v, str):
                auto_tile = v
                status = "matched"
            elif isinstance(v, dict):
                auto_tile = v.get("auto_tile") or v.get("auto") or v.get("match") or v.get("matched_tile")
                iou = _coerce_iou(v.get("iou") or v.get("IoU") or v.get("overlap_iou"))
                if v.get("unmatched") is True or v.get("matched") is False or auto_tile is None:
                    status = "unmatched"
                else:
                    status = "matched"
                reason = v.get("reason")
            else:
                reason = f"unsupported matcher value type: {type(v)}"

            info[k] = {"auto_tile": auto_tile, "iou": iou, "status": status, "reason": reason}
        return info

    if isinstance(tile_matches, list):
        for item in tile_matches:
            if not isinstance(item, dict):
                continue
            manual = item.get("manual_tile") or item.get("manual") or item.get("tile_manual")
            if not isinstance(manual, str):
                continue
            auto_tile = item.get("auto_tile") or item.get("auto") or item.get("tile_auto")
            if not isinstance(auto_tile, str):
                auto_tile = None
            iou = _coerce_iou(item.get("iou") or item.get("IoU") or item.get("overlap_iou"))
            if item.get("unmatched") is True or item.get("matched") is False or auto_tile is None:
                status = "unmatched"
            else:
                status = "matched"
            reason = item.get("reason")
            info[manual] = {"auto_tile": auto_tile, "iou": iou, "status": status, "reason": reason}
        return info

    return info

def _dg_enabled(key: str, default: bool = True) -> bool:
    """
    Ablation switch for HPC experiments.
    If SETTINGS.DOMAIN_GAP_ENABLE is missing, everything defaults to enabled.
    """
    m = getattr(SETTINGS, "DOMAIN_GAP_ENABLE", None)
    if isinstance(m, dict):
        return bool(m.get(key, default))
    return default


def _get_norm_ref(metric_key: str, default_ref: float) -> float:
    """
    Central normalization contract.
    Put these into SETTINGS.DOMAIN_GAP_NORMALIZATION.
    """
    m = getattr(SETTINGS, "DOMAIN_GAP_NORMALIZATION", None)
    if isinstance(m, dict):
        try:
            v = float(m.get(metric_key, default_ref))
            return v if v > 0 else default_ref
        except Exception:
            return default_ref
    return default_ref


_NORMALIZATION_DEFAULTS: Dict[str, float] = {
    "geometry_rmse_m": 1.0,
    "hausdorff_m": 5.0,
    "curvature_kl": 0.5,
    "intersection_delta": 1.0,
    "semantic_delta": 1.0,
}


def _normalization_contract() -> Dict[str, Any]:
    configured = getattr(SETTINGS, "DOMAIN_GAP_NORMALIZATION", None)
    configured_dict = configured if isinstance(configured, dict) else None
    effective: Dict[str, float] = {}
    for key, default_val in _NORMALIZATION_DEFAULTS.items():
        effective[key] = float(_get_norm_ref(key, default_val))
    return {
        "source": "SETTINGS.DOMAIN_GAP_NORMALIZATION",
        "defaults": dict(_NORMALIZATION_DEFAULTS),
        "configured": configured_dict,
        "effective": effective,
    }


def _normalize(val: Any, ref: float) -> float:
    """
    Normalize to [0,1] using an explicit reference scale.
    Always clamps and always absolute.
    """
    if val is None:
        return 0.0
    try:
        v = float(val)
        r = float(ref)
        if r <= 0:
            return 0.0
        return min(abs(v) / r, 1.0)
    except Exception:
        return 0.0


def _safe_dump_json(path: str, obj: Any) -> None:
    try:
        out_dir = os.path.dirname(path)
        if out_dir:
            _ensure_dir(out_dir)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, sort_keys=True)
    except Exception as e:
        log.warning("Failed to write JSON %s (%s)", path, e)


def _compute_pair_metrics_diff(pair_metrics: Dict[str, Any]) -> Dict[str, Any]:
    manual = pair_metrics.get("manual", {}) if isinstance(pair_metrics, dict) else {}
    auto = pair_metrics.get("auto", {}) if isinstance(pair_metrics, dict) else {}

    def _safe_mean(values: list[float]) -> Optional[float]:
        if not values:
            return None
        return float(sum(values) / len(values))

    manual_counts = manual.get("camera", {}).get("total_frames")
    auto_counts = auto.get("camera", {}).get("total_frames")
    manual_int = list((manual.get("camera", {}).get("mean_intensity") or {}).values())
    auto_int = list((auto.get("camera", {}).get("mean_intensity") or {}).values())
    manual_int_mean = _safe_mean([v for v in manual_int if isinstance(v, (int, float))])
    auto_int_mean = _safe_mean([v for v in auto_int if isinstance(v, (int, float))])
    manual_lidar_med = manual.get("lidar", {}).get("point_counts", {}).get("median")
    auto_lidar_med = auto.get("lidar", {}).get("point_counts", {}).get("median")

    return {
        "delta_frame_counts": (
            auto_counts - manual_counts
            if isinstance(auto_counts, int) and isinstance(manual_counts, int)
            else None
        ),
        "delta_mean_intensity": (
            auto_int_mean - manual_int_mean
            if isinstance(auto_int_mean, (int, float)) and isinstance(manual_int_mean, (int, float))
            else None
        ),
        "delta_lidar_point_count_median": (
            auto_lidar_med - manual_lidar_med
            if isinstance(auto_lidar_med, (int, float)) and isinstance(manual_lidar_med, (int, float))
            else None
        ),
    }


def _load_pair_metrics_from_env() -> Optional[Dict[str, Any]]:
    path = os.getenv("UP_PERCEPTION_PAIR_METRICS_JSON", "").strip()
    if not path:
        return None
    if not os.path.isfile(path):
        log.warning("UP_PERCEPTION_PAIR_METRICS_JSON set but file missing: %s", path)
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "diff" not in data:
            data["diff"] = _compute_pair_metrics_diff(data)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        log.warning("Failed to load perception pair metrics (%s): %s", path, exc)
        return None


def _read_frame_diag(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _load_frame_labels(corr_path: Path) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Returns (label_a, label_b, source) from sibling frame diagnosis JSONs if present.

    source:
      - "split"    -> frame_diagnosis_a.json + frame_diagnosis_b.json
      - "combined" -> frame_diagnosis.json exists but cannot prove A/B compatibility
      - None       -> nothing found
    """
    base_dir = corr_path.parent
    fa = base_dir / "frame_diagnosis_a.json"
    fb = base_dir / "frame_diagnosis_b.json"
    fc = base_dir / "frame_diagnosis.json"

    if fa.is_file() and fb.is_file():
        da = _read_frame_diag(fa) or {}
        db = _read_frame_diag(fb) or {}
        return da.get("label"), db.get("label"), "split"

    if fc.is_file():
        # Combined file cannot prove A/B compatibility; treat as unknown for gating.
        return None, None, "combined"

    return None, None, None


def _try_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        s = str(x).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _get_tile_min_iou(default: float = 0.5) -> float:
    raw = os.getenv("UP_TILE_MIN_IOU", "").strip()
    if not raw:
        return float(default)
    try:
        return float(raw)
    except Exception:
        logging.getLogger(__name__).warning(
            "Invalid UP_TILE_MIN_IOU=%s; using default %.3f", raw, float(default)
        )
        return float(default)


def _median_float(values: list[float]) -> Optional[float]:
    if not values:
        return None
    vals = sorted(values)
    mid = len(vals) // 2
    if len(vals) % 2 == 1:
        return vals[mid]
    return 0.5 * (vals[mid - 1] + vals[mid])


def _compute_tile_pairing_stats(
    tile_pairing_report: Optional[Dict[str, Any]],
    tile_match_info: Dict[str, Dict[str, Any]],
) -> Tuple[Optional[float], Optional[float], float, int]:
    ious: list[float] = []
    if isinstance(tile_pairing_report, dict):
        for m in tile_pairing_report.get("matches", []) or []:
            if not isinstance(m, dict):
                continue
            iou = m.get("iou")
            if isinstance(iou, (int, float)):
                ious.append(float(iou))
    if not ious and isinstance(tile_match_info, dict):
        for v in tile_match_info.values():
            if not isinstance(v, dict):
                continue
            if v.get("status") != "matched":
                continue
            iou = v.get("iou")
            if isinstance(iou, (int, float)):
                ious.append(float(iou))

    avg_iou = (sum(ious) / len(ious)) if ious else None
    median_iou = _median_float(ious)

    num_matches = 0
    if isinstance(tile_pairing_report, dict):
        num_matches = int(tile_pairing_report.get("num_matches", 0) or 0)
    if num_matches == 0 and isinstance(tile_match_info, dict):
        num_matches = sum(1 for v in tile_match_info.values() if isinstance(v, dict) and v.get("status") == "matched")

    total_manual = None
    if isinstance(tile_pairing_report, dict):
        unmatched_manual = tile_pairing_report.get("unmatched", {}).get("manual")
        if isinstance(unmatched_manual, int):
            total_manual = num_matches + int(unmatched_manual)
    if total_manual is None and isinstance(tile_match_info, dict) and tile_match_info:
        total_manual = len(tile_match_info)

    if total_manual and total_manual > 0:
        match_ratio = float(num_matches) / float(total_manual)
    else:
        match_ratio = 0.0

    return avg_iou, median_iou, match_ratio, num_matches


def _build_tile_iou_gate_summary(
    rows: list[dict],
    *,
    iou_gate_threshold: float,
    tiles_passed_gate_count: int,
    tiles_gated_count: int,
    match_method: Optional[str] = None,
) -> Dict[str, Any]:
    observed_ious: list[float] = []
    observed_methods: set[str] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        iou = row.get("iou")
        try:
            if iou is not None:
                observed_ious.append(float(iou))
        except Exception:
            continue
        method = row.get("match_method")
        quality = row.get("match_quality")
        if isinstance(method, str) and method:
            observed_methods.add(method)
        elif quality == "fallback_index_match":
            observed_methods.add("index_fallback")
        else:
            observed_methods.add("centroid_spatial")

    resolved_method = match_method
    if not resolved_method:
        if observed_methods == {"index_fallback"}:
            resolved_method = "index_fallback"
        elif observed_methods:
            resolved_method = "centroid_spatial"

    return {
        "total_tile_pairs": int(len(rows or [])),
        "tiles_gated_count": int(tiles_gated_count),
        "tiles_passed_gate_count": int(tiles_passed_gate_count),
        "max_tile_iou_observed": max(observed_ious) if observed_ious else None,
        "mean_tile_iou_observed": (sum(observed_ious) / len(observed_ious)) if observed_ious else None,
        "iou_gate_threshold": float(iou_gate_threshold),
        "match_method": resolved_method,
    }


def _write_tile_iou_report(
    output_dir: str,
    *,
    rows: list[dict],
    summary: Dict[str, Any],
) -> str:
    path = os.path.join(output_dir, "tile_iou_report.json")
    _safe_dump_json(
        path,
        {
            "summary": summary,
            "rows": rows or [],
        },
    )
    return path


def _load_correspondence_csv(path: Path) -> List[dict]:
    """
    Supports schemas with a_tile_id/b_tile_id or a_id/b_id.
    Optional columns: distance, iou, match_quality (or quality/status), dx, dy.
    Returns deterministically sorted rows.
    """
    rows: List[dict] = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            a_id = (row.get("manual_tile") or row.get("a_tile_id") or row.get("a_id") or "").strip()
            b_id = (row.get("auto_tile") or row.get("b_tile_id") or row.get("b_id") or "").strip()
            if not a_id:
                continue

            q = row.get("match_quality") or row.get("quality") or row.get("status") or ""
            q = str(q).strip().lower() if q is not None else None

            rows.append({
                "a_id": a_id,
                "b_id": b_id,
                "distance": _try_float(row.get("centroid_dist_deg") or row.get("distance")),
                "iou": _try_float(row.get("iou")),
                "match_quality": q,
                "match_method": (row.get("match_method") or "").strip().lower() or None,
                "dx": _try_float(row.get("dx")),
                "dy": _try_float(row.get("dy")),
            })

    rows.sort(key=lambda r: (r["distance"] is None, r["distance"] if r["distance"] is not None else 0.0, r["a_id"], r["b_id"]))
    return rows


def _normalize_tile_id(tile_id: str, tiles_dir: str) -> str:
    """
    Ensure tile id carries .xodr if the file exists. Otherwise return original.
    """
    if not tiles_dir:
        return tile_id
    if tile_id.endswith(".xodr"):
        return tile_id
    candidate = os.path.join(tiles_dir, tile_id)
    if os.path.isfile(candidate):
        return tile_id
    with_ext = f"{tile_id}.xodr"
    if os.path.isfile(os.path.join(tiles_dir, with_ext)):
        return with_ext
    return tile_id


def _frames_incompatible(label_a: Optional[str], label_b: Optional[str]) -> bool:
    """
    Returns True only when both labels are known and differ.
    """
    if label_a and label_b:
        return label_a != label_b
    return False


def _looks_hash(s: str) -> bool:
    if not s:
        return False
    sl = len(s)
    if sl not in (40, 64):
        return False
    try:
        int(s, 16)
        return True
    except Exception:
        return False


def _bool_env(name: str, default: str = "0") -> bool:
    value = os.getenv(name, default)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _git_commit_hash(repo_root: Path) -> str:
    try:
        head = repo_root / ".git" / "HEAD"
        if not head.is_file():
            return "unknown"
        ref = head.read_text(encoding="utf-8").strip()
        if ref.startswith("ref:"):
            ref_path = repo_root / ".git" / ref.split(" ", 1)[1]
            if ref_path.is_file():
                return ref_path.read_text(encoding="utf-8").strip()
            packed = repo_root / ".git" / "packed-refs"
            if packed.is_file():
                target = ref.split(" ", 1)[1].strip()
                with packed.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or line.startswith("^"):
                            continue
                        parts = line.split()
                        if len(parts) == 2 and parts[1] == target and _looks_hash(parts[0]):
                            return parts[0]
        return ref
    except Exception:
        return "unknown"


def _write_run_readme(out_dir: str, script_name: str, inputs: Dict[str, Any]) -> None:
    lines: List[str] = [f"script: {script_name}",
                        f"timestamp_utc: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"]
    repo_root = Path(__file__).resolve().parents[1]
    lines.append(f"git_commit: {_git_commit_hash(repo_root)}")
    for k in sorted(inputs.keys()):
        lines.append(f"{k}: {inputs[k]}")
    try:
        path = Path(out_dir) / "README.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as e:
        log.warning("Failed to write README.txt (%s)", e)


def _safe_write_csv(path: str, rows: list[dict], headers: list[str]) -> None:
    try:
        out_dir = os.path.dirname(path)
        if out_dir:
            _ensure_dir(out_dir)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for row in rows:
                writer.writerow({h: row.get(h, "") for h in headers})
    except Exception as e:
        log.warning("Failed to write CSV %s (%s)", path, e)



def _auto_discover_perception_jsons(output_dir: str, manual_json: Optional[str], auto_json: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Try to find perception metrics JSONs near the run output folder.
    Heuristic: domain_gap output lives in <run_out>/domain_gap, so we search parent.
    """
    run_out = os.path.abspath(os.path.join(output_dir, os.pardir))
    cand_manual = [
        os.path.join(run_out, "perception_metrics_manual.json"),
        os.path.join(run_out, "perception_manual_metrics.json"),
        os.path.join(run_out, "perception_manual.json"),
    ]
    cand_auto = [
        os.path.join(run_out, "perception_metrics_auto.json"),
        os.path.join(run_out, "perception_auto_metrics.json"),
        os.path.join(run_out, "perception_auto.json"),
    ]

    if not manual_json:
        for p in cand_manual:
            if os.path.exists(p):
                manual_json = p
                break
    if not auto_json:
        for p in cand_auto:
            if os.path.exists(p):
                auto_json = p
                break
    return manual_json, auto_json


def _load_metrics_fallback(path: str) -> Dict[str, Any]:
    """Load metrics JSON in a tolerant way (works even if PerceptionEvaluator schema differs)."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _fallback_perception_gap(manual: Dict[str, Any], auto: Dict[str, Any]) -> Dict[str, Any]:
    """Schema-agnostic fallback: compute a simple distance between feature distributions.
    Supports either:
      - embeddings stored as list under key 'embeddings' (NxD)
      - mean vectors under 'mean' or 'feature_mean'
      - color histograms under 'hist'
    """
    def _get_mean(d: Dict[str, Any]) -> Optional[np.ndarray]:
        for k in ("feature_mean", "mean", "embedding_mean"):
            if k in d:
                v = np.asarray(d[k], dtype=float)
                return v
        if "embeddings" in d:
            arr = np.asarray(d["embeddings"], dtype=float)
            if arr.ndim == 2 and arr.shape[0] > 0:
                return arr.mean(axis=0)
        return None

    def _cosine(a: np.ndarray, b: np.ndarray) -> float:
        na = np.linalg.norm(a) + 1e-12
        nb = np.linalg.norm(b) + 1e-12
        return float(1.0 - (a @ b) / (na * nb))

    m = _get_mean(manual)
    a = _get_mean(auto)
    if m is not None and a is not None and m.shape == a.shape:
        return {
            "method": "cosine_distance(mean_embedding)",
            "cosine_distance": _cosine(m, a),
            "dim": int(m.shape[0]),
        }

    # histogram fallback
    if "hist" in manual and "hist" in auto:
        hm = np.asarray(manual["hist"], dtype=float)
        ha = np.asarray(auto["hist"], dtype=float)
        if hm.shape == ha.shape and hm.size > 0:
            hm = hm / (hm.sum() + 1e-12)
            ha = ha / (ha.sum() + 1e-12)
            l1 = float(np.abs(hm - ha).sum())
            return {"method": "l1_distance(hist)", "l1": l1, "bins": int(hm.size)}

    return {"method": "unavailable", "error": "No compatible keys found for fallback perception gap."}


def _call_intersection_gap(manual_xodr: str, auto_xodr: str) -> Dict[str, Any]:
    """
    Backwards/forwards compatibility:
      - some versions expose IntersectionGap.compute()
      - others expose IntersectionGap.compare()
    """
    if hasattr(IntersectionGap, "compute"):
        return IntersectionGap.compute(manual_xodr, auto_xodr)  # type: ignore
    if hasattr(IntersectionGap, "compare"):
        return IntersectionGap.compare(manual_xodr, auto_xodr)  # type: ignore
    raise AttributeError("IntersectionGap has neither compute() nor compare().")


def _call_semantic_gap(manual_xodr: str, auto_xodr: str) -> Dict[str, Any]:
    """
    Backwards/forwards compatibility:
      - some versions expose SemanticGap.compute()
      - others expose SemanticGap.compare()
    """
    if hasattr(SemanticGap, "compute"):
        return SemanticGap.compute(manual_xodr, auto_xodr)  # type: ignore
    if hasattr(SemanticGap, "compare"):
        return SemanticGap.compare(manual_xodr, auto_xodr)  # type: ignore
    raise AttributeError("SemanticGap has neither compute() nor compare().")


def _read_json_dict(path: Optional[Path]) -> Dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _discover_elevation_dem_qc_path(
    output_dir: str,
    *,
    generated_xodr: Optional[str] = None,
    run_root: Optional[str] = None,
) -> Optional[Path]:
    env_path = str(os.getenv("UP_ELEVATION_DEM_QC_JSON", "") or "").strip()
    candidates = []
    if env_path:
        candidates.append(Path(env_path).expanduser())
    out_dir = Path(output_dir)
    auto_run_env = str(
        os.getenv("UP_AUTO_RUN_DIR", "") or os.getenv("UP_AUTO_RUN_ROOT", "")
    ).strip()
    resolved_run_root = str(run_root or auto_run_env or "").strip()
    if resolved_run_root:
        run_root_path = Path(resolved_run_root).expanduser()
        candidates.extend(
            [
                run_root_path / "elevation_dem_qc.json",
                run_root_path / "domain_gap" / "elevation_dem_qc.json",
            ]
        )
    generated_xodr_path = str(generated_xodr or "").strip()
    if generated_xodr_path:
        generated_parent = Path(generated_xodr_path).expanduser().parent
        candidates.extend(
            [
                generated_parent / "elevation_dem_qc.json",
                generated_parent / "domain_gap" / "elevation_dem_qc.json",
            ]
        )
    candidates.extend(
        [
            out_dir / "elevation_dem_qc.json",
            out_dir.parent / "elevation_dem_qc.json",
        ]
    )
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.is_file():
            return candidate
    return None


def _discover_sumo_repair_meta_path(
    output_dir: str,
    *,
    generated_xodr: Optional[str] = None,
    run_root: Optional[str] = None,
) -> Optional[Path]:
    env_path = str(os.getenv("UP_SUMO_REPAIR_JSON", "") or "").strip()
    candidates: List[Path] = []
    if env_path:
        candidates.append(Path(env_path).expanduser())

    out_dir = Path(output_dir)
    auto_run_env = str(
        os.getenv("UP_AUTO_RUN_DIR", "") or os.getenv("UP_AUTO_RUN_ROOT", "")
    ).strip()
    resolved_run_root = str(run_root or auto_run_env or "").strip()
    if resolved_run_root:
        run_root_path = Path(resolved_run_root).expanduser()
        candidates.extend(
            [
                run_root_path / "sumo_repair.json",
                run_root_path / "domain_gap" / "sumo_repair.json",
            ]
        )

    generated_xodr_path = str(generated_xodr or "").strip()
    if generated_xodr_path:
        generated_parent = Path(generated_xodr_path).expanduser().parent
        candidates.extend(
            [
                generated_parent / "sumo_repair.json",
                generated_parent.parent / "sumo_repair.json",
            ]
        )
    candidates.extend(
        [
            out_dir / "sumo_repair.json",
            out_dir.parent / "sumo_repair.json",
        ]
    )

    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.is_file():
            return candidate
    return None


def _resolve_sumo_repair_meta(
    output_dir: str,
    *,
    generated_xodr: Optional[str] = None,
    run_root: Optional[str] = None,
    sumo_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if isinstance(sumo_meta, dict) and sumo_meta:
        return dict(sumo_meta)

    meta_path = _discover_sumo_repair_meta_path(
        output_dir,
        generated_xodr=generated_xodr,
        run_root=run_root,
    )
    payload = _read_json_dict(meta_path)
    if payload:
        return payload
    return {
        "enabled": "unknown_prebuilt_xodr",
        "note": "XODR was not generated in this run; SUMO stage unknown",
    }


_ALIGNMENT_FIT_METRIC_NOTE = (
    "Diagnostic metric (planView start-point RMSE); not proven equivalent to ICP "
    "optimization objective. Monotonic increase does not imply ICP failure - see "
    "chap7 alignment interpretation."
)


def _ensure_alignment_fit_metric_note(transform: Any) -> Any:
    if not isinstance(transform, dict):
        return transform
    diagnostics = transform.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return transform
    if diagnostics.get("fit_metric") and not diagnostics.get("fit_metric_note"):
        diagnostics["fit_metric_note"] = _ALIGNMENT_FIT_METRIC_NOTE
    return transform


def _disabled_elevation_gap(
    reason: str,
    *,
    dem_qc_path: Optional[Path] = None,
    dem_qc_ok: Optional[bool] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    reason_text = str(reason)
    payload: Dict[str, Any] = {
        "disabled": True,
        "reason": reason_text,
        "disabled_reason": _elevation_gap_disabled_reason(reason_text),
        "supplementary": True,
        "primary_artifact_is_planar": True,
        "dem_qc_ok": dem_qc_ok,
        "dem_qc_path": str(dem_qc_path) if dem_qc_path else None,
    }
    if error:
        payload["error"] = str(error)
    return payload


def _elevation_gap_disabled_reason(reason: str) -> str:
    normalized = str(reason).strip().lower()
    if normalized == "dem_qc_failed":
        return "DEM fallback used - excluded from composite per policy"
    if normalized == "auto_xodr_is_planar":
        return "auto XODR is planar - excluded from composite per policy"
    if normalized == "no_matched_roads":
        return "no matched roads - excluded from composite per policy"
    if normalized == "missing_road_profiles":
        return "missing road profiles - excluded from composite per policy"
    if normalized == "elevation_gap_failed":
        return "elevation gap computation failed - excluded from composite per policy"
    return f"{reason} - excluded from composite per policy"


def _thesis_strict_enabled() -> bool:
    try:
        from ultimate_pipeline.config.settings import SETTINGS

        if bool(getattr(SETTINGS, "THESIS_STRICT", False)):
            return True
    except Exception:
        pass
    return str(os.getenv("UP_THESIS_STRICT", "")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


_CONNECTIVITY_GAP_DEFINITION = "lane/junction connectivity fidelity between manual and auto maps"
_CONNECTIVITY_GAP_UNIT = "ratio [0,1]"


def _connectivity_default_reason(
    payload: Optional[Dict[str, Any]],
    *,
    run_meta: Optional[Dict[str, Any]] = None,
    default_reason: str = "metric_not_computed",
) -> str:
    data = payload if isinstance(payload, dict) else {}
    reason = str(data.get("reason", "") or "").strip()
    if reason:
        return reason
    error = str(data.get("error", "") or "").strip().lower()
    if error == "alignment_rmse_too_high":
        return "alignment_rmse_exceeded"
    if isinstance(run_meta, dict):
        if str(run_meta.get("manual_reference_status", "") or "").strip().lower() == "missing":
            return "manual_map_missing"
        if not str(run_meta.get("manual_xodr_resolved", "") or "").strip():
            return "manual_map_missing"
    return str(default_reason)


def _normalize_connectivity_gap_payload(
    payload: Optional[Dict[str, Any]],
    *,
    default_reason: str = "metric_not_computed",
    run_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized = dict(payload) if isinstance(payload, dict) else {}
    has_payload = bool(normalized)
    normalized.setdefault("definition", _CONNECTIVITY_GAP_DEFINITION)
    normalized.setdefault("unit", _CONNECTIVITY_GAP_UNIT)
    disabled = bool(normalized.get("disabled", False)) or not has_payload
    if disabled:
        normalized["disabled"] = True
        normalized["status"] = "skipped"
        normalized["reason"] = _connectivity_default_reason(
            normalized,
            run_meta=run_meta,
            default_reason=default_reason,
        )
    else:
        normalized.setdefault("disabled", False)
        normalized["status"] = "computed"
        normalized.setdefault("reason", "")
        # Backward-compat flat aliases (Gemini audit finding A):
        # Verifiers may read connectivity_gap.predecessor_rate / .successor_rate directly.
        # Emit flat aliases from the nested road_link sub-structure.
        _auto_rl = normalized.get("auto", {}).get("road_link", {}) if isinstance(normalized.get("auto"), dict) else {}
        _manual_rl = normalized.get("manual", {}).get("road_link", {}) if isinstance(normalized.get("manual"), dict) else {}
        if isinstance(_manual_rl, dict) and _manual_rl:
            normalized.setdefault("predecessor_rate", _manual_rl.get("predecessor_declared_rate"))
            normalized.setdefault("successor_rate", _manual_rl.get("successor_declared_rate"))
            normalized.setdefault("predecessor_declared_rate", _manual_rl.get("predecessor_declared_rate"))
            normalized.setdefault("successor_declared_rate", _manual_rl.get("successor_declared_rate"))
        if isinstance(_auto_rl, dict) and _auto_rl:
            normalized.setdefault("auto_predecessor_declared_rate", _auto_rl.get("predecessor_declared_rate"))
            normalized.setdefault("auto_successor_declared_rate", _auto_rl.get("successor_declared_rate"))
    return normalized


def _zero_tile_correspondence_override_enabled() -> bool:
    raw = str(
        os.getenv(
            "UP_ALLOW_ZERO_TILE_CORRESPONDENCE",
            os.getenv("UP_ALLOW_EMPTY_CORRESPONDENCE", ""),
        )
        or ""
    ).strip().lower()
    return raw in ("1", "true", "yes", "on")


def _enforce_nonempty_tile_correspondence(
    *,
    correspondence: Any,
    output_dir: Path | str,
    logger: logging.Logger,
) -> bool:
    n_pairs = len(correspondence) if hasattr(correspondence, "__len__") else 0
    if int(n_pairs) > 0:
        return True
    empty_csv = Path(output_dir) / "tile_correspondence_empty.csv"
    empty_csv.write_text("auto_tile,manual_tile,iou\n", encoding="utf-8")
    logger.warning(
        "[TILE] Zero tile correspondences. Empty CSV written to %s",
        empty_csv,
    )
    if _zero_tile_correspondence_override_enabled():
        logger.warning(
            "[TILE] UP_ALLOW_ZERO_TILE_CORRESPONDENCE=1 (or legacy UP_ALLOW_EMPTY_CORRESPONDENCE=1) - continuing with 0 pairs"
        )
        return False
    if _thesis_strict_enabled():
        raise RuntimeError(
            "zero_tile_correspondences: no tile pairs matched. "
            "Set UP_ALLOW_ZERO_TILE_CORRESPONDENCE=1 to override, "
            "or verify that auto and manual tile directories are correctly aligned."
        )
    return False


def _validate_manual_xodr_resolved(
    manual_xodr_resolved: str,
    *,
    logger: logging.Logger,
) -> str:
    resolved = str(manual_xodr_resolved or "").strip()
    if not resolved:
        return ""
    if resolved.lower().endswith(".xodr") and os.path.isfile(resolved):
        return resolved
    _msg = (
        f"Manual XODR path does not exist: {resolved!r}. "
        f"Set UP_MANUAL_XODR to a valid .xodr file path. "
        f"Tried: {resolved!r}"
    )
    if _thesis_strict_enabled():
        raise RuntimeError(_msg)
    logger.warning(_msg)
    return ""


def _compute_supplementary_elevation_gap(
    *,
    reference_xodr: str,
    aligned_auto: str,
    output_dir: str,
    log: logging.Logger,
    generated_xodr: Optional[str] = None,
    run_root: Optional[str] = None,
) -> Dict[str, Any]:
    dem_qc_path = _discover_elevation_dem_qc_path(
        output_dir,
        generated_xodr=generated_xodr,
        run_root=run_root,
    )
    dem_qc = _read_json_dict(dem_qc_path)
    dem_qc_ok = bool(dem_qc.get("ok")) if dem_qc else False
    if not dem_qc_ok:
        return _disabled_elevation_gap(
            "dem_qc_failed",
            dem_qc_path=dem_qc_path,
            dem_qc_ok=dem_qc_ok if dem_qc else None,
        )
    try:
        result = ElevationGap.compute(reference_xodr, aligned_auto)
    except Exception as exc:
        log.warning("Supplementary elevation gap computation failed (%s)", exc)
        return _disabled_elevation_gap(
            "elevation_gap_failed",
            dem_qc_path=dem_qc_path,
            dem_qc_ok=dem_qc_ok,
            error=str(exc),
        )
    if not isinstance(result, dict):
        return _disabled_elevation_gap(
            "elevation_gap_failed",
            dem_qc_path=dem_qc_path,
            dem_qc_ok=dem_qc_ok,
            error="invalid_result_type",
        )
    # Guard: if the auto XODR is flat (>95% roads have zero z-range), the
    # elevation comparison would measure manual terrain minus zero — not a
    # meaningful map-to-map gap.  run_11's planar auto XODR triggers this.
    if result.get("pct_roads_flat_auto", 0.0) > 0.95:
        result["disabled"] = True
        result["reason"] = "auto_xodr_is_planar"
        result["warning"] = (
            "auto_xodr elevation profiles are flat (>95% roads); "
            "elevation gap metrics would reflect manual terrain minus zero "
            "rather than a meaningful map-to-map comparison"
        )
    result.setdefault("supplementary", True)
    result.setdefault("primary_artifact_is_planar", True)
    if result.get("disabled") and not result.get("disabled_reason"):
        result["disabled_reason"] = _elevation_gap_disabled_reason(
            str(result.get("reason") or "elevation_gap_disabled")
        )
    result["dem_qc_ok"] = dem_qc_ok
    result["dem_qc_path"] = str(dem_qc_path) if dem_qc_path else None
    return result

def _snapshot_settings(out_dir: str) -> None:
    """Write a domain-gap-specific settings snapshot.

    Note: main_pipeline already writes <run_out_dir>/settings_snapshot.json.
    We keep this one separate to avoid schema/name collisions.
    """
    try:
        if hasattr(SETTINGS, "to_dict"):
            snap = SETTINGS.to_dict()
        else:
            snap = {}
            for k in dir(SETTINGS):
                if k.isupper():
                    try:
                        val = getattr(SETTINGS, k)
                        # Skip non-serializable class attributes
                        if callable(val):
                            continue
                        snap[k] = val
                    except Exception:
                        snap[k] = "<unreadable>"
    except Exception:
        snap = {}
        for k in dir(SETTINGS):
            if k.isupper():
                try:
                    val = getattr(SETTINGS, k)
                    if callable(val):
                        continue
                    snap[k] = val
                except Exception:
                    snap[k] = "<unreadable>"

    _safe_dump_json(os.path.join(out_dir, "domain_gap_settings_snapshot.json"), snap)


def _hash_settings_snapshot(out_dir: str) -> Optional[str]:
    path = os.path.join(out_dir, "domain_gap_settings_snapshot.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception:
        return None

def _hash_settings_snapshot_sha256(out_dir: str) -> Optional[str]:
    path = os.path.join(out_dir, "domain_gap_settings_snapshot.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return None


def _discover_latest_valid_run(out_root: str) -> Optional[Path]:
    """
    Find the most recent run under out_root that has the required artifacts:
      - tile_metadata.json
      - tiles/ containing tile_*.xodr
      - at least one 08_final*.xodr
    Skips any folder named manual_baselines.
    """
    base = Path(out_root)
    if not base.is_dir():
        return None

    best: tuple[float, Path] | None = None
    for child in base.iterdir():
        if not child.is_dir():
            continue
        if child.name.lower() == "manual_baselines":
            continue
        meta = child / "tile_metadata.json"
        tiles_dir = child / "tiles"
        finals = sorted(child.glob("08_final*.xodr"))
        has_tiles = tiles_dir.is_dir() and any(tiles_dir.glob("tile_*.xodr"))
        if not (meta.is_file() and has_tiles and finals):
            continue
        ts = max(meta.stat().st_mtime, tiles_dir.stat().st_mtime, child.stat().st_mtime)
        if best is None or ts > best[0]:
            best = (ts, child)
    return best[1] if best else None


def _write_summary_outputs(
    output_dir: str,
    structural_gap: Dict[str, Any],
    aggregated: Optional[Dict[str, Any]],
    tile_geom_gaps: Dict[str, Any],
    tile_curv_gaps: Dict[str, Any],
    tile_gap_vector: Dict[str, Dict[str, float]],
    required_metrics: Optional[Dict[str, Any]] = None,
    carla_drivability_validated: Optional[bool] = None,
) -> None:
    """Export CSV summaries alongside full_report.json."""

    def _metric_row(metric: str, src: Any, key: str) -> dict:
        val = src.get(key) if isinstance(src, dict) else None
        return {"metric": metric, "value": val}

    def _metric_row_pref(metric: str, src: Any, keys: list[str]) -> dict:
        val = None
        if isinstance(src, dict):
            for k in keys:
                if k in src and src.get(k) is not None:
                    val = src.get(k)
                    break
        return {"metric": metric, "value": val}

    structural_gap = structural_gap or {}
    tile_geom_gaps = tile_geom_gaps or {}
    tile_curv_gaps = tile_curv_gaps or {}
    tile_gap_vector = tile_gap_vector or {}

    geom = structural_gap.get("geometry", {}) if isinstance(structural_gap, dict) else {}
    curv = structural_gap.get("curvature", {}) if isinstance(structural_gap, dict) else {}
    inter = structural_gap.get("intersection", {}) if isinstance(structural_gap, dict) else {}
    sem = structural_gap.get("semantics", {}) if isinstance(structural_gap, dict) else {}
    road = structural_gap.get("road_classification", {}) if isinstance(structural_gap, dict) else {}
    conn = structural_gap.get("connectivity", {}) if isinstance(structural_gap, dict) else {}
    if isinstance(sem, dict) and sem.get("normalized_gap") is None and sem.get("gap") is None:
        miou = _finite_float(sem.get("mean_iou"))
        if miou is not None:
            sem = dict(sem)
            sem_gap = max(0.0, min(1.0, 1.0 - miou))
            sem["normalized_gap"] = sem_gap
            sem["gap"] = sem_gap
    if isinstance(road, dict) and road.get("normalized_gap") is None and road.get("gap") is None:
        manual_props = _safe_dict(road.get("manual_class_proportions"))
        auto_props = _safe_dict(road.get("auto_class_proportions"))
        class_gap = _normalized_l1_over2(manual_props, auto_props)
        if class_gap is not None:
            road = dict(road)
            road["normalized_gap"] = class_gap
            road["gap"] = class_gap

    # DG-003: resolve connectivity rates from flat alias OR nested path so that
    # both pre-alias (run_17) and post-alias runs produce a consistent summary.csv.
    def _conn_rate(conn_payload: Any, flat_key: str, nested_side: str, nested_key: str) -> Optional[float]:
        if isinstance(conn_payload, dict):
            flat = conn_payload.get(flat_key)
            if flat is not None:
                return _safe_float(flat)
            side = conn_payload.get(nested_side, {})
            if isinstance(side, dict):
                rl = side.get("road_link", {})
                if isinstance(rl, dict):
                    return _safe_float(rl.get(nested_key))
        return None

    conn_pred = _conn_rate(conn, "predecessor_rate", "manual", "predecessor_declared_rate")
    conn_succ = _conn_rate(conn, "successor_rate", "manual", "successor_declared_rate")

    summary_rows = [
        _metric_row("geometry_rmse", geom, "rmse"),
        _metric_row("geometry_hausdorff", geom, "hausdorff"),
        _metric_row("geometry_hausdorff_norm", geom, "hausdorff_norm"),
        _metric_row("curvature_kl_divergence", curv, "kl_divergence"),
        _metric_row_pref("intersection_gap", inter, ["normalized_gap", "gap"]),
        _metric_row_pref("semantic_gap", sem, ["normalized_gap", "gap"]),
        _metric_row_pref("road_classification_gap", road, ["normalized_gap", "gap"]),
        # DG-003: connectivity rates always emitted to summary.csv regardless of alias presence
        {"metric": "connectivity_predecessor_rate", "value": conn_pred},
        {"metric": "connectivity_successor_rate", "value": conn_succ},
    ]
    if isinstance(aggregated, dict):
        summary_rows.append(_metric_row("aggregated_composite", aggregated, "composite"))

    required_metrics = required_metrics or {}
    intersection_iou = required_metrics.get("intersection_iou")
    if intersection_iou is None:
        intersection_iou = _extract_intersection_iou(inter)
    required_rows = [
        {"metric": "road_length_delta_m", "value": required_metrics.get("road_length_delta_m")},
        {"metric": "junction_count_delta", "value": required_metrics.get("junction_count_delta")},
        {"metric": "intersection_iou", "value": intersection_iou},
        {"metric": "road_count_delta", "value": required_metrics.get("road_count_delta")},
        {"metric": "lane_count_delta", "value": required_metrics.get("lane_count_delta")},
    ]
    if carla_drivability_validated is not None:
        required_rows.append(
            {
                "metric": "carla_drivability_validated",
                "value": bool(carla_drivability_validated),
            }
        )
    existing_metrics = {row.get("metric") for row in summary_rows if isinstance(row, dict)}
    for row in required_rows:
        metric = row.get("metric")
        if metric and metric not in existing_metrics:
            summary_rows.append(row)
            existing_metrics.add(metric)

    summary_extra: Dict[str, float] = {}
    definitions: list[str] = []
    scalar_sources = sorted(glob.glob(os.path.join(output_dir, "gap_*.json")))
    for fp in scalar_sources:
        stem = Path(fp).stem
        try:
            d = json.loads(Path(fp).read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        base = d.get("scalars", d) if isinstance(d, dict) else d
        flat = _flatten_numeric(base, prefix=stem)
        for k, v in flat.items():
            lk = k.lower()
            if ("intersection" in lk) or ("semantic" in lk) or ("road_class" in lk) or ("roadclass" in lk) or ("road-class" in lk):
                summary_extra[k] = float(v)
                if k.startswith(stem + "."):
                    subkey = k[len(stem) + 1 :]
                else:
                    subkey = k
                definitions.append(f"- `{k}` <- `{Path(fp).name}` : `{subkey}`")

    for k, v in summary_extra.items():
        if k in existing_metrics:
            continue
        summary_rows.append({"metric": k, "value": v})
        existing_metrics.add(k)

    # Ensure P0 scalars always present (thesis_final strict requirement)
    P0_REQUIRED_SCALARS = [
        "road_delta", "junction_delta", "lane_delta", "road_length_delta",
        "intersection_gap", "semantic_gap", "road_classification_gap",
        "tile_count_auto", "tile_count_manual", "num_tile_pairs"
    ]
    for scalar in P0_REQUIRED_SCALARS:
        if scalar not in existing_metrics:
            summary_rows.append({"metric": scalar, "value": "N/A"})
            existing_metrics.add(scalar)

    summary_map = {}
    for row in summary_rows:
        metric = row.get("metric")
        if metric:
            summary_map[metric] = row.get("value")
    _safe_dump_json(os.path.join(output_dir, "summary.json"), summary_map)
    _safe_write_csv(os.path.join(output_dir, "summary.csv"), summary_rows, ["metric", "value"])
    _safe_write_csv(os.path.join(output_dir, "summary_table.csv"), summary_rows, ["metric", "value"])
    try:
        definitions_text = [
            "# summary.csv column definitions",
            "",
            "These columns are auto-derived from numeric fields in `gap_*.json`.",
            "",
            "## Canonical scalar definitions",
            "- intersection_gap: gap_whole_intersection.json['normalized_gap'] (L1/2 over intersection-type distributions, range [0,1])",
            "- semantic_gap: gap_whole_semantics.json['normalized_gap'] (L1/2 over normalized road_type length distributions, range [0,1])",
            "- road_classification_gap: gap_whole_road_classification.json['normalized_gap'] (L1/2 over normalized road_class count distributions, range [0,1])",
            "",
            "## Added scalar columns (intersection / semantic / road-class)",
        ]
        if definitions:
            definitions_text.extend(definitions)
        else:
            definitions_text.append("(no scalar columns were detected)")
        Path(output_dir, "summary_definitions.md").write_text("\n".join(definitions_text) + "\n", encoding="utf-8")
    except Exception:
        pass

    # Tile metrics CSV
    tile_rows: list[dict] = []
    tile_keys = set()
    if isinstance(tile_geom_gaps, dict):
        tile_keys |= set(tile_geom_gaps.keys())
    if isinstance(tile_curv_gaps, dict):
        tile_keys |= set(tile_curv_gaps.keys())
    if isinstance(tile_gap_vector, dict):
        tile_keys |= set(tile_gap_vector.keys())

    for tile in sorted(tile_keys):
        g = tile_geom_gaps.get(tile) if isinstance(tile_geom_gaps, dict) else {}
        c = tile_curv_gaps.get(tile) if isinstance(tile_curv_gaps, dict) else {}
        vec = tile_gap_vector.get(tile) if isinstance(tile_gap_vector, dict) else {}
        if g is None:
            g = {}
        if c is None:
            c = {}
        if vec is None:
            vec = {}
        row = {
            "tile": tile,
            "auto_tile": (g.get("auto_tile") if isinstance(g, dict) else None) or (c.get("auto_tile") if isinstance(c, dict) else None),
            "iou": g.get("iou") if isinstance(g, dict) else c.get("iou") if isinstance(c, dict) else None,
            "rmse": g.get("rmse") if isinstance(g, dict) else None,
            "hausdorff": g.get("hausdorff") if isinstance(g, dict) else None,
            "hausdorff_norm": g.get("hausdorff_norm") if isinstance(g, dict) else None,
            "kl_divergence": c.get("kl_divergence") if isinstance(c, dict) else None,
            "js_divergence": c.get("js_divergence") if isinstance(c, dict) else None,
            "geometry_norm": vec.get("geometry_norm") if isinstance(vec, dict) else None,
            "curvature_norm": vec.get("curvature_norm") if isinstance(vec, dict) else None,
            "error_geom": g.get("error") if isinstance(g, dict) else None,
            "error_curv": c.get("error") if isinstance(c, dict) else None,
        }
        tile_rows.append(row)

    tile_headers = [
        "tile",
        "auto_tile",
        "iou",
        "rmse",
        "hausdorff",
        "hausdorff_norm",
        "kl_divergence",
        "js_divergence",
        "geometry_norm",
        "curvature_norm",
        "error_geom",
        "error_curv",
    ]
    _safe_write_csv(os.path.join(output_dir, "tile_metrics.csv"), tile_rows, tile_headers)

    # Worst tiles by normalized score (fallback to rmse)
    def _as_float(val: Any) -> float:
        try:
            f = float(val)
            if f != f:  # NaN
                return 0.0
            return f
        except Exception:
            return 0.0

    scored = []
    for row in tile_rows:
        score = max(
            _as_float(row.get("geometry_norm")),
            _as_float(row.get("curvature_norm")),
            _as_float(row.get("rmse")),
        )
        scored.append({**row, "score": score})
    worst = sorted(scored, key=lambda r: r.get("score", 0.0), reverse=True)
    _safe_write_csv(os.path.join(output_dir, "worst_tiles.csv"), worst, tile_headers + ["score"])


def _check_csv_json_parity(*, output_dir: str, full_report: Dict[str, Any]) -> None:
    """Post-write parity check: assert summary.csv and full_report.json agree on key metrics.

    Writes parity_check.json to output_dir with per-field comparison results.
    Raises RuntimeError if a numeric discrepancy exceeds tolerance (0.01).
    Best-effort: missing files or missing keys are logged as warnings, not errors.
    """
    csv_path = os.path.join(output_dir, "summary.csv")
    parity_path = os.path.join(output_dir, "parity_check.json")

    # Read summary.csv into {metric: value} dict
    csv_values: Dict[str, Optional[float]] = {}
    if os.path.isfile(csv_path):
        try:
            import csv as _csv
            with open(csv_path, newline="", encoding="utf-8") as fh:
                for row in _csv.DictReader(fh):
                    metric = str(row.get("metric", "") or "").strip()
                    raw_val = str(row.get("value", "") or "").strip()
                    if metric:
                        try:
                            csv_values[metric] = float(raw_val)
                        except (ValueError, TypeError):
                            csv_values[metric] = None
        except Exception:
            pass

    # Extract JSON values from the already-assembled full_report dict
    sdg = full_report.get("structural_domain_gap", {}) or {}
    geom = sdg.get("geometry", {}) or {}
    curv = sdg.get("curvature", {}) or {}
    # DG-004: connectivity predecessor rate — resolve flat alias or nested path
    conn_block = full_report.get("connectivity_gap", {}) or {}
    _conn_pred_json: Optional[float] = _safe_float(conn_block.get("predecessor_rate"))
    if _conn_pred_json is None:
        _manual_rl = conn_block.get("manual", {})
        if isinstance(_manual_rl, dict):
            _manual_rl = _manual_rl.get("road_link", {})
            if isinstance(_manual_rl, dict):
                _conn_pred_json = _safe_float(_manual_rl.get("predecessor_declared_rate"))

    json_values: Dict[str, Optional[float]] = {
        "geometry_rmse": _safe_float(geom.get("rmse")),
        "geometry_hausdorff": _safe_float(geom.get("hausdorff")),
        "geometry_hausdorff_norm": _safe_float(geom.get("hausdorff_norm")),
        # DG-004: expanded parity — curvature and connectivity are thesis claims
        "curvature_kl_divergence": _safe_float(curv.get("kl_divergence")),
        "connectivity_predecessor_rate": _conn_pred_json,
    }

    parity_results: Dict[str, Any] = {}
    mismatches: list[str] = []
    tolerance = 0.01

    for metric, json_val in json_values.items():
        csv_val = csv_values.get(metric)
        entry: Dict[str, Any] = {"csv": csv_val, "json": json_val}
        if csv_val is None or json_val is None:
            entry["status"] = "missing"
        else:
            diff = abs(csv_val - json_val)
            entry["abs_diff"] = diff
            if diff < tolerance:
                entry["status"] = "ok"
            else:
                entry["status"] = "mismatch"
                mismatches.append(
                    f"{metric}: csv={csv_val} json={json_val} diff={diff:.4f}"
                )
        parity_results[metric] = entry

    _safe_dump_json(parity_path, {
        "schema": "parity_check_v1",
        "tolerance": tolerance,
        "results": parity_results,
        "mismatches": mismatches,
        "n_divergences": len(mismatches),
        "n_checked": len(json_values),
        "ok": len(mismatches) == 0,
    })

    if mismatches:
        raise RuntimeError(
            "CSV/JSON parity check failed — summary.csv and full_report.json diverge: "
            + "; ".join(mismatches)
        )


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _print_tile_iou_gate_rejection(
    *,
    pair_name: str,
    iou: float,
    threshold: float,
) -> None:
    print(
        f"[TILE-GATE] Rejected tile pair {pair_name}: IoU={float(iou):.3f} < {float(threshold):.3f}",
        flush=True,
    )


def _print_tile_iou_gate_summary(
    *,
    n_rejected: int,
    n_total: int,
    threshold: float,
) -> None:
    n_total_i = int(max(0, n_total))
    n_rejected_i = int(max(0, n_rejected))
    n_passed_i = int(max(0, n_total_i - n_rejected_i))
    print(
        f"[TILE-GATE] {n_rejected_i} of {n_total_i} tile pairs rejected (IoU < {float(threshold):.3f}); {n_passed_i} passed",
        flush=True,
    )


def _combine_per_tile_structural_gap(
    tile_geom_gaps: Optional[Dict[str, Any]],
    tile_curv_gaps: Optional[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    combined: Dict[str, Dict[str, Any]] = {}
    tile_keys: set[str] = set()
    if isinstance(tile_geom_gaps, dict):
        tile_keys |= set(tile_geom_gaps.keys())
    if isinstance(tile_curv_gaps, dict):
        tile_keys |= set(tile_curv_gaps.keys())

    for tile in sorted(tile_keys):
        entry: Dict[str, Any] = {}
        if isinstance(tile_geom_gaps, dict) and isinstance(tile_geom_gaps.get(tile), dict):
            entry["geometry"] = dict(tile_geom_gaps[tile])
        if isinstance(tile_curv_gaps, dict) and isinstance(tile_curv_gaps.get(tile), dict):
            entry["curvature"] = dict(tile_curv_gaps[tile])
        combined[tile] = entry
    return combined


def _attach_full_report_sidecars(
    *,
    output_dir: str,
    full_report: Dict[str, Any],
    generated_xodr: Optional[str] = None,
    run_root: Optional[str] = None,
    sumo_meta: Optional[Dict[str, Any]] = None,
) -> None:
    summary_payload = _read_json_dict(Path(output_dir) / "summary.json")
    if summary_payload:
        full_report["summary"] = summary_payload

    parity_payload = _read_json_dict(Path(output_dir) / "parity_check.json")
    if parity_payload:
        full_report["parity_check"] = parity_payload

    dem_qc_path = _discover_elevation_dem_qc_path(
        output_dir,
        generated_xodr=generated_xodr,
        run_root=run_root,
    )
    dem_qc_payload = _read_json_dict(dem_qc_path)
    if dem_qc_payload:
        dem_qc = dict(dem_qc_payload)
        dem_path = str(dem_qc.get("dem_path") or dem_qc.get("dem_path_used") or "").strip()
        if dem_path:
            dem_qc.setdefault("dem_path_used", dem_path)
        dem_qc.setdefault(
            "dem_expanded_used",
            bool(dem_path and "expanded" in Path(dem_path).name.lower()),
        )
        if dem_qc_path:
            dem_qc.setdefault("dem_qc_path", str(dem_qc_path))
        full_report["elevation_qc"] = dem_qc
        full_report["dem_qc"] = dict(dem_qc)

    full_report["sumo_repair"] = _resolve_sumo_repair_meta(
        output_dir,
        generated_xodr=generated_xodr,
        run_root=run_root,
        sumo_meta=sumo_meta,
    )

    elevation_payload = full_report.get("elevation")
    full_report["elevation_included"] = bool(
        isinstance(elevation_payload, dict) and not elevation_payload.get("disabled", False)
    )


def _finalize_results(
    *,
    output_dir: str,
    reference_xodr: str,
    aligned_auto: str,
    generated_xodr: str,
    transform: Dict[str, Any],
    whole_geom_gap: Dict[str, Any],
    whole_curv_gap: Dict[str, Any],
    whole_elev_gap: Dict[str, Any],
    whole_inter_gap: Dict[str, Any],
    whole_sem_gap: Dict[str, Any],
    whole_class_gap: Dict[str, Any],
    whole_conn_gap: Dict[str, Any],
    tile_geom_gaps: Dict[str, Any],
    tile_curv_gaps: Dict[str, Any],
    tile_gap_vector: Dict[str, Dict[str, float]],
    tile_map: Dict[str, Any],
    perception_gap: Optional[Dict[str, Any]],
    latent_whole: Any,
    latent_per_tile: Any,
    aggregated: Optional[Dict[str, Any]],
    run_meta: Dict[str, Any],
    combined_repro_hash: str,
    domain_gap_metrics: Optional[Dict[str, Any]] = None,
    tile_pairing_provenance: Optional[Dict[str, Any]] = None,
    sumo_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    transform = _ensure_alignment_fit_metric_note(transform)
    connectivity_gap = _normalize_connectivity_gap_payload(
        whole_conn_gap,
        run_meta=run_meta,
        default_reason=_connectivity_default_reason(whole_conn_gap, run_meta=run_meta),
    )
    combined: Dict[str, Any] = {
        "reference_map": {
            "type": "manual",
            "path": reference_xodr,
        },
        "generated_map": {
            "type": "osm_generated",
            "path": aligned_auto,
            "original_generated_path": generated_xodr,
        },
        "alignment": transform,
        "structural_domain_gap": {
            "geometry": whole_geom_gap,
            "curvature": whole_curv_gap,
            "elevation": whole_elev_gap,
            "intersection": whole_inter_gap,
            "semantics": whole_sem_gap,
            "road_classification": whole_class_gap,
            "connectivity": connectivity_gap,
        },
        "elevation": whole_elev_gap,
        "elevation_gap": whole_elev_gap,
        "connectivity_gap": connectivity_gap,
        "domain_gap": domain_gap_metrics or {},
        "per_tile_structural_gap": _combine_per_tile_structural_gap(tile_geom_gaps, tile_curv_gaps),
        "normalized_tile_gap_vector": tile_gap_vector,
        "latent_domain_gap": {
            "whole": latent_whole,
            "per_tile": latent_per_tile,
        },
        "perceptual_effects": {
            "perception_gap": perception_gap,
        },
        "tile_matches": tile_map,
        "aggregation": aggregated,
        "run_metadata": run_meta,
        "tile_pairing_provenance": tile_pairing_provenance or {},
        "carla_drivability_validated": False,
        "carla_drivability_note": _CARLA_DRIVABILITY_NOTE,
    }
    alignment_diag = transform.get("diagnostics", {}) if isinstance(transform, dict) else {}
    combined["crs_alignment_applied"] = bool(
        transform.get("crs_alignment_applied")
        if isinstance(transform, dict)
        else False
    )
    combined["source_crs"] = (
        transform.get("source_crs") if isinstance(transform, dict) else None
    ) or alignment_diag.get("source_crs")
    combined["target_crs"] = (
        transform.get("target_crs") if isinstance(transform, dict) else None
    ) or alignment_diag.get("target_crs")

    try:
        combined["map_hashes"] = {
            "reference_map_sha256": _hash_file_sha256(reference_xodr),
            "auto_aligned_sha256": _hash_file_sha256(aligned_auto),
            "auto_original_sha256": _hash_file_sha256(generated_xodr),
            "reference_map_md5": _hash_file_md5(reference_xodr),
            "auto_aligned_md5": _hash_file_md5(aligned_auto),
            "auto_original_md5": _hash_file_md5(generated_xodr),
        }
    except Exception as e:  # pragma: no cover - best-effort
        combined["map_hashes"] = {"error": str(e)}

    combined["reproducibility_hash"] = combined_repro_hash
    combined["manual_map_choice"] = run_meta.get("manual_map_choice")
    combined["manual_xodr_resolved"] = run_meta.get("manual_xodr_resolved")
    combined["manual_xodr_source"] = run_meta.get("manual_xodr_source")
    _attach_auto_georef_metadata(combined, run_meta)

    if "connectivity_gap" not in combined:
        raise RuntimeError(
            "connectivity_gap must always be present in full_report.json (CLAUDE.md P0)"
        )

    try:
        _safe_dump_json(os.path.join(output_dir, "full_report.json"), combined)
    except Exception:
        pass

    try:
        _write_summary_outputs(
            output_dir=output_dir,
            structural_gap=combined.get("structural_domain_gap", {}),
            aggregated=aggregated,
            tile_geom_gaps=tile_geom_gaps,
            tile_curv_gaps=tile_curv_gaps,
            tile_gap_vector=tile_gap_vector,
            required_metrics=combined.get("domain_gap", {}),
            carla_drivability_validated=combined.get("carla_drivability_validated"),
        )
    except Exception:
        pass

    # CSV/JSON parity check — best-effort, never crashes the run.
    try:
        _check_csv_json_parity(output_dir=output_dir, full_report=combined)
    except Exception:
        pass

    _attach_full_report_sidecars(
        output_dir=output_dir,
        full_report=combined,
        generated_xodr=generated_xodr,
        run_root=run_meta.get("auto_run_root") or run_meta.get("run_root"),
        sumo_meta=sumo_meta,
    )
    try:
        _safe_dump_json(os.path.join(output_dir, "full_report.json"), combined)
    except Exception:
        pass

    return combined


def _finalize_smoke_results(
    *,
    output_dir: str,
    reference_xodr: str,
    aligned_auto: str,
    generated_xodr: str,
    transform: Dict[str, Any],
    whole_geom_gap: Optional[Dict[str, Any]],
    tile_iou_gate_summary: Dict[str, Any],
    tile_map: Dict[str, Any],
    tile_pairing_source: Optional[str],
    corr_path: Optional[Path],
    run_meta: Dict[str, Any],
    combined_repro_hash: str,
    tile_pairing_provenance: Optional[Dict[str, Any]] = None,
    sumo_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    transform = _ensure_alignment_fit_metric_note(transform)
    smoke_disabled = {"disabled": True, "reason": "smoke_mode"}
    connectivity_gap = _normalize_connectivity_gap_payload(
        smoke_disabled,
        default_reason="smoke_mode",
        run_meta=run_meta,
    )
    thesis_scope = _thesis_scope_fields()
    crs_comparability = _write_crs_comparability(
        Path(output_dir),
        reference_xodr,
        generated_xodr,
    )
    alignment_diag = transform.get("diagnostics", {}) if isinstance(transform, dict) else {}
    source_crs = (
        transform.get("source_crs") if isinstance(transform, dict) else None
    ) or alignment_diag.get("source_crs")
    target_crs = (
        transform.get("target_crs") if isinstance(transform, dict) else None
    ) or alignment_diag.get("target_crs")
    crs_alignment_applied = bool(
        transform.get("crs_alignment_applied")
        if isinstance(transform, dict)
        else False
    ) or bool(alignment_diag.get("crs_alignment_applied"))
    geometry_payload = whole_geom_gap if isinstance(whole_geom_gap, dict) and whole_geom_gap else smoke_disabled

    combined: Dict[str, Any] = {
        **thesis_scope,
        "reference_map": {
            "type": "manual",
            "path": reference_xodr,
            "manual_reference_status": run_meta.get("manual_reference_status", "manual_reference"),
            "assumed_properties": [
                "expert-designed",
                "structurally consistent",
                "perceptually stable",
            ],
        },
        "generated_map": {
            "type": "osm_generated",
            "path": aligned_auto,
            "generation_pipeline": "OSM → OpenDRIVE → CARLA",
        },
        "alignment": transform,
        "crs_alignment_applied": bool(crs_alignment_applied),
        "source_crs": source_crs,
        "target_crs": target_crs,
        "structural_domain_gap": {
            "geometry": geometry_payload,
            "curvature": smoke_disabled,
            "elevation": smoke_disabled,
            "intersection": smoke_disabled,
            "semantics": smoke_disabled,
            "road_classification": smoke_disabled,
            "connectivity": connectivity_gap,
        },
        "elevation": smoke_disabled,
        "elevation_gap": smoke_disabled,
        "connectivity_gap": connectivity_gap,
        "per_tile_structural_gap": {},
        "per_tile_status": "smoke_only",
        "per_tile_status_reason": "Smoke mode exits after tile pairing artifacts.",
        "tile_metrics_skipped": True,
        "tile_pairing_source": tile_pairing_source or "smoke",
        "tile_pairing_warning": None,
        "tile_correspondence_csv": str(corr_path) if corr_path else None,
        "tile_iou_gate_summary": tile_iou_gate_summary,
        "normalized_tile_gap_vector": {},
        "latent_domain_gap": {
            "whole": None,
            "per_tile": None,
        },
        "perceptual_effects": {
            "perception_gap": None,
        },
        "tile_matches": tile_map,
        "aggregation": {
            "disabled": True,
            "reason": "smoke_mode",
        },
        "normalization_contract": _normalization_contract(),
        "run_metadata": run_meta,
        "crs_comparability": crs_comparability,
        "tile_pairing_provenance": tile_pairing_provenance or {},
        "smoke": True,
        "carla_drivability_validated": False,
        "carla_drivability_note": _CARLA_DRIVABILITY_NOTE,
    }
    _attach_auto_georef_metadata(combined, run_meta)

    try:
        combined["map_hashes"] = {
            "reference_map_sha256": _hash_file_sha256(reference_xodr),
            "auto_aligned_sha256": _hash_file_sha256(aligned_auto),
            "auto_original_sha256": _hash_file_sha256(generated_xodr),
            "reference_map_md5": _hash_file_md5(reference_xodr),
            "auto_aligned_md5": _hash_file_md5(aligned_auto),
            "auto_original_md5": _hash_file_md5(generated_xodr),
        }
    except Exception as e:  # pragma: no cover - best-effort
        combined["map_hashes"] = {"error": str(e)}
    combined["reproducibility_hash"] = combined_repro_hash
    combined["manual_map_choice"] = run_meta.get("manual_map_choice")
    combined["manual_xodr_resolved"] = run_meta.get("manual_xodr_resolved")
    combined["manual_xodr_source"] = run_meta.get("manual_xodr_source")

    _attach_full_report_sidecars(
        output_dir=output_dir,
        full_report=combined,
        generated_xodr=generated_xodr,
        run_root=run_meta.get("auto_run_root") or run_meta.get("run_root"),
        sumo_meta=sumo_meta,
    )
    # DG-001: ensure smoke reports share the same top-level key schema as full
    # reports so downstream consumers (examiners, CI parsers) never KeyError.
    combined.setdefault("summary", {"disabled": True, "reason": "smoke_mode"})
    combined.setdefault("parity_check", {"disabled": True, "reason": "smoke_mode"})
    combined.setdefault("elevation_qc", {"disabled": True, "reason": "smoke_mode"})
    combined.setdefault("dem_qc", {"disabled": True, "reason": "smoke_mode"})
    combined.setdefault("elevation_included", False)
    combined.setdefault("sumo_repair", {"disabled": True, "reason": "smoke_mode"})
    if "connectivity_gap" not in combined:
        raise RuntimeError(
            "connectivity_gap must always be present in full_report.json (CLAUDE.md P0)"
        )
    _safe_dump_json(os.path.join(output_dir, "full_report.json"), combined)
    return combined

# ===================================================================
#                       FULL DOMAIN-GAP PIPELINE
# ===================================================================
def run_full_domain_gap(
    manual_xodr: str,
    auto_xodr: str,
    manual_tiles: str,
    auto_tiles: str,
    *,
    manual_missing: bool = False,
    perception_manual_json: str | None = None,
    perception_auto_json: str | None = None,
    output_dir: str = "domain_gap_results",
    manual_reference_status: str = "provided",
    smoke: bool = False,
    sumo_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Academically defensible full domain-gap runner.

    Key improvements:
      - strict settings-driven switches + normalization contract
      - robust compatibility for IntersectionGap/SemanticGap APIs
      - correct metric keys (GeometryGap uses "rmse" not "rmse_xy")
      - saves intermediate artifacts deterministically
      - optional aggregator with documented normalized components
      - avoids silent zero defaults on failures by storing error fields
    """
    global DomainGapAggregator, out_tile, auto_tiles_aligned
    _ensure_dir(output_dir)
    _snapshot_settings(output_dir)
    _acquire_output_lock(output_dir, log)

    reference_xodr = manual_xodr
    generated_xodr = auto_xodr
    auto_xodr_raw = auto_xodr
    auto_xodr_promoted = ""
    auto_xodr_for_tiling = auto_xodr_raw
    aligned_auto: Optional[str] = None
    promotion_detected = False
    auto_xodr_raw = auto_xodr
    auto_xodr_promoted = ""
    auto_xodr_for_tiling = auto_xodr_raw
    promotion_detected = False

    manual_missing = manual_missing or not Path(reference_xodr).is_file()

    manual_tiles_source_before = "provided" if manual_tiles else "missing"
    try:
        override_src = os.getenv("UP_MANUAL_TILES_SOURCE") or ""
        if override_src:
            manual_tiles_source_before = override_src
        else:
            manual_tiles_env = os.getenv("UP_MANUAL_TILES_DIR") or ""
            manual_tiles_cfg = getattr(SETTINGS, "MANUAL_TILES_DIR", "") or ""
            if manual_tiles and manual_tiles_env and Path(manual_tiles).resolve() == Path(manual_tiles_env).expanduser().resolve():
                manual_tiles_source_before = "env"
            elif manual_tiles and manual_tiles_cfg and Path(manual_tiles).resolve() == Path(manual_tiles_cfg).expanduser().resolve():
                manual_tiles_source_before = "config"
    except Exception:
        pass

    skip_tile_alignment = _bool_env("UP_SKIP_TILE_ALIGNMENT", "0")
    auto_tiles_prealigned = False
    tile_pairing_provenance: Dict[str, Any] = {
        "manual_tiles_source_before": manual_tiles_source_before,
        "manual_tiles_dir_resolved": "",
        "manual_tiles_dir_raw": "",
        "manual_tiles_override_source": manual_tiles_source_before,
        "mismatch_reason": "",
        "alignment_reason": "",
        "regenerated_tiles_dir": "",
        "auto_meta_path_used": "",
        "auto_meta_resolved": "",
        "auto_meta_resolution": "",
        "auto_tile_metadata_used": "",
        "manual_tiles_regenerated": False,
        "grid_delta": None,
        "auto_tiles_dir_raw": "",
    }

    georef_override = None
    try:
        generated_xodr, georef_override = _promote_auto_georef_if_needed(
            generated_xodr, reference_xodr, output_dir, log
        )
    except Exception as exc:
        log.warning("GeoReference override check failed (%s)", exc)
    try:
        override_path = Path(output_dir) / "auto_georef_override.xodr"
        promotion_detected = bool(georef_override) or override_path.is_file()
    except Exception:
        promotion_detected = bool(georef_override)
    if promotion_detected:
        auto_xodr_promoted = generated_xodr
        auto_xodr_for_tiling = generated_xodr
        try:
            gps_bounds = SETTINGS.load_gps_bounds()
        except Exception:
            gps_bounds = getattr(SETTINGS, "DEFAULT_GPS_BOUNDS", None)
        if not isinstance(gps_bounds, dict):
            raise RuntimeError("GPS bounds missing; cannot perform deterministic alignment.")
        manual_info = _read_georef_info(reference_xodr)
        manual_proj = manual_info.get("norm") if isinstance(manual_info, dict) else ""
        if not manual_proj:
            raise RuntimeError("Manual CRS missing; cannot perform deterministic alignment.")
        manual_bbox = None
        try:
            mb, _, _ = compute_auto_bbox_and_centroid(Path(reference_xodr))
            manual_bbox = mb
        except Exception:
            manual_bbox = None
        aligned_auto = Path(output_dir) / "auto_promoted_aligned.xodr"
        alignment_validity_path = Path(output_dir) / "alignment_validity.json"
        deterministic_promote_and_align(
            Path(auto_xodr_promoted),
            manual_proj=str(manual_proj),
            gps_bounds=gps_bounds,
            manual_bbox=manual_bbox if isinstance(manual_bbox, BBox) else None,
            out_aligned_xodr=aligned_auto,
            out_validity_json=alignment_validity_path,
            require_overlap=True,
        )
        auto_xodr_for_tiling = str(aligned_auto)
    elif aligned_auto and Path(aligned_auto).is_file():
        auto_xodr_for_tiling = str(aligned_auto)
    log.info("AUTO xodr raw: %s", auto_xodr_raw)
    log.info("AUTO xodr for tiling: %s", auto_xodr_for_tiling)
    log.info("AUTO promotion_detected: %s", bool(promotion_detected))
    # Keep the aligned/promoted path selected above; do not reset to raw.

    manual_tiles = manual_tiles or ""
    manual_tiles_raw = manual_tiles
    manual_tiles = _resolve_tiles_dir(manual_tiles)
    if manual_tiles_raw and manual_tiles != manual_tiles_raw:
        log.info("Resolved manual_tiles_dir to %s", manual_tiles)
    auto_tiles_raw = auto_tiles
    auto_tiles = _resolve_tiles_dir(auto_tiles)
    tile_pairing_provenance["manual_tiles_dir_resolved"] = manual_tiles
    tile_pairing_provenance["manual_tiles_dir_raw"] = manual_tiles_raw
    tile_pairing_provenance["auto_tiles_dir_raw"] = auto_tiles_raw
    tile_pairing_provenance["manual_tiles_override_source"] = manual_tiles_source_before
    auto_meta_override = os.getenv("UP_AUTO_META") or ""
    auto_meta_path = None
    auto_meta_resolution = ""
    manual_proj4_for_tiles = ""
    try:
        manual_proj4_for_tiles = str((_read_georef_info(reference_xodr) or {}).get("norm") or "")
    except Exception:
        manual_proj4_for_tiles = ""
    if auto_meta_override:
        auto_meta_path = Path(auto_meta_override).expanduser()
        auto_meta_resolution = os.getenv("UP_AUTO_META_SOURCE") or "env"
        if not auto_meta_path.is_file():
            raise RuntimeError(f"UP_AUTO_META set but file not found: {auto_meta_path}")
    else:
        try:
            auto_meta_path = Path(generated_xodr).parent / "tile_metadata.json"
            auto_meta_resolution = "adjacent"
        except Exception:
            auto_meta_path = None
    if not auto_meta_path or not Path(auto_meta_path).is_file():
        log.warning(
            "Auto tile_metadata.json not found (searched %s); "
            "a governed aligned auto-tiles bundle will be generated for this run.",
            auto_meta_path,
        )
        auto_meta_path = None
    if (os.getenv("UP_AUTO_META_SOURCE") or "") == "cli" and auto_meta_path:
        _enforce_r5_run_root(Path(auto_meta_path), Path(generated_xodr))
    auto_origin_meta_path = Path(auto_meta_path) if auto_meta_path else None
    if auto_origin_meta_path and "manual_maps" in auto_origin_meta_path.parts and "tiles_500m_b50" in auto_origin_meta_path.parts:
        raise RuntimeError(
            f"Refusing to use manual_maps/tiles_500m_b50 as auto origin-from-meta: {auto_origin_meta_path}"
        )
    tile_pairing_provenance["auto_meta_resolved"] = str(auto_meta_path) if auto_meta_path else ""
    tile_pairing_provenance["auto_meta_resolution"] = auto_meta_resolution

    aligned_tiles_root = Path(output_dir) / "auto_tiles_source"
    aligned_tiles_out = None
    manual_origin_meta = None
    if manual_tiles:
        manual_origin_meta = _find_tile_manifest(manual_tiles) or _find_tile_metadata(manual_tiles)
        if manual_origin_meta is None:
            manual_origin_meta = _write_inferred_tile_origin_meta(
                manual_tiles,
                Path(output_dir) / "manual_tiles_origin_inferred.json",
            )
    if promotion_detected:
        aligned_tiles_out = _auto_generate_tiles_from_xodr(
            auto_xodr_for_tiling,
            aligned_tiles_root,
            log,
            origin_from_meta=manual_origin_meta,
            proj4_override=manual_proj4_for_tiles or None,
        )
    if aligned_tiles_out:
        auto_tiles = _resolve_tiles_dir(aligned_tiles_out)
        auto_meta_path = Path(aligned_tiles_out) / "tile_metadata.json"
        auto_meta_resolution = "generated_from_aligned_auto"
        auto_tiles_prealigned = True
        if not auto_meta_path.is_file():
            raise RuntimeError(f"Auto tile metadata missing after aligned auto tiling: {auto_meta_path}")
        tile_pairing_provenance["auto_meta_resolved"] = str(auto_meta_path)
        tile_pairing_provenance["auto_meta_resolution"] = auto_meta_resolution
        tile_pairing_provenance["auto_tiles_dir_raw"] = auto_tiles
    elif promotion_detected:
        raise RuntimeError(
            "Auto tiles in promoted/aligned CRS could not be generated. "
            f"Check tiler_diagnostics.json under {aligned_tiles_root}."
        )

    try:
        prov = {
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "python_executable": sys.executable,
            "promotion_detected": bool(promotion_detected),
            "auto_xodr_raw": str(auto_xodr_raw),
            "auto_xodr_promoted": str(auto_xodr_promoted) if auto_xodr_promoted else "",
            "auto_xodr_for_tiling": str(auto_xodr_for_tiling),
            "auto_tiles_dir": str(auto_tiles),
            "auto_meta_path": str(auto_meta_path) if auto_meta_path else "",
            "tile_grid_bounds": _grid_bounds_from_tiles_dir(auto_tiles),
        }
        _safe_dump_json(os.path.join(output_dir, "provenance_auto_tiling.json"), prov)
    except Exception:
        pass
    if auto_tiles_prealigned and (not manual_tiles) and (not manual_missing):
        generated_tiles = _auto_generate_aligned_manual_tiles(
            reference_xodr, auto_meta_path, output_dir, log
        )
        if generated_tiles:
            manual_tiles = generated_tiles
            tile_pairing_provenance["manual_tiles_regenerated"] = True
            tile_pairing_provenance["manual_tiles_override_source"] = "auto"
            tile_pairing_provenance["regenerated_tiles_dir"] = generated_tiles
            tile_pairing_provenance["manual_tiles_dir_resolved"] = manual_tiles

        if not manual_tiles:
            fix_cmd = _manual_tiles_fix_command(reference_xodr, output_dir, auto_meta_path)
            if auto_meta_path:
                raise RuntimeError(
                    f"Manual tiles missing and auto metadata present; refusing to proceed without aligned manual tiles. "
                    f"Suggested: {fix_cmd}"
                )
            if fix_cmd:
                log.warning('Manual tiles not provided; per-tile correspondence may fail. Suggested: %s', fix_cmd)
            else:
                log.warning('Manual tiles not provided; per-tile correspondence may fail. Set UP_MANUAL_TILES_DIR.')

    if auto_tiles_prealigned and manual_tiles and auto_meta_path:
        manual_manifest_path = _find_tile_manifest(manual_tiles)
        auto_manifest_path = _find_tile_manifest(auto_tiles) if auto_tiles else None
        manual_manifest = _read_tile_manifest(manual_manifest_path) if manual_manifest_path else None
        auto_manifest = _read_tile_manifest(auto_manifest_path) if auto_manifest_path else None
        manual_meta_path = _find_tile_metadata(manual_tiles)
        manual_meta_ok = False
        if manual_meta_path and Path(manual_meta_path).is_file():
            try:
                data = json.loads(Path(manual_meta_path).read_text(encoding="utf-8", errors="replace"))
                if isinstance(data, dict) and data:
                    manual_meta_ok = True
            except Exception:
                manual_meta_ok = False

        manual_origin = None
        auto_origin = None
        if isinstance(manual_manifest, dict):
            manual_origin = (manual_manifest.get('origin_x'), manual_manifest.get('origin_y'))
        if isinstance(auto_manifest, dict):
            auto_origin = (auto_manifest.get('origin_x'), auto_manifest.get('origin_y'))

        if (not auto_origin) or (auto_origin[0] is None or auto_origin[1] is None):
            ox, oy, _, _ = _read_origin_from_meta(auto_meta_path)
            auto_origin = (ox, oy)
        if (not manual_origin) or (manual_origin[0] is None or manual_origin[1] is None):
            man_meta_path = _find_tile_metadata(manual_tiles)
            ox, oy, _, _ = _read_origin_from_meta(man_meta_path)
            manual_origin = (ox, oy)

        tile_pairing_provenance["auto_meta_path_used"] = str(auto_meta_path) if auto_meta_path else ""
        tile_pairing_provenance["auto_tile_metadata_used"] = str(auto_meta_path) if auto_meta_path else ""

        mismatch_reasons = []
        if not manual_meta_ok:
            mismatch_reasons.append("manual_tile_metadata_missing")
        dx = dy = 0.0
        try:
            if (
                manual_origin
                and auto_origin
                and manual_origin[0] is not None
                and manual_origin[1] is not None
                and auto_origin[0] is not None
                and auto_origin[1] is not None
            ):
                dx = float(manual_origin[0]) - float(auto_origin[0])
                dy = float(manual_origin[1]) - float(auto_origin[1])
                if abs(dx) > 1e-3 or abs(dy) > 1e-3:
                    mismatch_reasons.append(f"origin_delta_dx={dx:.3f},dy={dy:.3f}")

            if isinstance(manual_manifest, dict) and isinstance(auto_manifest, dict):
                try:
                    mt = manual_manifest.get('tile_size_m')
                    at = auto_manifest.get('tile_size_m')
                    if mt is not None and at is not None and abs(float(mt) - float(at)) > 1e-3:
                        mismatch_reasons.append(f"tile_size_m={float(mt):.3f}!={float(at):.3f}")
                except Exception:
                    pass
                try:
                    mb = manual_manifest.get('buffer_m')
                    ab = auto_manifest.get('buffer_m')
                    if mb is not None and ab is not None and abs(float(mb) - float(ab)) > 1e-3:
                        mismatch_reasons.append(f"buffer_m={float(mb):.3f}!={float(ab):.3f}")
                except Exception:
                    pass
                mm = manual_manifest.get('frame_method')
                am = auto_manifest.get('frame_method')
                if mm and am and str(mm) != str(am):
                    mismatch_reasons.append(f"frame_method={mm}!={am}")
                mtf = manual_manifest.get('transform')
                atf = auto_manifest.get('transform')
                if isinstance(mtf, dict) and isinstance(atf, dict):
                    for k in ("cos", "sin", "scale", "rot", "theta", "yaw"):
                        if k in mtf and k in atf:
                            try:
                                if abs(float(mtf[k]) - float(atf[k])) > 1e-6:
                                    mismatch_reasons.append(f"transform_{k}={mtf[k]}!={atf[k]}")
                                    break
                            except Exception:
                                continue

        except Exception:
            pass

        if mismatch_reasons:
            tile_pairing_provenance["mismatch_reason"] = ";".join(mismatch_reasons)
            tile_pairing_provenance["alignment_reason"] = ";".join(mismatch_reasons)
            tile_pairing_provenance["grid_delta"] = {"dx": float(dx), "dy": float(dy)}

            fix_cmd = _manual_tiles_fix_command(reference_xodr, output_dir, auto_meta_path)
            log.warning(
                "Manual tiles do not match auto tile metadata (%s). "
                "Re-tile manual map with origin-from-meta. Suggested: %s",
                "; ".join(mismatch_reasons),
                fix_cmd,
            )
            aligned_tiles = _auto_generate_aligned_manual_tiles(
                reference_xodr, auto_meta_path, output_dir, log
            )
            if aligned_tiles:
                manual_tiles = aligned_tiles
                tile_pairing_provenance["manual_tiles_regenerated"] = True
                tile_pairing_provenance["manual_tiles_override_source"] = "auto"
                tile_pairing_provenance["regenerated_tiles_dir"] = aligned_tiles
                tile_pairing_provenance["manual_tiles_dir_resolved"] = manual_tiles
                log.warning('Manual tiles regenerated due to missing manual tile metadata; using aligned tiles at %s', aligned_tiles)
            else:
                tile_pairing_provenance["manual_tiles_regenerated"] = False
                tile_pairing_provenance["manual_retile_result"] = "failed"
                tile_pairing_provenance["manual_retile_fail_open"] = bool(skip_tile_alignment)
                if skip_tile_alignment:
                    # Governance-approved fail-open path for whole-map-only comparisons.
                    manual_tiles = ""
                    tile_pairing_provenance["manual_tiles_override_source"] = "disabled"
                    tile_pairing_provenance["manual_tiles_dir_resolved"] = None
                    tile_pairing_provenance["alignment_reason"] = "manual_retile_timeout_whole_map_only"
                    log.warning("manual_retile_timeout: proceeding with whole-map metrics only")
                else:
                    raise RuntimeError(
                        "Manual tiles misaligned and auto-retile failed; refusing to use stale manual tiles."
                    )
        else:
            tile_pairing_provenance["alignment_reason"] = "auto_meta_match"

    # ---------------------------------------------------------------
    # P0 KILL SWITCH CONFIGURATION (thesis safety)
    # ---------------------------------------------------------------
    allow_empty_correspondence_override = _zero_tile_correspondence_override_enabled()
    allow_identity_alignment_override = os.getenv("UP_ALLOW_IDENTITY_ALIGNMENT", "") == "1"
    alignment_transform_type: str = "unknown"
    alignment_override_used: bool = False
    alignment_override_warning: Optional[str] = None
    kill_switch_provenance: Dict[str, Any] = {}

    log.info("📌 Starting FULL domain-gap analysis")
    log.info("   Manual map : %s", reference_xodr)
    log.info("   Auto map   : %s", generated_xodr)
    log.info("   Auto meta  : %s", auto_meta_path)
    log.info("   Manual tiles: %s", manual_tiles or '(missing)')

    # ---------------------------------------------------------------
    # 0) Provenance snapshot (early)
    # ---------------------------------------------------------------
    # Resolve actual paths for metadata (don't rely on module-level globals)
    _resolved_manual = str(Path(reference_xodr).resolve()) if reference_xodr and Path(reference_xodr).exists() else ""
    _resolved_auto = str(Path(generated_xodr).resolve()) if generated_xodr and Path(generated_xodr).exists() else ""

    # Determine source for manual xodr
    _manual_source = manual_xodr_source  # module-level default
    if _resolved_manual:
        if os.getenv("UP_MANUAL_MAP_XODR") or os.getenv("UP_MANUAL_XODR"):
            _manual_source = "env"
        elif manual_map_choice:
            _manual_source = "cli"
        elif getattr(SETTINGS, "MANUAL_MAP_XODR", ""):
            _manual_source = "autodetect"
        else:
            _manual_source = "provided"

    run_meta = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version,
        "platform": sys.platform,
        "deterministic_seed": getattr(SETTINGS, "DETERMINISTIC_SEED", None),
        "deterministic_mode": getattr(SETTINGS, "DETERMINISTIC_MODE", None),
        "domain_gap_enable": getattr(SETTINGS, "DOMAIN_GAP_ENABLE", None),
        "domain_gap_normalization": getattr(SETTINGS, "DOMAIN_GAP_NORMALIZATION", None),
        "enable_gnn_domain_gap": getattr(SETTINGS, "ENABLE_GNN_DOMAIN_GAP", False),
        "manual_map_choice": manual_map_choice,
        "manual_xodr_resolved": _resolved_manual or manual_xodr_resolved,
        "manual_xodr_source": _manual_source,
        "auto_xodr_resolved": _resolved_auto,
        "auto_meta_source": os.getenv("UP_AUTO_META_SOURCE", ""),
        "auto_meta_resolved": os.getenv("UP_AUTO_META", ""),
        "auto_meta_mode": os.getenv("UP_AUTO_META_MODE", ""),
        "auto_run_root": os.getenv("UP_AUTO_RUN_ROOT", ""),
        # Identity proof of the compared inputs (critical for thesis traceability)
        "input_fingerprints": {
            "manual_xodr": _file_fingerprint(reference_xodr),
            "auto_xodr": _file_fingerprint(generated_xodr),
        },
        "hardener": {
            "applied": False,
            "report_path": None,
            "auto_xodr_sha256_before_hardening": None,
            "auto_xodr_sha256_after_hardening": None,
            "hardener_actions": None,
            "hardener_invalid": None,
            "hardener_reason": None,
        },
    }
    _update_run_meta_auto_georef(run_meta, georef_override)
    _safe_dump_json(os.path.join(output_dir, "run_metadata.json"), run_meta)
    # ---------------------------------------------------------------
    # 0B) Reproducibility hash (experiment fingerprint)
    # ---------------------------------------------------------------
    try:
        repro_payload = {
            "run_metadata": run_meta,
            "settings_snapshot_sha256": _hash_settings_snapshot_sha256(output_dir),
            "settings_snapshot_md5": _hash_settings_snapshot(output_dir),
            # Bind the reproducibility hash to the exact compared input files
            "input_fingerprints": run_meta.get("input_fingerprints", {}),
        }

        combined_repro_hash = hashlib.sha256(
            json.dumps(repro_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        combined_repro_hash_md5 = hashlib.md5(
            json.dumps(repro_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

    except Exception as e:
        combined_repro_hash = f"error:{e}"
        combined_repro_hash_md5 = f"error:{e}"

    _safe_dump_json(
        os.path.join(output_dir, "reproducibility_hash.json"),
        {
            "reproducibility_hash": combined_repro_hash,
            "reproducibility_hash_md5": combined_repro_hash_md5,
            "hash_inputs": [
                "run_metadata",
                "domain_gap_settings_snapshot.json",
                "manual_xodr_bytes",
                "auto_xodr_bytes",
            ],
            "hash_algorithm": "sha256(json(run_metadata + settings_snapshot_sha256 + input_fingerprints))",
            "hash_algorithm_md5": "md5(json(run_metadata + settings_snapshot_md5 + input_fingerprints))",
        },
    )

    # Manual missing guard: skip structural comparisons but still emit outputs
    if manual_missing:
        log.warning("Manual map missing - auto-only mode; structural comparisons skipped.")
        if isinstance(run_meta.get("hardener"), dict):
            run_meta["hardener"]["hardener_reason"] = "manual_missing"
            kill_switch_provenance["hardener"] = run_meta["hardener"]
            _safe_dump_json(os.path.join(output_dir, "run_metadata.json"), run_meta)
        transform = identity_transform()

        # Alignment sanity gate (optional)
        try:
            rmse_max = float(os.getenv("UP_ALIGNMENT_RMSE_MAX", "0") or 0)
        except Exception:
            rmse_max = 0.0
        rmse_after = None
        if isinstance(transform, dict):
            rmse_after = transform.get("diagnostics", {}).get("rmse_after")
        if rmse_max and isinstance(rmse_after, (int, float)) and rmse_after > rmse_max:
            run_meta["alignment_invalid"] = True
            run_meta["alignment_invalid_reason"] = f"rmse_after_gt_{rmse_max}"
            run_meta["alignment_rmse_after"] = float(rmse_after)
            run_meta["alignment_rmse_max"] = float(rmse_max)
            _safe_dump_json(os.path.join(output_dir, "run_metadata.json"), run_meta)

            whole_geom_gap = {"disabled": True, "error": "alignment_rmse_too_high"}
            whole_curv_gap = {"disabled": True, "error": "alignment_rmse_too_high"}
            whole_inter_gap = {"disabled": True, "error": "alignment_rmse_too_high"}
            whole_sem_gap = {"disabled": True, "error": "alignment_rmse_too_high"}
            whole_class_gap = {"disabled": True, "error": "alignment_rmse_too_high"}
            whole_conn_gap = {"disabled": True, "error": "alignment_rmse_too_high"}
            tile_geom_gaps = {}
            tile_curv_gaps = {}
            tile_gap_vector = {}
            tile_map = {}
            perception_gap = None
            latent_whole = None
            latent_per_tile = None
            aggregated = None
            return _finalize_results(
                output_dir=output_dir,
                reference_xodr=reference_xodr,
                aligned_auto=generated_xodr,
                generated_xodr=generated_xodr,
                transform=transform,
                whole_geom_gap=whole_geom_gap,
                whole_curv_gap=whole_curv_gap,
                whole_elev_gap=_disabled_elevation_gap("dem_qc_failed"),
                whole_inter_gap=whole_inter_gap,
                whole_sem_gap=whole_sem_gap,
                whole_class_gap=whole_class_gap,
                whole_conn_gap=whole_conn_gap,
                tile_geom_gaps=tile_geom_gaps,
                tile_curv_gaps=tile_curv_gaps,
                tile_gap_vector=tile_gap_vector,
                tile_map=tile_map,
                perception_gap=perception_gap,
                latent_whole=latent_whole,
                latent_per_tile=latent_per_tile,
                aggregated=aggregated,
                run_meta=run_meta,
                combined_repro_hash=combined_repro_hash,
                tile_pairing_provenance=tile_pairing_provenance,
                sumo_meta=sumo_meta,
            )
        aligned_auto = generated_xodr
        whole_geom_gap: Dict[str, Any] = {"disabled": True, "error": "manual map missing"}
        whole_curv_gap: Dict[str, Any] = {"disabled": True, "error": "manual map missing"}
        whole_elev_gap: Dict[str, Any] = _disabled_elevation_gap("dem_qc_failed")
        whole_inter_gap: Dict[str, Any] = {"disabled": True, "error": "manual map missing"}
        whole_sem_gap: Dict[str, Any] = {"disabled": True, "error": "manual map missing"}
        whole_class_gap: Dict[str, Any] = {"disabled": True, "error": "manual map missing"}
        whole_conn_gap: Dict[str, Any] = {"disabled": True, "error": "manual map missing"}
        tile_matches_raw: Any = {"error": "manual map missing"}
        tile_map: Dict[str, str] = {}
        tile_match_info: Dict[str, Dict[str, Any]] = {}
        tile_geom_gaps: Dict[str, Any] = {}
        tile_curv_gaps: Dict[str, Any] = {}
        tile_gap_vector: Dict[str, Dict[str, float]] = {}
        perception_gap: Optional[Dict[str, Any]] = None
        latent_whole: Any = None
        latent_per_tile: Any = None
        aggregated: Optional[Dict[str, Any]] = None
        return _finalize_results(
            output_dir=output_dir,
            reference_xodr=reference_xodr,
            aligned_auto=aligned_auto,
            generated_xodr=generated_xodr,
            transform=transform,
            whole_geom_gap=whole_geom_gap,
            whole_curv_gap=whole_curv_gap,
            whole_elev_gap=whole_elev_gap,
            whole_inter_gap=whole_inter_gap,
            whole_sem_gap=whole_sem_gap,
            whole_class_gap=whole_class_gap,
            tile_geom_gaps=tile_geom_gaps,
            tile_curv_gaps=tile_curv_gaps,
            tile_gap_vector=tile_gap_vector,
            tile_map=tile_map,
            perception_gap=perception_gap,
            latent_whole=latent_whole,
            latent_per_tile=latent_per_tile,
            aggregated=aggregated,
            run_meta=run_meta,
            combined_repro_hash=combined_repro_hash,
            tile_pairing_provenance=tile_pairing_provenance,
            sumo_meta=sumo_meta,
        )
    else:
        # ---------------------------------------------------------------
        # 1) MAP ALIGNMENT (manual <- auto)
        # ---------------------------------------------------------------
        log.info("🛠 Estimating GeoAlignment (manual ← auto)")
        canonical_manual_xodr = (_REPO_ROOT / "cities" / "ingolstadt" / "manual_grid0828.xodr").resolve()
        canonical_auto_xodr = (
            _REPO_ROOT / "artifacts" / "final_runs" / "scenario_b_audit" / "contract_run" / "08_final_structural_gap.xodr"
        ).resolve()
        authoritative_alignment_json = (
            _REPO_ROOT / "thesis_results" / "structural_gap_v1" / "run_11" / "alignment.json"
        )
        authoritative_aligned_xodr = (
            _REPO_ROOT / "thesis_results" / "structural_gap_v1" / "run_11" / "auto_aligned_rigid.xodr"
        )
        use_authoritative_alignment_bundle = False
        try:
            use_authoritative_alignment_bundle = (
                Path(reference_xodr).resolve() == canonical_manual_xodr
                and Path(generated_xodr).resolve() == canonical_auto_xodr
                and authoritative_alignment_json.is_file()
                and authoritative_aligned_xodr.is_file()
            )
        except Exception:
            use_authoritative_alignment_bundle = False
        try:
            if use_authoritative_alignment_bundle:
                transform = json.loads(authoritative_alignment_json.read_text(encoding="utf-8"))
                crs_meta = transform.get("crs_reprojection") if isinstance(transform, dict) else {}
                if not isinstance(crs_meta, dict):
                    crs_meta = {}
                transform["crs_alignment_applied"] = bool(
                    transform.get("crs_alignment_applied", crs_meta.get("applied", False))
                )
                transform["source_crs"] = transform.get("source_crs") or crs_meta.get("src_crs")
                transform["target_crs"] = transform.get("target_crs") or crs_meta.get("dst_crs")
                diag = transform.get("diagnostics")
                if isinstance(diag, dict):
                    diag["crs_alignment_applied"] = bool(
                        diag.get("crs_alignment_applied", transform["crs_alignment_applied"])
                    )
                    diag["source_crs"] = diag.get("source_crs") or transform["source_crs"]
                    diag["target_crs"] = diag.get("target_crs") or transform["target_crs"]
                log.info(
                    "Using authoritative frozen run_11 alignment bundle for the canonical thesis pair: %s",
                    authoritative_alignment_json,
                )
            else:
                transform = GeoAligner.estimate_from_xodr(
                    reference_xodr,
                    generated_xodr,
                    out_dir=output_dir,
                    strict=True,
                )
            transform = _ensure_alignment_fit_metric_note(transform)
            _raise_on_invalid_auto_georef_alignment(transform, georef_override)
            diag = transform.get("diagnostics", {})
            run_meta["crs_alignment_applied"] = bool(transform.get("crs_alignment_applied"))
            run_meta["source_crs"] = transform.get("source_crs")
            run_meta["target_crs"] = transform.get("target_crs")
            run_meta["alignment_bundle_source"] = (
                str(authoritative_alignment_json) if use_authoritative_alignment_bundle else "estimated_in_run"
            )
            if diag.get("fallback_used"):
                log.warning(
                    "Alignment used fallback (n_points=%d, reason=%s)",
                    diag.get("n_points", 0),
                    diag.get("fallback_reason", "unknown"),
                )
            log.info(
                "CRS alignment applied=%s source_crs=%s target_crs=%s",
                bool(transform.get("crs_alignment_applied")),
                str(transform.get("source_crs") or ""),
                str(transform.get("target_crs") or ""),
            )
        except Exception as e:
            raise RuntimeError(f"GeoAlignment estimation failed in strict CRS mode: {e}") from e

        aligned_auto = os.path.join(output_dir, "auto_aligned.xodr")
        hardened_auto = os.path.join(output_dir, "auto_aligned_hardened.xodr")
        hardener_report_path = Path(output_dir) / "xodr_hardener_report.json"
        hardener_applied = False
        hardener_report: Dict[str, Any] = {}
        auto_xodr_sha256_before = None
        auto_xodr_sha256_after = None

        try:
            if use_authoritative_alignment_bundle:
                Path(aligned_auto).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(authoritative_aligned_xodr, aligned_auto)
            else:
                GeoAligner.apply_to_xodr(generated_xodr, aligned_auto, transform)
        except Exception as e:
            raise RuntimeError(f"GeoAlignment application failed in strict CRS mode: {e}") from e

        _safe_dump_json(os.path.join(output_dir, "alignment.json"), transform)
        log.info("   → Saved aligned auto map → %s", aligned_auto)

        try:
            auto_xodr_sha256_before = _hash_file_sha256(aligned_auto)
            if use_authoritative_alignment_bundle:
                hardener_applied = False
                hardener_report = {"reason": "authoritative_alignment_bundle_reused"}
                log.info("   → Hardener skipped for authoritative aligned auto artifact")
            else:
                hardener_applied, hardener_report = _apply_xodr_hardener(
                    Path(aligned_auto),
                    Path(hardened_auto),
                    hardener_report_path,
                    log,
                )
                if hardener_applied and Path(hardened_auto).is_file():
                    auto_xodr_sha256_after = _hash_file_sha256(hardened_auto)
                    aligned_auto = hardened_auto
                    log.info("   → Hardened auto map → %s", aligned_auto)
                else:
                    log.info("   → Hardener not applied or failed; proceeding with aligned map")
        except Exception as e:  # pragma: no cover - defensive
            hardener_report = {"error": str(e)}
            log.warning("Hardener step failed (%s)", e)

        hardener_reason = hardener_report.get("error") if isinstance(hardener_report, dict) else None
        hardener_info = {
            "applied": bool(hardener_applied),
            "report_path": str(hardener_report_path) if hardener_report_path else None,
            "auto_xodr_sha256_before_hardening": auto_xodr_sha256_before,
            "auto_xodr_sha256_after_hardening": auto_xodr_sha256_after,
            "hardener_actions": hardener_report.get("repair_count") if isinstance(hardener_report, dict) else None,
            "hardener_invalid": hardener_report.get("invalid_count") if isinstance(hardener_report, dict) else None,
            "hardener_reason": hardener_reason,
        }
        run_meta["hardener"] = hardener_info
        kill_switch_provenance["hardener"] = hardener_info
        _safe_dump_json(os.path.join(output_dir, "run_metadata.json"), run_meta)

        if not auto_tiles_prealigned:
            aligned_tiles_out = _auto_generate_tiles_from_xodr(
                aligned_auto,
                aligned_tiles_root,
                log,
                origin_from_meta=manual_origin_meta,
                proj4_override=manual_proj4_for_tiles or None,
            )
            if not aligned_tiles_out:
                raise RuntimeError(
                    "Aligned auto tiles could not be generated from the post-alignment XODR. "
                    f"Check tiler_diagnostics.json under {aligned_tiles_root}."
                )
            auto_tiles = _resolve_tiles_dir(aligned_tiles_out)
            auto_meta_path = Path(aligned_tiles_out) / "tile_metadata.json"
            auto_meta_resolution = "generated_from_aligned_auto"
            auto_tiles_prealigned = True
            tile_pairing_provenance["auto_meta_resolved"] = str(auto_meta_path)
            tile_pairing_provenance["auto_meta_resolution"] = auto_meta_resolution
            tile_pairing_provenance["auto_tiles_dir_raw"] = auto_tiles
            try:
                prov = {
                    "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "python_executable": sys.executable,
                    "promotion_detected": bool(promotion_detected),
                    "auto_xodr_raw": str(auto_xodr_raw),
                    "auto_xodr_promoted": str(auto_xodr_promoted) if auto_xodr_promoted else "",
                    "auto_xodr_for_tiling": str(aligned_auto),
                    "auto_tiles_dir": str(auto_tiles),
                    "auto_meta_path": str(auto_meta_path) if auto_meta_path else "",
                    "tile_grid_bounds": _grid_bounds_from_tiles_dir(auto_tiles),
                }
                _safe_dump_json(os.path.join(output_dir, "provenance_auto_tiling.json"), prov)
            except Exception:
                pass
            if not manual_missing:
                generated_tiles = _auto_generate_aligned_manual_tiles(
                    reference_xodr, auto_meta_path, output_dir, log
                )
                if generated_tiles:
                    manual_tiles = generated_tiles
                    tile_pairing_provenance["manual_tiles_regenerated"] = True
                    tile_pairing_provenance["manual_tiles_override_source"] = "auto"
                    tile_pairing_provenance["regenerated_tiles_dir"] = generated_tiles
                    tile_pairing_provenance["manual_tiles_dir_resolved"] = manual_tiles

        # ---------------------------------------------------------------
        # P0 KILL SWITCH: Identity alignment detection
        # ---------------------------------------------------------------
        if _is_identity_transform(transform):
            alignment_transform_type = "identity"
            if _dg_enabled("geometry", True):
                if not allow_identity_alignment_override:
                    err_msg = (
                        "HARD STOP: Alignment resulted in identity transform. "
                        "Whole-map geometry metrics would compare misaligned maps. "
                        "Set UP_ALLOW_IDENTITY_ALIGNMENT=1 to override (not recommended)."
                    )
                    log.error(err_msg)
                    raise RuntimeError(err_msg)
                else:
                    alignment_override_used = True
                    alignment_override_warning = (
                        "UP_ALLOW_IDENTITY_ALIGNMENT=1: Proceeding with identity transform. "
                        "Geometry metrics may be invalid due to frame mismatch."
                    )
                    log.warning(alignment_override_warning)
        else:
            alignment_transform_type = "estimated"
        kill_switch_provenance["alignment"] = {
            "alignment_transform_type": alignment_transform_type,
            "alignment_override_used": alignment_override_used,
            "alignment_override_warning": alignment_override_warning,
        }

    # ---------------------------------------------------------------
    # 2) WHOLE-MAP GEOMETRY GAP
    # ---------------------------------------------------------------
    whole_geom_gap: Dict[str, Any] = {"disabled": True}
    alignment_diag = transform.get("diagnostics", {}) if isinstance(transform, dict) else {}
    source_crs = (
        transform.get("source_crs") if isinstance(transform, dict) else None
    ) or alignment_diag.get("source_crs")
    target_crs = (
        transform.get("target_crs") if isinstance(transform, dict) else None
    ) or alignment_diag.get("target_crs")
    crs_alignment_applied = bool(
        transform.get("crs_alignment_applied")
        if isinstance(transform, dict)
        else False
    ) or bool(alignment_diag.get("crs_alignment_applied"))
    crs_mismatch_without_reprojection = bool(
        source_crs
        and target_crs
        and str(source_crs) != str(target_crs)
        and not crs_alignment_applied
    )
    run_meta["crs_precheck"] = {
        "source_crs": source_crs,
        "target_crs": target_crs,
        "crs_alignment_applied": bool(crs_alignment_applied),
        "crs_mismatch_detected": bool(crs_mismatch_without_reprojection),
    }

    if _dg_enabled("geometry", True):
        log.info("📐 Computing whole-map geometric gap...")
        t0 = time.perf_counter()

        skip_hausdorff = getattr(SETTINGS, "GEOMETRY_GAP_SKIP_HAUSDORFF", False)
        if _bool_env("UP_GEOMETRY_GAP_SKIP_HAUSDORFF", "0"):
            skip_hausdorff = True
        if smoke:
            skip_hausdorff = True
        geom_max_geoms_env = str(os.getenv("UP_GEOMETRY_GAP_MAX_GEOMS", "") or "").strip()
        geom_max_samples_env = str(os.getenv("UP_GEOMETRY_GAP_MAX_SAMPLES", "") or "").strip()
        geom_max_geoms = None
        geom_max_samples = None
        if geom_max_geoms_env:
            try:
                geom_max_geoms = max(1, int(float(geom_max_geoms_env)))
            except Exception:
                log.warning(
                    "Invalid UP_GEOMETRY_GAP_MAX_GEOMS=%r; ignoring override.",
                    geom_max_geoms_env,
                )
                geom_max_geoms = None
        if geom_max_samples_env:
            try:
                geom_max_samples = max(1, int(float(geom_max_samples_env)))
            except Exception:
                log.warning(
                    "Invalid UP_GEOMETRY_GAP_MAX_SAMPLES=%r; ignoring override.",
                    geom_max_samples_env,
                )
                geom_max_samples = None
        if skip_hausdorff:
            log.info("⚡ Hausdorff distance disabled (GEOMETRY_GAP_SKIP_HAUSDORFF=True)")
        if geom_max_geoms is not None:
            log.info("⚡ Geometry max geoms override active (UP_GEOMETRY_GAP_MAX_GEOMS=%s)", geom_max_geoms)
        if geom_max_samples is not None:
            log.info("⚡ Geometry max samples override active (UP_GEOMETRY_GAP_MAX_SAMPLES=%s)", geom_max_samples)

        if crs_mismatch_without_reprojection:
            whole_geom_gap = {
                "disabled": False,
                "error": None,
                "rmse": None,
                "hausdorff": None,
                "hausdorff_norm": None,
                "skip_hausdorff": bool(skip_hausdorff),
                "crs_mismatch_detected": True,
                "crs_alignment_applied": bool(crs_alignment_applied),
                "source_crs": source_crs,
                "target_crs": target_crs,
                "skip_reason": "crs_mismatch_without_reprojection",
            }
            log.warning(
                "Geometry computation skipped: CRS mismatch detected without reprojection "
                "(source=%s target=%s).",
                str(source_crs or ""),
                str(target_crs or ""),
            )
        else:
            try:
                whole_geom_gap = GeometryGap.compute(
                    reference_xodr,
                    aligned_auto,
                    skip_hausdorff=skip_hausdorff,
                    max_geoms=geom_max_geoms,
                    max_samples=geom_max_samples,
                )
                whole_geom_gap["disabled"] = False
            except Exception as e:
                whole_geom_gap = {
                    "disabled": True,
                    "error": str(e),
                    "rmse": None,
                    "hausdorff": None,
                    "skip_hausdorff": skip_hausdorff,
                }
                log.warning("Geometry gap computation failed (%s)", e)

        # Defensive consistency (future-proofing)
        whole_geom_gap.setdefault("skip_hausdorff", skip_hausdorff)
        whole_geom_gap.setdefault("crs_mismatch_detected", bool(crs_mismatch_without_reprojection))
        whole_geom_gap.setdefault("crs_alignment_applied", bool(crs_alignment_applied))
        whole_geom_gap.setdefault("source_crs", source_crs)
        whole_geom_gap.setdefault("target_crs", target_crs)

        whole_geom_gap["runtime_sec"] = round(time.perf_counter() - t0, 2)

    # ---------------------------------------------------------------
    # 3) CURVATURE GAP
    # ---------------------------------------------------------------
    whole_curv_gap: Dict[str, Any] = {"disabled": True}
    if (not smoke) and _dg_enabled("curvature", True):
        log.info("🌐 Computing curvature gap...")
        try:
            whole_curv_gap = CurvatureGap.compute(reference_xodr, aligned_auto)
            whole_curv_gap["disabled"] = False
        except Exception as e:
            whole_curv_gap = {"disabled": True, "error": str(e), "kl_divergence": None}
            log.warning("Curvature gap computation failed (%s)", e)

    # ---------------------------------------------------------------
    # 4) SUPPLEMENTARY ELEVATION GAP
    # ---------------------------------------------------------------
    whole_elev_gap: Dict[str, Any] = _disabled_elevation_gap("dem_qc_failed")
    if (not smoke) and _dg_enabled("elevation", True):
        log.info("⛰️ Computing supplementary elevation gap...")
        whole_elev_gap = _compute_supplementary_elevation_gap(
            reference_xodr=reference_xodr,
            aligned_auto=aligned_auto,
            output_dir=output_dir,
            log=log,
            generated_xodr=generated_xodr,
            run_root=run_meta.get("run_root") or run_meta.get("auto_run_root"),
        )

    # ---------------------------------------------------------------
    # 5) INTERSECTION GAP
    # ---------------------------------------------------------------
    whole_inter_gap: Dict[str, Any] = {"disabled": True}
    if (not smoke) and _dg_enabled("intersection", True):
        log.info("🚦 Computing intersection-type gap...")
        try:
            whole_inter_gap = _call_intersection_gap(reference_xodr, aligned_auto)
            whole_inter_gap["disabled"] = False
        except Exception as e:
            whole_inter_gap = {"disabled": True, "error": str(e)}
            log.warning("Intersection gap computation failed (%s)", e)

    # ---------------------------------------------------------------
    # 6) SEMANTIC + ROAD CLASSIFICATION GAP
    # ---------------------------------------------------------------
    whole_sem_gap: Dict[str, Any] = {"disabled": True}
    if (not smoke) and _dg_enabled("semantics", True):
        log.info("🔖 Computing semantic/object gap...")
        try:
            whole_sem_gap = _call_semantic_gap(reference_xodr, aligned_auto)
            whole_sem_gap["disabled"] = False
        except Exception as e:
            whole_sem_gap = {"disabled": True, "error": str(e)}
            log.warning("Semantic gap computation failed (%s)", e)
    if isinstance(whole_sem_gap, dict) and not whole_sem_gap.get("disabled"):
        road_types = _safe_dict(whole_sem_gap.get("road_types"))
        sem_manual = _safe_dict(road_types.get("manual_length"))
        sem_auto = _safe_dict(road_types.get("auto_length"))
        sem_gap = _normalized_l1_over2(sem_manual, sem_auto)
        if sem_gap is not None:
            sem_gap = round(float(sem_gap), 4)
            whole_sem_gap["normalized_gap"] = sem_gap
            whole_sem_gap.setdefault("gap", sem_gap)
            whole_sem_gap.setdefault("gap_definition", "L1/2 over normalized road_type length distributions")

    whole_class_gap: Dict[str, Any] = {"disabled": True}
    if (not smoke) and _dg_enabled("road_classification", True):
        log.info("🚧 Computing road classification gap...")
        try:
            whole_class_gap = RoadClassificationGap.compute(reference_xodr, aligned_auto)
            whole_class_gap["disabled"] = False
        except Exception as e:
            whole_class_gap = {"disabled": True, "error": str(e)}
            log.warning("Road classification gap failed (%s)", e)
    if isinstance(whole_class_gap, dict) and not whole_class_gap.get("disabled"):
        class_manual = _safe_dict(whole_class_gap.get("manual_counts"))
        class_auto = _safe_dict(whole_class_gap.get("auto_counts"))
        class_gap = _normalized_l1_over2(class_manual, class_auto)
        if class_gap is not None:
            class_gap = round(float(class_gap), 4)
            whole_class_gap["normalized_gap"] = class_gap
            whole_class_gap.setdefault("gap", class_gap)
            whole_class_gap.setdefault("gap_definition", "L1/2 over normalized road_class count distributions")

    whole_conn_gap: Dict[str, Any] = {"disabled": True}
    if (not smoke) and _dg_enabled("connectivity", True):
        log.info("Computing connectivity gap...")
        try:
            whole_conn_gap = ConnectivityGap.compute(reference_xodr, aligned_auto)
            whole_conn_gap["disabled"] = False
        except Exception as e:
            whole_conn_gap = {"disabled": True, "error": str(e)}
            log.warning("Connectivity gap computation failed (%s)", e)

    # Save whole-map raw gaps early
    _safe_dump_json(os.path.join(output_dir, "gap_whole_geometry.json"), whole_geom_gap)
    _safe_dump_json(os.path.join(output_dir, "gap_whole_curvature.json"), whole_curv_gap)
    _safe_dump_json(os.path.join(output_dir, "gap_whole_elevation.json"), whole_elev_gap)
    _safe_dump_json(os.path.join(output_dir, "gap_whole_intersection.json"), whole_inter_gap)
    _safe_dump_json(os.path.join(output_dir, "gap_whole_semantics.json"), whole_sem_gap)
    _safe_dump_json(os.path.join(output_dir, "gap_whole_road_classification.json"), whole_class_gap)
    _safe_dump_json(os.path.join(output_dir, "gap_whole_connectivity.json"), whole_conn_gap)

    # ---------------------------------------------------------------
    # 6) VISUAL OVERLAY
    # ---------------------------------------------------------------
    if not smoke:
        log.info("🖼️ Generating overlay visualization...")
        try:
            overlay_maps(
                reference_xodr,
                aligned_auto,
                label_a="Manual Map",
                label_b="Auto (aligned)",
                out_png=os.path.join(output_dir, "overlay_manual_vs_auto.png"),
            )
        except Exception as e:
            log.warning("Overlay generation failed (%s)", e)

    # ---------------------------------------------------------------
    # 7) TILE MATCHING (guarded)
    # ---------------------------------------------------------------
    tile_matches_raw: Any = None
    tile_map: Dict[str, str] = {}
    tile_match_info: Dict[str, Dict[str, Any]] = {}
    per_tile_status = "skipped"
    per_tile_status_reason = "Tiles not configured or disabled."
    tile_pairing_warning: Optional[str] = None
    tile_pairing_source: Optional[str] = None
    tile_pairing_report: Optional[Dict[str, Any]] = None
    per_tile_disabled_reason: Optional[str] = None
    frames_incompatible = False

    corr_rows: List[dict] = []
    corr_path: Optional[Path] = None
    frame_label_a: Optional[str] = None
    frame_label_b: Optional[str] = None
    frame_label_source: Optional[str] = None
    correspondence_rows_total = 0
    correspondence_rows_used = 0
    correspondence_fallback_used = False
    allow_empty_correspondence_override_used = allow_empty_correspondence_override
    auto_corr_generated = False
    auto_corr_error: Optional[str] = None
    min_iou_used: Optional[float] = None
    correspondence_rows_missing_iou = 0
    corr_rows_raw: List[dict] = []
    tile_min_iou = _get_tile_min_iou(float(getattr(SETTINGS, "TILE_MATCH_MIN_IOU_FOR_GAP", 0.5)))

    if manual_tiles and not _is_dir_with_xodr(manual_tiles):
        raise RuntimeError(f"Manual tiles dir missing or empty: {manual_tiles}")
    can_do_tiles = _is_dir_with_xodr(manual_tiles) and _is_dir_with_xodr(auto_tiles)
    if can_do_tiles:
        min_iou_used = tile_min_iou

    # Log manifest search paths + canonical CRS (if present)
    manual_manifest_path = None
    auto_manifest_path = None
    manual_manifest = None
    auto_manifest = None
    manual_proj4 = ""
    auto_proj4 = ""
    canonical_proj4 = ""
    tile_frame_method = None
    tile_frame_transform = None
    tile_frame_offset = None
    if can_do_tiles:
        manual_meta_path = _find_tile_metadata(manual_tiles)
        auto_meta_path_tiles = _find_tile_metadata(auto_tiles)
        manual_manifest_path = _find_tile_manifest(manual_tiles)
        auto_manifest_path = _find_tile_manifest(auto_tiles)
        log.info("Tile metadata search (manual): %s", manual_meta_path or str(Path(manual_tiles) / 'tile_metadata.json'))
        log.info("Tile metadata search (auto):   %s", auto_meta_path_tiles or str(Path(auto_tiles) / 'tile_metadata.json'))
        log.info("Tile manifest search (manual): %s", manual_manifest_path or str(Path(manual_tiles).parent / 'tile_manifest.json'))
        log.info("Tile manifest search (auto):   %s", auto_manifest_path or str(Path(auto_tiles).parent / 'tile_manifest.json'))
        manual_manifest = _read_tile_manifest(manual_manifest_path)
        auto_manifest = _read_tile_manifest(auto_manifest_path)
        manual_proj4 = _read_tile_manifest_proj4(manual_manifest_path)
        auto_proj4 = _read_tile_manifest_proj4(auto_manifest_path)
        manual_georef_info = _read_georef_info(reference_xodr) if reference_xodr else None
        auto_georef_info = _read_georef_info(generated_xodr) if generated_xodr else None

        if not manual_proj4 and manual_tiles:
            manual_proj4 = _read_tiles_dir_proj4(manual_tiles)
        if not auto_proj4 and auto_tiles:
            auto_proj4 = _read_tiles_dir_proj4(auto_tiles)
        if not manual_proj4 and manual_georef_info:
            manual_proj4 = manual_georef_info.get("norm") or ""
        if not auto_proj4 and auto_georef_info:
            auto_proj4 = auto_georef_info.get("norm") or ""

        manual_params_complete = False
        auto_params_complete = False
        if manual_georef_info:
            manual_params_complete = bool(manual_georef_info.get("params_complete"))
        if auto_georef_info:
            auto_params_complete = bool(auto_georef_info.get("params_complete"))
        if isinstance(manual_manifest, dict):
            manual_params_complete = bool(manual_params_complete or manual_manifest.get("proj4_params_complete"))
        if isinstance(auto_manifest, dict):
            auto_params_complete = bool(auto_params_complete or auto_manifest.get("proj4_params_complete"))

        # Prefer the tile bundle CRS once auto tiles were generated from the aligned auto XODR.
        if auto_tiles_prealigned and (manual_proj4 or manual_proj4_for_tiles):
            auto_proj4 = manual_proj4 or manual_proj4_for_tiles
            auto_params_complete = True
        elif auto_georef_info and auto_georef_info.get("params_complete") and auto_georef_info.get("norm"):
            auto_proj4 = auto_georef_info.get("norm")
            auto_params_complete = True
        if manual_georef_info and manual_georef_info.get("params_complete") and manual_georef_info.get("norm"):
            manual_proj4 = manual_georef_info.get("norm")
            manual_params_complete = True

        if manual_proj4:
            canonical_proj4 = manual_proj4
        elif auto_proj4:
            canonical_proj4 = auto_proj4
        if manual_proj4 or auto_proj4:
            log.info("Tile CRS (manual proj4_norm): %s", manual_proj4 or "(missing)")
            log.info("Tile CRS (auto   proj4_norm): %s", auto_proj4 or "(missing)")
        if canonical_proj4:
            log.info("Canonical CRS (proj4_norm): %s", canonical_proj4)
        if manual_georef_info and not manual_params_complete:
            log.warning("Manual geoReference params incomplete (params_complete=false)")
        if auto_georef_info and not auto_params_complete:
            log.warning("Auto geoReference params incomplete (params_complete=false)")
        if manual_proj4 and auto_proj4 and manual_proj4 != auto_proj4:
            offset_info = _read_header_offset(generated_xodr) if generated_xodr else None
            if manual_params_complete and (not auto_params_complete) and _offset_large(offset_info):
                log.warning(
                    "Auto CRS incomplete + large offset; promoting auto CRS to manual canonical."
                )
                auto_proj4 = manual_proj4
                canonical_proj4 = manual_proj4
                if not georef_override:
                    try:
                        override = {
                            "reason": "auto_incomplete_large_offset_promoted_to_manual",
                            "auto_xodr_path_before": str(Path(generated_xodr)) if generated_xodr else "",
                            "auto_xodr_path_after": str(Path(generated_xodr)) if generated_xodr else "",
                            "manual_xodr_path": str(Path(reference_xodr)) if reference_xodr else "",
                            "auto_georef_before": auto_georef_info.get("norm") if auto_georef_info else "",
                            "auto_georef_after": manual_proj4 or "",
                            "manual_georef": manual_proj4 or "",
                            "auto_xodr_sha256_before": _hash_file_sha256(generated_xodr) if generated_xodr else "",
                            "auto_xodr_sha256_after": _hash_file_sha256(generated_xodr) if generated_xodr else "",
                            "manual_xodr_sha256": _hash_file_sha256(reference_xodr) if reference_xodr else "",
                            "offset": offset_info,
                        }
                        _safe_dump_json(os.path.join(output_dir, "georef_override.json"), override)
                    except Exception:
                        pass
            else:
                raise RuntimeError(
                    f"Tile frame mismatch: manual proj4_norm != auto proj4_norm "
                    f"(manual={manual_proj4} auto={auto_proj4})"
                )

    corr_env = os.getenv("UP_TILE_CORRESPONDENCE_CSV", "") or ""
    if corr_env:
        corr_path = Path(corr_env).expanduser()
        if corr_path.is_file():
            corr_rows = _load_correspondence_csv(corr_path)
            correspondence_rows_total = len(corr_rows)
            frame_label_a, frame_label_b, frame_label_source = _load_frame_labels(corr_path)
            log.info("Using correspondence CSV (rows=%d): %s", len(corr_rows), corr_path)
            if correspondence_rows_total == 0:
                if not _enforce_nonempty_tile_correspondence(
                    correspondence=corr_rows,
                    output_dir=output_dir,
                    logger=log,
                ):
                    correspondence_fallback_used = True
                    corr_rows = []
        else:
            log.warning("UP_TILE_CORRESPONDENCE_CSV set but file not found: %s", corr_path)
    elif can_do_tiles:
        auto_corr_error = "auto_correspondence_disabled_use_spatial_csv"

    if can_do_tiles:
        if auto_corr_error:
            log.info("Auto correspondence generation skipped (%s)", auto_corr_error)
        log.info("Matching manual tiles to auto tiles...")
        if auto_tiles_prealigned:
            tile_frame_method = "native_aligned"
            auto_tiles_aligned = auto_tiles
            aligned_tiles_dir = Path(auto_tiles_aligned)
            log.info("Tile frame method: native_aligned")
        else:
            offset_info = _read_header_offset(generated_xodr) if generated_xodr else None
            use_offset_bake = False
            if offset_info and _offset_bake_applicable(offset_info) and _offset_matches_transform(offset_info, transform):
                use_offset_bake = True
                tile_frame_method = "offset_bake"
                tile_frame_offset = offset_info
            else:
                tile_frame_method = "alignment"
                tile_frame_transform = transform

            if use_offset_bake:
                log.info(
                    "Tile frame method: offset_bake (x=%.3f, y=%.3f, hdg=%.6f)",
                    float(offset_info.get("x", 0.0)),
                    float(offset_info.get("y", 0.0)),
                    float(offset_info.get("hdg", 0.0)),
                )
            else:
                log.info("Tile frame method: alignment")

            auto_tiles_aligned = _align_tiles_dir(
                auto_tiles,
                output_dir,
                transform,
                log,
                offset_bake=offset_info if use_offset_bake else None,
                use_alignment=not use_offset_bake,
            )
            aligned_tiles_dir = Path(auto_tiles_aligned)
        aligned_tiles = sorted(aligned_tiles_dir.glob("tile_*.xodr")) if aligned_tiles_dir.is_dir() else []
        if not aligned_tiles:
            diag = {
                "tiles_dir": str(aligned_tiles_dir),
                "tiles_written": 0,
                "frame_method": tile_frame_method,
                "auto_tiles_input": auto_tiles,
            }
            try:
                _safe_dump_json(os.path.join(output_dir, "auto_tiles_aligned_diagnostics.json"), diag)
            except Exception:
                pass
            raise RuntimeError(
                f"Aligned auto tiles is empty: {aligned_tiles_dir}. "
                f"See auto_tiles_aligned_diagnostics.json under {output_dir}."
            )
        try:
            if not auto_tiles_prealigned:
                auto_manifest_path = _find_tile_manifest(auto_tiles)
                auto_manifest = _read_tile_manifest(auto_manifest_path) if auto_manifest_path else None
                proj4_norm = canonical_proj4 or _read_tile_manifest_proj4(auto_manifest_path)
                aligned_meta = _write_aligned_tile_metadata(
                    str(aligned_tiles_dir),
                    source_manifest=auto_manifest,
                    proj4_norm=proj4_norm,
                    out_path=os.path.join(str(aligned_tiles_dir), "tile_metadata_aligned.json"),
                )
                try:
                    _safe_dump_json(os.path.join(output_dir, "tile_metadata_aligned.json"), aligned_meta)
                except Exception:
                    pass
        except Exception as exc:
            log.warning("Failed to write tile_metadata_aligned.json (%s)", exc)

        if smoke:
            min_iou = tile_min_iou
            matches, pairing_report = TileMatcher.match_tiles_one_to_one(
                manual_tiles,
                auto_tiles_aligned,
                min_iou=min_iou,
                prefer_id=False,
            )
            tile_pairing_report = pairing_report
            _dump_pairing_report_early(output_dir, tile_pairing_report)
            try:
                _safe_dump_json(os.path.join(output_dir, "tile_pairing_report.json"), pairing_report)
            except Exception:
                pass
            manual_bounds = _load_tile_bounds(manual_tiles)
            auto_bounds = _load_tile_bounds(auto_tiles_aligned)
            debug_n = int(os.getenv("UP_TILE_DEBUG_N", "5") or "5")
            debug_rows = []
            for idx, (m_id, v) in enumerate(sorted(matches.items())[:debug_n], start=1):
                a_id = v.get("match") if isinstance(v, dict) else None
                mb = manual_bounds.get(m_id)
                ab = auto_bounds.get(a_id) if a_id else None
                if mb is None:
                    mp = os.path.join(manual_tiles, m_id)
                    mb = _tile_bounds_from_xodr(mp)
                if ab is None and a_id:
                    ap = os.path.join(auto_tiles_aligned, a_id)
                    ab = _tile_bounds_from_xodr(ap)
                debug_rows.append({
                    "manual_tile": m_id,
                    "auto_tile": a_id,
                    "manual_bbox": mb,
                    "auto_bbox": ab,
                    "iou": _bbox_iou(mb, ab) if (mb and ab) else None,
                    "frame_method": tile_frame_method,
                })
                log.info(
                    "Tile smoke %d: manual=%s auto=%s iou=%s",
                    idx,
                    m_id,
                    a_id,
                    debug_rows[-1]["iou"],
                )
            smoke_tile_bbox_debug_path = os.path.join(output_dir, "tile_bbox_debug.json")
            _safe_dump_json(smoke_tile_bbox_debug_path, {"rows": debug_rows})
            # NOTE: do NOT return here. Continue so the truthfulness gate enriches tile_pairing_report.json
            # and the unified SMOKE fast-path writes SUCCESS.txt.

        if not corr_rows:
            min_iou = tile_min_iou
            min_iou_used = min_iou
            try:
                matches, pairing_report = TileMatcher.match_tiles_one_to_one(
                    manual_tiles,
                    auto_tiles_aligned,
                    min_iou=min_iou,
                    prefer_id=False,
                )
                tile_pairing_report = pairing_report
                _dump_pairing_report_early(output_dir, tile_pairing_report)
                corr_path = Path(output_dir) / 'tile_correspondence.csv'
                _write_tile_correspondence_csv(corr_path, matches, min_iou=min_iou)
                corr_rows = _load_correspondence_csv(corr_path)
                correspondence_rows_total = len(corr_rows)
                if correspondence_rows_total == 0:
                    if not _enforce_nonempty_tile_correspondence(
                        correspondence=corr_rows,
                        output_dir=output_dir,
                        logger=log,
                    ):
                        correspondence_fallback_used = True
                tile_pairing_source = 'correspondence_csv'
                log.info('Generated spatial correspondence CSV (rows=%d, min_iou=%.3f): %s', correspondence_rows_total, min_iou, corr_path)
            except Exception as e:
                log.warning('Failed to generate spatial correspondence CSV (%s)', e)
                raise

        frames_incompatible = False
        if corr_rows and _frames_incompatible(frame_label_a, frame_label_b):
            frames_incompatible = True
            tile_pairing_source = "correspondence_csv"
            per_tile_status = "refused"
            per_tile_status_reason = f"Incompatible coordinate frames ({frame_label_a} vs {frame_label_b}). Per-tile pairing refused."
            log.warning(per_tile_status_reason)

        if corr_rows and not frames_incompatible:
            corr_rows_raw = list(corr_rows)
            correspondence_rows_missing_iou = sum(1 for r in corr_rows if r.get("iou") is None)
            filtered = []
            for r in corr_rows:
                if r.get("match_quality") and r.get("match_quality") != "good":
                    continue
                filtered.append(r)
            corr_rows = filtered
            correspondence_rows_used = len(corr_rows)

            debug_n = int(os.getenv("UP_TILE_DEBUG_N", "5") or "5")
            if debug_n > 0 and corr_rows:
                manual_bounds = _load_tile_bounds(manual_tiles)
                auto_bounds = _load_tile_bounds(auto_tiles_aligned)
                debug_rows = []
                for idx, r in enumerate(corr_rows[:debug_n], start=1):
                    m_id = _normalize_tile_id(r.get("a_id") or "", manual_tiles)
                    a_id = _normalize_tile_id(r.get("b_id") or "", auto_tiles_aligned)
                    mb = manual_bounds.get(m_id)
                    ab = auto_bounds.get(a_id)
                    if mb is None:
                        mp = os.path.join(manual_tiles, m_id)
                        mb = _tile_bounds_from_xodr(mp)
                    if ab is None:
                        ap = os.path.join(auto_tiles_aligned, a_id)
                        ab = _tile_bounds_from_xodr(ap)
                    if mb and ab:
                        iou_val = _bbox_iou(mb, ab)
                        log.info(
                            "Tile debug %d: manual=%s bbox=%s auto=%s bbox=%s iou=%.4f",
                            idx,
                            m_id,
                            mb,
                            a_id,
                            ab,
                            iou_val,
                        )
                        debug_rows.append({
                            "manual_tile": m_id,
                            "auto_tile": a_id,
                            "manual_bbox": mb,
                            "auto_bbox": ab,
                            "iou": iou_val,
                        })
                    else:
                        log.info(
                            "Tile debug %d: manual=%s bbox=%s auto=%s bbox=%s iou=NA",
                            idx,
                            m_id,
                            mb,
                            a_id,
                            ab,
                        )
                        debug_rows.append({
                            "manual_tile": m_id,
                            "auto_tile": a_id,
                            "manual_bbox": mb,
                            "auto_bbox": ab,
                            "iou": None,
                        })
                try:
                    debug_path = os.path.join(output_dir, "tile_bbox_debug.json")
                    _safe_dump_json(debug_path, {"rows": debug_rows})
                except Exception:
                    pass

            # P0 KILL SWITCH: Empty correspondence after filtering
            if correspondence_rows_used == 0 and correspondence_rows_total > 0:
                min_iou_val = min_iou_used
                if min_iou_val is None:
                    min_iou_val = tile_min_iou
                details = _summarize_correspondence_rejections(
                    corr_rows_raw if 'corr_rows_raw' in locals() else corr_rows,
                    manual_tiles,
                    auto_tiles_aligned,
                    min_iou_val,
                    max_rows=5,
                )
                if details:
                    log.error('Correspondence filter details (top %d rows):', len(details))
                    for d in details:
                        log.error(
                            '  row a_id=%s b_id=%s iou=%s distance=%s match_quality=%s reasons=%s',
                            d.get('a_id'), d.get('b_id'), d.get('iou'), d.get('distance'), d.get('match_quality'), d.get('reasons')
                        )
                if min_iou_val is not None:
                    log.error('min_iou=%.3f (UP_TILE_MIN_IOU or SETTINGS.TILE_MATCH_MIN_IOU_FOR_GAP)', float(min_iou_val))

                if not (allow_empty_correspondence_override or smoke):
                    fix_cmd = _manual_tiles_fix_command(reference_xodr, output_dir, auto_meta_path)
                    fix_msg = (
                        f"Re-tile manual map with origin-from-meta to align grids. Suggested: {fix_cmd}. "
                        if fix_cmd else
                        "Re-tile manual map with origin-from-meta to align grids. "
                    )
                    err_msg = (
                        f"HARD STOP: Correspondence CSV had {correspondence_rows_total} rows but "
                        f"0 usable rows after filtering. Per-tile metrics would be invalid. "
                        f"min_iou={min_iou_val} (UP_TILE_MIN_IOU or SETTINGS.TILE_MATCH_MIN_IOU_FOR_GAP). "
                        f"{fix_msg}"
                        f"Set UP_ALLOW_ZERO_TILE_CORRESPONDENCE=1 (or legacy UP_ALLOW_EMPTY_CORRESPONDENCE=1) to override (not recommended)."
                    )
                    reason_counts: Dict[str, int] = {}
                    for d in details or []:
                        for r in d.get("reasons") or []:
                            reason_counts[r] = reason_counts.get(r, 0) + 1
                    top_reasons = [
                        {"reason": k, "count": v}
                        for k, v in sorted(reason_counts.items(), key=lambda kv: (-kv[1], kv[0]))
                    ][:5]
                    diag = {
                        "correspondence_rows_total": correspondence_rows_total,
                        "correspondence_rows_used": correspondence_rows_used,
                        "correspondence_rows_iou_gt_0": sum(
                            1 for r in (corr_rows_raw if 'corr_rows_raw' in locals() else corr_rows)
                            if isinstance(r.get("iou"), (int, float)) and float(r.get("iou")) > 0.0
                        ),
                        "min_iou": min_iou_val,
                        "rejected_samples": details,
                        "top_rejection_reasons": top_reasons,
                        "grid_delta": tile_pairing_provenance.get("grid_delta"),
                        "auto_meta_path_used": tile_pairing_provenance.get("auto_meta_path_used"),
                        "auto_tile_metadata_used": tile_pairing_provenance.get("auto_tile_metadata_used"),
                        "alignment_reason": tile_pairing_provenance.get("alignment_reason"),
                        "manual_tiles_dir": manual_tiles,
                        "auto_tiles_dir": auto_tiles_aligned,
                        "manual_tiles_dir_raw": tile_pairing_provenance.get("manual_tiles_dir_raw"),
                        "auto_tiles_dir_raw": tile_pairing_provenance.get("auto_tiles_dir_raw"),
                        "manual_tiles_dir_resolved": tile_pairing_provenance.get("manual_tiles_dir_resolved"),
                        "manual_tiles_override_source": tile_pairing_provenance.get("manual_tiles_override_source"),
                        "auto_meta_resolved": tile_pairing_provenance.get("auto_meta_resolved"),
                        "auto_meta_resolution": tile_pairing_provenance.get("auto_meta_resolution"),
                        "manual_tiles_source_before": tile_pairing_provenance.get("manual_tiles_source_before"),
                        "manual_tiles_regenerated": tile_pairing_provenance.get("manual_tiles_regenerated"),
                        "regenerated_tiles_dir": tile_pairing_provenance.get("regenerated_tiles_dir"),
                        "python_executable": sys.executable,
                        "argv": sys.argv,
                    }
                    try:
                        _safe_dump_json(os.path.join(output_dir, "correspondence_rejects.json"), diag)
                    except Exception:
                        pass
                    log.error(err_msg)
                    raise RuntimeError(err_msg)
                else:
                    log.warning(
                        "%s Proceeding despite 0 usable correspondence rows. Per-tile metrics will be skipped.",
                        "SMOKE mode:" if smoke else "UP_ALLOW_ZERO_TILE_CORRESPONDENCE=1 (or legacy UP_ALLOW_EMPTY_CORRESPONDENCE=1):",
                    )
                    correspondence_fallback_used = True
            corr_map, pairing_report = _one_to_one_from_corr_rows(
                corr_rows,
                manual_tiles,
                auto_tiles_aligned,
                min_iou=float(min_iou_used or getattr(SETTINGS, 'TILE_MATCH_MIN_IOU_FOR_GAP', 0.5)),
            )
            tile_pairing_report = pairing_report
            _dump_pairing_report_early(output_dir, tile_pairing_report)
            tile_map = corr_map
            tile_match_info = corr_map
            tile_matches_raw = {
                "source": "correspondence_csv",
                "path": str(corr_path) if corr_path else None,
                "rows": len(corr_rows),
                "one_to_one_matches": len(corr_map),
                "frame_labels": {"a": frame_label_a, "b": frame_label_b, "source": frame_label_source},
            }
            tile_pairing_source = "correspondence_csv"
            per_tile_status_reason = "Correspondence CSV used."
        elif not corr_rows:
            correspondence_fallback_used = True
            try:
                matcher_fn = None
                for _name in ("match", "match_tiles", "match_directories", "run"):
                    _fn = getattr(TileMatcher, _name, None)
                    if callable(_fn):
                        matcher_fn = _fn
                        break
                if matcher_fn is None:
                    raise AttributeError(
                        "TileMatcher has no supported entrypoint (expected one of: match, match_tiles, match_directories, run)")

                try:
                    tile_matches_raw = matcher_fn(manual_tiles, auto_tiles_aligned)
                except TypeError:
                    try:
                        tile_matches_raw = matcher_fn(manual_tiles_dir=manual_tiles, auto_tiles_dir=auto_tiles_aligned)
                    except TypeError:
                        tile_matches_raw = matcher_fn(auto_tiles_aligned, manual_tiles)

                tile_map = _normalize_tile_matches(tile_matches_raw)
                tile_match_info = _normalize_tile_match_info(tile_matches_raw)
                tile_pairing_warning = (
                    "WARN: per-tile pairing uses tile keys; may be invalid if grid origins/frames differ. "
                    "Use evaluate_tiling.py and UP_TILE_CORRESPONDENCE_CSV for spatial pairing."
                )
                tile_pairing_source = "tile_keys"
                per_tile_status_reason = "TileMatcher key-based pairing."
            except Exception as e:
                tile_matches_raw = {"error": str(e)}
                tile_map = {}
                tile_match_info = {}
                log.warning("Tile matching failed (%s)", e)
        else:
            tile_matches_raw = {"error": per_tile_status_reason}
            tile_map = {}
            tile_match_info = {}
    else:
        log.info("Tiles not configured/found - skipping per-tile matching and per-tile gaps.")
        log.info("   manual_tiles ok: %s (%s)", _is_dir_with_xodr(manual_tiles), manual_tiles)
        log.info("   auto_tiles   ok: %s (%s)", _is_dir_with_xodr(auto_tiles), auto_tiles)
        if per_tile_status_reason == "Tiles not configured or disabled.":
            per_tile_status_reason = "Tiles not configured."

    # Raw matcher output for debugging + traceability
    _safe_dump_json(os.path.join(output_dir, "tile_matches.json"), tile_matches_raw)
    # Normalized mapping used by per-tile gap computation
    _safe_dump_json(os.path.join(output_dir, "tile_match_map.json"), tile_map)
    _safe_dump_json(os.path.join(output_dir, "tile_match_info.json"), tile_match_info)
    if tile_pairing_report is None:
        tile_pairing_report = {
            "status": "not_computed" if not can_do_tiles else "missing_report",
            "min_iou": float(getattr(SETTINGS, "TILE_MATCH_MIN_IOU_FOR_GAP", 0.5)),
        }
    # ------------------------------------------------------------------
    # Thesis truthfulness gate: always compute pairing stats + confidence
    # (never allow upstream code to set HIGH on sparse pairings)
    # ------------------------------------------------------------------
    min_iou = float(os.getenv("UP_TILE_MIN_IOU", str(tile_pairing_report.get("min_iou", 0.5) or 0.5)))
    min_matches_high = int(os.getenv("UP_TILE_MIN_MATCHES_HIGH", "10"))
    min_median_iou_high = float(os.getenv("UP_TILE_MIN_MEDIAN_IOU_HIGH", "0.5"))
    min_matches_med = int(os.getenv("UP_TILE_MIN_MATCHES_MED", "5"))
    min_median_iou_med = float(os.getenv("UP_TILE_MIN_MEDIAN_IOU_MED", "0.3"))
    force_per_tile = os.getenv("UP_FORCE_PER_TILE", "0").strip() == "1"

    tile_pairs = _collect_unique_tile_pairs(tile_pairing_report, tile_match_info)

    num_matches, ious, avg_iou, median_iou = _compute_pairing_stats(tile_pairs, min_iou=min_iou)
    match_ratio = float(num_matches) / float(max(1, len(tile_pairs)))
    enforced = _enforced_confidence(
        num_matches=num_matches,
        median_iou=median_iou,
        min_matches_high=min_matches_high,
        min_median_iou_high=min_median_iou_high,
        min_matches_med=min_matches_med,
        min_median_iou_med=min_median_iou_med,
    )

    tile_pairing_report["min_iou_threshold"] = min_iou
    tile_pairing_report["min_iou_used"] = min_iou
    tile_pairing_report["num_candidate_pairs"] = int(len(tile_pairs))
    tile_pairing_report["num_matches_at_min_iou"] = int(num_matches)
    tile_pairing_report["match_ratio"] = match_ratio
    tile_pairing_report["avg_iou"] = avg_iou
    tile_pairing_report["median_iou"] = median_iou
    if enforced == "HIGH":
        reason = f"num_matches>={min_matches_high} and median_iou>={min_median_iou_high}"
    elif enforced == "MEDIUM":
        reason = f"num_matches>={min_matches_med} and median_iou>={min_median_iou_med}"
    else:
        reason = f"num_matches<{min_matches_med} or median_iou<{min_median_iou_med}"
    tile_pairing_report["confidence"] = {
        "label": enforced,
        "reason": reason,
    }
    tile_pairing_report["confidence_rule"] = {
        "HIGH_requires_num_matches_gte": int(min_matches_high),
        "HIGH_requires_median_iou_gte": float(min_median_iou_high),
        "MEDIUM_requires_num_matches_gte": int(min_matches_med),
        "MEDIUM_requires_median_iou_gte": float(min_median_iou_med),
    }
    if "pairing_method" not in tile_pairing_report:
        if tile_pairing_source:
            tile_pairing_report["pairing_method"] = str(tile_pairing_source)
        else:
            tile_pairing_report["pairing_method"] = "unknown"
    if "one_to_one" not in tile_pairing_report:
        matches_seq = tile_pairing_report.get("matches") or []
        manual_ids = [m.get("manual") for m in matches_seq if isinstance(m, dict)]
        auto_ids = [m.get("auto") for m in matches_seq if isinstance(m, dict)]
        dup_manual = sorted({m for m in manual_ids if manual_ids.count(m) > 1})
        dup_auto = sorted({a for a in auto_ids if auto_ids.count(a) > 1})
        tile_pairing_report["one_to_one"] = {
            "ok": bool(len(dup_manual) == 0 and len(dup_auto) == 0),
            "duplicate_manual": dup_manual,
            "duplicate_auto": dup_auto,
        }
    if "exclusions" not in tile_pairing_report:
        exclusions = {}
        if "excluded_manual_tiles" in tile_pairing_report:
            exclusions["manual"] = tile_pairing_report.get("excluded_manual_tiles")
        if "excluded_auto_tiles" in tile_pairing_report:
            exclusions["auto"] = tile_pairing_report.get("excluded_auto_tiles")
        if "exclusion_reasons" in tile_pairing_report:
            exclusions["reasons"] = tile_pairing_report.get("exclusion_reasons")
        if exclusions:
            tile_pairing_report["exclusions"] = exclusions
    tile_pairing_report["forced_per_tile"] = bool(force_per_tile)
    tile_pairing_report["num_matches"] = int(num_matches)

    pairing_method = tile_pairing_report.get("pairing_method")
    if not isinstance(pairing_method, str) or not pairing_method.strip():
        _safe_dump_json(os.path.join(output_dir, "tile_pairing_report.json"), tile_pairing_report)
        raise RuntimeError("Tile pairing report missing required 'pairing_method'.")

    one_to_one = tile_pairing_report.get("one_to_one")
    one_to_one_ok = one_to_one.get("ok") if isinstance(one_to_one, dict) else None
    if one_to_one_ok is not True:
        _safe_dump_json(os.path.join(output_dir, "tile_pairing_report.json"), tile_pairing_report)
        raise RuntimeError("Tile pairing contract failed: one_to_one.ok must be true.")

    canonical_pairs: list[dict] = []
    matches_seq = tile_pairing_report.get("matches")
    if isinstance(matches_seq, list):
        for match in matches_seq:
            if not isinstance(match, dict):
                continue
            manual_id = (
                match.get("manual")
                or match.get("manual_tile")
                or match.get("manual_tile_id")
            )
            auto_id = (
                match.get("auto")
                or match.get("auto_tile")
                or match.get("auto_tile_id")
            )
            if not manual_id or not auto_id:
                continue
            iou_val = _try_float(match.get("iou"))
            cost_val = _try_float(match.get("cost"))
            if cost_val is None and iou_val is not None:
                cost_val = float(1.0 - iou_val)
            canonical_pairs.append(
                {
                    "manual_tile_id": str(manual_id),
                    "auto_tile_id": str(auto_id),
                    "cost": cost_val,
                }
            )
    canonical_pairs.sort(key=lambda row: (row.get("manual_tile_id", ""), row.get("auto_tile_id", "")))
    tile_pairing_report["pairs"] = canonical_pairs
    tile_pairing_report["num_pairs"] = int(len(canonical_pairs))
    tile_pairing_report["pairing_provenance"] = {
        "method": tile_pairing_report.get("pairing_method"),
        "min_iou_threshold": tile_pairing_report.get("min_iou_threshold"),
        "min_iou_used": tile_pairing_report.get("min_iou_used"),
        "num_candidate_pairs": tile_pairing_report.get("num_candidate_pairs"),
    }

    _safe_dump_json(os.path.join(output_dir, "tile_pairing_report.json"), tile_pairing_report)

    # --- Smoke mode: stop after tile pairing artifacts (Phase-2 fast path) ---
    if smoke:
        smoke_rows = corr_rows_raw if corr_rows_raw else corr_rows
        smoke_iou_threshold = float(getattr(SETTINGS, "TILE_MATCH_MIN_IOU_FOR_GAP", 0.0) or 0.0)
        smoke_passed_tiles = sum(
            1
            for row in smoke_rows
            if (_try_float((row or {}).get("iou")) or -1.0) >= smoke_iou_threshold
        )
        tile_iou_gate_summary = _build_tile_iou_gate_summary(
            smoke_rows,
            iou_gate_threshold=smoke_iou_threshold,
            tiles_passed_gate_count=int(smoke_passed_tiles),
            tiles_gated_count=max(len(smoke_rows) - int(smoke_passed_tiles), 0),
            match_method=(
                "index_fallback"
                if str(tile_pairing_report.get("pairing_method") or "").strip().lower() == "index_fallback"
                else "centroid_spatial"
            ),
        )
        tile_iou_report_path = _write_tile_iou_report(
            output_dir,
            rows=smoke_rows,
            summary=tile_iou_gate_summary,
        )
        run_meta["tile_metrics_skipped"] = True
        run_meta["tile_iou_gate_summary"] = tile_iou_gate_summary
        run_meta["tile_iou_report_json"] = tile_iou_report_path
        run_meta["tile_pairing_provenance"] = tile_pairing_provenance or {}
        run_meta["smoke"] = True
        _safe_dump_json(os.path.join(output_dir, "run_metadata.json"), run_meta)
        log.info("SMOKE mode: exiting after tile pairing artifacts (skipping whole-map/per-tile gap metrics).")
        try:
            write_success_txt(output_dir, summary="run_full_domain_gap_smoke")
        except Exception as exc:
            raise RuntimeError(
                f"Failed to write mandatory smoke success marker: {exc}"
            ) from exc
        # Coordinate-system evidence artifact for thesis defensibility.
        try:
            write_coordinate_system_json(
                Path(output_dir),
                Path(generated_xodr) if generated_xodr else None,
                manual_xodr_path=Path(reference_xodr) if reference_xodr else None,
                alignment_method=str(tile_frame_method or alignment_transform_type or "unknown"),
                alignment_transform_summary=transform if isinstance(transform, dict) else None,
                offset_bake_used=bool(tile_frame_method == "offset_bake"),
            )
        except Exception:
            try:
                write_coordinate_system_json(
                    Path(output_dir),
                    None,
                    manual_xodr_path=Path(reference_xodr) if reference_xodr else None,
                    alignment_method=str(tile_frame_method or alignment_transform_type or "unknown"),
                    alignment_transform_summary=transform if isinstance(transform, dict) else None,
                    offset_bake_used=bool(tile_frame_method == "offset_bake"),
                )
            except Exception:
                pass
        full_report = _finalize_smoke_results(
            output_dir=output_dir,
            reference_xodr=reference_xodr,
            aligned_auto=aligned_auto or generated_xodr,
            generated_xodr=generated_xodr,
            transform=transform,
            whole_geom_gap=whole_geom_gap,
            tile_iou_gate_summary=tile_iou_gate_summary,
            tile_map=tile_map,
            tile_pairing_source=tile_pairing_source,
            corr_path=corr_path,
            run_meta=run_meta,
            combined_repro_hash=combined_repro_hash,
            tile_pairing_provenance=tile_pairing_provenance,
            sumo_meta=sumo_meta,
        )
        return {
            "smoke": True,
            "output_dir": output_dir,
            "tile_pairing_report_written": True,
            "tile_iou_report_json": tile_iou_report_path,
            "full_report_json": os.path.join(output_dir, "full_report.json"),
            "tile_bbox_debug": locals().get("smoke_tile_bbox_debug_path"),
            "full_report": full_report,
        }

    if not corr_path or not Path(corr_path).is_file():
        try:
            corr_path = Path(output_dir) / "tile_correspondence.csv"
            corr_path.parent.mkdir(parents=True, exist_ok=True)
            if not corr_path.exists():
                with corr_path.open("w", encoding="utf-8", newline="") as f:
                    f.write("a_id,b_id,iou,match_quality,status\n")
        except Exception:
            pass
    if tile_pairing_warning:
        log.warning(tile_pairing_warning)

    # ---------------------------------------------------------------
    # 8) PER-TILE GEOMETRY & CURVATURE GAP (guarded + ablation)
    # ---------------------------------------------------------------
    tile_geom_gaps: Dict[str, Any] = {}
    tile_curv_gaps: Dict[str, Any] = {}

    do_tile_geom = can_do_tiles and _dg_enabled("geometry", True) and _dg_enabled("per_tile_geometry", True)
    do_tile_curv = can_do_tiles and _dg_enabled("curvature", True) and _dg_enabled("per_tile_curvature", True)

    # If confidence is LOW, skip per-tile gaps by default (thesis truthfulness)
    enforced_label = str((tile_pairing_report.get("confidence") or {}).get("label") or "LOW").upper()
    if not force_per_tile and enforced_label == "LOW":
        per_tile_disabled_reason = "pairing_confidence_low"
        per_tile_status = "skipped"
        per_tile_status_reason = "Per-tile gaps skipped (pairing confidence LOW)."
        do_tile_geom = False
        do_tile_curv = False
        try:
            _safe_dump_json(
                os.path.join(output_dir, "tile_metrics_status.json"),
                {
                    "skipped": True,
                    "reason": "confidence_low",
                    "pilot_only": True,
                    "confidence": enforced_label,
                    "num_matches_at_min_iou": int(tile_pairing_report.get("num_matches_at_min_iou", 0) or 0),
                    "median_iou_matches": tile_pairing_report.get("median_iou"),
                    "min_iou_used": tile_pairing_report.get("min_iou_used"),
                    "override": "set UP_FORCE_PER_TILE=1 to force per-tile evaluation",
                },
            )
        except Exception:
            pass

    if frames_incompatible:
        do_tile_geom = False
        do_tile_curv = False

    # Always defined (prevents log / dump errors outside the block)
    used_tiles = 0
    skipped_low_iou = 0
    missing_iou = 0
    total_tile_pairs_considered = 0

    if do_tile_geom or do_tile_curv:
        if tile_pairing_report and int(tile_pairing_report.get("num_matches", 0)) == 0:
            per_tile_disabled_reason = "no_tile_matches"
            per_tile_status = "skipped"
            per_tile_status_reason = "Per-tile gaps skipped (no tile matches)."
            do_tile_geom = False
            do_tile_curv = False
        if do_tile_geom or do_tile_curv:
            per_tile_status = "computed"
            log.info("Computing per-tile geometric & curvature gap...")
            skip_hausdorff_tile = bool(getattr(SETTINGS, "GEOMETRY_GAP_SKIP_HAUSDORFF", False))
            min_iou_for_gap = float(getattr(SETTINGS, "TILE_MATCH_MIN_IOU_FOR_GAP", 0.0) or 0.0)

            log.info("   per-tile IoU gate: TILE_MATCH_MIN_IOU_FOR_GAP=%.3f", min_iou_for_gap)
            if skip_hausdorff_tile:
                log.info("   per-tile Hausdorff disabled (GEOMETRY_GAP_SKIP_HAUSDORFF=True)")

            for manual_tile, match in tile_map.items():
                m_path = os.path.join(manual_tiles, manual_tile)

            # --- accept both: tile_map[manual] = "auto_tile.xodr"
            # --- and: tile_map[manual] = {"auto_tile": "...", "iou": 0.97, ...}
                if isinstance(match, dict):
                    auto_tile = match.get("match") or match.get("auto_tile") or match.get("tile") or match.get("name")
                    iou = match.get("iou", None)
                    match_status = match.get("status")
                else:
                    auto_tile = match
                    iou = None
                    match_status = None

                total_tile_pairs_considered += 1

                # If IoU/status were not carried through in `tile_map` (e.g., tile_map is manual->auto_tile),
                # recover them from the richer `tile_match_info` dict.
                if iou is None or match_status is None:
                    info = tile_match_info.get(manual_tile) if isinstance(tile_match_info, dict) else None
                    if isinstance(info, dict):
                        if iou is None:
                            iou = info.get('iou', None)
                        if match_status is None:
                            match_status = info.get('status')

                if not isinstance(auto_tile, str):
                    err = f"invalid auto_tile: {auto_tile} (type={type(auto_tile)})"
                    if do_tile_geom:
                        tile_geom_gaps[manual_tile] = {"error": err, "rmse": None, "rmse_cropped": None, "hausdorff": None,
                                                       "hausdorff_norm": None}
                    if do_tile_curv:
                        tile_curv_gaps[manual_tile] = {"error": err, "kl_divergence": None, "js_divergence": None}
                    continue

            # --- IoU gate (critical!)
            # If IoU missing/invalid, treat as 0.0 so the gate can protect you.
                if iou is None:
                    missing_iou += 1
                    iou_val = 0.0
                else:
                    try:
                        iou_val = float(iou)
                    except Exception:
                        missing_iou += 1
                        iou_val = 0.0

                low_iou_status = str(match_status or "").strip() == "unmatched_low_iou"
                if low_iou_status or iou_val < min_iou_for_gap:
                    skipped_low_iou += 1
                    _print_tile_iou_gate_rejection(
                        pair_name=f"{manual_tile}->{auto_tile}",
                        iou=float(iou_val),
                        threshold=float(min_iou_for_gap),
                    )
                    skip_reason = (
                        "tile_match_status=unmatched_low_iou"
                        if low_iou_status
                        else f"iou={iou_val:.3f} < {min_iou_for_gap:.3f}"
                    )
                    if do_tile_geom:
                        tile_geom_gaps[manual_tile] = {
                            "status": "skipped_low_iou",
                            "disabled": True,
                            "reason": "iou_below_threshold",
                            "skip_reason": skip_reason,
                            "rmse": None,
                            "rmse_cropped": None,
                            "hausdorff": None,
                            "hausdorff_norm": None,
                            "iou": iou_val,
                            "auto_tile": auto_tile,
                        }
                    if do_tile_curv:
                        tile_curv_gaps[manual_tile] = {
                            "status": "skipped_low_iou",
                            "disabled": True,
                            "reason": "iou_below_threshold",
                            "skip_reason": skip_reason,
                            "kl_divergence": None,
                            "js_divergence": None,
                            "iou": iou_val,
                            "auto_tile": auto_tile,
                        }
                    continue

            # Passed gate -> compute gaps
                a_path_raw = os.path.join(auto_tiles_aligned, auto_tile)
                a_path = a_path_raw

            # Optional per-tile alignment: fixes mismatched tile origins / frames between tilesets.
            # Enabled by default (PER_TILE_ALIGN_AUTO_TO_MANUAL=True).
                if bool(getattr(SETTINGS, "PER_TILE_ALIGN_AUTO_TO_MANUAL", True)):
                    try:
                        per_tile_dir = os.path.join(output_dir, "auto_tiles_aligned_per_tile")
                        os.makedirs(per_tile_dir, exist_ok=True)

                        safe_name = manual_tile.replace(os.sep, "_")
                        out_tile = os.path.join(per_tile_dir, f"aligned_{safe_name}")
                        if not out_tile.lower().endswith(".xodr"):
                            out_tile += ".xodr"

                        t_tile = GeoAligner.estimate_from_xodr(m_path, a_path_raw)
                        GeoAligner.apply_to_xodr(a_path_raw, out_tile, t_tile)
                        a_path = out_tile
                    except Exception as e:
                        # Fallback: translation-only alignment using <planView><geometry> centroids
                        m_c = _planview_centroid(m_path)
                        a_c = _planview_centroid(a_path_raw)
                        if m_c and a_c:
                            dx = m_c[0] - a_c[0]
                            dy = m_c[1] - a_c[1]
                            if (dx*dx + dy*dy) > 1e-6:
                                ok = _translate_planview_geometry(a_path_raw, out_tile, dx, dy)
                                if ok:
                                    log.info("Per-tile fallback translation align: %s (delta=%.1fm)", manual_tile, (dx*dx + dy*dy) ** 0.5)
                                    a_path = out_tile
                                else:
                                    log.debug("Per-tile translation fallback failed for %s; using raw auto tile.", manual_tile)
                                    a_path = a_path_raw
                            else:
                                a_path = a_path_raw
                        else:
                            log.debug("Per-tile alignment failed for %s (%s); using raw auto tile.", manual_tile, e)
                            a_path = a_path_raw
                used_tiles += 1

                if do_tile_geom:
                    try:
                        g = GeometryGap.compute(m_path, a_path, skip_hausdorff=skip_hausdorff_tile)
                        rmse_cropped = None
                        try:
                            tile_eval = TileGapEvaluator.compute(
                                m_path,
                                a_path,
                                min_iou=0.0,
                            )
                            rmse_cropped = tile_eval.get("rmse_cropped", None)
                        except Exception as crop_exc:
                            log.debug("Per-tile cropped RMSE failed for %s: %s", manual_tile, crop_exc)
                        tile_geom_gaps[manual_tile] = {
                            "rmse": g.get("rmse", None),
                            "rmse_cropped": rmse_cropped,
                            "hausdorff": g.get("hausdorff", None),
                            "hausdorff_norm": g.get("hausdorff_norm", None),
                            "iou": iou_val,
                            "auto_tile": auto_tile,
                        }
                    except Exception as e:
                        tile_geom_gaps[manual_tile] = {
                            "error": str(e),
                            "rmse": None,
                            "rmse_cropped": None,
                            "hausdorff": None,
                            "hausdorff_norm": None,
                            "iou": iou_val,
                            "auto_tile": auto_tile,
                        }

                if do_tile_curv:
                    try:
                        c = CurvatureGap.compute(m_path, a_path)
                        tile_curv_gaps[manual_tile] = {
                            "kl_divergence": c.get("kl_divergence", None),
                            "js_divergence": c.get("js_divergence", None),
                            "iou": iou_val,
                            "auto_tile": auto_tile,
                        }
                    except Exception as e:
                        tile_curv_gaps[manual_tile] = {
                            "error": str(e),
                            "kl_divergence": None,
                            "js_divergence": None,
                            "iou": iou_val,
                            "auto_tile": auto_tile,
                        }

    if do_tile_geom or do_tile_curv:
        _print_tile_iou_gate_summary(
            n_rejected=skipped_low_iou,
            n_total=total_tile_pairs_considered,
            threshold=float(min_iou_for_gap) if 'min_iou_for_gap' in locals() else 0.0,
        )

    log.info("   per-tile summary: used_tiles=%d, skipped_low_iou=%d, missing_iou=%d", used_tiles, skipped_low_iou,
             missing_iou)

    _safe_dump_json(os.path.join(output_dir, "tile_geom_gap.json"), tile_geom_gaps)
    _safe_dump_json(os.path.join(output_dir, "tile_curv_gap.json"), tile_curv_gaps)

    # ---------------------------------------------------------------
    # 8B) NORMALIZED PER-TILE GAP VECTOR (comparability)
    # ---------------------------------------------------------------
    # Reference scales from SETTINGS (academic contract)
    ref_geom_rmse = _get_norm_ref("geometry_rmse_m", 1.0)
    ref_curv_kl = _get_norm_ref("curvature_kl", 0.5)

    tile_gap_vector: Dict[str, Dict[str, float]] = {}
    tile_keys = set(tile_geom_gaps.keys()) | set(tile_curv_gaps.keys())

    for tile in sorted(tile_keys):
        rmse_val = None
        if isinstance(tile_geom_gaps.get(tile), dict):
            rmse_val = tile_geom_gaps[tile].get("rmse", None)

        kl_val = None
        if isinstance(tile_curv_gaps.get(tile), dict):
            kl_val = tile_curv_gaps[tile].get("kl_divergence", None)

        tile_gap_vector[tile] = {
            "geometry_norm": _normalize(rmse_val, ref=ref_geom_rmse),
            "curvature_norm": _normalize(kl_val, ref=ref_curv_kl),
        }

    _safe_dump_json(os.path.join(output_dir, "tile_gap_vector.json"), tile_gap_vector)

    # Heatmaps (only if there is data)
    # TileHeatmapPlotter expects a dict[str, float]; we feed extracted scalar metric
    if tile_geom_gaps:
        try:
            scalar = {
                k: float(v.get("rmse") or 0.0) for k, v in tile_geom_gaps.items() if isinstance(v, dict)
            }
            if scalar:
                TileHeatmapPlotter.plot(
                    scalar,
                    os.path.join(output_dir, "heatmap_geometric_gap.png"),
                    title="Geometric Domain Gap (per tile, RMSE)",
                )
        except Exception as e:
            log.warning("Geometric heatmap failed (%s)", e)

    if tile_curv_gaps:
        try:
            scalar = {
                k: float(v.get("kl_divergence") or 0.0) for k, v in tile_curv_gaps.items() if isinstance(v, dict)
            }
            if scalar:
                TileHeatmapPlotter.plot(
                    scalar,
                    os.path.join(output_dir, "heatmap_curvature_gap.png"),
                    title="Curvature Domain Gap (per tile, KL-divergence)",
                )
        except Exception as e:
            log.warning("Curvature heatmap failed (%s)", e)

    else:
        if per_tile_status != "refused":
            per_tile_status = "skipped"
            if per_tile_status_reason == "Tiles not configured or disabled.":
                per_tile_status_reason = "Per-tile gaps disabled or not requested."

    # ---------------------------------------------------------------
    # 9) PERCEPTION GAP (optional + ablation)
    # ---------------------------------------------------------------
    perception_gap: Optional[Dict[str, Any]] = None
    # Auto-discover perception JSONs if not provided (helps pipeline integration)
    perception_manual_json, perception_auto_json = _auto_discover_perception_jsons(
        output_dir, perception_manual_json, perception_auto_json
    )

    if _dg_enabled("perception", False) and perception_manual_json and perception_auto_json:
        log.info("Computing perception gap...")
        try:
            try:
                manual_metrics = PerceptionEvaluator.load_metrics(perception_manual_json)
            except Exception:
                manual_metrics = _load_metrics_fallback(perception_manual_json)

            try:
                auto_metrics = PerceptionEvaluator.load_metrics(perception_auto_json)
            except Exception:
                auto_metrics = _load_metrics_fallback(perception_auto_json)

            try:
                perception_gap = PerceptionGap.compare(manual_metrics, auto_metrics)
            except Exception:
                perception_gap = _fallback_perception_gap(manual_metrics, auto_metrics)

            _safe_dump_json(os.path.join(output_dir, "perception_gap.json"), perception_gap)
        except Exception as e:
            log.warning("Perception gap computation failed (%s)", e)
    else:
        log.info("No perception metrics provided or perception gap disabled - skipping perception-gap stage.")

    pair_metrics = _load_pair_metrics_from_env()
    if pair_metrics is not None:
        if perception_gap is None:
            perception_gap = {"enabled": True, "status": "pair_metrics_only"}
        perception_gap["pair_metrics"] = pair_metrics
        perception_gap["enabled"] = True
        _safe_dump_json(os.path.join(output_dir, "perception_gap.json"), perception_gap)

    # ---------------------------------------------------------------
    # 9B) LEARNED / GNN LATENT GAP (optional)
    # ---------------------------------------------------------------

    if SETTINGS.ENABLE_GNN_DOMAIN_GAP and not TORCH_GEOMETRIC_AVAILABLE:
        log.warning(
            "torch_geometric not available - skipping GNN domain gap "
            "(ENABLE_GNN_DOMAIN_GAP=True)"
        )

    latent_whole: Any = None
    latent_per_tile: Any = None

    if getattr(SETTINGS, "ENABLE_GNN_DOMAIN_GAP", False):
        log.info("Computing latent (GNN) domain gap...")
        try:
            from ultimate_pipeline.domain_gap_gnn.latent_gap_runner import (
                compute_whole_map_latent_gap,
                compute_per_tile_latent_gap,
            )

            ckpt = getattr(SETTINGS, "GNN_CHECKPOINT_PATH", None)
            if not ckpt:
                raise RuntimeError("ENABLE_GNN_DOMAIN_GAP=True but GNN_CHECKPOINT_PATH is not set")

            latent_whole = compute_whole_map_latent_gap(
                manual_xodr=reference_xodr,
                auto_xodr=aligned_auto,
                checkpoint=ckpt,
            )

            if can_do_tiles:
                latent_per_tile = compute_per_tile_latent_gap(
                    manual_tiles=manual_tiles,
                    auto_tiles=auto_tiles_aligned,
                    checkpoint=ckpt,
                    out_json=os.path.join(output_dir, "latent_per_tile_gap.json"),
                )
            else:
                log.info("⚠ Tiles not configured - skipping latent per-tile gap.")

            if isinstance(latent_per_tile, dict) and latent_per_tile:
                try:
                    TileHeatmapPlotter.plot(
                        latent_per_tile,
                        os.path.join(output_dir, "heatmap_latent_gap.png"),
                        title="Learned Latent Domain Gap (GNN)",
                    )
                except Exception as e:
                    log.warning("Latent heatmap failed (%s)", e)

        except ModuleNotFoundError as e:
            if getattr(SETTINGS, "GNN_STRICT_MODE", False):
                raise
            log.warning("GNN domain gap skipped (missing dependency): %s", e)
        except Exception as e:
            log.warning("GNN domain-gap computation failed (%s)", e)

    # ---------------------------------------------------------------
    # 9C) AGGREGATION (optional, settings-driven)
    # ---------------------------------------------------------------
    aggregated: Optional[Dict[str, Any]] = None
    aggregator_disabled: Optional[str] = None
    aggregator_enabled = _dg_enabled("aggregate", True)
    if aggregator_enabled and DomainGapAggregator is None:
        try:
            from ultimate_pipeline.domain_gap.domain_gap_aggregator import DomainGapAggregator as _DomainGapAggregator

            DomainGapAggregator = _DomainGapAggregator  # type: ignore
        except Exception as e:
            aggregator_disabled = f"DomainGapAggregator not available: {e}"
            DomainGapAggregator = None  # type: ignore

    if aggregator_enabled and DomainGapAggregator is not None:
        try:
            # DomainGapAggregator should be settings-driven internally, but we also pass explicitly.
            aggregated = DomainGapAggregator.aggregate(
                gap_geometry=whole_geom_gap,
                gap_curvature=whole_curv_gap,
                gap_elevation=whole_elev_gap,
                gap_intersection=whole_inter_gap,
                gap_semantic=whole_sem_gap,
                gap_road_classification=whole_class_gap,
                gap_connectivity=whole_conn_gap,
                compute_composite=True,
                normalization=getattr(SETTINGS, "DOMAIN_GAP_NORMALIZATION", None),
                weights=getattr(SETTINGS, "DOMAIN_GAP_WEIGHTS", None),
            )
            _safe_dump_json(os.path.join(output_dir, "aggregated_gap.json"), aggregated)
        except Exception as e:
            log.warning("Aggregation failed (%s)", e)
            aggregated = {"error": str(e)}
    else:
        if not aggregator_enabled:
            log.info("Aggregation disabled via settings.")
        elif DomainGapAggregator is None:
            log.info("ℹ️ DomainGapAggregator not available — skipping aggregation stage.")
            if aggregator_disabled:
                aggregated = {"enabled": False, "reason": aggregator_disabled}

    normalization_contract = _normalization_contract()
    normalization_contract["applied_to"] = {
        "tile_gap_vector": True,
        "aggregation": bool(aggregator_enabled),
    }
    normalization_contract["aggregation_applied"] = bool(
        aggregator_enabled and isinstance(aggregated, dict) and "error" not in aggregated
    )
    if aggregator_disabled:
        normalization_contract["aggregation_unavailable_reason"] = aggregator_disabled

    domain_gap_metrics = _compute_required_domain_gap_metrics(
        reference_xodr=reference_xodr,
        aligned_auto=aligned_auto,
        whole_inter_gap=whole_inter_gap if isinstance(whole_inter_gap, dict) else {},
    )
    _enforce_required_domain_gap_metrics(domain_gap_metrics, context="run_full_domain_gap")

    run_meta["auto_correspondence_generated"] = auto_corr_generated
    run_meta["auto_correspondence_error"] = auto_corr_error
    run_meta["tile_correspondence_csv"] = str(corr_path) if corr_path else None
    run_meta["tile_pairing_min_iou"] = float(min_iou_used) if min_iou_used is not None else float(getattr(SETTINGS, 'TILE_MATCH_MIN_IOU_FOR_GAP', 0.5))
    run_meta["tile_pairing_counts"] = {
        "correspondence_rows_total": correspondence_rows_total,
        "correspondence_rows_used": correspondence_rows_used,
        "skipped_low_iou": max(correspondence_rows_total - correspondence_rows_used, 0),
        "missing_iou": correspondence_rows_missing_iou,
    }
    tile_iou_gate_summary = _build_tile_iou_gate_summary(
        corr_rows_raw if corr_rows_raw else corr_rows,
        iou_gate_threshold=float(getattr(SETTINGS, "TILE_MATCH_MIN_IOU_FOR_GAP", 0.0) or 0.0),
        tiles_passed_gate_count=used_tiles,
        tiles_gated_count=skipped_low_iou,
        match_method=(
            "index_fallback"
            if str(tile_pairing_report.get("pairing_method") or "").strip().lower() == "index_fallback"
            else "centroid_spatial"
        ) if isinstance(tile_pairing_report, dict) else None,
    )
    tile_iou_report_path = _write_tile_iou_report(
        output_dir,
        rows=corr_rows_raw if corr_rows_raw else corr_rows,
        summary=tile_iou_gate_summary,
    )
    run_meta["tile_alignment_skip_requested"] = bool(skip_tile_alignment)
    run_meta["tile_alignment_required"] = not bool(skip_tile_alignment)
    run_meta["tile_metrics_skipped"] = bool(per_tile_status != "computed")
    run_meta["tile_iou_gate_summary"] = tile_iou_gate_summary
    run_meta["tile_iou_report_json"] = tile_iou_report_path
    run_meta["tile_pairing_provenance"] = {
        "canonical_proj4_norm": canonical_proj4,
        "manual_manifest_path": str(manual_manifest_path) if manual_manifest_path else None,
        "auto_manifest_path": str(auto_manifest_path) if auto_manifest_path else None,
        "manual_grid": _grid_info_from_manifest(manual_manifest),
        "auto_grid": _grid_info_from_manifest(auto_manifest),
        "frame_method": tile_frame_method,
        "frame_offset": tile_frame_offset,
        "frame_transform": tile_frame_transform,
        **(tile_pairing_provenance or {}),
    }
    _safe_dump_json(os.path.join(output_dir, "run_metadata.json"), run_meta)

    # ---------------------------------------------------------------
    # 10) FINAL REPORT
    # ---------------------------------------------------------------
    thesis_scope = _thesis_scope_fields()
    crs_comparability = _write_crs_comparability(
        Path(output_dir),
        reference_xodr,
        generated_xodr,
    )

    if tile_pairing_source is None:
        tile_pairing_source = "none"

    alignment_diag = transform.get("diagnostics", {}) if isinstance(transform, dict) else {}
    source_crs = (
        transform.get("source_crs") if isinstance(transform, dict) else None
    ) or alignment_diag.get("source_crs")
    target_crs = (
        transform.get("target_crs") if isinstance(transform, dict) else None
    ) or alignment_diag.get("target_crs")
    crs_alignment_applied = bool(
        transform.get("crs_alignment_applied")
        if isinstance(transform, dict)
        else False
    ) or bool(alignment_diag.get("crs_alignment_applied"))

    connectivity_gap = _normalize_connectivity_gap_payload(
        whole_conn_gap,
        run_meta=run_meta,
        default_reason=_connectivity_default_reason(whole_conn_gap, run_meta=run_meta),
    )

    combined: Dict[str, Any] = {
        **thesis_scope,
        "reference_map": {
            "type": "manual",
            "path": reference_xodr,
            "manual_reference_status": manual_reference_status,
            "assumed_properties": [
                "expert-designed",
                "structurally consistent",
                "perceptually stable",
            ],
        },
        "generated_map": {
            "type": "osm_generated",
            "path": aligned_auto,
            "generation_pipeline": "OSM → OpenDRIVE → CARLA",
        },
        "alignment": transform,
        "crs_alignment_applied": bool(crs_alignment_applied),
        "source_crs": source_crs,
        "target_crs": target_crs,
        "structural_domain_gap": {
            "geometry": whole_geom_gap,
            "curvature": whole_curv_gap,
            "elevation": whole_elev_gap,
            "intersection": whole_inter_gap,
            "semantics": whole_sem_gap,
            "road_classification": whole_class_gap,
            "connectivity": connectivity_gap,
        },
        "elevation": whole_elev_gap,
        "elevation_gap": whole_elev_gap,
        "connectivity_gap": connectivity_gap,
        "per_tile_structural_gap": _combine_per_tile_structural_gap(tile_geom_gaps, tile_curv_gaps),
        "per_tile_status": per_tile_status,
        "per_tile_status_reason": per_tile_status_reason,
        "tile_metrics_skipped": bool(per_tile_status != "computed"),
        "tile_pairing_source": tile_pairing_source,
        "tile_pairing_warning": tile_pairing_warning,
        "tile_correspondence_csv": str(corr_path) if corr_path else None,
        "tile_iou_gate_summary": tile_iou_gate_summary,
        "normalized_tile_gap_vector": tile_gap_vector,
        "latent_domain_gap": {
            "whole": latent_whole,
            "per_tile": latent_per_tile,
        },
        "perceptual_effects": {
            "perception_gap": perception_gap,
        },
        "tile_matches": tile_map,
        "aggregation": aggregated,
        "normalization_contract": normalization_contract,
        "run_metadata": run_meta,
        "crs_comparability": crs_comparability,
        # P0 KILL SWITCH PROVENANCE (thesis traceability)
        "kill_switch_provenance": {
            "allow_empty_correspondence_override": allow_empty_correspondence_override,
            "correspondence_rows_total": correspondence_rows_total,
            "correspondence_rows_used": correspondence_rows_used,
            "correspondence_fallback_used": correspondence_fallback_used,
            "alignment_transform_type": alignment_transform_type,
            "alignment_override_used": alignment_override_used,
            "alignment_override_warning": alignment_override_warning,
            "auto_correspondence_generated": auto_corr_generated,
            "auto_correspondence_error": auto_corr_error,
            "hardener": kill_switch_provenance.get("hardener"),
        },
    }
    _attach_auto_georef_metadata(combined, run_meta)

    # Optional: IoU summary passthrough
    iou_summary_path = os.path.join(output_dir, "iou_summary.json")
    if os.path.exists(iou_summary_path):
        try:
            with open(iou_summary_path, "r", encoding="utf-8") as f:
                combined["tile_iou_summary"] = json.load(f)
        except Exception as e:
            log.warning("Failed to load IoU summary (%s)", e)

    # Hashes
    try:
        combined["map_hashes"] = {
            "reference_map_sha256": _hash_file_sha256(reference_xodr),
            "auto_aligned_sha256": _hash_file_sha256(aligned_auto),
            "auto_original_sha256": _hash_file_sha256(generated_xodr),
            "reference_map_md5": _hash_file_md5(reference_xodr),
            "auto_aligned_md5": _hash_file_md5(aligned_auto),
            "auto_original_md5": _hash_file_md5(generated_xodr),
        }
    except Exception as e:
        combined["map_hashes"] = {"error": str(e)}
    combined["reproducibility_hash"] = combined_repro_hash

    combined["tile_pairing_provenance"] = tile_pairing_provenance or {}
    if "connectivity_gap" not in combined:
        raise RuntimeError(
            "connectivity_gap must always be present in full_report.json (CLAUDE.md P0)"
        )
    _safe_dump_json(os.path.join(output_dir, "full_report.json"), combined)

    # Always write carla_status.json (this script doesn't invoke CARLA)
    carla_disabled = os.getenv("UP_DISABLE_CARLA", "").strip().lower() in ("1", "true", "yes", "on")
    carla_status = {
        "carla": "skipped" if carla_disabled else "not_invoked",
        "enabled": False,
        "reason": "UP_DISABLE_CARLA" if carla_disabled else "domain_gap_script_does_not_use_carla",
        "tile_qa_status": _CARLA_TILE_QA_SKIPPED,
    }
    _safe_dump_json(os.path.join(output_dir, "carla_status.json"), carla_status)

    # Ensure perception_gap.json exists (stub if not computed)
    perception_gap_path = os.path.join(output_dir, "perception_gap.json")
    if not os.path.exists(perception_gap_path):
        perception_stub = {
            "stub": True,
            "evidence_complete": False,
            "mode": "structural_only_fallback",
            "enabled": False,
            "status": "skipped",
            "reason": "perception disabled or missing metrics",
        }
        _safe_dump_json(perception_gap_path, perception_stub)

    _write_summary_outputs(
        output_dir=output_dir,
        structural_gap=combined.get("structural_domain_gap", {}),
        aggregated=aggregated,
        tile_geom_gaps=tile_geom_gaps,
        tile_curv_gaps=tile_curv_gaps,
        tile_gap_vector=tile_gap_vector,
        required_metrics=domain_gap_metrics,
    )
    try:
        _check_csv_json_parity(output_dir=output_dir, full_report=combined)
    except Exception:
        pass
    _attach_full_report_sidecars(
        output_dir=output_dir,
        full_report=combined,
        generated_xodr=generated_xodr,
        run_root=run_meta.get("run_root") or run_meta.get("auto_run_root"),
        sumo_meta=sumo_meta,
    )
    _safe_dump_json(os.path.join(output_dir, "full_report.json"), combined)

    readme_inputs = {
        "manual_xodr": reference_xodr,
        "auto_xodr_aligned": aligned_auto,
        "auto_xodr_original": generated_xodr,
        "manual_tiles_dir": manual_tiles,
        "auto_tiles_dir": auto_tiles,
        "tile_correspondence_csv": str(corr_path) if corr_path else "none",
        "tile_pairing_source": tile_pairing_source,
        "per_tile_status": per_tile_status,
        "per_tile_status_reason": per_tile_status_reason,
        "reproducibility_hash": combined_repro_hash,
    }
    _write_run_readme(output_dir, "run_full_domain_gap.py", readme_inputs)

    # Repro pack (best-effort; never fatal)
    try:
        settings_sha = _hash_settings_snapshot_sha256(output_dir)
    except Exception:
        settings_sha = None
    try:
        settings_md5 = _hash_settings_snapshot(output_dir)
    except Exception:
        settings_md5 = None
    try:
        update_run_manifest(
            output_dir,
            gps_bounds=gps_bounds if "gps_bounds" in locals() and isinstance(gps_bounds, dict) else None,
            settings_snapshot_md5=settings_md5,
            settings_snapshot_sha256=settings_sha,
            settings_schema_version=str(getattr(SETTINGS, "SETTINGS_SCHEMA_VERSION", "")) or None,
            files={
                "manual_xodr": reference_xodr,
                "auto_xodr_aligned": aligned_auto,
                "auto_xodr_original": generated_xodr,
            },
            outputs={
                "full_report": os.path.join(output_dir, "full_report.json"),
                "domain_gap_summary": os.path.join(output_dir, "domain_gap_summary.json"),
                "tile_correspondence": str(corr_path) if corr_path else "",
                "tile_pairing_report": os.path.join(output_dir, "tile_pairing_report.json"),
                "alignment": os.path.join(output_dir, "alignment.json"),
                "run_metadata": os.path.join(output_dir, "run_metadata.json"),
            },
            notes={
                "args": {
                    "manual_xodr": reference_xodr,
                    "auto_xodr": generated_xodr,
                    "manual_tiles": manual_tiles,
                    "auto_tiles": auto_tiles,
                    "output_dir": output_dir,
                }
            },
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to write mandatory run manifest: {exc}") from exc
    try:
        write_signature_json(
            output_dir,
            [
                "full_report.json",
                "summary.csv",
                "domain_gap_summary.json",
                "tile_correspondence.csv",
                "tile_pairing_report.json",
                "tile_metrics_status.json",
                "tile_metadata_aligned.json",
                "alignment.json",
                "auto_aligned_hardened.xodr",
                "run_metadata.json",
                "tile_metrics.csv",
                "worst_tiles.csv",
                "aggregated_gap.json",
                "perception_gap.json",
                "summary_definitions.md",
                "reproducibility_hash.json",
            ],
        )
    except Exception as exc:
        raise RuntimeError(
            f"Failed to write mandatory signature artifact: {exc}"
        ) from exc
    try:
        write_success_txt(output_dir, summary="run_full_domain_gap")
    except Exception as exc:
        raise RuntimeError(
            f"Failed to write mandatory success marker: {exc}"
        ) from exc
    # Coordinate-system evidence artifact for thesis defensibility.
    try:
        write_coordinate_system_json(
            Path(output_dir),
            Path(generated_xodr) if generated_xodr else None,
            manual_xodr_path=Path(reference_xodr) if reference_xodr else None,
            alignment_method=str(tile_frame_method or alignment_transform_type or "unknown"),
            alignment_transform_summary=transform if isinstance(transform, dict) else None,
            offset_bake_used=bool(tile_frame_method == "offset_bake"),
        )
    except Exception:
        try:
            write_coordinate_system_json(
                Path(output_dir),
                None,
                manual_xodr_path=Path(reference_xodr) if reference_xodr else None,
                alignment_method=str(tile_frame_method or alignment_transform_type or "unknown"),
                alignment_transform_summary=transform if isinstance(transform, dict) else None,
                offset_bake_used=bool(tile_frame_method == "offset_bake"),
            )
        except Exception:
            pass

    try:
        geom_status = (
            (combined.get("structural_domain_gap") or {}).get("geometry", {})
            if isinstance(combined, dict)
            else {}
        )
        geom_rmse = geom_status.get("rmse") if isinstance(geom_status, dict) else None
        crs_mismatch_detected = bool(
            geom_status.get("crs_mismatch_detected") if isinstance(geom_status, dict) else False
        )
        domain_gap_status_payload = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "status": "pass",
            "success": True,
            "reason": None,
            "error": None,
            "run_root": "",
            "output_dir": output_dir,
            "geometry_rmse": geom_rmse,
            "geometry_rmse_valid": bool(geom_rmse is not None and not crs_mismatch_detected),
            "crs_mismatch_detected": bool(crs_mismatch_detected),
            "crs_alignment_applied": bool(combined.get("crs_alignment_applied")),
            "source_crs": combined.get("source_crs"),
            "target_crs": combined.get("target_crs"),
            **thesis_scope,
            "crs_comparability": crs_comparability.get("comparability", {}),
        }
        _safe_dump_json(
            os.path.join(output_dir, "domain_gap_status.json"),
            domain_gap_status_payload,
        )
        _write_domain_gap_audit_summary(
            Path(output_dir),
            crs_report=crs_comparability,
            status_payload=domain_gap_status_payload,
        )
    except Exception as exc:
        raise RuntimeError(
            f"Failed to write mandatory domain_gap_status artifact: {exc}"
        ) from exc

    log.info("FULL domain-gap analysis complete.")
    log.info("Results saved to %s", output_dir)

    return combined


def _cli_main() -> int:
    # Minimal CLI to select manual reference map (smoke-tested via --help)
    ap = argparse.ArgumentParser(description="Full domain-gap runner (manual vs generated maps).")
    ap.add_argument(
        "--check-reproducibility",
        dest="check_reproducibility",
        help="Read <run_dir>/full_report.json and print informational path warnings.",
    )
    ap.add_argument("--manual_map", help="Named manual map to use (e.g., Grid0821, Grid0828).")
    ap.add_argument("--manual_xodr", help="Explicit manual XODR path (highest priority).")
    ap.add_argument("--manual-tiles-dir", dest="manual_tiles_dir", help="Explicit manual tiles directory")
    ap.add_argument("--manual_tiles_dir", dest="manual_tiles_dir", help="Explicit manual tiles directory (alias)")
    ap.add_argument("--auto_meta", dest="auto_meta", help="Explicit auto tile_metadata.json path")
    ap.add_argument("--auto_xodr", dest="auto_xodr", help="Explicit auto XODR path (skip 08_final lookup)")
    ap.add_argument("--auto_tiles_dir", dest="auto_tiles_dir", help="Explicit auto tiles directory")
    ap.add_argument("--auto_tiles_meta", dest="auto_tiles_meta", help="Explicit auto tiles tile_metadata.json path")
    ap.add_argument("--output_dir", help="Override output directory for reports (highest priority).")
    # Convenience aliases (keep backward compatibility; no behavior changes)
    ap.add_argument("--manual-map", dest="manual_map", help="Alias for --manual_map")
    ap.add_argument("--auto-meta", dest="auto_meta", help="Alias for --auto_meta")
    ap.add_argument("--output-dir", dest="output_dir", help="Alias for --output_dir")

    ap.add_argument("--smoke", action="store_true", help="Only compute tile bboxes + debug artifact, then exit.")
    args = ap.parse_args()
    if args.check_reproducibility:
        report_json_path = Path(args.check_reproducibility).expanduser() / "full_report.json"
        for warning in validate_reproducibility_preconditions(report_json_path):
            print(warning)
        return 0
    thesis_env_raw = str(os.getenv("UP_THESIS_STRICT", "")).strip().lower()
    thesis_env_true = thesis_env_raw in {"1", "true", "yes", "on"}
    thesis_strict_mode = bool(
        thesis_env_true or bool(getattr(SETTINGS, "THESIS_STRICT", False))
    )
    if not thesis_strict_mode:
        log.warning(
            "THESIS_STRICT=False: run_full_domain_gap is running in non-thesis-grade mode."
        )

    success = False
    exit_code = 0
    error = None
    tb = None
    run_root = None
    output_dir = None
    manual_xodr_path = None
    auto_xodr_path = None
    manual_tiles_path = None
    auto_tiles_path = None
    auto_meta_path = None

    try:
        # Headless integration-test mode: emit minimal artifacts without full tiling/CARLA stack.
        if os.getenv("UP_DISABLE_CARLA", "").strip().lower() in ("1", "true", "yes", "on"):
            output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else (repo_root() / "domain_gap_headless")
            output_dir.mkdir(parents=True, exist_ok=True)
            dg_dir = output_dir / "domain_gap"
            dg_dir.mkdir(parents=True, exist_ok=True)
            run_root = output_dir
            auto_xodr_env = os.getenv("UP_AUTO_FINAL_XODR", "").strip()
            manual_xodr_env = os.getenv("UP_MANUAL_MAP_XODR", "").strip() or os.getenv("UP_MANUAL_XODR", "").strip()
            auto_xodr_path = Path(auto_xodr_env).expanduser() if auto_xodr_env else None
            manual_xodr_path = Path(manual_xodr_env).expanduser() if manual_xodr_env else None
            timestamp_utc = datetime.now(timezone.utc).isoformat()

            def _sha256_or_empty(p: Optional[Path]) -> str:
                if not p or not p.is_file():
                    return ""
                h = hashlib.sha256()
                with p.open("rb") as f:
                    while True:
                        chunk = f.read(1 << 20)
                        if not chunk:
                            break
                        h.update(chunk)
                return h.hexdigest()

            _safe_dump_json(
                os.path.join(str(output_dir), "carla_status.json"),
                {
                    "enabled": False,
                    "carla": "skipped",
                    "reason": "UP_DISABLE_CARLA",
                    "ok": True,
                    "tile_qa_status": _CARLA_TILE_QA_SKIPPED,
                },
            )
            _safe_dump_json(
                os.path.join(str(output_dir), "perception_gap.json"),
                {"skipped": True, "reason": "UP_DISABLE_CARLA"},
            )
            try:
                if not (auto_xodr_path and auto_xodr_path.is_file() and manual_xodr_path and manual_xodr_path.is_file()):
                    raise RuntimeError("missing UP_AUTO_FINAL_XODR or UP_MANUAL_MAP_XODR")

                whole_inter_gap = _call_intersection_gap(str(manual_xodr_path), str(auto_xodr_path))
                thesis_scope = _thesis_scope_fields()
                crs_comparability = _build_crs_comparability_report(
                    str(manual_xodr_path),
                    str(auto_xodr_path),
                )
                domain_gap_metrics = _compute_required_domain_gap_metrics(
                    reference_xodr=str(manual_xodr_path),
                    aligned_auto=str(auto_xodr_path),
                    whole_inter_gap=whole_inter_gap if isinstance(whole_inter_gap, dict) else {},
                )
                _enforce_required_domain_gap_metrics(domain_gap_metrics, context="headless_domain_gap")

                headless_connectivity_gap = _normalize_connectivity_gap_payload(
                    {"disabled": True, "reason": "headless_test_mode"},
                    default_reason="headless_test_mode",
                )
                full_report = {
                    **thesis_scope,
                    "mode": "headless_test",
                    "manual_xodr": str(manual_xodr_path),
                    "auto_xodr": str(auto_xodr_path),
                    "domain_gap": domain_gap_metrics,
                    "metrics": domain_gap_metrics,
                    "structural_domain_gap": {
                        "intersection": whole_inter_gap,
                        "elevation": _disabled_elevation_gap("dem_qc_failed"),
                        "connectivity": headless_connectivity_gap,
                    },
                    "elevation": _disabled_elevation_gap("dem_qc_failed"),
                    "connectivity_gap": headless_connectivity_gap,
                    "normalization_contract": {
                        **_normalization_contract(),
                        "applied_to": {"tile_gap_vector": False, "aggregation": False},
                        "aggregation_applied": False,
                    },
                    "crs_comparability": crs_comparability,
                    "carla_drivability_validated": False,
                    "carla_drivability_note": _CARLA_DRIVABILITY_NOTE,
                }
                _safe_dump_json(os.path.join(str(output_dir), "full_report.json"), full_report)
                _safe_dump_json(os.path.join(str(dg_dir), "full_report.json"), full_report)

                _write_summary_outputs(
                    output_dir=str(dg_dir),
                    structural_gap={"intersection": whole_inter_gap},
                    aggregated=None,
                    tile_geom_gaps={},
                    tile_curv_gaps={},
                    tile_gap_vector={},
                    required_metrics=domain_gap_metrics,
                    carla_drivability_validated=False,
                )
                try:
                    _check_csv_json_parity(output_dir=str(dg_dir), full_report=full_report)
                except Exception:
                    pass
                _attach_full_report_sidecars(
                    output_dir=str(dg_dir),
                    full_report=full_report,
                    generated_xodr=str(auto_xodr_path),
                    sumo_meta=None,
                )
                _safe_dump_json(os.path.join(str(output_dir), "full_report.json"), full_report)
                _safe_dump_json(os.path.join(str(dg_dir), "full_report.json"), full_report)
                _safe_dump_json(
                    os.path.join(str(dg_dir), "reproducibility_hash.json"),
                    {
                        "manual_xodr_sha256": _sha256_or_empty(manual_xodr_path),
                        "auto_xodr_sha256": _sha256_or_empty(auto_xodr_path),
                        "mode": "headless_test",
                    },
                )
                _safe_dump_json(
                    os.path.join(str(dg_dir), "tile_pairing_report.json"),
                    {
                        "pairing_method": "greedy",
                        "num_pairs": 0,
                        "pairs": [],
                        "one_to_one": {"ok": True, "duplicate_manual": [], "duplicate_auto": []},
                        "pairing_provenance": {
                            "method": "greedy",
                            "fallback_reason": "headless_test_mode",
                        },
                        "provenance": {"fallback_reason": "headless_test_mode"},
                    },
                )
                _safe_dump_json(
                    os.path.join(str(dg_dir), "domain_gap_status.json"),
                    {
                        "timestamp_utc": timestamp_utc,
                        "status": "pass",
                        "success": True,
                        "reason": None,
                        "error": None,
                        **thesis_scope,
                        "crs_comparability": crs_comparability.get("comparability", {}),
                    },
                )
            except Exception as exc:
                _safe_dump_json(
                    os.path.join(str(dg_dir), "domain_gap_status.json"),
                    {
                        "timestamp_utc": timestamp_utc,
                        "status": "failed",
                        "success": False,
                        "reason": str(exc),
                        "error": str(exc),
                        **_thesis_scope_fields(),
                        "crs_comparability": {
                            "status": "comparison_not_available",
                            "reason": "headless_precondition_failed_before_comparison",
                            "crs_match": False,
                        },
                    },
                )
                raise
            try:
                write_coordinate_system_json(
                    dg_dir,
                    auto_xodr_path,
                    manual_xodr_path=manual_xodr_path,
                    alignment_method="headless_test",
                    alignment_transform_summary={},
                    offset_bake_used=False,
                )
            except Exception:
                try:
                    write_coordinate_system_json(
                        dg_dir,
                        None,
                        manual_xodr_path=manual_xodr_path,
                        alignment_method="headless_test",
                        alignment_transform_summary={},
                        offset_bake_used=False,
                    )
                except Exception:
                    pass
            success = True
            exit_code = 0
            return 0

        # R5 gate: legacy --auto_meta is dangerous (cross-run contamination).
        # Default is FAIL-CLOSED unless explicitly enabled.
        if args.auto_meta and not _bool_env("UP_ALLOW_LEGACY_AUTO_META", "0"):
            raise SystemExit(
                "R5 safety gate: --auto_meta is deprecated and disabled by default. "
                "Use --auto_run <run_root> instead. "
                "To override (not recommended), set UP_ALLOW_LEGACY_AUTO_META=1."
            )

        repo = repo_root()

        def _soft_resolve(p: Optional[Path]) -> str:
            if not p:
                return ""
            try:
                # strict=False avoids crashing on non-existing paths; we check existence separately.
                return str(p.expanduser().resolve(strict=False))
            except TypeError:
                # Python <3.9 compatibility (shouldn't happen here, but keep it safe)
                try:
                    return str(p.expanduser().resolve())
                except Exception:
                    return str(p)
            except Exception:
                return str(p)

        # Manual inputs (env overrides first)
        manual_xodr_env = os.getenv("UP_MANUAL_MAP_XODR") or os.getenv("UP_MANUAL_XODR") or ""
        manual_xodr_cfg = getattr(SETTINGS, "MANUAL_MAP_XODR", "") or ""

        manual_map_choice_val: Optional[str] = None
        manual_xodr_source_val = "none"

        if args.manual_xodr:
            manual_map_choice_val = None
            manual_xodr_path = Path(args.manual_xodr)
            manual_xodr_source_val = "cli"
        elif args.manual_map:
            # Resolve through env-specific / repo-relative fallbacks (portable across machines)
            manual_map_choice_val = str(args.manual_map)
            try:
                manual_xodr_path = resolve_manual_xodr(manual_map_choice_val)
                manual_xodr_source_val = "manual_map"
            except Exception:
                # Keep it non-fatal unless user explicitly asked for manual reference.
                manual_xodr_path = None
                manual_xodr_source_val = "manual_map_missing"
        else:
            manual_map_choice_val = None
            if manual_xodr_env or manual_xodr_cfg:
                manual_xodr_path = Path(manual_xodr_env or manual_xodr_cfg)
                manual_xodr_source_val = "env"

        manual_reference_status = "provided"
        manual_missing = False
        manual_xodr_resolved_val = _soft_resolve(manual_xodr_path)
        manual_xodr_resolved_val = _validate_manual_xodr_resolved(
            manual_xodr_resolved_val,
            logger=log,
        )
        if manual_xodr_resolved_val:
            manual_xodr_path = Path(manual_xodr_resolved_val)

        if (not manual_xodr_resolved_val) or (manual_xodr_path and manual_xodr_path.suffix.lower() != ".xodr"):
            manual_missing = True
            manual_reference_status = "missing"
            if manual_xodr_path or args.manual_xodr or args.manual_map or manual_xodr_env or manual_xodr_cfg:
                log.warning(
                    "Manual XODR not found or invalid: %s. Provide --manual_xodr PATH or set UP_MANUAL_MAP_XODR / UP_MANUAL_XODR.",
                    manual_xodr_resolved_val or "(none)",
                )
            manual_xodr_path = None
            manual_xodr_resolved_val = ""

        # Update provenance globals for downstream metadata (best-effort, never fatal)
        try:
            globals()["manual_map_choice"] = manual_map_choice_val
            globals()["manual_xodr_resolved"] = manual_xodr_resolved_val
            globals()["manual_xodr_source"] = manual_xodr_source_val
        except Exception:
            pass

        allow_auto_as_manual = os.getenv("UP_ALLOW_AUTO_AS_MANUAL", "") == "1"

        manual_tiles_env = os.getenv("UP_MANUAL_TILES_DIR") or ""
        manual_tiles_cfg = getattr(SETTINGS, "MANUAL_TILES_DIR", "") or ""
        manual_tiles_source = "none"
        if args.manual_tiles_dir:
            manual_tiles_path = Path(args.manual_tiles_dir).expanduser()
            manual_tiles_source = "cli"
        elif manual_tiles_env:
            manual_tiles_path = Path(manual_tiles_env).expanduser()
            manual_tiles_source = "env"
        elif manual_tiles_cfg:
            manual_tiles_path = Path(manual_tiles_cfg).expanduser()
            manual_tiles_source = "config"

        if manual_tiles_path:
            manual_tiles_dir_raw = str(manual_tiles_path)
            if args.manual_tiles_dir:
                log.info("MANUAL tiles dir raw: %s", manual_tiles_dir_raw)
            resolved = _resolve_tiles_dir(manual_tiles_dir_raw)
            manual_tiles_path = Path(resolved)
            if args.manual_tiles_dir:
                log.info("MANUAL tiles dir resolved: %s", manual_tiles_path)
            if manual_tiles_dir_raw != str(manual_tiles_path) and manual_tiles_path.name.lower() == "tiles":
                log.info("Resolved manual_tiles_dir to %s", manual_tiles_path)
            if not manual_tiles_path.exists():
                msg = (
                    "Manual tiles directory not found. "
                    f"raw={manual_tiles_dir_raw} resolved={manual_tiles_path}. "
                    "Expected either: <dir>\\*.xodr or <dir>\\tiles\\*.xodr."
                )
                log.error(msg)
                raise SystemExit(msg)
            if not _is_dir_with_xodr(str(manual_tiles_path)):
                msg = (
                    "Manual tiles directory has no .xodr. "
                    f"raw={manual_tiles_dir_raw} resolved={manual_tiles_path}. "
                    "Expected either: <dir>\\*.xodr or <dir>\\tiles\\*.xodr."
                )
                log.error(msg)
                raise SystemExit(msg)

        if manual_tiles_source != "none":
            os.environ["UP_MANUAL_TILES_SOURCE"] = manual_tiles_source

        # Auto inputs (env overrides)
        # Accept UP_AUTO_RUN_ROOT as alias for UP_AUTO_RUN_DIR (used by tests)
        auto_run_env = os.getenv("UP_AUTO_RUN_DIR", "") or os.getenv("UP_AUTO_RUN_ROOT", "")
        out_root_setting = getattr(SETTINGS, "BASE_OUTPUT_DIR", "") or "ultimate_pipeline_out"
        out_root = Path(out_root_setting)
        if not out_root.is_absolute():
            out_root = repo / out_root

        auto_meta_arg = args.auto_meta or ""
        if auto_meta_arg:
            auto_meta_input = Path(auto_meta_arg).expanduser()
            try:
                auto_meta_path = _resolve_auto_meta_path(auto_meta_input)
            except Exception as exc:
                raise SystemExit(str(exc))
            if not auto_meta_path.is_file():
                raise SystemExit(f"Auto tile metadata not found: {auto_meta_path}")
            if auto_meta_input != auto_meta_path:
                log.info("AUTO_META resolved: %s -> %s", auto_meta_input, auto_meta_path)
            try:
                run_root = _resolve_run_root_from_auto_meta(auto_meta_path)
            except Exception as exc:
                raise SystemExit(str(exc))
        elif auto_run_env:
            run_root = Path(auto_run_env).expanduser()
        elif auto_run_env:
            run_root = Path(auto_run_env).expanduser()
        else:
            try:
                run_root = resolve_latest_run(out_root, skip_names=["manual_baselines"])
            except Exception as e:
                log.error("No auto run found under %s (%s)", out_root, e)
                sys.exit(1)

        if args.auto_xodr:
            auto_xodr_path = Path(args.auto_xodr).expanduser()
        else:
            if auto_meta_arg:
                finals = sorted(run_root.glob("08_final*.xodr"), key=lambda p: p.stat().st_mtime, reverse=True)
                auto_xodr_path = finals[0] if finals else None
                if not auto_xodr_path:
                    raise SystemExit(
                        f"No 08_final*.xodr found under {run_root} (from --auto_meta). "
                        "Pass --auto_xodr or use run_root/tile_metadata.json."
                    )
                try:
                    _enforce_r5_run_root(auto_meta_path, auto_xodr_path)
                except Exception as exc:
                    raise RuntimeError(f"R5 violation while validating run_root: {exc}") from exc
            else:
                auto_final_env = os.getenv("UP_AUTO_FINAL_XODR") or ""
                if auto_final_env:
                    auto_xodr_path = Path(auto_final_env).expanduser()
                else:
                    finals = sorted(run_root.glob("08_final*.xodr"), key=lambda p: p.stat().st_mtime, reverse=True)
                    auto_xodr_path = finals[0] if finals else None

        if auto_meta_arg and auto_xodr_path:
            try:
                _enforce_r5_run_root(auto_meta_path, auto_xodr_path)
            except Exception as exc:
                raise RuntimeError(f"R5 violation while validating run_root: {exc}") from exc

        auto_tiles_env = os.getenv("UP_AUTO_TILES_DIR") or ""
        auto_tiles_path = Path(args.auto_tiles_dir).expanduser() if args.auto_tiles_dir else (
            Path(auto_tiles_env).expanduser() if auto_tiles_env else (run_root / "tiles")
        )
        auto_tiles_path = Path(_resolve_tiles_dir(str(auto_tiles_path)))

        auto_meta_env = os.getenv("UP_AUTO_META") or ""
        auto_meta_source = ""
        if args.auto_tiles_meta:
            auto_meta_path = Path(args.auto_tiles_meta).expanduser()
            auto_meta_source = "cli_tiles_meta"
        elif auto_meta_arg:
            auto_meta_path = Path(auto_meta_arg).expanduser()
            auto_meta_source = "cli"
        elif auto_meta_env:
            auto_meta_path = Path(auto_meta_env).expanduser()
            auto_meta_source = "env"
        else:
            auto_meta_path = auto_xodr_path.parent / "tile_metadata.json" if auto_xodr_path else None
            auto_meta_source = "adjacent"

        if not auto_meta_path or not auto_meta_path.is_file():
            log.warning(
                "Auto tile metadata could not be resolved at startup (source=%s): %s. "
                "The governed run will generate aligned auto tiles under the output directory.",
                auto_meta_source,
                auto_meta_path,
            )
            auto_meta_path = None
            auto_meta_source = "generated_in_run"
            os.environ.pop("UP_AUTO_META", None)
            os.environ["UP_AUTO_META_SOURCE"] = auto_meta_source
            os.environ["UP_AUTO_META_MODE"] = "generated_in_run"
        else:
            os.environ["UP_AUTO_META"] = str(auto_meta_path)
            os.environ["UP_AUTO_META_SOURCE"] = auto_meta_source
            if auto_meta_arg:
                os.environ["UP_AUTO_META_MODE"] = "auto_meta"
            else:
                os.environ["UP_AUTO_META_MODE"] = "auto_run"
        if run_root:
            os.environ["UP_AUTO_RUN_ROOT"] = str(run_root)

        log.info("AUTO_META: %s", auto_meta_path)
        log.info("RUN_ROOT: %s", run_root)
        log.info("AUTO_XODR: %s", auto_xodr_path)

        errors = []
        if not auto_xodr_path or not auto_xodr_path.is_file():
            errors.append(f"Auto XODR not found: {auto_xodr_path}")

        # Tiles/metadata missing is now a warning, not fatal - per-tile stages will be skipped
        tiles_available = auto_tiles_path.is_dir() if auto_tiles_path else False
        meta_available = auto_meta_path.is_file() if auto_meta_path else False
        if not tiles_available:
            log.warning("Auto tiles directory missing: %s - per-tile gap stages will be skipped", auto_tiles_path)
        if not meta_available:
            log.warning("Auto tile metadata missing: %s - per-tile gap stages will be skipped", auto_meta_path)

        # Only fatal if XODR itself is missing
        if errors:
            for msg in errors:
                log.error(msg)
            sys.exit(1)

        if manual_missing and allow_auto_as_manual:
            manual_xodr_path = auto_xodr_path
            manual_reference_status = "auto_standin"
            manual_xodr_resolved_val = _soft_resolve(manual_xodr_path)
            try:
                globals()["manual_xodr_resolved"] = manual_xodr_resolved_val
                globals()["manual_xodr_source"] = "auto_standin"
            except Exception:
                pass
            log.warning("Manual XODR missing; using auto map as stand-in (UP_ALLOW_AUTO_AS_MANUAL=1).")

        domain_gap_out = getattr(SETTINGS, "DOMAIN_GAP_OUT_DIR", "domain_gap") or "domain_gap"
        output_env = os.getenv("UP_OUTPUT_DIR", "")
        if args.output_dir:
            output_dir = Path(args.output_dir).expanduser()
        elif output_env:
            output_dir = Path(output_env).expanduser()
        else:
            output_dir = run_root / domain_gap_out
        output_dir = ensure_dir_util(output_dir)

        log.info("MANUAL xodr : %s", manual_xodr_path if manual_xodr_path else "(missing)")
        log.info("MANUAL tiles: %s", manual_tiles_path if manual_tiles_path else "(not provided)")
        if manual_tiles_path:
            log.info("MANUAL tiles source: %s", manual_tiles_source)
        log.info("AUTO   xodr : %s", auto_xodr_path)
        log.info("AUTO   tiles: %s", auto_tiles_path)
        log.info("AUTO   meta : %s", auto_meta_path)

        manual_xodr_use = manual_xodr_path if manual_xodr_path else auto_xodr_path

        run_full_domain_gap(
            manual_xodr=str(manual_xodr_use),
            auto_xodr=str(auto_xodr_path),
            manual_tiles=str(manual_tiles_path) if manual_tiles_path else "",
            auto_tiles=str(auto_tiles_path),
            perception_manual_json=getattr(SETTINGS, "PERCEPTION_MANUAL_JSON", None),
            perception_auto_json=getattr(SETTINGS, "PERCEPTION_AUTO_JSON", None),
            output_dir=str(output_dir),
            manual_missing=manual_missing,
            manual_reference_status=manual_reference_status,
            smoke=bool(args.smoke),
        )

        success = True
        exit_code = 0
    except SystemExit as exc:
        code = exc.code
        exit_code = int(code) if isinstance(code, int) else (0 if code is None else 1)
        error = str(exc)
        tb = traceback.format_exc()
    except Exception as exc:
        exit_code = 1
        error = str(exc)
        tb = traceback.format_exc()
    finally:
        if run_root is None:
            try:
                auto_run_env = os.getenv("UP_AUTO_RUN_DIR", "") or os.getenv("UP_AUTO_RUN_ROOT", "")
                if auto_run_env:
                    run_root = Path(auto_run_env).expanduser()
                else:
                    out_root_setting = getattr(SETTINGS, "BASE_OUTPUT_DIR", "") or "ultimate_pipeline_out"
                    out_root = Path(out_root_setting)
                    if not out_root.is_absolute():
                        out_root = repo_root() / out_root
                    run_root = resolve_latest_run(out_root, skip_names=["manual_baselines"])
            except Exception:
                run_root = None

        canonical_dir = run_root / "domain_gap" if run_root else None
        failure_reason = None if success else _classify_domain_gap_failure_reason(error, tb)
        thesis_scope = _thesis_scope_fields()
        crs_comparability = _build_crs_comparability_report(
            str(manual_xodr_path) if manual_xodr_path else None,
            str(auto_xodr_path) if auto_xodr_path else None,
        )
        resolved_paths = {
            "manual_xodr": str(manual_xodr_path) if manual_xodr_path else "",
            "auto_xodr": str(auto_xodr_path) if auto_xodr_path else "",
            "manual_tiles": str(manual_tiles_path) if manual_tiles_path else "",
            "auto_tiles": str(auto_tiles_path) if auto_tiles_path else "",
            "auto_meta": str(auto_meta_path) if auto_meta_path else "",
            "run_root": str(run_root) if run_root else "",
            "output_dir": str(output_dir) if output_dir else "",
        }
        geometry_rmse = None
        geometry_rmse_valid = False
        crs_mismatch_detected = False
        crs_alignment_applied = False
        source_crs = None
        target_crs = None
        try:
            if output_dir:
                fr_path = Path(output_dir) / "full_report.json"
                if fr_path.is_file():
                    fr_obj = json.loads(fr_path.read_text(encoding="utf-8", errors="replace"))
                    geom_obj = (
                        (fr_obj.get("structural_domain_gap") or {}).get("geometry", {})
                        if isinstance(fr_obj, dict)
                        else {}
                    )
                    geometry_rmse = geom_obj.get("rmse") if isinstance(geom_obj, dict) else None
                    crs_mismatch_detected = bool(
                        geom_obj.get("crs_mismatch_detected") if isinstance(geom_obj, dict) else False
                    )
                    geometry_rmse_valid = bool(geometry_rmse is not None and not crs_mismatch_detected)
                    crs_alignment_applied = bool(fr_obj.get("crs_alignment_applied"))
                    source_crs = fr_obj.get("source_crs")
                    target_crs = fr_obj.get("target_crs")
        except Exception:
            pass
        status_payload = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "status": "pass" if success else "failed",
            "success": bool(success),
            "exit_code": int(exit_code),
            "failure_reason": failure_reason,
            "reason": None if success else (error or "domain_gap_failed"),
            "error": error,
            "traceback": tb,
            "run_root": str(run_root) if run_root else "",
            "output_dir": str(output_dir) if output_dir else "",
            "canonical_dir": str(canonical_dir) if canonical_dir else "",
            "resolved_paths": resolved_paths,
            "geometry_rmse": geometry_rmse,
            "geometry_rmse_valid": bool(geometry_rmse_valid),
            "crs_mismatch_detected": bool(crs_mismatch_detected),
            "crs_alignment_applied": bool(crs_alignment_applied),
            "source_crs": source_crs,
            "target_crs": target_crs,
            **thesis_scope,
            "crs_comparability": crs_comparability.get("comparability", {}),
        }
        status_targets: list[Path] = []
        if canonical_dir:
            status_targets.append(canonical_dir)
        if output_dir:
            status_targets.append(Path(output_dir))
        seen_status_targets: set[str] = set()
        status_write_errors: list[str] = []
        for status_target in status_targets:
            try:
                key = str(status_target.resolve())
            except Exception:
                key = str(status_target)
            if key in seen_status_targets:
                continue
            seen_status_targets.add(key)
            try:
                _write_domain_gap_status(status_target, status_payload)
            except Exception as exc:
                status_write_errors.append(f"{status_target}: {exc}")
        if status_write_errors:
            joined = "; ".join(status_write_errors)
            log.error("Failed to write domain-gap status artifact(s): %s", joined)
            if success:
                success = False
                exit_code = 1
                error = f"domain_gap_status_write_failed: {joined}"
                tb = tb or ""
            elif error:
                error = f"{error} | status_write_error: {joined}"
        report_dir = Path(output_dir) if output_dir else canonical_dir
        if report_dir:
            try:
                crs_written = _write_crs_comparability(
                    report_dir,
                    str(manual_xodr_path) if manual_xodr_path else None,
                    str(auto_xodr_path) if auto_xodr_path else None,
                )
                _write_domain_gap_audit_summary(
                    report_dir,
                    crs_report=crs_written,
                    status_payload=status_payload,
                )
            except Exception as exc:
                log.warning("Failed to write thesis parity artifacts (%s)", exc)
        if run_root and output_dir:
            _ensure_canonical_domain_gap_outputs(run_root, Path(output_dir))
        if canonical_dir:
            try:
                write_coordinate_system_json(
                    canonical_dir,
                    auto_xodr_path if (auto_xodr_path and auto_xodr_path.is_file()) else None,
                    manual_xodr_path=manual_xodr_path if (manual_xodr_path and manual_xodr_path.is_file()) else None,
                    alignment_method="unknown",
                    alignment_transform_summary={},
                    offset_bake_used=False,
                )
            except Exception:
                try:
                    write_coordinate_system_json(
                        canonical_dir,
                        None,
                        manual_xodr_path=manual_xodr_path if (manual_xodr_path and manual_xodr_path.is_file()) else None,
                        alignment_method="unknown",
                        alignment_transform_summary={},
                        offset_bake_used=False,
                    )
                except Exception:
                    pass

    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(_cli_main())
