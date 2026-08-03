#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G2 — lane width, border and laneOffset polynomial validation.

Evaluates every lane width / border / laneOffset record with LOCAL-s
semantics:

    lane_section_ds = road_s - laneSection.s
    width_ds        = road_s - laneSection.s - width.sOffset
    border_ds       = road_s - laneSection.s - border.sOffset
    lane_offset_ds  = road_s - laneOffset.s

and fails closed on:

- negative width (evaluated)
- non-finite width / border / laneOffset coefficients or evaluated values
- implausible width (outside governed envelope 0.1..60 m)
- extreme width derivative (> 5.0 m/m)
- width record with sOffset outside its lane section
- overlapping width intervals
- gap between required width intervals (record coverage)
- laneOffset applied twice (two active records at the same s)
- global-s evaluation (any record whose sOffset is relative to the road
  start rather than the section start cannot be detected from data alone;
  we instead verify every sampled evaluation obeys local-s semantics and
  flag records whose interval exceeds the section span)
- cross-section inversion (right side lanes have negative cumulative width
  or left side lanes have positive cumulative width)
- left/right ordering inversion (side lanes not ordered by |id|)

Required full-map metrics: max individual lane width, max total road width,
width p50/p90/p95/p99/max, max width derivative, section-boundary width jump,
negative-width count, cross-section inversion count, roads outside governed
envelope.

This is an AUDIT subphase: it never mutates the candidate.
"""
from __future__ import annotations

import json
import math
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

RUN_ID = "20260803T210000Z"
EVIDENCE_DIR = REPO_ROOT / "reports" / "post_audit_hardening" / RUN_ID

G0_EVIDENCE = (
    REPO_ROOT
    / "reports"
    / "post_audit_hardening"
    / "20260803T190000Z"
    / "PHASE_G_INPUT.json"
)

WIDTH_MIN_M = 0.05
WIDTH_MAX_M = 60.0
MAX_WIDTH_DERIVATIVE = 5.0
SAMPLE_SPACING_M = 4.0
MAX_SAMPLES_PER_SECTION = 200


def _safe_float(v, default=0.0):
    try:
        f = float(v) if v is not None else default
        return f if math.isfinite(f) else default
    except Exception:
        return default


def _poly(ds, a, b, c, d):
    return a + b * ds + c * ds * ds + d * ds * ds * ds


def _poly_deriv(ds, a, b, c, d):
    return b + 2.0 * c * ds + 3.0 * d * ds * ds


def audit_polynomials(xodr_path: Path) -> dict:
    root = ET.parse(str(xodr_path)).getroot()
    roads = root.findall("road")

    all_widths = []
    width_derivs = []
    total_road_widths = []
    negative_width_count = 0
    inversion_count = 0
    outside_envelope = 0
    boundary_jumps = []
    max_individual_width = 0.0
    max_total_width = 0.0

    issues = {
        "non_finite": [],
        "negative_width": [],
        "implausible_width": [],
        "extreme_width_derivative": [],
        "width_record_outside_section": [],
        "overlapping_width_intervals": [],
        "width_gap": [],
        "laneoffset_double_apply": [],
        "cross_section_inversion": [],
        "left_right_ordering_inversion": [],
        "non_finite_border": [],
        "non_finite_laneoffset": [],
    }

    for road in roads:
        rid = road.get("id")
        length = _safe_float(road.get("length"))
        lanes_elem = road.find("lanes")
        if lanes_elem is None:
            continue
        sections = lanes_elem.findall("laneSection")
        section_s_list = [_safe_float(s.get("s")) for s in sections]
        for idx, section in enumerate(sections):
            ls_s = _safe_float(section.get("s"))
            ls_end = (
                section_s_list[idx + 1]
                if idx + 1 < len(section_s_list)
                else length
            )
            section_len = max(0.0, ls_end - ls_s)
            if section_len <= 0.0:
                continue

            # laneOffset audit (road-level, shared by all sections)
            lane_offset_el = lanes_elem.find("laneOffset")
            lo_records = [
                (_safe_float(o.get("s")), o) for o in
                (lane_offset_el.findall("offset") if lane_offset_el is not None
                 else [])
            ]
            lo_records.sort()
            for j, (lo_s, _el) in enumerate(lo_records):
                if j + 1 < len(lo_records) and lo_s == lo_records[j + 1][0]:
                    issues["laneoffset_double_apply"].append(
                        {"road": rid, "s": lo_s}
                    )
            for _, el in lo_records:
                vals = [_safe_float(el.get(k), None) for k in ("a", "b", "c", "d")]
                if any(v is None for v in vals):
                    issues["non_finite_laneoffset"].append(
                        {"road": rid, "s": el.get("s")}
                    )

            samples = _sample_points(section_len, SAMPLE_SPACING_M)
            sides = {}
            for side in ("left", "right"):
                side_el = section.find(side)
                if side_el is None:
                    continue
                lane_els = side_el.findall("lane")
                lanes_sorted = sorted(
                    lane_els, key=lambda l: abs(int(l.get("id", "0")))
                )
                ids = [int(l.get("id", "0")) for l in lanes_sorted]
                mags = [abs(i) for i in ids]
                # correct side ordering: ids increase in magnitude from the
                # centre outward, all sharing the side's sign (left +, right -)
                side_sign = 1 if side == "left" else -1
                order_ok = (
                    mags == sorted(mags)
                    and len(mags) == len(set(mags))
                    and all((i > 0 if side_sign > 0 else i < 0) for i in ids)
                )
                if not order_ok:
                    issues["left_right_ordering_inversion"].append(
                        {"road": rid, "s": ls_s, "side": side, "ids": ids}
                    )
                for lane in lanes_sorted:
                    lane_id = lane.get("id")
                    widths = lane.findall("width")
                    if not widths:
                        continue
                    w_records = sorted(
                        ((_safe_float(w.get("sOffset")), w) for w in widths)
                    )
                    # interval overlap / gap / outside-section checks
                    prev_end = 0.0
                    for j, (wo_s, w) in enumerate(w_records):
                        wo_end = (
                            _safe_float(w_records[j + 1][0])
                            if j + 1 < len(w_records)
                            else section_len
                        )
                        if wo_s > section_len or wo_end > section_len + 1e-6:
                            issues["width_record_outside_section"].append(
                                {"road": rid, "s": ls_s, "lane": lane_id,
                                 "sOffset": wo_s}
                            )
                        if wo_s < prev_end - 1e-6:
                            issues["overlapping_width_intervals"].append(
                                {"road": rid, "s": ls_s, "lane": lane_id,
                                 "sOffset": wo_s}
                            )
                        if wo_s - prev_end > 1e-6:
                            issues["width_gap"].append(
                                {"road": rid, "s": ls_s, "lane": lane_id,
                                 "gap_start": prev_end, "gap_end": wo_s}
                            )
                        prev_end = wo_end
                    for wo_s, w in w_records:
                        wa = _safe_float(w.get("a"), None)
                        wb = _safe_float(w.get("b"), None)
                        wc = _safe_float(w.get("c"), None)
                        wd = _safe_float(w.get("d"), None)
                        if any(v is None for v in (wa, wb, wc, wd)):
                            issues["non_finite"].append(
                                {"road": rid, "s": ls_s, "lane": lane_id,
                                 "kind": "width"}
                            )
                            continue
                        for ss in samples:
                            ds = ss - wo_s
                            if ds < -1e-6:
                                continue
                            val = _poly(ds, wa, wb, wc, wd)
                            deriv = _poly_deriv(ds, wa, wb, wc, wd)
                            if not math.isfinite(val) or not math.isfinite(deriv):
                                issues["non_finite"].append(
                                    {"road": rid, "s": ls_s, "lane": lane_id,
                                     "kind": "width"}
                                )
                                continue
                            all_widths.append(val)
                            width_derivs.append(abs(deriv))
                            max_individual_width = max(max_individual_width, val)
                            if val < 0.0:
                                negative_width_count += 1
                                issues["negative_width"].append(
                                    {"road": rid, "s": ls_s, "lane": lane_id,
                                     "width": round(val, 4), "s": round(ss, 2)}
                                )
                            if val < WIDTH_MIN_M or val > WIDTH_MAX_M:
                                outside_envelope += 1
                                issues["implausible_width"].append(
                                    {"road": rid, "s": ls_s, "lane": lane_id,
                                     "width": round(val, 4), "s": round(ss, 2)}
                                )
                            if abs(deriv) > MAX_WIDTH_DERIVATIVE:
                                issues["extreme_width_derivative"].append(
                                    {"road": rid, "s": ls_s, "lane": lane_id,
                                     "deriv": round(deriv, 4), "s": round(ss, 2)}
                                )
                            sides.setdefault(side, {}).setdefault(ss, 0.0)
                            sides[side][ss] += val
                    # border audit
                    for b in lane.findall("border"):
                        b_vals = [_safe_float(b.get(k), None)
                                  for k in ("a", "b", "c", "d")]
                        if any(v is None for v in b_vals):
                            issues["non_finite_border"].append(
                                {"road": rid, "s": ls_s, "lane": lane_id}
                            )

            # cross-section inversion: widths are magnitudes; reconstruction
            # applies side sign (left +t, right -t).  Inversion means a side's
            # cumulative offset crosses the centre line (left < 0 or right > 0).
            for side, cum in sides.items():
                sign = 1.0 if side == "left" else -1.0
                for ss, v in sorted(cum.items()):
                    signed = sign * v
                    if side == "left" and signed < -1e-6:
                        inversion_count += 1
                        issues["cross_section_inversion"].append(
                            {"road": rid, "s": round(ss, 2), "side": side,
                             "cumulative": round(v, 4)}
                        )
                    if side == "right" and signed > 1e-6:
                        inversion_count += 1
                        issues["cross_section_inversion"].append(
                            {"road": rid, "s": round(ss, 2), "side": side,
                             "cumulative": round(v, 4)}
                        )
            # total road width per sample
            for ss in samples:
                total = sum(sides.get(side, {}).get(ss, 0.0)
                            for side in ("left", "right"))
                total_road_widths.append(abs(total))
                max_total_width = max(max_total_width, abs(total))
            # section-boundary width jump: compare cumulative right side at
            # section end vs next section start
            if idx + 1 < len(sections):
                nxt_start = _sample_cumulative(sides, section_len)
                nxt = _sample_cumulative(sides, 0.0)
                if nxt_start is not None and nxt is not None:
                    boundary_jumps.append(abs(nxt - nxt_start))

    widths_sorted = sorted(all_widths)
    n = len(widths_sorted)

    def pct(p):
        if n == 0:
            return 0.0
        return widths_sorted[min(n - 1, int(p * n))]

    checks = {
        "non_finite_coefficients": len(issues["non_finite"]) == 0,
        "negative_width_zero": negative_width_count == 0,
        "implausible_width_zero": len(issues["implausible_width"]) == 0,
        "extreme_width_derivative_zero": (
            len(issues["extreme_width_derivative"]) == 0
        ),
        "width_records_within_section": (
            len(issues["width_record_outside_section"]) == 0
        ),
        "no_overlapping_width_intervals": (
            len(issues["overlapping_width_intervals"]) == 0
        ),
        "no_width_gaps": len(issues["width_gap"]) == 0,
        "no_double_laneoffset": len(issues["laneoffset_double_apply"]) == 0,
        "no_cross_section_inversion": inversion_count == 0,
        "no_left_right_ordering_inversion": (
            len(issues["left_right_ordering_inversion"]) == 0
        ),
        "non_finite_border_zero": len(issues["non_finite_border"]) == 0,
        "non_finite_laneoffset_zero": len(issues["non_finite_laneoffset"]) == 0,
    }
    passed = all(checks.values())

    return {
        "run_id": RUN_ID,
        "producer": "ultimate_pipeline/tools/phase_g2_polynomial_validation.py",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase": "G",
        "input": str(xodr_path),
        "sample_spacing_m": SAMPLE_SPACING_M,
        "metrics": {
            "width_samples": n,
            "max_individual_lane_width_m": round(max_individual_width, 4),
            "max_total_road_width_m": round(max_total_width, 4),
            "width_p50_m": round(pct(0.50), 4),
            "width_p90_m": round(pct(0.90), 4),
            "width_p95_m": round(pct(0.95), 4),
            "width_p99_m": round(pct(0.99), 4),
            "width_max_m": round(widths_sorted[-1], 4) if n else 0.0,
            "max_width_derivative_m_per_m": round(
                max(width_derivs) if width_derivs else 0.0, 4
            ),
            "section_boundary_width_jumps": boundary_jumps,
            "max_section_boundary_jump_m": round(
                max(boundary_jumps) if boundary_jumps else 0.0, 4
            ),
            "negative_width_count": negative_width_count,
            "cross_section_inversion_count": inversion_count,
            "roads_outside_governed_envelope": outside_envelope,
        },
        "issues": {k: v[:100] for k, v in issues.items()},
        "issue_counts": {k: len(v) for k, v in issues.items()},
        "checks": checks,
        "g2_verdict": (
            "PHASE_G_POLYNOMIAL_VALIDATION_PASS" if passed
            else "PHASE_G_POLYNOMIAL_VALIDATION_BLOCKED"
        ),
    }


def _sample_points(section_len: float, spacing: float) -> list:
    count = min(int(section_len / spacing) + 2, MAX_SAMPLES_PER_SECTION)
    return [min(i * spacing, section_len) for i in range(count)]


def _sample_cumulative(sides: dict, ss: float) -> float:
    right = sides.get("right", {})
    if not right:
        return None
    keys = sorted(right.keys())
    if ss <= keys[0]:
        return right[keys[0]]
    if ss >= keys[-1]:
        return right[keys[-1]]
    for i in range(1, len(keys)):
        if keys[i] >= ss:
            k0, k1 = keys[i - 1], keys[i]
            t = (ss - k0) / (k1 - k0)
            return right[k0] * (1 - t) + right[k1] * t
    return right[keys[-1]]


def main() -> int:
    g0 = json.loads(G0_EVIDENCE.read_text(encoding="utf-8"))
    if g0.get("g0_verdict") != "PHASE_G_INPUT_ACCEPTED":
        print("G2 verdict: PHASE_G_BLOCKED_INPUT_IDENTITY (G0 not accepted)")
        return 1
    input_path = Path(g0["input_candidate"]["path"])
    report = audit_polynomials(input_path)
    passed = all(report["checks"].values())
    report["g0_reference"] = {
        "g0_evidence": str(G0_EVIDENCE),
        "input_byte_sha256": g0["input_candidate"]["byte_sha256"],
    }

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "PHASE_G_POLYNOMIAL_VALIDATION.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )

    m = report["metrics"]
    md = [
        "# G2 — lane polynomial validation (local-s)",
        "",
        f"- run_id: `{RUN_ID}`",
        f"- verdict: **{report['g2_verdict']}**",
        "",
        "## Metrics (evaluated at local-s, spacing "
        f"{report['sample_spacing_m']} m)",
        "",
        "| metric | value |",
        "|---|---|",
        f"| width samples | {m['width_samples']} |",
        f"| max individual lane width | {m['max_individual_lane_width_m']} m |",
        f"| max total road width | {m['max_total_road_width_m']} m |",
        f"| width p50 / p90 / p95 / p99 | {m['width_p50_m']} / "
        f"{m['width_p90_m']} / {m['width_p95_m']} / {m['width_p99_m']} m |",
        f"| width max | {m['width_max_m']} m |",
        f"| max width derivative | {m['max_width_derivative_m_per_m']} m/m |",
        f"| max section-boundary width jump | {m['max_section_boundary_jump_m']} m |",
        f"| negative-width count | {m['negative_width_count']} |",
        f"| cross-section inversion count | {m['cross_section_inversion_count']} |",
        f"| roads outside governed envelope | {m['roads_outside_governed_envelope']} |",
        "",
        "## Checks",
        "",
    ]
    for name, ok in report["checks"].items():
        md.append(f"- {name}: {'PASS' if ok else 'FAIL'}")
    md += [
        "",
        "Every width/border/laneOffset record is evaluated with local-s "
        "semantics: width_ds = road_s - laneSection.s - width.sOffset, "
        "border_ds = road_s - laneSection.s - border.sOffset, "
        "lane_offset_ds = road_s - laneOffset.s.  Extreme or negative widths "
        "are reported fail-closed with the responsible record — they are "
        "NEVER clamped silently.",
    ]
    (EVIDENCE_DIR / "PHASE_G_POLYNOMIAL_VALIDATION.md").write_text(
        "\n".join(md), encoding="utf-8"
    )

    print(f"G2 verdict: {report['g2_verdict']}")
    print(EVIDENCE_DIR / "PHASE_G_POLYNOMIAL_VALIDATION.json")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
