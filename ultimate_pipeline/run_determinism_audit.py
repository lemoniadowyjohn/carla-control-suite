#!/usr/bin/env python3
"""
Determinism audit entrypoint.

What it does:
1) Runs the pipeline N times (default 5) in fresh processes.
2) Extracts each run's output directory from stdout.
3) Compares the produced artifacts with a conservative ignore list
   (logs + known timestamped metadata).

Thesis-friendly behavior:
- external audit
- fail-loud (non-zero exit on mismatch)
- writes determinism_audit_report.json and per-run manifests

Usage:
    python -m ultimate_pipeline.run_determinism_audit --runs 5 --out ./audit_out
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import json
import subprocess
import argparse
from datetime import datetime, timezone
from pathlib import Path
import csv
import xml.etree.ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[1]

from typing import Any, Dict, Iterable, List, Optional, Tuple


from ultimate_pipeline.utils.timestamped_print import enable_timestamped_print

enable_timestamped_print()

OUTPUT_DIR_RE = re.compile(r"(?:^|\n).*?Output dir:\s*(.+)$", re.MULTILINE)
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")

_RELAXED_AUDIT_FORCED_ENV_OVERRIDES: Dict[str, str] = {
    "UP_THESIS_STRICT": "0",
    "UP_STRICT_QUALITY_GATES": "0",
    "UP_DEM_STRICT_MODE": "0",
    "UP_DEM_FULL_COVERAGE_STRICT": "0",
    "UP_FAIL_ON_FLAT_ELEVATION": "0",
    "UP_DISABLE_CARLA": "1",
    "UP_NO_CARLA_AUTOSTART": "1",
    "ENABLE_OSM2WORLD": "0",
    "UP_ENABLE_OSM2WORLD": "0",
}


def _env_truthy(value: Any) -> bool:
    txt = str(value or "").strip().lower()
    return txt in {"1", "true", "yes", "on"}


def _audit_pipeline_profile(
    *,
    offline_only: bool,
    thesis_evidence: bool,
    forced_env_overrides: Optional[Dict[str, str]] = None,
    effective_env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    forced = dict(forced_env_overrides or {})
    conditional = {"UP_OFFLINE_ONLY": "1"} if bool(offline_only) else {}
    if thesis_evidence:
        env_view = effective_env if isinstance(effective_env, dict) else os.environ
        strict_raw = str(env_view.get("UP_THESIS_STRICT", "")).strip()
        strict_effective = _env_truthy(strict_raw)
        return {
            "name": "thesis_evidence_determinism_audit",
            "mode": "thesis_evidence",
            "thesis_strict_equivalent": bool(strict_effective),
            "effective_up_thesis_strict": strict_raw,
            "description": (
                "Thesis-evidence determinism audit: does not force relaxed strictness "
                "overrides. Strictness reflects effective runtime environment."
            ),
            "offline_only_requested": bool(offline_only),
            "forced_env_overrides": forced,
            "conditional_env_overrides": conditional,
        }

    return {
        "name": "relaxed_offline_determinism_audit",
        "mode": "relaxed_offline",
        "thesis_strict_equivalent": False,
        "description": (
            "Determinism audit intentionally forces relaxed offline pipeline flags "
            "for reproducible hash comparison; this profile is not thesis-strict."
        ),
        "offline_only_requested": bool(offline_only),
        "forced_env_overrides": forced,
        "conditional_env_overrides": conditional,
    }


def _get_default_out_dir() -> Path:
    """Return the default output directory with timestamp."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Path("_analysis_out") / "determinism_audit" / timestamp


def _resolve_smoke_input_xodr() -> Optional[Path]:
    """
    Resolve a small in-repo XODR fixture for fast smoke-mode verification.

    Resolution order:
      1) explicit UP_DETERMINISM_SMOKE_INPUT_XODR env path
      2) preferred known fixture locations
      3) bounded triage scan for small auto-aligned fixtures
    """
    explicit = os.getenv("UP_DETERMINISM_SMOKE_INPUT_XODR", "").strip()
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_file():
            try:
                return p.resolve()
            except Exception:
                return p

    preferred = (
        REPO_ROOT
        / "artifacts"
        / "triage"
        / "20260316_024746_t_crs_reproject_common_frame"
        / "full_run"
        / "auto_aligned.xodr",
        REPO_ROOT
        / "artifacts"
        / "triage"
        / "20260316_024516_t_crs_reproject_common_frame"
        / "full_run"
        / "auto_aligned.xodr",
        REPO_ROOT
        / "artifacts"
        / "triage"
        / "20260316_024353_t_crs_reproject_common_frame"
        / "auto_aligned.xodr",
    )
    for candidate in preferred:
        if candidate.is_file():
            try:
                return candidate.resolve()
            except Exception:
                return candidate

    triage_root = REPO_ROOT / "artifacts" / "triage"
    if not triage_root.is_dir():
        return None

    candidates: List[Path] = []
    for pattern in ("**/auto_aligned*.xodr", "**/auto*.xodr"):
        try:
            for p in triage_root.glob(pattern):
                if not p.is_file():
                    continue
                size = int(p.stat().st_size)
                # Skip degenerate placeholders and very large maps in smoke mode.
                if size < 500 or size > 2_000_000:
                    continue
                candidates.append(p)
        except Exception:
            continue
        if candidates:
            break

    if not candidates:
        return None

    candidates.sort(key=lambda p: (int(p.stat().st_size), str(p).lower()))
    chosen = candidates[0]
    try:
        return chosen.resolve()
    except Exception:
        return chosen


def _find_run_pipeline_script() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        here.parent / "run_pipeline.py",
        here.parent.parent / "run_pipeline.py",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(
        "Could not locate run_pipeline.py. Put this script next to run_pipeline.py, or adjust _find_run_pipeline_script()."
    )


def _run_once(
    run_tag: str,
    offline_only: bool,
    seed: Optional[int] = None,
    *,
    forced_env_overrides: Optional[Dict[str, str]] = None,
    thesis_evidence: bool = False,
) -> Tuple[int, str, str]:
    """Run pipeline in a fresh process and return (rc, combined_output, out_dir)."""
    run_pipeline = _find_run_pipeline_script()

    env = os.environ.copy()
    # Ensure UTF-8 IO to avoid Windows codepage decoding issues
    env["PYTHONIOENCODING"] = "utf-8"
    # Ensure subprocess can import ultimate_pipeline
    env["PYTHONPATH"] = str(REPO_ROOT)
    # Keep audit runs deterministic with mode-specific environment policy.
    applied_overrides = dict(forced_env_overrides or {})
    env.update(applied_overrides)
    if offline_only:
        env["UP_OFFLINE_ONLY"] = "1"
    env["UP_RUN_TAG"] = run_tag
    if seed is not None:
        env["UP_SEED"] = str(seed)
    audit_profile = _audit_pipeline_profile(
        offline_only=offline_only,
        thesis_evidence=bool(thesis_evidence),
        forced_env_overrides=applied_overrides,
        effective_env=env,
    )

    cmd = [sys.executable, str(run_pipeline)]
    timeout_s = max(1, int(os.getenv("UP_DETERMINISM_RUN_TIMEOUT_S", "120")))
    try:
        p = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(REPO_ROOT),
            timeout=float(timeout_s),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = str(getattr(exc, "stdout", "") or "")
        stderr = str(getattr(exc, "stderr", "") or "")
        combined = (
            stdout
            + "\n"
            + stderr
            + f"\nERROR: determinism run timed out after {timeout_s}s (run_tag={run_tag})"
        )
        guessed = _guess_output_dir_from_run_tag(run_tag)
        out_dir = str(guessed) if guessed else ""
        _write_audit_env_to_run_manifest(
            run_tag, out_dir, env, 124, audit_profile=audit_profile
        )
        return 124, combined, out_dir

    stdout = p.stdout or ""
    stderr = p.stderr or ""
    combined = stdout + "\n" + stderr

    out_dir = _extract_output_dir_from_log(combined)
    if not out_dir and int(p.returncode) == 0:
        guessed = _guess_output_dir_from_run_tag(run_tag)
        out_dir = str(guessed) if guessed else ""
    _write_audit_env_to_run_manifest(
        run_tag, out_dir, env, int(p.returncode), audit_profile=audit_profile
    )
    return int(p.returncode), combined, out_dir


def _clean_log_line(line: str) -> str:
    txt = ANSI_ESCAPE_RE.sub("", str(line or ""))
    return txt.strip()


def _extract_output_dir_from_log(log_text: str) -> str:
    """
    Extract output directory from pipeline logs.

    Handles plain and timestamp-prefixed lines such as:
      Output dir: C:\\...\\run
      [2026-02-19T10:00:00Z] Output dir: C:\\...\\run
    """
    text = str(log_text or "")
    m = OUTPUT_DIR_RE.search(text)
    if m:
        return _clean_log_line(m.group(1))

    for raw in reversed(text.splitlines()):
        line = _clean_log_line(raw)
        if not line:
            continue
        marker_idx = line.find("Output dir:")
        if marker_idx >= 0:
            candidate = line[marker_idx + len("Output dir:") :].strip()
            if candidate:
                return candidate
    return ""


def _guess_output_dir_from_run_tag(run_tag: str) -> Optional[Path]:
    """Fallback when output-dir line is missing or decorated by logger wrappers."""
    tag = str(run_tag or "").strip()
    if not tag:
        return None

    data_root = os.getenv("UP_DATA_ROOT", "").strip()
    candidates = [
        REPO_ROOT / "ultimate_pipeline_out" / tag,
        Path.cwd() / "ultimate_pipeline_out" / tag,
    ]
    if data_root:
        candidates.append(Path(data_root).expanduser() / "ultimate_pipeline_out" / tag)

    for c in candidates:
        try:
            if c.is_dir():
                return c.resolve()
        except Exception:
            continue
    return None


_AUDIT_ENV_KEYS = (
    "UP_THESIS_STRICT",
    "UP_DEM_STRICT_MODE",
    "UP_DEM_FULL_COVERAGE_STRICT",
    "UP_DISABLE_DEM",
    "UP_AUTO_EXPAND_DEM",
    "OPENTOPO_API_KEY",
    "UP_OPENTOPO_API_KEY",
    "UP_DEM_DIR",
    "UP_INPUT_XODR",
    "UP_STRICT_QUALITY_GATES",
    "UP_FAIL_ON_FLAT_ELEVATION",
    "UP_DISABLE_CARLA",
    "UP_NO_CARLA_AUTOSTART",
    "UP_OFFLINE_ONLY",
    "ENABLE_OSM2WORLD",
    "UP_ENABLE_OSM2WORLD",
    "UP_LAT_MIN",
    "UP_LON_MIN",
    "UP_LAT_MAX",
    "UP_LON_MAX",
)


def _audit_env_snapshot(env: Dict[str, str]) -> Dict[str, str]:
    return {k: str(env.get(k, "")) for k in _AUDIT_ENV_KEYS}


def _write_audit_env_to_run_manifest(
    run_tag: str,
    out_dir: str,
    env: Dict[str, str],
    return_code: int,
    *,
    audit_profile: Optional[Dict[str, Any]] = None,
) -> None:
    target_dir: Optional[Path] = Path(out_dir) if out_dir else _guess_output_dir_from_run_tag(run_tag)
    if target_dir is None:
        return
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return

    manifest_path = target_dir / "run_manifest.json"
    payload: Dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(loaded, dict):
                payload = loaded
        except Exception:
            payload = {}

    payload["determinism_audit_env"] = {
        "run_tag": str(run_tag),
        "return_code": int(return_code),
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "audit_pipeline_profile": (
            dict(audit_profile)
            if isinstance(audit_profile, dict)
            else _audit_pipeline_profile(
                offline_only=bool(str(env.get("UP_OFFLINE_ONLY", "")).strip()),
                thesis_evidence=False,
                forced_env_overrides=None,
                effective_env=env,
            )
        ),
        "vars": _audit_env_snapshot(env),
    }
    try:
        manifest_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _iter_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_file():
            yield p


def _should_ignore(rel: str) -> bool:
    rel = rel.replace("\\", "/")

    # Ignore noisy / non-deterministic by design
    if rel.startswith("logs/") or "/logs/" in rel:
        return True
    if rel.endswith(".log") or rel.endswith(".tmp") or rel.endswith(".cache"):
        return True
    if rel.endswith("crash_traceback.txt") or rel.endswith("crash_summary.json"):
        return True

    # Settings snapshots contain export timestamps; compare separately if needed.
    if rel.endswith("settings_snapshot.json") or rel.endswith(
        "domain_gap_settings_snapshot.json"
    ):
        return True

    # DBs often include wall-clock times / run IDs
    if rel.endswith(".sqlite") or rel.endswith(".db"):
        return True

    return False


def _hash_file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_file_md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _find_final_xodr(run_dir: Path) -> Optional[Path]:
    candidates = sorted(
        run_dir.glob("08_final*.xodr"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if candidates:
        return candidates[0]
    plain = run_dir / "08_final.xodr"
    if plain.is_file():
        return plain
    return None


def _find_tile_metadata(run_dir: Path) -> Optional[Path]:
    candidates = [
        run_dir / "tile_metadata.json",
        run_dir / "tiles" / "tile_metadata.json",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def _count_tiles(meta_path: Optional[Path], tiles_dir: Optional[Path]) -> Optional[int]:
    if meta_path and meta_path.is_file():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(data, dict):
                return len(
                    [
                        k
                        for k, v in data.items()
                        if isinstance(k, str)
                        and not k.startswith("_")
                        and isinstance(v, dict)
                    ]
                )
        except Exception:
            pass
    if tiles_dir and tiles_dir.is_dir():
        try:
            return len(list(tiles_dir.glob("tile_*.xodr")))
        except Exception:
            return None
    return None


def _count_roads_and_junctions(
    xodr_path: Optional[Path],
) -> Tuple[Optional[int], Optional[int]]:
    if not xodr_path or not xodr_path.is_file():
        return None, None
    try:
        root = ET.parse(xodr_path).getroot()
        roads = len(root.findall("road"))
        junctions = len(root.findall(".//junction"))
        return roads, junctions
    except Exception:
        return None, None


def _safe_sha256(path: Optional[Path]) -> str:
    if not path or not path.is_file():
        return ""
    return _hash_file_sha256(path)


def _infer_map_name(run_dir: Path) -> str:
    candidates = [
        run_dir / "run_metadata.json",
        run_dir / "settings_snapshot.json",
        run_dir / "domain_gap_settings_snapshot.json",
    ]
    for c in candidates:
        if not c.is_file():
            continue
        try:
            data = json.loads(c.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if isinstance(data, dict):
            for key in (
                "manual_map",
                "manual_map_name",
                "MANUAL_MAP",
                "MANUAL_MAP_NAME",
            ):
                v = data.get(key)
                if isinstance(v, str) and v:
                    return v
            # nested settings may appear under "settings"
            settings = (
                data.get("settings") if isinstance(data.get("settings"), dict) else {}
            )
            if isinstance(settings, dict):
                v = settings.get("MANUAL_MAP")
                if isinstance(v, str) and v:
                    return v
    return ""


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


def _find_source_osm_file(run_dir: Path, hint: str) -> Optional[Path]:
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
        return {
            "source_osm_identity": _safe_relpath(source_file, run_dir),
            "source_osm_sha256": _hash_file_sha256(source_file),
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


def _classify_signature(
    sig: Dict[str, Any], baseline: Dict[str, Any]
) -> Tuple[bool, str]:
    missing = (
        not sig.get("xodr_sha256")
        or not sig.get("tile_metadata_sha256")
        or sig.get("tile_count") is None
        or sig.get("road_count") is None
        or sig.get("junction_count") is None
    )
    identical = (
        (sig.get("xodr_sha256") == baseline.get("xodr_sha256"))
        and (sig.get("tile_metadata_sha256") == baseline.get("tile_metadata_sha256"))
        and (sig.get("tile_count") == baseline.get("tile_count"))
        and (sig.get("road_count") == baseline.get("road_count"))
        and (sig.get("junction_count") == baseline.get("junction_count"))
    )
    if missing:
        verdict = "NONDETERMINISTIC"
    elif identical:
        verdict = "DETERMINISTIC"
    elif sig.get("xodr_sha256") != baseline.get("xodr_sha256") and (
        sig.get("tile_count") == baseline.get("tile_count")
        and sig.get("road_count") == baseline.get("road_count")
        and sig.get("junction_count") == baseline.get("junction_count")
    ):
        verdict = "NATURAL_RANDOMIZATION"
    else:
        verdict = "NONDETERMINISTIC"
    return bool(identical), verdict


def _compute_overall_verdict(
    map_signatures: List[Dict[str, Any]],
    comparison_is_deterministic: Optional[bool] = None,
) -> str:
    if len(map_signatures) < 2:
        return "VERDICT_UNDETERMINED"
    missing_signature = False
    topo_mismatch = False
    baseline_sig = None
    for sig in map_signatures:
        if (
            not sig.get("xodr_sha256")
            or not sig.get("tile_metadata_sha256")
            or sig.get("tile_count") is None
            or sig.get("road_count") is None
            or sig.get("junction_count") is None
        ):
            missing_signature = True
        if baseline_sig is None:
            baseline_sig = sig
        else:
            if (
                sig.get("tile_count") != baseline_sig.get("tile_count")
                or sig.get("road_count") != baseline_sig.get("road_count")
                or sig.get("junction_count") != baseline_sig.get("junction_count")
            ):
                topo_mismatch = True

    unique_xodr_hashes = sorted(
        {s.get("xodr_sha256") for s in map_signatures if s.get("xodr_sha256")}
    )
    unique_tilemeta_hashes = sorted(
        {
            s.get("tile_metadata_sha256")
            for s in map_signatures
            if s.get("tile_metadata_sha256")
        }
    )

    if missing_signature:
        return "NONDETERMINISTIC"

    if comparison_is_deterministic is None:
        comparison_is_deterministic = True

    if (
        comparison_is_deterministic
        and len(unique_xodr_hashes) <= 1
        and len(unique_tilemeta_hashes) <= 1
    ):
        return "DETERMINISTIC"
    if (not topo_mismatch) and (
        len(unique_xodr_hashes) > 1 or len(unique_tilemeta_hashes) > 1
    ):
        return "NATURAL_RANDOMIZATION"
    return "NONDETERMINISTIC"


def _required_successful_runs_for_request(runs_requested: int) -> int:
    return 1 if int(runs_requested) <= 1 else 2


def _coeff_of_variation(values: List[float]) -> Optional[float]:
    vals = [float(v) for v in values if v is not None]
    if len(vals) < 2:
        return None
    mean = sum(vals) / float(len(vals))
    if mean == 0.0:
        return None
    variance = sum((v - mean) ** 2 for v in vals) / float(len(vals))
    std = variance**0.5
    return float(std / mean)


def _compute_topology_cv(
    map_signatures: List[Dict[str, Any]],
) -> Dict[str, Optional[float]]:
    return {
        "tile_count": _coeff_of_variation(
            [
                s.get("tile_count")
                for s in map_signatures
                if s.get("tile_count") is not None
            ]
        ),
        "road_count": _coeff_of_variation(
            [
                s.get("road_count")
                for s in map_signatures
                if s.get("road_count") is not None
            ]
        ),
        "junction_count": _coeff_of_variation(
            [
                s.get("junction_count")
                for s in map_signatures
                if s.get("junction_count") is not None
            ]
        ),
    }


def _all_required_artifacts_exist(paths: List[Path]) -> bool:
    try:
        return all(p.is_file() for p in paths)
    except Exception:
        return False


def _count_timed_out_runs(run_results: List[Dict[str, Any]]) -> int:
    count = 0
    for item in run_results:
        try:
            if int(item.get("return_code", 0)) == 124:
                count += 1
        except Exception:
            continue
    return int(count)


def _classify_verdict(
    *,
    runs_successful: int,
    topology_hashes: List[str],
    runs_timed_out: int,
) -> Tuple[str, int, Optional[str]]:
    hashes = [str(h).strip() for h in topology_hashes if str(h).strip()]
    hashes_computed = int(len(hashes))
    if int(runs_successful) < 2:
        reason = "timeouts" if int(runs_timed_out) > 0 else "insufficient_successful_runs"
        return "VERDICT_UNDETERMINED", hashes_computed, reason
    if hashes_computed < 2:
        return "INCONCLUSIVE", hashes_computed, "insufficient_hashes"
    unique_hashes = sorted(set(hashes))
    if len(unique_hashes) == 1:
        return "DETERMINISTIC", hashes_computed, None
    return "NONDETERMINISTIC", hashes_computed, None


def _write_thesis_table(
    map_signatures: List[Dict[str, Any]], out_csv: Path, overall_verdict: str
) -> int:
    fieldnames = [
        "run_index",
        "run_dir",
        "xodr_sha256",
        "tile_metadata_sha256",
        "tile_count",
        "road_count",
        "junction_count",
        "identical_to_baseline",
        "per_run_verdict",
        "overall_verdict",
    ]
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    if not map_signatures:
        with out_csv.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
        print("No runs available to export determinism_thesis_table.csv")
        return 2

    baseline = map_signatures[0]
    rows: List[Dict[str, Any]] = []
    for sig in map_signatures:
        identical, per_run_verdict = _classify_signature(sig, baseline)
        rows.append(
            {
                "run_index": sig.get("run_index"),
                "run_dir": sig.get("run_dir"),
                "xodr_sha256": sig.get("xodr_sha256") or "",
                "tile_metadata_sha256": sig.get("tile_metadata_sha256") or "",
                "tile_count": ""
                if sig.get("tile_count") is None
                else sig.get("tile_count"),
                "road_count": ""
                if sig.get("road_count") is None
                else sig.get("road_count"),
                "junction_count": ""
                if sig.get("junction_count") is None
                else sig.get("junction_count"),
                "identical_to_baseline": bool(identical),
                "per_run_verdict": per_run_verdict,
                "overall_verdict": overall_verdict,
            }
        )

    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(row)
    print(f"Wrote thesis determinism table: {out_csv}")
    return 0


def _export_thesis_table(runs_root: Path, out_csv: Path) -> int:
    runs_root = runs_root.resolve()
    det_files = sorted(runs_root.rglob("determinism_fingerprint.json"))
    run_dirs = [p.parent for p in det_files]
    if not run_dirs:
        print(f"No determinism_fingerprint.json files found under {runs_root}")
        return _write_thesis_table([], out_csv, "INCONCLUSIVE")

    run_dirs = sorted(run_dirs, key=lambda p: p.name)
    map_signatures = []
    for i, run_dir in enumerate(run_dirs):
        final_xodr = _find_final_xodr(run_dir)
        tile_meta = _find_tile_metadata(run_dir)
        tile_count = _count_tiles(tile_meta, run_dir / "tiles")
        road_count, junction_count = _count_roads_and_junctions(final_xodr)
        osm_prov = _capture_source_osm_provenance(run_dir)
        map_signatures.append(
            {
                "run_index": i,
                "run_dir": str(run_dir),
                "xodr_sha256": _safe_sha256(final_xodr),
                "tile_metadata_sha256": _safe_sha256(tile_meta),
                "tile_count": tile_count,
                "road_count": road_count,
                "junction_count": junction_count,
                "source_osm_identity": osm_prov.get("source_osm_identity", ""),
                "source_osm_sha256": osm_prov.get("source_osm_sha256", ""),
                "source_osm_origin": osm_prov.get("source_osm_origin", "missing"),
            }
        )

    overall_verdict = _compute_overall_verdict(
        map_signatures, comparison_is_deterministic=None
    )
    return _write_thesis_table(map_signatures, out_csv, overall_verdict)


def _export_thesis_table_from_runs(
    run_dirs: List[Path], out_csv: Path, overall_verdict: Optional[str] = None
) -> int:
    map_signatures = []
    for i, run_dir in enumerate(run_dirs):
        final_xodr = _find_final_xodr(run_dir)
        tile_meta = _find_tile_metadata(run_dir)
        tile_count = _count_tiles(tile_meta, run_dir / "tiles")
        road_count, junction_count = _count_roads_and_junctions(final_xodr)
        osm_prov = _capture_source_osm_provenance(run_dir)
        map_signatures.append(
            {
                "run_index": i,
                "run_dir": str(run_dir),
                "xodr_sha256": _safe_sha256(final_xodr),
                "tile_metadata_sha256": _safe_sha256(tile_meta),
                "tile_count": tile_count,
                "road_count": road_count,
                "junction_count": junction_count,
                "source_osm_identity": osm_prov.get("source_osm_identity", ""),
                "source_osm_sha256": osm_prov.get("source_osm_sha256", ""),
                "source_osm_origin": osm_prov.get("source_osm_origin", "missing"),
            }
        )

    if not map_signatures:
        print("No runs available to export determinism_thesis_table.csv")
        return _write_thesis_table([], out_csv, "INCONCLUSIVE")

    if overall_verdict is None:
        overall_verdict = _compute_overall_verdict(
            map_signatures, comparison_is_deterministic=None
        )

    return _write_thesis_table(map_signatures, out_csv, overall_verdict)


def _build_manifest(root: Path) -> Dict[str, str]:
    """Return {relative_path: sha256} for all relevant files under root."""
    manifest: Dict[str, str] = {}
    for p in _iter_files(root):
        rel = str(p.relative_to(root)).replace("\\", "/")
        if _should_ignore(rel):
            continue
        manifest[rel] = _hash_file_sha256(p)
    return manifest


def _build_detailed_manifest(
    root: Path,
    run_index: int,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Build a detailed manifest with file info for a single run.

    Returns dict with:
    - timestamp (ISO)
    - seed used (if applicable)
    - list of files with hash + size + mtime
    """
    files_info: Dict[str, Dict[str, Any]] = {}

    for p in _iter_files(root):
        rel = str(p.relative_to(root)).replace("\\", "/")
        if _should_ignore(rel):
            continue
        try:
            stat = p.stat()
            sha = _hash_file_sha256(p)
            md5 = _hash_file_md5(p)
            files_info[rel] = {
                "hash": sha,
                "sha256": sha,
                "hash_md5": md5,
                "md5": md5,
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            }
        except (OSError, IOError):
            continue

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "run_index": run_index,
        "seed": seed,
        "root_dir": str(root),
        "file_count": len(files_info),
        "files": files_info,
    }


def _read_settings_snapshot(root: Path) -> Optional[Dict[str, Any]]:
    """Read settings snapshot if it exists, removing timestamp fields for comparison."""
    candidates = [
        root / "settings_snapshot.json",
        root / "domain_gap_settings_snapshot.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            try:
                with candidate.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                # Remove timestamp fields for normalized comparison
                for key in list(data.keys()):
                    if "timestamp" in key.lower() or "time" in key.lower():
                        del data[key]
                return data
            except (json.JSONDecodeError, OSError):
                pass
    return None


def _compare_settings_snapshots(runs_roots: List[Path]) -> Dict[str, Any]:
    """Compare settings snapshots across runs."""
    snapshots = []
    for root in runs_roots:
        snap = _read_settings_snapshot(root)
        snapshots.append(snap)

    if all(s is None for s in snapshots):
        return {"status": "no_snapshots_found"}

    # Check if all non-None snapshots are identical
    non_none = [s for s in snapshots if s is not None]
    if not non_none:
        return {"status": "no_valid_snapshots"}

    first = non_none[0]
    all_match = all(s == first for s in non_none[1:])

    return {
        "status": "match" if all_match else "mismatch",
        "snapshots_found": sum(1 for s in snapshots if s is not None),
        "total_runs": len(snapshots),
    }


def _compare_manifests(
    a: Dict[str, str], b: Dict[str, str]
) -> Tuple[List[str], List[str], List[str]]:
    a_keys = set(a.keys())
    b_keys = set(b.keys())

    only_a = sorted(a_keys - b_keys)
    only_b = sorted(b_keys - a_keys)

    changed = []
    for k in sorted(a_keys & b_keys):
        if a[k] != b[k]:
            changed.append(k)

    return only_a, only_b, changed


def _compare_all_manifests(manifests: List[Dict[str, str]]) -> Dict[str, Any]:
    """Compare all manifests pairwise and aggregate differences."""
    if len(manifests) < 2:
        return {"error": "Need at least 2 manifests to compare"}

    all_files_only_in: Dict[int, List[str]] = {}
    all_changed: List[str] = []

    # Compare each pair against the first manifest as baseline
    baseline = manifests[0]
    for i, other in enumerate(manifests[1:], start=1):
        only_baseline, only_other, changed = _compare_manifests(baseline, other)
        if only_baseline:
            all_files_only_in.setdefault(0, []).extend(only_baseline)
        if only_other:
            all_files_only_in.setdefault(i, []).extend(only_other)
        all_changed.extend(changed)

    # Deduplicate
    all_changed = sorted(set(all_changed))
    for k in all_files_only_in:
        all_files_only_in[k] = sorted(set(all_files_only_in[k]))

    return {
        "files_only_in_run": {str(k): v for k, v in all_files_only_in.items()},
        "changed_files": all_changed,
        "is_deterministic": len(all_changed) == 0 and len(all_files_only_in) == 0,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Determinism audit for ultimate_pipeline")
    ap.add_argument(
        "--export-thesis-table",
        action="store_true",
        help="Export thesis determinism CSV from existing runs (no pipeline runs)",
    )
    ap.add_argument(
        "--runs-root",
        default="",
        help="Root directory to search for determinism_fingerprint.json (default: ultimate_pipeline_out)",
    )
    ap.add_argument(
        "--out-csv",
        default="",
        help="Output CSV path (default: <runs-root>/determinism_thesis_table.csv)",
    )
    ap.add_argument(
        "--offline-only",
        action="store_true",
        help="Run pipeline with UP_OFFLINE_ONLY=1 to skip CARLA-dependent stages",
    )
    ap.add_argument(
        "--runs",
        type=int,
        default=None,
        help="Number of pipeline runs to compare (default: 5).",
    )
    ap.add_argument(
        "--n-runs",
        type=int,
        default=None,
        help="Alias for --runs.",
    )
    ap.add_argument(
        "--out",
        default="",
        help="Output directory for audit results (default: _analysis_out/determinism_audit/<timestamp>)",
    )
    ap.add_argument(
        "--seed", type=int, default=None, help="Seed to use for all runs (optional)"
    )
    ap.add_argument(
        "--timeout-per-run",
        type=int,
        default=None,
        help="Per-run pipeline timeout in seconds (default: 300; thesis recommendation: 600).",
    )
    ap.add_argument(
        "--run-timeout-s",
        type=int,
        default=None,
        help=argparse.SUPPRESS,
    )
    ap.add_argument(
        "--disable-dem",
        action="store_true",
        help="Set UP_DISABLE_DEM=1 for each pipeline subprocess run.",
    )
    ap.add_argument(
        "--smoke-mode",
        action="store_true",
        help="Fast verification mode: force exactly 2 runs with 120s timeout per run.",
    )
    ap.add_argument(
        "--thesis-evidence",
        action="store_true",
        help=(
            "Run in thesis-evidence mode (no forced relaxed strictness overrides). "
            "Requires explicit --out outside _analysis_out."
        ),
    )
    args = ap.parse_args()

    if args.export_thesis_table:
        runs_root = (
            Path(args.runs_root)
            if args.runs_root
            else (REPO_ROOT / "ultimate_pipeline_out")
        )
        out_csv = (
            Path(args.out_csv)
            if args.out_csv
            else (runs_root / "determinism_thesis_table.csv")
        )
        return _export_thesis_table(runs_root, out_csv)

    if (
        args.runs is not None
        and args.n_runs is not None
        and int(args.runs) != int(args.n_runs)
    ):
        print("Error: --runs and --n-runs provided with different values")
        return 2

    runs_requested = (
        int(args.runs)
        if args.runs is not None
        else (int(args.n_runs) if args.n_runs is not None else 5)
    )
    if runs_requested < 1:
        print("Error: --runs/--n-runs must be at least 1")
        return 2

    if bool(args.thesis_evidence):
        if not str(args.out or "").strip():
            print(
                "Error: --thesis-evidence requires explicit --out "
                "(default _analysis_out output is not allowed)."
            )
            return 2
        out_parts = Path(args.out).parts
        if out_parts and str(out_parts[0]).replace("\\", "/").rstrip("/") == "_analysis_out":
            print(
                "Error: --thesis-evidence --out must not point to _analysis_out; "
                "use a stable explicit output root."
            )
            return 2

    timeout_override = (
        int(args.timeout_per_run)
        if args.timeout_per_run is not None
        else (
            int(args.run_timeout_s) if args.run_timeout_s is not None else None
        )
    )
    run_timeout_s = (
        int(timeout_override)
        if timeout_override is not None
        else max(1, int(os.getenv("UP_DETERMINISM_RUN_TIMEOUT_S", "300")))
    )
    if bool(args.smoke_mode):
        runs_requested = 2
        run_timeout_s = 120

    forced_env_overrides = (
        {} if bool(args.thesis_evidence) else dict(_RELAXED_AUDIT_FORCED_ENV_OVERRIDES)
    )
    if bool(args.disable_dem):
        forced_env_overrides["UP_DISABLE_DEM"] = "1"
        # There is no pipeline-wide UP_DISABLE_DEM switch; clear API-key-based DEM download
        # paths and disable optional auto-expansion so Stage 05 degrades to flat elevation.
        forced_env_overrides["OPENTOPO_API_KEY"] = ""
        forced_env_overrides["UP_OPENTOPO_API_KEY"] = ""
        forced_env_overrides["UP_AUTO_EXPAND_DEM"] = "0"
        forced_env_overrides["UP_DEM_DIR"] = str(REPO_ROOT / "_tmp_determinism_no_dem")
    if bool(args.smoke_mode):
        smoke_input = _resolve_smoke_input_xodr()
        if smoke_input is not None:
            forced_env_overrides.setdefault("UP_INPUT_XODR", str(smoke_input))
    audit_profile = _audit_pipeline_profile(
        offline_only=bool(args.offline_only),
        thesis_evidence=bool(args.thesis_evidence),
        forced_env_overrides=forced_env_overrides,
    )
    if run_timeout_s < 1:
        print("Error: --timeout-per-run must be >= 1")
        return 2
    # Preserve existing timeout semantics while allowing CLI override.
    os.environ["UP_DETERMINISM_RUN_TIMEOUT_S"] = str(run_timeout_s)

    # Determine output directory
    if args.out:
        out_dir = Path(args.out)
    else:
        out_dir = _get_default_out_dir()

    os.makedirs(out_dir, exist_ok=True)

    print("\n==============================================")
    print(f"      DETERMINISM AUDIT ({runs_requested} runs)")
    print("==============================================")
    print(f"Output directory: {out_dir}\n")

    # Run the pipeline multiple times
    run_results: List[Dict[str, Any]] = []
    run_dirs: List[Path] = []

    for i in range(runs_requested):
        run_tag = f"audit_run_{i:03d}"
        print(f"\n--- Running pipeline (run {i + 1}/{runs_requested}) ---")

        started = datetime.now(timezone.utc)
        try:
            rc, log, out_path = _run_once(
                run_tag,
                offline_only=args.offline_only,
                seed=args.seed,
                forced_env_overrides=forced_env_overrides,
                thesis_evidence=bool(args.thesis_evidence),
            )
        except Exception as exc:
            rc = 2
            out_path = ""
            log = (
                f"ERROR: failed to execute run {run_tag}: "
                f"{exc.__class__.__name__}: {exc}"
            )
        finished = datetime.now(timezone.utc)
        wall_clock_s = max(
            0.0,
            (finished - started).total_seconds(),
        )
        print(log)

        run_info: Dict[str, Any] = {
            "run_index": i,
            "run_tag": run_tag,
            "return_code": rc,
            "output_dir": out_path,
            "success": rc == 0 and bool(out_path),
            "wall_clock_s": round(float(wall_clock_s), 3),
            "timeout_hit": bool(int(rc) == 124),
        }
        run_results.append(run_info)

        if rc != 0 or not out_path:
            print(f"Run {i + 1} failed or output dir not detected.")
            continue

        p = Path(out_path)
        if not p.exists():
            print(f"Output dir does not exist: {p}")
            run_info["success"] = False
            continue

        run_dirs.append(p)

        # Build and write detailed manifest for this run
        try:
            manifest = _build_detailed_manifest(p, i, seed=args.seed)
            manifest_path = out_dir / f"manifest_run_{i:03d}.json"
            with manifest_path.open("w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
            print(f"Wrote manifest: {manifest_path}")
        except Exception as exc:
            run_info["manifest_error"] = str(exc)
            run_info["success"] = False
            print(
                f"ERROR: failed to write mandatory manifest for run {i}; "
                f"marking run as failed: {exc}"
            )
            if run_dirs and run_dirs[-1] == p:
                run_dirs.pop()
            continue

    # Check if we have enough successful runs
    if len(run_dirs) < 2:
        print(f"\nOnly {len(run_dirs)} successful runs.")

        thesis_table_path = out_dir / "determinism_thesis_table.csv"
        required_successful_runs = _required_successful_runs_for_request(runs_requested)
        runs_timed_out = _count_timed_out_runs(run_results)
        verdict, hashes_computed, inconclusive_reason = _classify_verdict(
            runs_successful=len(run_dirs),
            topology_hashes=[],
            runs_timed_out=runs_timed_out,
        )
        report = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "status": "pass" if len(run_dirs) >= required_successful_runs else "failed",
            "reason": "single_run_no_pairwise_comparison"
            if len(run_dirs) == 1
            else "insufficient_successful_runs",
            "verdict": verdict,
            "runs_requested": runs_requested,
            "runs_successful": len(run_dirs),
            "runs_timed_out": int(runs_timed_out),
            "hashes_computed": int(hashes_computed),
            "inconclusive_reason": str(inconclusive_reason)
            if inconclusive_reason
            else None,
            "audit_pipeline_profile": dict(audit_profile),
            "run_timeout_s": int(run_timeout_s),
            "run_results": run_results,
            "determinism_thesis_table_csv": str(thesis_table_path),
        }

        # Write canonical thesis filename + backward-compatible alias
        report_path = out_dir / "determinism_report.json"
        alias_path = out_dir / "determinism_audit_report.json"
        for p in (report_path, alias_path):
            with p.open("w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)

        if run_dirs:
            try:
                _export_thesis_table_from_runs(run_dirs, thesis_table_path)
            except Exception as exc:
                print(f"WARNING: failed to write determinism_thesis_table.csv: {exc}")
                _write_thesis_table(
                    [], thesis_table_path, report.get("verdict", "INCONCLUSIVE")
                )
        else:
            _write_thesis_table(
                [], thesis_table_path, report.get("verdict", "INCONCLUSIVE")
            )

        hash_rows = []
        map_signatures = []
        for i, rd in enumerate(run_dirs):
            final_xodr = _find_final_xodr(rd)
            tile_meta = _find_tile_metadata(rd)
            tile_count = _count_tiles(tile_meta, rd / "tiles")
            road_count, junction_count = _count_roads_and_junctions(final_xodr)
            osm_prov = _capture_source_osm_provenance(rd)
            map_signatures.append(
                {
                    "run_index": i,
                    "run_dir": str(rd),
                    "xodr_sha256": _safe_sha256(final_xodr),
                    "tile_metadata_sha256": _safe_sha256(tile_meta),
                    "tile_count": tile_count,
                    "road_count": road_count,
                    "junction_count": junction_count,
                    "source_osm_identity": osm_prov.get("source_osm_identity", ""),
                    "source_osm_sha256": osm_prov.get("source_osm_sha256", ""),
                    "source_osm_origin": osm_prov.get("source_osm_origin", "missing"),
                }
            )
            if final_xodr and final_xodr.is_file():
                hash_rows.append(
                    {
                        "run_index": i,
                        "run_dir": str(rd),
                        "final_xodr": str(final_xodr),
                        "sha256": _hash_file_sha256(final_xodr),
                        "size_bytes": final_xodr.stat().st_size,
                    }
                )
            else:
                hash_rows.append(
                    {
                        "run_index": i,
                        "run_dir": str(rd),
                        "final_xodr": "",
                        "sha256": "",
                        "size_bytes": "",
                    }
                )

        hashes_path = out_dir / "determinism_hashes.csv"
        with hashes_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "run_index",
                    "run_dir",
                    "final_xodr",
                    "sha256",
                    "size_bytes",
                ],
            )
            w.writeheader()
            for row in hash_rows:
                w.writerow(row)
        report["hashes_computed"] = int(
            sum(1 for row in hash_rows if str(row.get("sha256", "")).strip())
        )

        delta_path = out_dir / "determinism_delta.csv"
        baseline = map_signatures[0] if map_signatures else {}
        with delta_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "run_index",
                    "tile_count",
                    "road_count",
                    "junction_count",
                    "delta_tile_count",
                    "delta_road_count",
                    "delta_junction_count",
                    "xodr_changed",
                ],
            )
            w.writeheader()
            for i, sig in enumerate(map_signatures):

                def delta(k: str):
                    try:
                        return int(sig.get(k)) - int(baseline.get(k))
                    except Exception:
                        return ""

                w.writerow(
                    {
                        "run_index": i,
                        "tile_count": sig.get("tile_count"),
                        "road_count": sig.get("road_count"),
                        "junction_count": sig.get("junction_count"),
                        "delta_tile_count": delta("tile_count"),
                        "delta_road_count": delta("road_count"),
                        "delta_junction_count": delta("junction_count"),
                        "xodr_changed": sig.get("xodr_sha256")
                        != baseline.get("xodr_sha256"),
                    }
                )

        report["required_successful_runs"] = required_successful_runs
        report["source_osm_provenance"] = {
            "identities": sorted(
                {
                    str(sig.get("source_osm_identity", "")).strip()
                    for sig in map_signatures
                    if str(sig.get("source_osm_identity", "")).strip()
                }
            ),
            "hashes": sorted(
                {
                    str(sig.get("source_osm_sha256", "")).strip()
                    for sig in map_signatures
                    if str(sig.get("source_osm_sha256", "")).strip()
                }
            ),
        }
        required_files = [report_path, hashes_path, thesis_table_path, delta_path]
        artifacts_ok = _all_required_artifacts_exist(required_files)
        if not artifacts_ok:
            report["status"] = "failed"
            report["reason"] = "required_artifacts_missing"
        for p in (report_path, alias_path):
            with p.open("w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)

        return 0 if report.get("status") == "pass" else 2

    print("\n==============================================")
    print("      Comparing artifacts")
    print("==============================================")
    for i, rd in enumerate(run_dirs):
        print(f"Run {i}: {rd}")
    print()

    # Build manifests for comparison
    manifests: List[Dict[str, str]] = []
    for rd in run_dirs:
        try:
            manifests.append(_build_manifest(rd))
        except Exception as exc:
            print(f"WARNING: failed to build manifest for comparison ({rd}): {exc}")
            manifests.append({})

    # Compare all manifests
    comparison = _compare_all_manifests(manifests)
    checked_files = int(
        len(
            {
                rel_path
                for manifest in manifests
                for rel_path in manifest.keys()
                if str(rel_path).strip()
            }
        )
    )

    # Compare settings snapshots
    settings_comparison = _compare_settings_snapshots(run_dirs)

    # Build map signatures (thesis contract)
    map_signatures = []
    missing_signature = False
    topo_mismatch = False
    baseline_sig = None
    for i, rd in enumerate(run_dirs):
        final_xodr = _find_final_xodr(rd)
        tile_meta = _find_tile_metadata(rd)
        tile_count = _count_tiles(tile_meta, rd / "tiles")
        road_count, junction_count = _count_roads_and_junctions(final_xodr)
        osm_prov = _capture_source_osm_provenance(rd)
        sig = {
            "run_index": i,
            "run_dir": str(rd),
            "xodr_sha256": _safe_sha256(final_xodr),
            "tile_metadata_sha256": _safe_sha256(tile_meta),
            "tile_count": tile_count,
            "road_count": road_count,
            "junction_count": junction_count,
            "source_osm_identity": osm_prov.get("source_osm_identity", ""),
            "source_osm_sha256": osm_prov.get("source_osm_sha256", ""),
            "source_osm_origin": osm_prov.get("source_osm_origin", "missing"),
        }
        map_signatures.append(sig)
        if (
            not sig["xodr_sha256"]
            or not sig["tile_metadata_sha256"]
            or sig["tile_count"] is None
            or sig["road_count"] is None
            or sig["junction_count"] is None
        ):
            missing_signature = True
        if baseline_sig is None:
            baseline_sig = sig
        else:
            # topology match check (counts only; conservative)
            if (
                sig["tile_count"] != baseline_sig["tile_count"]
                or sig["road_count"] != baseline_sig["road_count"]
                or sig["junction_count"] != baseline_sig["junction_count"]
            ):
                topo_mismatch = True

    runs_timed_out = _count_timed_out_runs(run_results)
    verdict, hashes_computed, inconclusive_reason = _classify_verdict(
        runs_successful=len(run_dirs),
        topology_hashes=[str(s.get("xodr_sha256") or "") for s in map_signatures],
        runs_timed_out=runs_timed_out,
    )

    # Build final report (thesis-friendly)
    thesis_table_path = out_dir / "determinism_thesis_table.csv"
    cv_fields = _compute_topology_cv(map_signatures) if len(run_dirs) >= 2 else {}
    required_successful_runs = _required_successful_runs_for_request(runs_requested)
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if len(run_dirs) >= required_successful_runs else "failed",
        "reason": None
        if len(run_dirs) >= required_successful_runs
        else "insufficient_successful_runs",
        "verdict": verdict,
        "runs_requested": runs_requested,
        "runs_successful": len(run_dirs),
        "runs_timed_out": int(runs_timed_out),
        "checked_files": int(checked_files),
        "hashes_computed": int(hashes_computed),
        "inconclusive_reason": str(inconclusive_reason)
        if inconclusive_reason
        else None,
        "audit_pipeline_profile": dict(audit_profile),
        "run_timeout_s": int(run_timeout_s),
        "required_successful_runs": required_successful_runs,
        "seed": args.seed,
        "offline_only": args.offline_only,
        "run_dirs": [str(rd) for rd in run_dirs],
        "comparison": comparison,
        "settings_snapshot_comparison": settings_comparison,
        "ignore_note": "logs, settings snapshots, crash artifacts, and db files are ignored by default",
        "run_results": run_results,
        "map_signature_fields": [
            "xodr_sha256",
            "tile_metadata_sha256",
            "tile_count",
            "road_count",
            "junction_count",
            "source_osm_identity",
            "source_osm_sha256",
            "source_osm_origin",
        ],
        "map_signatures": map_signatures,
        "source_osm_provenance": {
            "identities": sorted(
                {
                    str(sig.get("source_osm_identity", "")).strip()
                    for sig in map_signatures
                    if str(sig.get("source_osm_identity", "")).strip()
                }
            ),
            "hashes": sorted(
                {
                    str(sig.get("source_osm_sha256", "")).strip()
                    for sig in map_signatures
                    if str(sig.get("source_osm_sha256", "")).strip()
                }
            ),
        },
        "determinism_thesis_table_csv": str(thesis_table_path),
    }
    if verdict == "INCONCLUSIVE" and report.get("status") == "pass":
        report["status"] = "failed"
        report["reason"] = str(inconclusive_reason or "inconclusive")
    if cv_fields:
        report["coefficient_of_variation"] = cv_fields
        report["coefficient_of_variation.tile_count"] = cv_fields.get("tile_count")
        report["coefficient_of_variation.road_count"] = cv_fields.get("road_count")
        report["coefficient_of_variation.junction_count"] = cv_fields.get(
            "junction_count"
        )

    # Write canonical thesis filename + backward-compatible alias
    report_path = out_dir / "determinism_report.json"
    alias_path = out_dir / "determinism_audit_report.json"
    for p in (report_path, alias_path):
        with p.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
    print(f"Wrote report: {report_path} (alias: {alias_path})")

    # Write determinism_thesis_table.csv into the same out_dir
    try:
        _export_thesis_table_from_runs(
            run_dirs, thesis_table_path, overall_verdict=verdict
        )
        # Record where the thesis table was written for citeability
        try:
            report["determinism_thesis_table_csv"] = str(thesis_table_path)
            for p in (report_path, alias_path):
                with p.open("w", encoding="utf-8") as f:
                    json.dump(report, f, indent=2)
        except Exception:
            # Never fail audit due to metadata writeback
            pass
    except Exception as exc:
        print(f"WARNING: failed to write determinism_thesis_table.csv: {exc}")
        _write_thesis_table([], thesis_table_path, verdict)

    # Determinism hash summary (final XODR only)
    hash_rows = []
    for i, rd in enumerate(run_dirs):
        final_xodr = _find_final_xodr(rd)
        if not final_xodr:
            hash_rows.append(
                {
                    "run_index": i,
                    "run_dir": str(rd),
                    "final_xodr": "",
                    "sha256": "",
                    "size_bytes": "",
                }
            )
            continue
        sha = _hash_file_sha256(final_xodr)
        size = final_xodr.stat().st_size
        hash_rows.append(
            {
                "run_index": i,
                "run_dir": str(rd),
                "final_xodr": str(final_xodr),
                "sha256": sha,
                "size_bytes": size,
            }
        )
    hashes_path = out_dir / "determinism_hashes.csv"
    with hashes_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["run_index", "run_dir", "final_xodr", "sha256", "size_bytes"]
        )
        w.writeheader()
        for row in hash_rows:
            w.writerow(row)
    unique_hashes = sorted({r["sha256"] for r in hash_rows if r.get("sha256")})
    summary = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "runs_successful": len(run_dirs),
        "unique_hashes": unique_hashes,
        "hash_count": len(unique_hashes),
        "classification": "deterministic" if len(unique_hashes) <= 1 else "divergent",
        "hashes_csv": str(hashes_path),
    }
    summary_path = out_dir / "determinism_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"Wrote hash summary: {summary_path}")

    # ---------------------------------
    # Delta attribution (examiner-ready)
    # ---------------------------------
    delta_path = out_dir / "determinism_delta.csv"
    baseline = map_signatures[0] if map_signatures else {}
    with delta_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "run_index",
                "tile_count",
                "road_count",
                "junction_count",
                "delta_tile_count",
                "delta_road_count",
                "delta_junction_count",
                "xodr_changed",
            ],
        )
        w.writeheader()
        for i, sig in enumerate(map_signatures):

            def delta(k: str):
                try:
                    return int(sig.get(k)) - int(baseline.get(k))
                except Exception:
                    return ""

            w.writerow(
                {
                    "run_index": i,
                    "tile_count": sig.get("tile_count"),
                    "road_count": sig.get("road_count"),
                    "junction_count": sig.get("junction_count"),
                    "delta_tile_count": delta("tile_count"),
                    "delta_road_count": delta("road_count"),
                    "delta_junction_count": delta("junction_count"),
                    "xodr_changed": sig.get("xodr_sha256")
                    != baseline.get("xodr_sha256"),
                }
            )
    print(f"Wrote delta attribution: {delta_path}")

    required_files = [report_path, hashes_path, thesis_table_path, delta_path]
    artifacts_ok = _all_required_artifacts_exist(required_files)
    if not artifacts_ok:
        report["status"] = "failed"
        report["reason"] = "required_artifacts_missing"
    for p in (report_path, alias_path):
        with p.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    if verdict == "DETERMINISTIC":
        print("\nDeterminism audit PASSED: identical hashes across successful runs.\n")
        return 0
    if verdict == "INCONCLUSIVE":
        print("\nDeterminism audit INCONCLUSIVE: insufficient successful hash evidence.\n")
        return 2

    print("\nDeterminism audit FAILED:\n")

    files_only_in = comparison.get("files_only_in_run", {})
    for run_idx, files in files_only_in.items():
        if files:
            print(f"Files only in Run {run_idx}:")
            for k in files[:200]:
                print("  +", k)
            if len(files) > 200:
                print(f"  ... ({len(files) - 200} more)")
            print()

    changed = comparison.get("changed_files", [])
    if changed:
        print("Files with different content:")
        for k in changed[:200]:
            print("  *", k)
        if len(changed) > 200:
            print(f"  ... ({len(changed) - 200} more)")
        print()

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
