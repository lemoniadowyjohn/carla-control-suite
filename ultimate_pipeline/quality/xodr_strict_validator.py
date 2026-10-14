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

OC-59: all numeric reads go through xodr_numeric strict parsing --
malformed/nonfinite attributes are reported with their MISSING/MALFORMED/
NONFINITE outcome and NEVER silently become physical zeros. Primitive
support follows xodr_validation_policy profiles (no hidden default).
"""

from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from ultimate_pipeline.quality.xodr_numeric import (
    ParseResult,
    parse_required_float,
    parse_required_int,
)
from ultimate_pipeline.quality.xodr_validation_policy import (
    ALL_PRIMITIVES,
    CARLA_0_9_16_COMPAT,
    GEOM_S_BOUNDARY_TOL_M,
    GEOM_S_EPS,
    LANESECTION_FIRST_S_TOL_M,
    LEGACY_CONSERVATIVE,
    MAX_PLAUSIBLE_LANE_WIDTH_M,
    PARAMPOLY3_PRANGE_SUPPORTED,
    PRIMITIVE_REQUIRED_ATTRS,
    classify_s_step,
    primitives_for_profile,
    road_length_check,
    width_extrema_over_interval,
)


SUPPORTED_GEOM_CHILDREN = {
    "line",
    "arc",
    "poly3",
    "paramPoly3",
    # OC-59: "spiral" support is profile-driven (see xodr_validation_policy),
    # not governed by this legacy set. Kept for backward-compatible import.
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
    """LEGACY fail-open parse (kept for backward-compatible import only).

    New validation code MUST use xodr_numeric.parse_required_float instead:
    this helper converts malformed/nonfinite input to ``default`` BEFORE any
    validity decision, which is exactly the OC-59 §2 defect.
    """
    parsed = parse_required_float(value)
    if parsed.ok:
        return float(parsed.value)
    return default


def _i(value: Optional[str], default: int = 0) -> int:
    """LEGACY fail-open int parse (kept for backward-compatible import only).

    New validation code MUST use xodr_numeric.parse_required_int instead.
    """
    parsed = parse_required_int(value)
    if parsed.ok:
        return int(parsed.value)
    return default


def _numeric_issue(
    field: str,
    result: ParseResult,
    *,
    road: str,
    code_suffix: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> Issue:
    """Build an error Issue for a non-VALID required numeric parse (§4).

    Outcome-specific codes (never a substituted zero): e.g.
    geom_hdg_missing / geom_hdg_malformed / geom_hdg_nonfinite.
    """
    outcome = result.status.lower()
    code = f"{field}_{outcome}{code_suffix}"
    ctx: Dict[str, Any] = {"road": road, "raw": result.raw}
    if extra:
        ctx.update(extra)
    return Issue(
        "error",
        code,
        f"Required numeric attribute {field!r} is {result.status} "
        f"(raw={result.raw!r}); refusing to substitute a default.",
        ctx,
    )


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
    """Validate an OpenDRIVE file for CARLA import stability.

    Args:
        profile: validation profile from xodr_validation_policy
            (OPEN_DRIVE_STRUCTURAL / CARLA_0_9_16_COMPAT /
            LEGACY_CONSERVATIVE). Default CARLA_0_9_16_COMPAT: spiral is a
            valid, coefficient-checked primitive (the production geometry
            pipeline supports all five primitives).
        allow_spiral: legacy toggle; True selects CARLA_0_9_16_COMPAT,
            False selects LEGACY_CONSERVATIVE (spiral flagged). Explicit
            ``profile`` wins when both are given.
    """

    def __init__(
        self,
        *,
        allow_spiral: Optional[bool] = None,
        profile: Optional[str] = None,
        max_abs_xy: float = 200000.0,
        max_abs_z: float = 10000.0,
        max_lane_width: float = 15.0,
        min_lane_width: float = 0.2,
        max_elevation_jump_m: float = 2.5,
        require_center_lane: bool = True,
    ) -> None:
        if profile is None:
            # Historical default (allow_spiral=False) blocked spiral; the
            # converged default accepts it per the compat profile (§5).
            profile = (
                CARLA_0_9_16_COMPAT if allow_spiral in (None, True)
                else LEGACY_CONSERVATIVE
            )
        self.profile = profile
        self.supported_primitives = primitives_for_profile(profile)
        self.allow_spiral = "spiral" in self.supported_primitives
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
            report = self._report(issues)
            report["profile"] = self.profile
            return report

        issues.extend(self.validate_root(root))
        report = self._report(issues)
        report["profile"] = self.profile
        return report

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
            "issues": [                {
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

        rev_major = parse_required_int(header.get("revMajor"))
        rev_minor = parse_required_int(header.get("revMinor"))
        if not rev_major.ok or not rev_minor.ok:
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

        length_res = parse_required_float(road.get("length"))
        if not length_res.ok:
            issues.append(
                _numeric_issue("road_length", length_res, road=rid)
            )
            length = float("nan")
        elif float(length_res.value) <= 0.0:
            issues.append(
                Issue(
                    "error",
                    "road_length_nonpositive",
                    "Road length must be positive.",
                    {"road": rid, "length": road.get("length")},
                )
            )
            length = float(length_res.value)
        else:
            length = float(length_res.value)

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
        last_len = 0.0
        total_len = 0.0

        for idx, g in enumerate(geoms):
            ctx = {"road": rid, "idx": idx}
            s_res = parse_required_float(g.get("s"))
            x_res = parse_required_float(g.get("x"))
            y_res = parse_required_float(g.get("y"))
            hdg_res = parse_required_float(g.get("hdg"))
            gl_res = parse_required_float(g.get("length"))

            geom_ok = True
            for field, res in (("geom_s", s_res), ("geom_x", x_res),
                               ("geom_y", y_res), ("geom_hdg", hdg_res),
                               ("geom_length", gl_res)):
                if not res.ok:
                    issues.append(_numeric_issue(field, res, road=rid, extra=ctx))
                    geom_ok = False
            if not geom_ok:
                # No zero substitution: skip boundary math for this segment
                # rather than validating against invented coordinates.
                continue

            s = float(s_res.value)
            x = float(x_res.value)
            y = float(y_res.value)
            # hdg validity already enforced above (no default substituted);
            # its value is not needed for static checks.
            gl = float(gl_res.value)

            # Segment-boundary classification (§9), not just monotonicity.
            # (Subsumes the old monotonic check: backward steps surface as
            # overlap/duplicate_s with a documented tolerance.)
            if idx == 0:
                if s < 0:
                    step = "negative_s"
                elif abs(s) <= GEOM_S_BOUNDARY_TOL_M:
                    step = "continuous"
                else:
                    step = "gap"
            else:
                step = classify_s_step(last_s, last_len, s)
            if step == "negative_s":
                issues.append(
                    Issue("error", "geom_s_negative",
                          "Geometry s must be >= 0.", {**ctx, "s": g.get("s")})
                )
            elif step == "duplicate_s":
                issues.append(
                    Issue("error", "geom_s_duplicate",
                          "Geometry s repeats the previous segment start.",
                          {**ctx, "s": s, "prev_s": last_s})
                )
            elif step == "overlap":
                issues.append(
                    Issue("error", "geom_s_overlap",
                          "Geometry s starts before the previous segment ends.",
                          {**ctx, "s": s,
                           "expected": last_s + last_len})
                )
            elif step == "gap":
                issues.append(
                    Issue("error", "geom_s_gap",
                          "Geometry s starts after the previous segment ends.",
                          {**ctx, "s": s,
                           "expected": last_s + last_len})
                )
            last_s = s
            last_len = gl if gl > 0 else 0.0

            if abs(x) > self.max_abs_xy or abs(y) > self.max_abs_xy:
                issues.append(
                    Issue(
                        "warn",
                        "geom_xy_large",
                        "Geometry x/y very large; check geoReference/offset.",
                        {"road": rid, "idx": idx, "x": x, "y": y},
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

            # Exactly one primitive child (§7); per-primitive coefficients (§6).
            children = [c for c in list(g) if isinstance(c.tag, str)]
            prim_names = [c.tag for c in children]
            known = [t for t in prim_names if t in ALL_PRIMITIVES]
            unknown = [t for t in prim_names if t not in ALL_PRIMITIVES]
            if unknown:
                issues.append(
                    Issue(
                        "error",
                        "geom_unknown_primitive",
                        "Geometry has an unknown primitive child.",
                        {"road": rid, "idx": idx, "children": prim_names},
                    )
                )
            elif len(known) != 1:
                issues.append(
                    Issue(
                        "error",
                        "geom_type_ambiguous" if known else "geom_type_missing",
                        "Geometry must have exactly one known primitive child.",
                        {"road": rid, "idx": idx, "children": prim_names},
                    )
                )
            else:
                t = known[0]
                if t not in self.supported_primitives:
                    issues.append(
                        Issue(
                            "error",
                            "geom_primitive_unsupported_by_profile",
                            f"Primitive {t!r} is not supported by profile "
                            f"{self.profile}.",
                            {"road": rid, "idx": idx, "profile": self.profile},
                        )
                    )
                else:
                    issues.extend(
                        self._check_primitive_coeffs(rid, idx, g, t)
                    )

        # Road length consistency via the single shared policy (§8).
        if math.isfinite(road_length) and road_length > 0 and total_len > 0:
            verdict = road_length_check(road_length, total_len)
            if verdict["status"] == "MISMATCH":
                issues.append(
                    Issue(
                        "warn",
                        "road_length_mismatch",
                        "Road length differs notably from sum(geometry.length). CARLA import may become unstable.",
                        {
                            "road": rid,
                            "road_length": road_length,
                            "sum_geom": total_len,
                            "absolute_error_m": verdict["absolute_error_m"],
                            "relative_error": verdict["relative_error"],
                            "abs_threshold_m": verdict["abs_threshold_m"],
                            "rel_threshold": verdict["rel_threshold"],
                        },
                    )
                )

        return issues

    @staticmethod
    def _check_primitive_coeffs(
        rid: str, idx: int, g: ET.Element, prim: str
    ) -> List[Issue]:
        """Validate required finite coefficients per primitive (§6)."""
        issues: List[Issue] = []
        el = g.find(prim)
        if el is None:  # cannot happen after the exactly-one check; defensive
            issues.append(
                Issue("error", "geom_primitive_missing",
                      f"Primitive <{prim}> element not found.",
                      {"road": rid, "idx": idx})
            )
            return issues
        for attr in PRIMITIVE_REQUIRED_ATTRS.get(prim, ()):
            res = parse_required_float(el.get(attr))
            if not res.ok:
                issues.append(
                    _numeric_issue(
                        f"{prim}_{attr}", res, road=rid,
                        extra={"idx": idx, "primitive": prim},
                    )
                )
        if prim == "paramPoly3":
            prange = el.get("pRange", "arcLength")
            if prange not in PARAMPOLY3_PRANGE_SUPPORTED:
                issues.append(
                    Issue(
                        "error",
                        "paramPoly3_pRange_unsupported",
                        "paramPoly3 pRange must be one of "
                        f"{list(PARAMPOLY3_PRANGE_SUPPORTED)}.",
                        {"road": rid, "idx": idx, "pRange": el.get("pRange")},
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

        # Section end boundaries for width-interval evaluation (§12): next
        # section s, else road length when finite.
        sec_starts: List[Optional[float]] = []
        for sec in secs:
            res = parse_required_float(sec.get("s"))
            sec_starts.append(float(res.value) if res.ok else None)

        last_s = -1e9
        for idx, sec in enumerate(secs):
            s_res = parse_required_float(sec.get("s"))
            if not s_res.ok:
                issues.append(
                    _numeric_issue("laneSection_s", s_res, road=rid,
                                   extra={"idx": idx})
                )
                continue
            s = float(s_res.value)
            if idx == 0 and abs(s) > LANESECTION_FIRST_S_TOL_M:
                issues.append(
                    Issue(
                        "error",
                        "laneSection_first_s_not_zero",
                        "First laneSection s must be approximately 0.",
                        {"road": rid, "idx": idx, "s": s},
                    )
                )
            if s < 0.0:
                issues.append(
                    Issue(
                        "error",
                        "laneSection_s_negative",
                        "laneSection s must be >= 0.",
                        {"road": rid, "idx": idx, "s": s},
                    )
                )
            if s + GEOM_S_EPS < last_s:
                issues.append(
                    Issue(
                        "error",
                        "laneSection_s_not_monotonic",
                        "laneSection s must be monotonic.",
                        {"road": rid, "idx": idx, "s": s, "prev_s": last_s},
                    )
                )
            last_s = s

            if math.isfinite(road_length) and road_length > 0 and s > road_length + GEOM_S_EPS:
                issues.append(
                    Issue(
                        "error",
                        "laneSection_s_gt_length",
                        "laneSection s beyond road length.",
                        {"road": rid, "idx": idx, "s": s, "road_length": road_length},
                    )
                )

            # Lane identity rules (§11): no contiguity assumption.
            issues.extend(self._check_lane_ids(rid, idx, sec))

            if self.require_center_lane:
                center = sec.find("center")
                if center is None or center.find("lane[@id='0']") is None:
                    issues.append(
                        Issue(
                            "error",
                            "center_lane_missing",
                            "Center lane id=0 missing.",
                            {"road": rid, "idx": idx},
                        )
                    )

            # Width validity over each record's applicable interval (§12).
            if idx + 1 < len(secs) and sec_starts[idx + 1] is not None:
                section_end: Optional[float] = sec_starts[idx + 1]
            elif math.isfinite(road_length) and road_length > 0:
                section_end = road_length
            else:
                section_end = None
            for lane in sec.findall(".//lane"):
                if lane.get("type") == "driving":
                    issues.extend(
                        self._check_lane_widths(rid, idx, lane,
                                              section_s=s,
                                              section_end=section_end)
                    )

        return issues

    def _check_lane_ids(
        self, rid: str, idx: int, sec: ET.Element
    ) -> List[Issue]:
        """Lane identity rules (§11)."""
        issues: List[Issue] = []
        center_ids: List[str] = []
        side_ids: Dict[str, List[str]] = {"left": [], "right": []}
        for side_name in ("left", "center", "right"):
            side = sec.find(side_name)
            if side is None:
                continue
            for lane in side.findall("lane"):
                lid_res = parse_required_int(lane.get("id"))
                if not lid_res.ok:
                    issues.append(
                        _numeric_issue("lane_id", lid_res, road=rid,
                                       extra={"idx": idx, "side": side_name})
                    )
                    continue
                lid = str(int(lid_res.value))
                if side_name == "center":
                    center_ids.append(lid)
                else:
                    side_ids[side_name].append(lid)
                if lane.get("type") == "driving" and lid == "0":
                    issues.append(
                        Issue(
                            "error",
                            "driving_lane_id_zero",
                            "Driving lanes must not use ID 0.",
                            {"road": rid, "idx": idx, "side": side_name},
                        )
                    )
        if len(center_ids) != len(set(center_ids)) or center_ids.count("0") > 1:
            issues.append(
                Issue("error", "center_lane_not_unique",
                      "Center lane id=0 must be unique.",
                      {"road": rid, "idx": idx, "center_ids": center_ids})
            )
        for side_name, ids in side_ids.items():
            if len(ids) != len(set(ids)):
                issues.append(
                    Issue("error", "duplicate_lane_id",
                          f"Duplicate lane id within {side_name}.",
                          {"road": rid, "idx": idx, "side": side_name,
                           "ids": ids})
                )
        cross = set(side_ids["left"]) & set(side_ids["right"])
        if cross:
            issues.append(
                Issue("error", "duplicate_lane_id_across_sides",
                      "Lane id appears in both left and right.",
                      {"road": rid, "idx": idx,
                       "ids": sorted(cross)})
            )
        return issues

    def _check_lane_widths(
        self, rid: str, idx: int, lane: ET.Element,
        *, section_s: float, section_end: Optional[float],
    ) -> List[Issue]:
        """Width-polynomial validity over the applicable interval (§12).

        Evaluates a+b·ds+c·ds²+d·ds³ (analytic extrema + sampling) instead of
        checking only width@a. Reports negative/zero/nonfinite/implausibly
        large evaluated width.
        """
        issues: List[Issue] = []
        lid = lane.get("id", "?")
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
            return issues
        records = []
        for w in widths:
            coeffs = {}
            bad = False
            for attr in ("sOffset", "a", "b", "c", "d"):
                res = parse_required_float(w.get(attr))
                if not res.ok:
                    issues.append(
                        _numeric_issue(f"width_{attr}", res, road=rid,
                                       extra={"lane": lid, "laneSection": idx})
                    )
                    bad = True
                else:
                    coeffs[attr] = float(res.value)
            if not bad:
                records.append(coeffs)
        if not records:
            return issues
        records.sort(key=lambda r: r["sOffset"])
        for n, rec in enumerate(records):
            interval_start = section_s + rec["sOffset"]
            if n + 1 < len(records):
                interval_end = section_s + records[n + 1]["sOffset"]
            elif section_end is not None:
                interval_end = section_end
            else:
                interval_end = interval_start + 5.0
            # ds is relative to the width record's sOffset: [0, interval_len].
            interval_len = max(interval_end - interval_start, 0.0)
            verdict = width_extrema_over_interval(
                rec["a"], rec["b"], rec["c"], rec["d"],
                0.0, interval_len,
            )
            if not verdict.get("ok"):
                issues.append(
                    Issue("error", "lane_width_nonfinite",
                          "Lane-width polynomial evaluates nonfinite.",
                          {"road": rid, "lane": lid, "laneSection": idx})
                )
                continue
            wmin = float(verdict["min"])
            wmax = float(verdict["max"])
            ctx = {"road": rid, "lane": lid, "laneSection": idx,
                   "min": wmin, "max": wmax}
            if wmin < 0:
                issues.append(
                    Issue("error", "lane_width_negative",
                          "Lane-width polynomial goes negative over its interval.",
                          ctx)
                )
            elif wmin <= 0:
                issues.append(
                    Issue("error", "lane_width_zero",
                          "Lane-width polynomial reaches zero over its interval.",
                          ctx)
                )
            if wmax > self.max_lane_width or wmax > MAX_PLAUSIBLE_LANE_WIDTH_M:
                issues.append(
                    Issue("warn", "lane_width_implausibly_large",
                          "Lane-width polynomial exceeds plausibility ceiling.",
                          ctx)
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
            ctx = {"road": rid, "idx": idx}
            s_res = parse_required_float(e.get("s"))
            if not s_res.ok:
                issues.append(
                    _numeric_issue("elev_s", s_res, road=rid, extra=ctx)
                )
                continue
            s = float(s_res.value)
            coeffs: Dict[str, float] = {}
            coeffs_ok = True
            for attr in ("a", "b", "c", "d"):
                res = parse_required_float(e.get(attr))
                if not res.ok:
                    issues.append(
                        _numeric_issue(f"elev_{attr}", res, road=rid,
                                       extra=ctx)
                    )
                    coeffs_ok = False
                else:
                    coeffs[attr] = float(res.value)
            if s < 0.0:
                issues.append(
                    Issue(
                        "error",
                        "elev_s_negative",
                        "Elevation s must be >= 0.",
                        {"road": rid, "idx": idx, "s": s},
                    )
                )
            if s + GEOM_S_EPS < last_s:
                issues.append(
                    Issue(
                        "error",
                        "elev_s_not_monotonic",
                        "Elevation s must be monotonic.",
                        {"road": rid, "idx": idx, "s": s, "prev_s": last_s},
                    )
                )
            last_s = s

            if coeffs_ok and abs(coeffs["a"]) > self.max_abs_z:
                issues.append(
                    Issue(
                        "error",
                        "elev_a_invalid",
                        "Elevation a is invalid (huge).",
                        {"road": rid, "idx": idx, "a": e.get("a")},
                    )
                )

            if last_a is not None and coeffs_ok:
                if abs(coeffs["a"] - last_a) > self.max_elevation_jump_m:
                    issues.append(
                        Issue(
                            "warn",
                            "elev_jump",
                            "Large elevation discontinuity between consecutive entries.",
                            {"road": rid, "idx": idx, "prev_a": last_a,
                             "a": coeffs["a"]},
                        )
                    )
            if coeffs_ok:
                last_a = coeffs["a"]

        return issues

    @staticmethod
    def _check_junctions(root: ET.Element, road_ids: set[str]) -> List[Issue]:
        """Junction structural identity (§13).

        Unique junction IDs; per-junction unique connection IDs; existing
        incoming/connecting roads; contactPoint start/end (missing is an
        error -- the reference is otherwise ambiguous); connecting-road
        junction-attr agreement stays a warning (deep laneLink semantics
        belong to the topology task, which this validator must not shadow).
        """
        issues: List[Issue] = []
        seen_junctions: set[str] = set()
        for j in root.findall("junction"):
            raw_jid = j.get("id")
            if not raw_jid:
                issues.append(
                    Issue("error", "junction_missing_id",
                          "Junction is missing id.", {})
                )
                continue
            jid = raw_jid
            if jid in seen_junctions:
                issues.append(
                    Issue("error", "junction_duplicate_id",
                          "Duplicate junction id.", {"junction": jid})
                )
            seen_junctions.add(jid)
            seen_connections: set[str] = set()
            for c in j.findall("connection"):
                cid = c.get("id")
                if cid is not None:
                    if cid in seen_connections:
                        issues.append(
                            Issue("error", "junction_duplicate_connection_id",
                                  "Duplicate connection id within junction.",
                                  {"junction": jid, "connection": cid})
                        )
                    seen_connections.add(cid)
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
                if cp is None:
                    issues.append(
                        Issue(
                            "error",
                            "junction_contactPoint_missing",
                            "Junction connection missing contactPoint "
                            "(must be start/end).",
                            {"junction": jid},
                        )
                    )
                elif cp not in ("start", "end"):
                    issues.append(
                        Issue(
                            "error",
                            "junction_contactPoint_invalid",
                            "contactPoint must be start/end.",
                            {"junction": jid, "contactPoint": cp},
                        )
                    )

        return issues
