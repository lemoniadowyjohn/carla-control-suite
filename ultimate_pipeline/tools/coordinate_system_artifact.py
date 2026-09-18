from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ultimate_pipeline.core.georef_utils import (
    normalize_georeference,
    parse_georeference,
)


CANONICAL_BBOX = {
    "lat_min": 48.74935649548228,
    "lon_min": 11.422268084715878,
    "lat_max": 48.77444431571603,
    "lon_max": 11.47882091528412,
}


def _iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_georeference_from_xodr(xodr_path: Path) -> Optional[str]:
    try:
        root = ET.parse(str(xodr_path)).getroot()
        header = root.find("header")
        if header is None:
            return None
        node = header.find("geoReference")
        if node is None:
            return None
        txt = (node.text or "").strip()
        return txt or None
    except Exception:
        return None


def _read_offset_from_xodr(xodr_path: Path) -> Dict[str, float]:
    out = {"x": 0.0, "y": 0.0, "z": 0.0, "hdg": 0.0}
    try:
        root = ET.parse(str(xodr_path)).getroot()
        header = root.find("header")
        if header is None:
            return out
        off = header.find("offset")
        if off is None:
            return out
        for key in ("x", "y", "z", "hdg"):
            try:
                out[key] = float(off.attrib.get(key, out[key]))
            except Exception:
                out[key] = 0.0
        return out
    except Exception:
        return out


def _offset_is_non_zero(offset: Dict[str, float], eps: float = 1e-9) -> bool:
    return any(
        abs(float(offset.get(k, 0.0))) > float(eps) for k in ("x", "y", "z", "hdg")
    )


def _coordinate_system_hash(payload: Dict[str, Any]) -> str:
    blob = json.dumps(
        payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _xodr_sha256(xodr_path: Optional[Path]) -> Optional[str]:
    if xodr_path is None:
        return None
    try:
        p = Path(xodr_path)
        if not p.is_file():
            return None
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _read_georef_info(xodr_path: Optional[Path]) -> Dict[str, Any]:
    if xodr_path is None:
        return {
            "raw": None,
            "norm": "",
            "valid": False,
            "params_complete": False,
            "offset": {"x": 0.0, "y": 0.0, "z": 0.0, "hdg": 0.0},
        }
    geo_ref = _read_georeference_from_xodr(Path(xodr_path))
    geo_norm = normalize_georeference(geo_ref)
    georef_valid, georef_params_complete, _ = parse_georeference(geo_norm)
    offset = _read_offset_from_xodr(Path(xodr_path))
    return {
        "raw": geo_ref,
        "norm": geo_norm,
        "valid": bool(georef_valid),
        "params_complete": bool(georef_params_complete),
        "offset": {
            "x": float(offset.get("x", 0.0)),
            "y": float(offset.get("y", 0.0)),
            "z": float(offset.get("z", 0.0)),
            "hdg": float(offset.get("hdg", 0.0)),
        },
    }


def _compact_alignment_summary(summary: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(summary, dict):
        return {}
    compact: Dict[str, Any] = {}
    for key in ("tx", "ty", "scale", "cos", "sin", "theta", "rot"):
        if key in summary:
            try:
                compact[key] = float(summary[key])
            except Exception:
                pass
    diagnostics = summary.get("diagnostics")
    if isinstance(diagnostics, dict):
        d_compact: Dict[str, Any] = {}
        for key in ("fallback_used", "fallback_reason", "n_points", "rmse_before", "rmse_after"):
            if key not in diagnostics:
                continue
            val = diagnostics[key]
            if isinstance(val, (str, bool, int, float)) or val is None:
                d_compact[key] = val
        if d_compact:
            compact["diagnostics"] = d_compact
    return compact


def _comparability_status(manual_info: Dict[str, Any], auto_info: Dict[str, Any]) -> str:
    if not manual_info.get("path_present"):
        return "manual_missing"
    if not auto_info.get("path_present"):
        return "auto_missing"
    if not manual_info.get("valid"):
        return "manual_georef_invalid"
    if not auto_info.get("valid"):
        return "auto_georef_invalid"
    manual_norm = str(manual_info.get("norm") or "")
    auto_norm = str(auto_info.get("norm") or "")
    if not manual_norm:
        return "manual_georef_missing"
    if not auto_norm:
        return "auto_georef_missing"
    if manual_norm != auto_norm:
        return "crs_mismatch"
    return "crs_match"


def write_coordinate_system_json(
    run_dir: Path,
    auto_xodr_path: Optional[Path] = None,
    *,
    manual_xodr_path: Optional[Path] = None,
    alignment_method: Optional[str] = None,
    alignment_transform_summary: Optional[Dict[str, Any]] = None,
    offset_bake_used: bool = False,
) -> Path:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / "coordinate_system.json"

    manual_info = _read_georef_info(Path(manual_xodr_path) if manual_xodr_path else None)
    auto_info = _read_georef_info(Path(auto_xodr_path) if auto_xodr_path else None)
    manual_info["path_present"] = bool(manual_xodr_path and Path(manual_xodr_path).is_file())
    auto_info["path_present"] = bool(auto_xodr_path and Path(auto_xodr_path).is_file())
    manual_norm = str(manual_info.get("norm") or "")
    auto_norm = str(auto_info.get("norm") or "")
    manual_raw = manual_info.get("raw")
    auto_raw = auto_info.get("raw")
    georef_valid = bool(auto_info.get("valid"))
    georef_params_complete = bool(auto_info.get("params_complete"))
    geo_norm = auto_norm
    geo_ref = auto_raw
    offset = auto_info.get("offset") or {"x": 0.0, "y": 0.0, "z": 0.0, "hdg": 0.0}
    mixed_offset_incomplete = bool(
        _offset_is_non_zero(offset) and not georef_params_complete
    )
    offset_policy = (
        "invalid_incomplete_crs_with_offset"
        if mixed_offset_incomplete
        else "allowed_with_complete_crs"
    )
    crs_match = bool(manual_norm and auto_norm and manual_norm == auto_norm)
    comparability_status = _comparability_status(manual_info, auto_info)
    alignment_summary = _compact_alignment_summary(alignment_transform_summary)
    manual_path_str = str(Path(manual_xodr_path)) if manual_xodr_path else ""
    auto_path_str = str(Path(auto_xodr_path)) if auto_xodr_path else ""

    hash_payload = {
        "units": "meters",
        "osm_bbox_wgs84": dict(CANONICAL_BBOX),
        "canonical_crs": geo_norm,
        "georeference_valid": bool(georef_valid),
        "georeference_params_complete": bool(georef_params_complete),
        "offset": {
            "x": float(offset.get("x", 0.0)),
            "y": float(offset.get("y", 0.0)),
            "z": float(offset.get("z", 0.0)),
            "hdg": float(offset.get("hdg", 0.0)),
        },
        "offset_policy": str(offset_policy),
        "mixed_offset_incomplete_crs": bool(mixed_offset_incomplete),
        "manual_xodr_path": manual_path_str or None,
        "auto_xodr_path": auto_path_str or None,
        "manual_geoReference_norm": manual_norm or None,
        "auto_geoReference_norm": auto_norm or None,
        "crs_match": bool(crs_match),
        "comparability_status": str(comparability_status),
        "alignment_method": str(alignment_method or "unknown"),
        "alignment_transform_summary": alignment_summary,
        "offset_bake_used": bool(offset_bake_used),
        "structural_scope": "planar_only",
        "elevation_scope": "excluded",
    }

    payload: Dict[str, Any] = {
        "generated_at_utc": _iso_utc(),
        "units": "meters",
        "carla_axes": "x_forward_y_right_z_up (unreal left-handed)",
        "osm_bbox_wgs84": dict(CANONICAL_BBOX),
        "structural_scope": "planar_only",
        "elevation_scope": "excluded",
        "manual_xodr_path": manual_path_str or None,
        "auto_xodr_path": auto_path_str or None,
        "manual_xodr_sha256": _xodr_sha256(Path(manual_xodr_path)) if manual_xodr_path else None,
        "auto_xodr_sha256": _xodr_sha256(Path(auto_xodr_path)) if auto_xodr_path else None,
        "manual_geoReference": manual_raw,
        "auto_geoReference": auto_raw,
        "manual_geoReference_norm": manual_norm or None,
        "auto_geoReference_norm": auto_norm or None,
        "manual_georeference_valid": bool(manual_info.get("valid")),
        "auto_georeference_valid": bool(auto_info.get("valid")),
        "manual_georeference_params_complete": bool(manual_info.get("params_complete")),
        "auto_georeference_params_complete": bool(auto_info.get("params_complete")),
        "crs_match": bool(crs_match),
        "comparability_status": str(comparability_status),
        "alignment_method": str(alignment_method or "unknown"),
        "alignment_transform_summary": alignment_summary,
        "offset_bake_used": bool(offset_bake_used),
        "xodr_geoReference": geo_ref,
        "canonical_crs": geo_norm,
        "georeference_valid": bool(georef_valid),
        "georeference_params_complete": bool(georef_params_complete),
        "offset": hash_payload["offset"],
        "offset_policy": str(offset_policy),
        "mixed_offset_incomplete_crs": bool(mixed_offset_incomplete),
        "coordinate_system_hash": _coordinate_system_hash(hash_payload),
        "notes": "Structural metrics computed in local XODR planView meters with explicit alignment; sensor transforms follow AGENT_SYNC (cTv direct, vTl inverted).",
    }

    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out
