#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NEW-325 -- remove heuristic calibration authority.

``ultimate_pipeline/tools/calibrate_sensors_in_carla.py`` scores both candidate
extrinsic conventions (stored matrix used directly, and stored matrix inverted)
by counting how many marker centres project inside the image, then picks the
higher score globally.  With no markers it always selects "no invert" because
the loop initialises ``best_sum = -1`` and both candidates score ``0``.

That contradicts the authoritative thesis rule, which fixes ``cTv``/
``vTl`` semantics (``cTv`` = vehicle->camera used directly, **not** inverted;
``vTl`` = lidar->vehicle, **inverted**).  A heuristic tool must never produce an
artifact that can be mistaken for authoritative thesis calibration.

This module

* defines a diagnostic status block that a heuristic export must carry,
* refuses heuristic convention selection under ``strict`` mode,
* defines the authoritative import path (which consumes
  ``sensors/calibration_contract.py``),
* and provides :func:`assert_loadable_by_perception` so a perception loader can
  reject a heuristic export outright.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

AUTHORITY_SCHEMA = "CALIBRATION_AUTHORITY/v1"

#: Schema name a heuristic export must carry.  The deliberate ``_diagnostic``
#: infix means a legacy consumer keying on the old name will not pick it up.
DIAGNOSTIC_EXPORT_SCHEMA = "carla_export_v1_DIAGNOSTIC_NON_AUTHORITATIVE"
LEGACY_EXPORT_FORMAT = "carla_export_v1"

STATUS_AUTHORITATIVE = "AUTHORITATIVE_THESIS_CALIBRATION"
STATUS_DIAGNOSTIC = "LEGACY_DIAGNOSTIC_CONVENTION_EXPLORER"

CALIBRATION_AUTHORITY_UNRESOLVED = "CALIBRATION_AUTHORITY_UNRESOLVED"
HEURISTIC_EXPORT_REJECTED = "HEURISTIC_EXPORT_REJECTED"
HEURISTIC_CONVENTION_FORBIDDEN = "HEURISTIC_CONVENTION_FORBIDDEN"
NON_AUTHORITATIVE_CALIBRATION = "NON_AUTHORITATIVE_CALIBRATION"

#: Keys that identify a heuristic export by content, not only by name.
DIAGNOSTIC_MARKER_KEYS: tuple = (
    "global_selected_convention",
    "selected_convention",
    "convention_search_performed",
)


def diagnostic_status_block(
    *,
    tool: str = "ultimate_pipeline.tools.calibrate_sensors_in_carla",
    selected_convention: Optional[str] = None,
    score_function: str = "marker_centre_visibility_count",
) -> Dict[str, Any]:
    """The mandatory non-authoritative status block for heuristic exports."""
    return {
        "schema": DIAGNOSTIC_EXPORT_SCHEMA,
        "status": STATUS_DIAGNOSTIC,
        "authoritative": False,
        "permissible_use": "diagnostic convention exploration only",
        "impermissible_use": [
            "thesis calibration input",
            "perception loader input",
            "sensor rig attachment source",
            "pair-manifest calibration_sha256 source",
        ],
        "producing_tool": str(tool),
        "convention_selection_method": "heuristic",
        "selected_convention": selected_convention,
        "score_function": score_function,
        "convention_search_performed": True,
        "contradicts_canonical_thesis_rule": True,
        "canonical_rule": (
            "cTv = vehicle->camera used DIRECTLY (not inverted); "
            "vTl = lidar->vehicle INVERTED to vehicle->lidar"
        ),
        "canonical_authority_module": "ultimate_pipeline.sensors.calibration_contract",
        "warning": (
            "This artifact does NOT establish thesis calibration. The extrinsic "
            "convention was chosen by marker-visibility heuristics, not by the "
            "authoritative contract."
        ),
    }


def attach_diagnostic_status(
    export: Mapping[str, Any], *, tool: str = "ultimate_pipeline.tools.calibrate_sensors_in_carla",
    selected_convention: Optional[str] = None,
) -> Dict[str, Any]:
    """Stamp a heuristic export with the diagnostic status block."""
    out = dict(export)
    status = diagnostic_status_block(tool=tool, selected_convention=selected_convention)
    convention = selected_convention
    if convention is None:
        convention = export.get("global_selected_convention") or export.get("selected_convention")
        status = diagnostic_status_block(tool=tool, selected_convention=convention)
    out["format"] = LEGACY_EXPORT_FORMAT
    out["schema"] = DIAGNOSTIC_EXPORT_SCHEMA
    out["calibration_authority"] = status
    out["authoritative"] = False
    return out


def is_diagnostic_export(payload: Any) -> bool:
    """Content-based detection of a heuristic export (not just name-based)."""
    if not isinstance(payload, Mapping):
        return False
    if str(payload.get("schema", "")) == DIAGNOSTIC_EXPORT_SCHEMA:
        return True
    status = payload.get("calibration_authority")
    if isinstance(status, Mapping) and status.get("authoritative") is False:
        return True
    if any(key in payload for key in DIAGNOSTIC_MARKER_KEYS):
        return True
    return False


def assert_loadable_by_perception(
    payload: Any, *, source: str = "", strict: bool = True
) -> Dict[str, Any]:
    """A perception loader must refuse a heuristic export.

    Returns a fail-closed verdict; ``strict`` never raises, so the caller can
    record the rejection as evidence.
    """
    if is_diagnostic_export(payload):
        return {
            "loadable": False,
            "invalid_reasons": [
                f"{HEURISTIC_EXPORT_REJECTED}:heuristic_convention_export:"
                f"{source or 'unknown_source'}"
            ],
            "authoritative": False,
            "status": STATUS_DIAGNOSTIC,
        }
    if strict and isinstance(payload, Mapping):
        if "K_undistortion" not in payload and "cameras" not in payload:
            return {
                "loadable": False,
                "invalid_reasons": [
                    f"{CALIBRATION_AUTHORITY_UNRESOLVED}:"
                    f"missing K_undistortion/cameras:{source or 'unknown_source'}"
                ],
                "authoritative": False,
                "status": None,
            }
    return {
        "loadable": True,
        "invalid_reasons": [],
        "authoritative": True,
        "status": STATUS_AUTHORITATIVE,
    }


def reject_heuristic_convention_selection(
    *,
    strict: bool,
    selected_convention: Optional[str] = None,
    source: str = "",
) -> Dict[str, Any]:
    """NEW-325: strict mode must refuse heuristic convention selection."""
    if not strict:
        return {
            "allowed": True,
            "authoritative": False,
            "status": STATUS_DIAGNOSTIC,
            "note": "heuristic convention exploration permitted in non-strict mode",
        }
    return {
        "allowed": False,
        "authoritative": False,
        "status": STATUS_DIAGNOSTIC,
        "invalid_reasons": [
            f"{HEURISTIC_CONVENTION_FORBIDDEN}:"
            f"strict_mode_refuses_heuristic_convention_selection:"
            f"selected={selected_convention}:source={source or 'unknown_source'}"
        ],
    }


def authoritative_calibration(calib_path: Any) -> Dict[str, Any]:
    """The canonical import path: consume ``calibration_contract`` directly.

    This is what a governed perception loader must use.  It never re-derives a
    convention.
    """
    from ultimate_pipeline.sensors import calibration_contract as cc

    path = Path(str(calib_path))
    report = cc.validate_calibration_contract(path)
    verdict = "PASS" if report.get("verdict") == "PASS" else "FAIL_CLOSED"
    reasons = list(report.get("errors") or [])
    return {
        "schema": AUTHORITY_SCHEMA,
        "authority": "ultimate_pipeline.sensors.calibration_contract",
        "status": STATUS_AUTHORITATIVE,
        "authoritative": verdict == "PASS",
        "calib_path": str(path),
        "calib_sha256": report.get("calib_sha256"),
        "verdict": verdict,
        "invalid_reasons": reasons,
        "calibration_semantics": report.get("calibration_semantics"),
        "camera_intrinsics": report.get("camera_intrinsics"),
        "contract_report": report,
    }


def evaluate_calibration_authority(
    calib_path: Any, *, heuristic_export_path: Optional[Any] = None
) -> Dict[str, Any]:
    """Combined authority report: canonical calibration + heuristic rejection."""
    authoritative = authoritative_calibration(calib_path)
    heuristic: Optional[Dict[str, Any]] = None
    if heuristic_export_path:
        try:
            payload = json.loads(Path(str(heuristic_export_path)).read_text(encoding="utf-8"))
        except Exception as exc:
            heuristic = {
                "path": str(heuristic_export_path),
                "read_error": f"{type(exc).__name__}:{exc}",
            }
        else:
            verdict = assert_loadable_by_perception(
                payload, source=str(heuristic_export_path), strict=True
            )
            heuristic = {
                "path": str(heuristic_export_path),
                "detected_as_diagnostic": is_diagnostic_export(payload),
                "loadable_by_perception": verdict["loadable"],
                "rejection_reasons": verdict["invalid_reasons"],
                "status": verdict["status"],
            }
    return {
        "schema": AUTHORITY_SCHEMA,
        "authoritative_calibration": authoritative,
        "heuristic_export": heuristic,
        "heuristic_cannot_override_canonical": True,
        "overall_authoritative": bool(authoritative["authoritative"]),
    }