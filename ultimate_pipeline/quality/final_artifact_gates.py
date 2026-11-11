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

import hashlib
import math
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_NOT_RUN = "NOT_RUN"
STATUS_BLOCKED_INPUT = "BLOCKED_INPUT"

#: Version of the release acceptance policy. Bump it when the mandatory gate
#: set or the strict-status semantics change.
ACCEPTANCE_POLICY_VERSION = "v86.1"

#: The largest final artifact accepted at the XML boundary. The map of record
#: is about 150 MB; this bounds memory if the input is hostile.
MAX_XODR_BYTES = 1 << 30

#: Gates the production release path must have evaluated, and passed, on the
#: final artifact. They are hard-fail classes in ``build_map_acceptance``.
#: ``origin_sanity``, ``geometric_continuity`` and ``lane_section_successors``
#: are computed separately by ``main_pipeline``, which already did so before
#: this module existed.
FINAL_ARTIFACT_MANDATORY_GATES: Tuple[str, ...] = (
    "artifact_structure",
    "lane_connectivity",
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
    """Wrap a checker's issue list. It never treats "no result" as zero issues (V86 A7).

    A checker must return a list or tuple whose items are dicts or strings.
    ``None``, a falsey non-collection, a string, a mapping or invalid items
    raise ``TypeError``. ``compute_final_artifact_reports`` turns that into a
    NOT_RUN report, never a pass.
    """
    if not isinstance(issues, (list, tuple)):
        raise TypeError(
            f"checker returned {type(issues).__name__}, expected a list of issues"
        )
    bad = [type(item).__name__ for item in issues if not isinstance(item, (dict, str))]
    if bad:
        raise TypeError(f"checker returned invalid issue entries: {sorted(set(bad))}")
    issues = list(issues)
    return {"ok": len(issues) == 0, "issue_count": len(issues), "issues": issues}


def normalize_lane_section_report(report: Any) -> Dict[str, Any]:
    """Give a lane-section-successor report an EXPLICIT boolean ``ok`` (V86 A4).

    The two producers emit different schemas. The pipeline's
    ``write_lane_connectivity_report`` gives ``broken_count``; the promotion
    path's ``repair_and_assert_lane_section_successors`` gives a ``failures``
    list. Neither sets ``ok``, and acceptance used to *infer* success. Here
    ``ok`` is derived only from explicit integer or list evidence. Without
    evidence the report is NOT_RUN.
    """
    if not isinstance(report, dict):
        return not_run_report("lane_section_successors", f"report is {type(report).__name__}")
    out = dict(report)
    if isinstance(out.get("ok"), bool):
        return out
    broken = out.get("broken_count")
    failures = out.get("failures")
    if isinstance(broken, int) and not isinstance(broken, bool) and broken >= 0:
        out["ok"] = broken == 0
        out["issue_count"] = broken
    elif isinstance(failures, list):
        out["ok"] = len(failures) == 0
        out["issue_count"] = len(failures)
    else:
        out.update({"ok": None, "status": STATUS_NOT_RUN,
                    "reason": "no explicit broken_count/failures evidence"})
    return out


# --- V86 A8: XML boundary ----------------------------------------------------
_PROLOG_DECL = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)


class UnsafeXMLError(ValueError):
    """The artifact violates the XML boundary policy."""


def check_xml_boundary(data: bytes) -> None:
    """Reject inputs that OpenDRIVE never needs and that enable XML attacks.

    Threat model: an XODR may come from an untrusted source (download, PR,
    operator copy). ``xml.etree`` on CPython 3.12 uses expat, which does not
    fetch external entities and limits entity amplification. That protection
    depends on the expat version, so the boundary does not rely on it: any
    DOCTYPE or ENTITY declaration is rejected outright, and the size is
    capped. Tested behaviour is in tests/unit/test_v86_acceptance_strict.py.
    It does not defend against a well-formed but semantically hostile map;
    the quality gates do that.
    """
    if len(data) > MAX_XODR_BYTES:
        raise UnsafeXMLError(f"artifact is {len(data)} bytes > limit {MAX_XODR_BYTES}")
    root_at = data.find(b"<OpenDRIVE")
    prolog = data if root_at < 0 else data[:root_at]
    if _PROLOG_DECL.search(prolog) or _PROLOG_DECL.search(data[: 1 << 16]):
        raise UnsafeXMLError("DOCTYPE/ENTITY declarations are not permitted in OpenDRIVE input")


def parse_xodr_bytes(data: bytes) -> ET.Element:
    check_xml_boundary(data)
    return ET.fromstring(data)


# --- V86 A6: immutable content-addressed snapshot ------------------------------
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot_final_artifact(final_out: str, snapshot_dir: str) -> Dict[str, Any]:
    """Freeze the exact bytes every release validator will evaluate.

    The artifact is read once and written to ``<snapshot_dir>/<sha256>.xodr``,
    which is made read-only. Every gate runs on that path. ``verify_artifact_unchanged``
    later proves the published ``final_out`` still has the same digest.
    """
    data = Path(final_out).read_bytes()
    digest = sha256_bytes(data)
    snap_dir = Path(snapshot_dir)
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap = snap_dir / f"{digest}.xodr"
    if snap.exists():
        if sha256_bytes(snap.read_bytes()) != digest:
            raise RuntimeError(f"existing snapshot {snap} does not match its content address")
    else:
        tmp = snap_dir / f".{digest}.{os.getpid()}.tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, snap)
        os.chmod(snap, 0o444)
    return {"path": str(snap), "sha256": digest, "bytes": len(data), "source_path": str(final_out)}


def verify_artifact_unchanged(path: str, expected_sha256: str) -> Tuple[bool, str]:
    try:
        actual = sha256_bytes(Path(path).read_bytes())
    except OSError as exc:
        return False, f"unreadable: {exc}"
    return actual == expected_sha256, actual


# --- V86 A2: structural scope -------------------------------------------------
def check_artifact_structure(root: ET.Element, expected_scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Threshold-independent structural validity of a release OpenDRIVE map.

    It requires an ``OpenDRIVE`` root with a ``header``, at least one road,
    and for every road a positive, finite length and at least one planView
    geometry. ``expected_scope`` (from the candidate manifest or release
    profile) may add ``min_roads`` and ``expected_road_ids``. No historical
    road count is hardcoded.
    """
    issues = []
    if root.tag != "OpenDRIVE":
        issues.append({"kind": "root_not_opendrive", "tag": root.tag})
    if root.find("header") is None:
        issues.append({"kind": "missing_header"})
    roads = root.findall("road")
    if not roads:
        issues.append({"kind": "no_roads"})
    for road in roads:
        rid = road.get("id")
        try:
            length = float(road.get("length", "nan"))
        except ValueError:
            length = float("nan")
        if not (math.isfinite(length) and length > 0):
            issues.append({"kind": "invalid_road_length", "road": rid, "length": road.get("length")})
        pv = road.find("planView")
        if pv is None or not pv.findall("geometry"):
            issues.append({"kind": "missing_planview_geometry", "road": rid})
    scope = dict(expected_scope or {})
    min_roads = scope.get("min_roads")
    if isinstance(min_roads, int) and len(roads) < min_roads:
        issues.append({"kind": "below_expected_scope", "road_count": len(roads), "min_roads": min_roads})
    expected_ids = scope.get("expected_road_ids")
    if expected_ids:
        missing = sorted(set(map(str, expected_ids)) - {r.get("id") for r in roads})
        if missing:
            issues.append({"kind": "expected_roads_missing", "count": len(missing), "examples": missing[:20]})
    return {"ok": not issues, "issue_count": len(issues), "issues": issues,
            "road_count": len(roads), "expected_scope": scope or None}


def _gate_table(expected_scope: Optional[Dict[str, Any]] = None) -> Dict[str, Callable[[str, Any], Dict[str, Any]]]:
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
    from ultimate_pipeline.quality.check_lane_link_targets_exist import (
        check_lane_link_targets_exist,
    )
    from ultimate_pipeline.quality.check_lane_width_continuity import check_lane_width_continuity
    from ultimate_pipeline.quality.check_physics_feasibility import PhysicsFeasibilityChecker
    from ultimate_pipeline.quality.check_post_tiling_integrity import check_post_tiling_integrity

    # Definitions identical to scripts/measure_candidate_acceptance.run_gates.
    return {
        "artifact_structure": lambda p, r: check_artifact_structure(r, expected_scope),
        "lane_connectivity": lambda p, r: check_lane_link_targets_exist(p, allow_dead_ends=True),
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


def compute_final_artifact_reports(
    xodr_path: str,
    *,
    expected_sha256: Optional[str] = None,
    expected_scope: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Evaluate every FINAL_ARTIFACT_MANDATORY_GATES gate on ``xodr_path``.

    The result always contains one dict per gate. If the artifact cannot be
    read, fails the XML boundary, does not match ``expected_sha256`` (V86 A6),
    or cannot be parsed, every gate is ``BLOCKED_INPUT``. An exception inside a
    gate becomes ``NOT_RUN`` with the exception recorded. Nothing is skipped.
    """
    reports: Dict[str, Dict[str, Any]] = {}
    root = None
    parse_error = None
    try:
        data = Path(str(xodr_path)).read_bytes()
        if expected_sha256 is not None and sha256_bytes(data) != expected_sha256:
            raise RuntimeError(
                f"artifact digest {sha256_bytes(data)} != expected {expected_sha256}"
            )
        root = parse_xodr_bytes(data)
    except Exception as exc:  # noqa: BLE001 - recorded, fail-closed
        parse_error = f"{type(exc).__name__}: {exc}"

    for gate, fn in _gate_table(expected_scope).items():
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
