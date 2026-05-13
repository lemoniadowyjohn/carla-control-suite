"""ultimate_pipeline.quality.xodr_strict_validator

Strict, CARLA-focused OpenDRIVE validator + (minimal) preflight repair.

Goals
-----
* Catch common OpenDRIVE issues that are known to crash CARLA's OpenDRIVE
  standalone mode during import or navigation build.
* Provide a *structured* report with severity levels (error/warn/info).
* Be import-safe (no CARLA dependency).

Notes
-----
This is intentionally conservative: it prefers to FAIL EARLY rather than let
CARLA crash (which is both slow and opaque).
"""

from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


SUPPORTED_GEOM_CHILDREN = {
    "line",
    "arc",
    "poly3",
    "paramPoly3",
    # "spiral" exists in OpenDRIVE, but has known rough edges in tooling;
    # treat as unsupported by default (can be allowed via options).
}


@dataclass
class Issue:
    severity: str  # "error" | "warn" | "info"
    code: str
    message: str
    context: Dict[str, Any]


def _is_finite(x: float) -> bool:
    return not (math.isnan(x) or math.isinf(x))


def _f(value: Optional[str], default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        v = float(value)
        if not _is_finite(v):
            return default
        return v
    except Exception:
        return default


def _i(value: Optional[str], default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except Exception:
        return default


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def thesis_strict_checks(run_dir: Path, strict: bool, errors: list[str]) -> None:
    """
    Enforce thesis strict gates that depend on run-level artifacts.

    Gates:
    - Gate 0: run_manifest.json must exist in strict mode.
    - Option A policy: GPS anchor override is forbidden in strict mode.
    - Gate 1: domain-gap geoReference parity between manual and auto reports.
    - Gate 2: CRS comparability requires manual reference present.
    """
    manifest_path = run_dir / "run_manifest.json"
    if strict and not manifest_path.exists():
        errors.append("Missing run_manifest.json (Gate 0 strict requirement).")
        return

    manifest = _read_json(manifest_path) if manifest_path.exists() else {}
    notes_raw = manifest.get("notes", {})
    notes = notes_raw if isinstance(notes_raw, dict) else {}

    if strict and notes.get("gps_anchor_override_applied") is True:
        errors.append(
            "gps_anchor_override_applied=True in run_manifest (Option A forbids this in strict mode)."
        )

    coord_manual = run_dir / "domain_gap" / "coord_manual.json"
    coord_auto = run_dir / "domain_gap" / "coord_auto.json"
    if strict and coord_manual.exists() and coord_auto.exists():
        manual_payload = _read_json(coord_manual)
        auto_payload = _read_json(coord_auto)
        georef_manual = manual_payload.get("geoReference_norm") or manual_payload.get(
            "geoReference"
        )
        georef_auto = auto_payload.get("geoReference_norm") or auto_payload.get(
            "geoReference"
        )
        if georef_manual and georef_auto:
            if str(georef_manual).strip() != str(georef_auto).strip():
                errors.append(
                    "Domain-gap CRS mismatch: coord_manual.geoReference_norm != coord_auto.geoReference_norm "
                    "(Gate 1 strict requirement)."
                )

    # Gate 2: Thesis strict requires manual reference CRS for comparability
    if strict:
        crs_comp = run_dir / "crs_comparability.json"
        manual_present = False
        if crs_comp.exists():
            try:
                data = json.loads(crs_comp.read_text(encoding="utf-8"))
                manual_present = bool((data.get("manual") or {}).get("present"))
            except Exception:
                manual_present = False
        if not manual_present:
            errors.append(
                "THESIS_STRICT requires manual reference CRS for comparability. "
                "crs_comparability.json missing or manual.present=false. "
                "Set UP_MANUAL_XODR to the manual map used for domain-gap (Gate 2 strict requirement)."
            )


class StrictXodrValidator:
    """Validate an OpenDRIVE file for CARLA import stability."""

    def __init__(
        self,
        *,
        allow_spiral: bool = False,
        max_abs_xy: float = 200000.0,
        max_abs_z: float = 10000.0,
        max_lane_width: float = 15.0,
        min_lane_width: float = 0.2,
        max_elevation_jump_m: float = 2.5,
        require_center_lane: bool = True,
    ) -> None:
        self.allow_spiral = bool(allow_spiral)
        self.max_abs_xy = float(max_abs_xy)
        self.max_abs_z = float(max_abs_z)
        self.max_lane_width = float(max_lane_width)
        self.min_lane_width = float(min_lane_width)
        self.max_elevation_jump_m = float(max_elevation_jump_m)
        self.require_center_lane = bool(require_center_lane)

    # ---------------- public API ----------------

    def validate_path(self, xodr_path: str | Path) -> Dict[str, Any]:
        xodr_path = Path(xodr_path)
        issues: List[Issue] = []
        try:
            root = ET.parse(str(xodr_path)).getroot()
        except Exception as e:
            issues.append(
                Issue(
                    "error",
                    "xml_parse",
                    f"Failed to parse XML: {e}",
                    {"path": str(xodr_path)},
                )
            )
            return self._report(issues)

        issues.extend(self.validate_root(root))
        return self._report(issues)

    def validate_root(self, root: ET.Element) -> List[Issue]:
        issues: List[Issue] = []

        if root.tag != "OpenDRIVE":
            issues.append(
                Issue(
                    "error",
                    "root_tag",
                    f"Root tag must be 'OpenDRIVE' (got {root.tag!r})",
                    {},
                )
            )
            return issues

        issues.extend(self._check_header(root))

        roads = [r for r in root.findall("road")]
        if not roads:
            issues.append(Issue("error", "no_roads", "No <road> elements found.", {}))
            return issues

        road_ids = set()
        for r in roads:
            rid = r.get("id")
            if not rid:
                issues.append(
                    Issue("error", "road_missing_id", "Road is missing id.", {})
                )
                continue
            if rid in road_ids:
                issues.append(
                    Issue(
                        "error",
                        "road_duplicate_id",
                        "Duplicate road id.",
                        {"road": rid},
                    )
                )
            road_ids.add(rid)

        # Per-road checks
        for r in roads:
            issues.extend(self._check_road(r))

        # Junction reference integrity
        issues.extend(self._check_junctions(root, road_ids))

        return issues

    # ---------------- report helpers ----------------

    @staticmethod
    def _report(issues: List[Issue]) -> Dict[str, Any]:
        out = {
            "ok": not any(i.severity == "error" for i in issues),
            "n_issues": len(issues),
            "n_errors": sum(1 for i in issues if i.severity == "error"),
            "n_warnings": sum(1 for i in issues if i.severity == "warn"),
            "issues": [
                {
                    "severity": i.severity,
                    "code": i.code,
                    "message": i.message,
                    "context": i.context,
                }
                for i in issues
            ],
        }
        return out

    # ---------------- concrete checks ----------------

    @staticmethod
    def _check_header(root: ET.Element) -> List[Issue]:
        issues: List[Issue] = []
        header = root.find("header")
        if header is None:
            issues.append(Issue("warn", "header_missing", "Missing <header>.", {}))
            return issues

        rev_major = _i(header.get("revMajor"), -1)
        rev_minor = _i(header.get("revMinor"), -1)
        if rev_major < 0 or rev_minor < 0:
            issues.append(
                Issue(
                    "warn",
                    "header_revision_missing",
                    "<header> missing revMajor/revMinor; CARLA expects OpenDRIVE 1.4.",
                    {
                        "revMajor": header.get("revMajor"),
                        "revMinor": header.get("revMinor"),
                    },
                )
            )

        geo = header.find("geoReference")
        if geo is None or not (geo.text or "").strip():
            issues.append(
                Issue(
                    "warn",
                    "georef_missing",
                    "Missing/empty <geoReference>. CARLA can load without it, but downstream alignment may break.",
                    {},
                )
            )

        return issues

    def _check_road(self, road: ET.Element) -> List[Issue]:
        issues: List[Issue] = []
        rid = road.get("id", "UNKNOWN")

        length = _f(road.get("length"), -1.0)
        if length <= 0.0:
            issues.append(
                Issue(
                    "error",
                    "road_length_nonpositive",
                    "Road length must be positive.",
                    {"road": rid, "length": road.get("length")},
                )
            )

        plan = road.find("planView")
        if plan is None:
            issues.append(
                Issue("error", "planView_missing", "Missing <planView>.", {"road": rid})
            )
        else:
            issues.extend(self._check_plan_view(rid, plan, length))

        lanes = road.find("lanes")
        if lanes is None:
            issues.append(
                Issue("error", "lanes_missing", "Missing <lanes>.", {"road": rid})
            )
        else:
            issues.extend(self._check_lanes(rid, lanes, length))

        # Elevation: check for jumps (common CARLA instability trigger in large maps)
        issues.extend(self._check_elevation_profile(rid, road))

        return issues

    def _check_plan_view(
        self, rid: str, plan: ET.Element, road_length: float
    ) -> List[Issue]:
        issues: List[Issue] = []
        geoms = plan.findall("geometry")
        if not geoms:
            issues.append(
                Issue(
                    "error",
                    "no_geometry",
                    "No <geometry> in <planView>.",
                    {"road": rid},
                )
            )
            return issues

        last_s = -1e9
        total_len = 0.0

        for idx, g in enumerate(geoms):
            s = _f(g.get("s"), -1.0)
            x = _f(g.get("x"), 0.0)
            y = _f(g.get("y"), 0.0)
            hdg = _f(g.get("hdg"), 0.0)
            gl = _f(g.get("length"), -1.0)

            if s < 0.0:
                issues.append(
                    Issue(
                        "error",
                        "geom_s_negative",
                        "Geometry s must be >= 0.",
                        {"road": rid, "idx": idx, "s": s},
                    )
                )
            if s + 1e-6 < last_s:
                issues.append(
                    Issue(
                        "error",
                        "geom_s_not_monotonic",
                        "Geometry s must be monotonic.",
                        {"road": rid, "idx": idx, "s": s, "prev_s": last_s},
                    )
                )
            last_s = s

            if abs(x) > self.max_abs_xy or abs(y) > self.max_abs_xy:
                issues.append(
                    Issue(
                        "warn",
                        "geom_xy_large",
                        "Geometry x/y very large; check geoReference/offset.",
                        {"road": rid, "idx": idx, "x": x, "y": y},
                    )
                )
            if not _is_finite(hdg):
                issues.append(
                    Issue(
                        "error",
                        "geom_hdg_nan",
                        "Geometry hdg is not finite.",
                        {"road": rid, "idx": idx, "hdg": g.get("hdg")},
                    )
                )

            if gl <= 0.0:
                issues.append(
                    Issue(
                        "error",
                        "geom_len_nonpositive",
                        "Geometry length must be positive.",
                        {"road": rid, "idx": idx, "length": g.get("length")},
                    )
                )
            else:
                total_len += gl

            # Exactly one child describing type
            children = [c.tag for c in list(g) if isinstance(c.tag, str)]
            if not children:
                issues.append(
                    Issue(
                        "error",
                        "geom_type_missing",
                        "Geometry is missing type child (<line>/<arc>/...).",
                        {"road": rid, "idx": idx},
                    )
                )
            else:
                # sometimes there are whitespace/text nodes; ensure we count element tags only
                type_children = [
                    t for t in children if t in (SUPPORTED_GEOM_CHILDREN | {"spiral"})
                ]
                if len(type_children) != 1:
                    issues.append(
                        Issue(
                            "error",
                            "geom_type_ambiguous",
                            "Geometry must have exactly one type child.",
                            {"road": rid, "idx": idx, "children": children},
                        )
                    )
                else:
                    t = type_children[0]
                    if t == "spiral" and not self.allow_spiral:
                        issues.append(
                            Issue(
                                "error",
                                "geom_spiral_unsupported",
                                "Spiral geometry present; block for CARLA stability.",
                                {"road": rid, "idx": idx},
                            )
                        )
                    if t == "arc":
                        arc = g.find("arc")
                        curv = _f(
                            arc.get("curvature") if arc is not None else None, 0.0
                        )
                        if not _is_finite(curv):
                            issues.append(
                                Issue(
                                    "error",
                                    "arc_curvature_nan",
                                    "Arc curvature not finite.",
                                    {"road": rid, "idx": idx},
                                )
                            )

        # Road length consistency is a common silent killer
        if road_length > 0 and total_len > 0:
            rel = abs(total_len - road_length) / max(1e-6, road_length)
            if rel > 0.10:
                issues.append(
                    Issue(
                        "warn",
                        "road_length_mismatch",
                        "Road length differs notably from sum(geometry.length). CARLA import may become unstable.",
                        {
                            "road": rid,
                            "road_length": road_length,
                            "sum_geom": total_len,
                            "rel": rel,
                        },
                    )
                )

        return issues

    def _check_lanes(
        self, rid: str, lanes: ET.Element, road_length: float
    ) -> List[Issue]:
        issues: List[Issue] = []
        secs = lanes.findall("laneSection")
        if not secs:
            issues.append(
                Issue(
                    "error",
                    "no_lane_sections",
                    "No <laneSection> found.",
                    {"road": rid},
                )
            )
            return issues

        last_s = -1e9
        for idx, sec in enumerate(secs):
            s = _f(sec.get("s"), -1.0)
            if s < 0.0:
                issues.append(
                    Issue(
                        "error",
                        "laneSection_s_negative",
                        "laneSection s must be >= 0.",
                        {"road": rid, "idx": idx, "s": s},
                    )
                )
            if s + 1e-6 < last_s:
                issues.append(
                    Issue(
                        "error",
                        "laneSection_s_not_monotonic",
                        "laneSection s must be monotonic.",
                        {"road": rid, "idx": idx, "s": s, "prev_s": last_s},
                    )
                )
            last_s = s

            if 0 < road_length < s - 1e-6:
                issues.append(
                    Issue(
                        "error",
                        "laneSection_s_gt_length",
                        "laneSection s beyond road length.",
                        {"road": rid, "idx": idx, "s": s, "road_length": road_length},
                    )
                )

            center = sec.find("center")
            if self.require_center_lane:
                if center is None or center.find("lane[@id='0']") is None:
                    issues.append(
                        Issue(
                            "error",
                            "center_lane_missing",
                            "Center lane id=0 missing.",
                            {"road": rid, "idx": idx},
                        )
                    )

            # Width sanity for driving lanes
            for lane in sec.findall(".//lane"):
                lid = lane.get("id")
                ltype = lane.get("type", "")
                if lid is None:
                    continue
                if ltype == "driving":
                    widths = lane.findall("width")
                    if not widths:
                        issues.append(
                            Issue(
                                "warn",
                                "driving_lane_missing_width",
                                "Driving lane has no <width>.",
                                {"road": rid, "lane": lid, "laneSection": idx},
                            )
                        )
                    for w in widths:
                        a = _f(w.get("a"), 0.0)
                        if a < self.min_lane_width or a > self.max_lane_width:
                            issues.append(
                                Issue(
                                    "error" if a <= 0 else "warn",
                                    "lane_width_out_of_bounds",
                                    "Lane width a is out of expected bounds.",
                                    {"road": rid, "lane": lid, "a": a},
                                )
                            )

        return issues

    def _check_elevation_profile(self, rid: str, road: ET.Element) -> List[Issue]:
        issues: List[Issue] = []
        prof = road.find("elevationProfile")
        if prof is None:
            return issues

        elevs = prof.findall("elevation")
        if not elevs:
            return issues

        last_s = -1e9
        last_a: Optional[float] = None
        for idx, e in enumerate(elevs):
            s = _f(e.get("s"), -1.0)
            a = _f(e.get("a"), 0.0)
            if s < 0.0:
                issues.append(
                    Issue(
                        "error",
                        "elev_s_negative",
                        "Elevation s must be >= 0.",
                        {"road": rid, "idx": idx, "s": s},
                    )
                )
            if s + 1e-6 < last_s:
                issues.append(
                    Issue(
                        "error",
                        "elev_s_not_monotonic",
                        "Elevation s must be monotonic.",
                        {"road": rid, "idx": idx, "s": s, "prev_s": last_s},
                    )
                )
            last_s = s

            if not _is_finite(a) or abs(a) > self.max_abs_z:
                issues.append(
                    Issue(
                        "error",
                        "elev_a_invalid",
                        "Elevation a is invalid (nan/inf/huge).",
                        {"road": rid, "idx": idx, "a": e.get("a")},
                    )
                )

            if last_a is not None:
                if abs(a - last_a) > self.max_elevation_jump_m:
                    issues.append(
                        Issue(
                            "warn",
                            "elev_jump",
                            "Large elevation discontinuity between consecutive entries.",
                            {"road": rid, "idx": idx, "prev_a": last_a, "a": a},
                        )
                    )
            last_a = a

        return issues

    @staticmethod
    def _check_junctions(root: ET.Element, road_ids: set[str]) -> List[Issue]:
        issues: List[Issue] = []
        for j in root.findall("junction"):
            jid = j.get("id", "UNKNOWN")
            for c in j.findall("connection"):
                incoming = c.get("incomingRoad")
                connecting = c.get("connectingRoad")
                if not incoming or not connecting:
                    issues.append(
                        Issue(
                            "error",
                            "junction_missing_ref",
                            "Junction connection missing road refs.",
                            {"junction": jid},
                        )
                    )
                    continue
                if incoming == connecting:
                    issues.append(
                        Issue(
                            "error",
                            "junction_self_connection",
                            "incomingRoad == connectingRoad.",
                            {"junction": jid, "road": incoming},
                        )
                    )
                if incoming not in road_ids:
                    issues.append(
                        Issue(
                            "error",
                            "junction_incoming_missing",
                            "incomingRoad not found.",
                            {"junction": jid, "incomingRoad": incoming},
                        )
                    )
                if connecting not in road_ids:
                    issues.append(
                        Issue(
                            "error",
                            "junction_connecting_missing",
                            "connectingRoad not found.",
                            {"junction": jid, "connectingRoad": connecting},
                        )
                    )
                cp = c.get("contactPoint")
                if cp and cp not in ("start", "end"):
                    issues.append(
                        Issue(
                            "warn",
                            "junction_contactPoint_invalid",
                            "contactPoint should be start/end.",
                            {"junction": jid, "contactPoint": cp},
                        )
                    )

        return issues
