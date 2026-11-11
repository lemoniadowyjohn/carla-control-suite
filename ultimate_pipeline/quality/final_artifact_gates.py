"""Mandatory map-quality gates recomputed on the FINAL artifact (V85 Phase 2).

Single source of truth for the report-producing gates that both the production
pipeline (``main_pipeline`` final acceptance) and the map-of-record promotion
path (``scripts/measure_candidate_acceptance.run_gates``) apply to the exact
published XODR. The gate definitions mirror ``run_gates`` one-for-one.

Why this exists: at 31bb6c7a the pipeline recomputed its "mandatory" gates via
``getattr(QualityGateManager, ...)``. Three of those methods did not exist and
three take a parsed root and return ``None``. Every failure was swallowed as
"recompute skipped", and ``elevation_continuity`` was never supplied at all.
``build_map_acceptance`` then treated the absent reports as passing. Here every
gate always yields a report dict. A gate that cannot run yields an explicit
``status`` of ``NOT_RUN`` (or ``BLOCKED_INPUT``) with ``ok: None``. It is never
silently absent, and never ``ok: True`` by default.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, Tuple

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_NOT_RUN = "NOT_RUN"
STATUS_BLOCKED_INPUT = "BLOCKED_INPUT"

#: Gates the production release path must have evaluated, and passed, on the
#: final artifact. They are hard-fail classes in ``build_map_acceptance``.
#: ``origin_sanity``, ``geometric_continuity`` and ``lane_section_successors``
#: are computed separately by ``main_pipeline``, which already did so before
#: this module existed.
FINAL_ARTIFACT_MANDATORY_GATES: Tuple[str, ...] = (
    "elevation_continuity",
    "junction_integrity",
    "lane_width_continuity",
    "lane_geometry_continuity",
    "elevation_missing_and_cliffs",
    "elevation_smoothness",
    "physics_feasibility",
    "post_tiling_integrity",
    "carla_import_s",
    "carla_opendrive_compat",
)

PIPELINE_SUPPLIED_MANDATORY_GATES: Tuple[str, ...] = (
    "origin_sanity",
    "geometric_continuity",
    "lane_section_successors",
)

#: Every gate the production release path treats as mandatory.
RELEASE_MANDATORY_GATES: Tuple[str, ...] = (
    PIPELINE_SUPPLIED_MANDATORY_GATES + FINAL_ARTIFACT_MANDATORY_GATES
)


def _issues_report(issues: Any) -> Dict[str, Any]:
    issues = list(issues or [])
    return {"ok": len(issues) == 0, "issue_count": len(issues), "issues": issues}


def _gate_table() -> Dict[str, Callable[[str, Any], Dict[str, Any]]]:
    # Imports are local so that importing this module stays cheap and does not
    # create import cycles with quality_gate_manager.
    from ultimate_pipeline.quality.check_carla_import_s import CarlaImportSChecker
    from ultimate_pipeline.quality.check_carla_opendrive_compat import StrictCarlaOpendriveGate
    from ultimate_pipeline.quality.check_elevation_continuity import check_elevation_continuity
    from ultimate_pipeline.quality.check_elevation_missing_and_cliffs import (
        check_elevation_missing_and_cliffs,
    )
    from ultimate_pipeline.quality.check_elevation_smoothness import ElevationSmoothnessGate
    from ultimate_pipeline.quality.check_junction_integrity import JunctionIntegrityGate
    from ultimate_pipeline.quality.check_lane_geometry_continuity import (
        check_lane_geometry_continuity,
    )
    from ultimate_pipeline.quality.check_lane_width_continuity import check_lane_width_continuity
    from ultimate_pipeline.quality.check_physics_feasibility import PhysicsFeasibilityChecker
    from ultimate_pipeline.quality.check_post_tiling_integrity import check_post_tiling_integrity

    # Definitions identical to scripts/measure_candidate_acceptance.run_gates.
    return {
        "elevation_continuity": lambda p, r: check_elevation_continuity(p, eps_z=0.5),
        "junction_integrity": lambda p, r: JunctionIntegrityGate.validate(p),
        "lane_width_continuity": lambda p, r: check_lane_width_continuity(p),
        "lane_geometry_continuity": lambda p, r: check_lane_geometry_continuity(p),
        "elevation_missing_and_cliffs": lambda p, r: check_elevation_missing_and_cliffs(p),
        "elevation_smoothness": lambda p, r: _issues_report(ElevationSmoothnessGate.validate(r)),
        "physics_feasibility": lambda p, r: _issues_report(PhysicsFeasibilityChecker.validate(r)),
        "post_tiling_integrity": lambda p, r: check_post_tiling_integrity(p),
        "carla_import_s": lambda p, r: _issues_report(CarlaImportSChecker.validate(r)),
        "carla_opendrive_compat": lambda p, r: _issues_report(StrictCarlaOpendriveGate.validate(r)),
    }


def not_run_report(gate: str, reason: str, *, status: str = STATUS_NOT_RUN) -> Dict[str, Any]:
    """An explicit non-passing report for a mandatory gate that did not run."""
    return {"ok": None, "status": status, "gate": gate, "reason": reason}


def compute_final_artifact_reports(xodr_path: str) -> Dict[str, Dict[str, Any]]:
    """Evaluate every FINAL_ARTIFACT_MANDATORY_GATES gate on ``xodr_path``.

    The result always contains one dict per gate. If the artifact cannot be
    parsed, every root-based gate is ``BLOCKED_INPUT``. An exception inside a
    gate becomes ``NOT_RUN`` with the exception recorded. Nothing is skipped.
    """
    reports: Dict[str, Dict[str, Any]] = {}
    root = None
    parse_error = None
    try:
        root = ET.parse(str(xodr_path)).getroot()
    except Exception as exc:  # noqa: BLE001 - recorded, fail-closed
        parse_error = f"{type(exc).__name__}: {exc}"

    for gate, fn in _gate_table().items():
        if root is None:
            reports[gate] = not_run_report(
                gate, f"final artifact could not be parsed: {parse_error}",
                status=STATUS_BLOCKED_INPUT,
            )
            continue
        try:
            rep = fn(str(xodr_path), root)
        except Exception as exc:  # noqa: BLE001 - recorded, fail-closed
            reports[gate] = not_run_report(gate, f"{type(exc).__name__}: {exc}")
            continue
        if not isinstance(rep, dict):
            reports[gate] = not_run_report(
                gate, f"gate returned {type(rep).__name__}, not a report dict"
            )
            continue
        reports[gate] = rep
    return reports
