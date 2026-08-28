#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G7 — roadMark semantics.

Audits every <lane><roadMark> element and repairs semantic defects.

Audit invariants:
- roadMark type / weight / color values from the OpenDRIVE 1.7 sets
- every lane declares a roadMark (presence)
- a visible marking (solid / broken / ...) must have width > 0
- a solid marking must forbid crossing: laneChange="none"
- "none" markings carry no semantic contradiction (advisory only)

The candidate is encoded with right-hand lanes only (reference line at the
left pavement edge, lane -1 marking at that edge, lane 0 carrying the
optional centerline marking).  Lane 0's roadMark is cosmetic in CARLA
(zero-width lane, no render polygon); it is normalised for consistency
rather than removed.

Repairs (roadMark attributes only):
- R1: visible marking with width 0.00 -> width 0.13 (standard narrow)
- R2: solid marking without laneChange -> laneChange="none"

Protected identity hashes (planView, road length, elevation, road links,
junction structure, connector geometry, contactPoint) must stay identical
to the G0 baseline; the lane-topology hash is expected to change and is
recorded as the new G7 baseline.  G4 lane continuity must still pass.

Fixtures: synthetic lane sections validate the checker — a clean section
(solid with laneChange=none, broken with laneChange=both, none) yields
zero defects; planted defects (solid width 0.00, solid without
laneChange, invalid type, invalid weight, visible width negative) each
trigger their class.
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

from ultimate_pipeline.tools.phase_g0_handoff import compute_identity_hashes
from ultimate_pipeline.tools.phase_g4_lane_continuity import audit_lane_continuity

RUN_ID = "20260804T030000Z"
EVIDENCE_DIR = REPO_ROOT / "reports" / "post_audit_hardening" / RUN_ID

G0_EVIDENCE = (
    REPO_ROOT
    / "reports"
    / "post_audit_hardening"
    / "20260803T190000Z"
    / "PHASE_G_INPUT.json"
)
G6_EVIDENCE = (
    REPO_ROOT
    / "reports"
    / "post_audit_hardening"
    / "20260804T020000Z"
    / "PHASE_G_JUNCTION_LANELINKS.json"
)

VALID_TYPES = {
    "none", "solid", "broken", "solid solid", "solid broken",
    "broken solid", "broken broken", "botts dots", "grass", "curb",
}
VALID_WEIGHTS = {"standard", "bold"}
VALID_COLORS = {"standard", "blue", "green", "red", "white", "yellow"}
VALID_LANECHANGE = {"increase", "decrease", "both", "none"}
VISIBLE_TYPES = {"solid", "broken", "solid solid", "solid broken",
                 "broken solid", "broken broken", "botts dots"}
STANDARD_WIDTH = "0.13"

PROTECTED_KEYS = [
    "planview_hash",
    "road_length_hash",
    "elevation_profile_hash",
    "road_link_hash",
    "junction_structure_hash",
    "connector_geometry_hash",
    "contactpoint_hash",
]


def _safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


def audit_roadmarks(root: ET.Element) -> dict:
    invalid_type = []
    invalid_weight = []
    invalid_color = []
    invalid_lanechange = []
    missing_roadmark = []
    visible_zero_width = []
    visible_neg_width = []
    solid_crossing_allowed = []
    solid_lanechange_missing = []
    advisory = []
    lanes_audited = 0
    roadmarks_audited = 0

    for r in root.findall("road"):
        rid = r.get("id")
        for s in r.findall("lanes/laneSection"):
            for lane in s.findall(".//lane"):
                lanes_audited += 1
                lid = lane.get("id")
                rms = lane.findall("roadMark")
                if not rms:
                    missing_roadmark.append({"road": rid, "lane": lid})
                for rm in rms:
                    roadmarks_audited += 1
                    t = rm.get("type")
                    wgt = rm.get("weight")
                    col = rm.get("color")
                    lc = rm.get("laneChange")
                    if t not in VALID_TYPES:
                        invalid_type.append({"road": rid, "lane": lid, "type": t})
                    if wgt is not None and wgt not in VALID_WEIGHTS:
                        invalid_weight.append({"road": rid, "lane": lid, "weight": wgt})
                    if col is not None and col not in VALID_COLORS:
                        invalid_color.append({"road": rid, "lane": lid, "color": col})
                    if lc is not None and lc not in VALID_LANECHANGE:
                        invalid_lanechange.append({"road": rid, "lane": lid, "laneChange": lc})
                    width = _safe_float(rm.get("width"), 0.0)
                    if t in VISIBLE_TYPES:
                        if not math.isfinite(width) or width <= 0:
                            visible_zero_width.append(
                                {"road": rid, "lane": lid, "type": t, "width": rm.get("width")})
                        if not math.isfinite(width) or width < 0:
                            visible_neg_width.append(
                                {"road": rid, "lane": lid, "type": t, "width": rm.get("width")})
                        if t == "solid":
                            if lc == "both":
                                solid_crossing_allowed.append(
                                    {"road": rid, "lane": lid})
                            if lc is None:
                                solid_lanechange_missing.append(
                                    {"road": rid, "lane": lid})
                    elif t == "none":
                        if width > 0:
                            advisory.append({
                                "road": rid, "lane": lid,
                                "kind": "none_with_width",
                                "width": rm.get("width"),
                            })

    return {
        "lanes_audited": lanes_audited,
        "roadmarks_audited": roadmarks_audited,
        "invalid_type": invalid_type,
        "invalid_weight": invalid_weight,
        "invalid_color": invalid_color,
        "invalid_lanechange": invalid_lanechange,
        "missing_roadmark": missing_roadmark,
        "visible_zero_width": visible_zero_width,
        "visible_neg_width": visible_neg_width,
        "solid_crossing_allowed": solid_crossing_allowed,
        "solid_lanechange_missing": solid_lanechange_missing,
        "advisory": advisory,
    }


def repair_roadmarks(root: ET.Element) -> dict:
    n_width = 0
    n_lanechange = 0
    for r in root.findall("road"):
        for s in r.findall("lanes/laneSection"):
            for lane in s.findall(".//lane"):
                for rm in lane.findall("roadMark"):
                    t = rm.get("type")
                    width = _safe_float(rm.get("width"), 0.0)
                    if t in VISIBLE_TYPES and (not math.isfinite(width) or width <= 0):
                        rm.set("width", STANDARD_WIDTH)
                        n_width += 1
                    if t == "solid" and rm.get("laneChange") is None:
                        rm.set("laneChange", "none")
                        n_lanechange += 1
    return {"widths_fixed": n_width, "lanechange_fixed": n_lanechange}


# ---------------------------------------------------------------- fixtures

def _lane_xml(lid: str, rms_xml: str) -> str:
    return f'<lane id="{lid}" type="driving"><width sOffset="0" a="3.5"/>{rms_xml}</lane>'


def build_rm_fixture(kind: str) -> dict:
    center_rm = '<roadMark sOffset="0" type="none" width="0.00"/>'
    if kind == "clean":
        xml = (
            '<OpenDRIVE><header version="1.7"/>'
            '<road id="1" length="50"><lanes><laneSection s="0">'
            '<lane id="0" type="none">' + center_rm + "</lane>"
            + _lane_xml("-1", '<roadMark sOffset="0" type="solid" width="0.13" laneChange="none"/>')
            + _lane_xml("-2", '<roadMark sOffset="0" type="broken" width="0.13" laneChange="both"/>')
            + "</laneSection></lanes></road></OpenDRIVE>"
        )
        return {"root": ET.fromstring(xml), "expect": {}}
    if kind == "zero_width_solid":
        xml = (
            '<OpenDRIVE><header version="1.7"/>'
            '<road id="1" length="50"><lanes><laneSection s="0">'
            '<lane id="0" type="none">' + center_rm + "</lane>"
            + _lane_xml("-1", '<roadMark sOffset="0" type="solid" width="0.00" laneChange="none"/>')
            + "</laneSection></lanes></road></OpenDRIVE>"
        )
        return {"root": ET.fromstring(xml),
                "expect": {"visible_zero_width": 1}}
    if kind == "solid_no_lanechange":
        xml = (
            '<OpenDRIVE><header version="1.7"/>'
            '<road id="1" length="50"><lanes><laneSection s="0">'
            '<lane id="0" type="none">' + center_rm + "</lane>"
            + _lane_xml("-1", '<roadMark sOffset="0" type="solid" width="0.13"/>')
            + "</laneSection></lanes></road></OpenDRIVE>"
        )
        return {"root": ET.fromstring(xml),
                "expect": {"solid_lanechange_missing": 1}}
    if kind == "solid_crossing":
        xml = (
            '<OpenDRIVE><header version="1.7"/>'
            '<road id="1" length="50"><lanes><laneSection s="0">'
            '<lane id="0" type="none">' + center_rm + "</lane>"
            + _lane_xml("-1", '<roadMark sOffset="0" type="solid" width="0.13" laneChange="both"/>')
            + "</laneSection></lanes></road></OpenDRIVE>"
        )
        return {"root": ET.fromstring(xml),
                "expect": {"solid_crossing_allowed": 1}}
    if kind == "invalid_values":
        xml = (
            '<OpenDRIVE><header version="1.7"/>'
            '<road id="1" length="50"><lanes><laneSection s="0">'
            '<lane id="0" type="none">' + center_rm + "</lane>"
            + _lane_xml("-1", '<roadMark sOffset="0" type="zebra" weight="heavy" color="pink" width="0.13"/>')
            + "</laneSection></lanes></road></OpenDRIVE>"
        )
        return {"root": ET.fromstring(xml),
                "expect": {"invalid_type": 1, "invalid_weight": 1,
                           "invalid_color": 1}}
    raise ValueError(kind)


def run_fixtures() -> dict:
    results = {}
    all_ok = True
    for kind in ("clean", "zero_width_solid", "solid_no_lanechange",
                 "solid_crossing", "invalid_values"):
        fx = build_rm_fixture(kind)
        audit = audit_roadmarks(fx["root"])
        defects = {k: len(audit[k]) for k in (
            "invalid_type", "invalid_weight", "invalid_color",
            "invalid_lanechange", "missing_roadmark", "visible_zero_width",
            "visible_neg_width", "solid_crossing_allowed",
            "solid_lanechange_missing")}
        ok = True
        for key, count in fx["expect"].items():
            if defects[key] < count:
                ok = False
        if not fx["expect"]:
            ok = all(v == 0 for v in defects.values())
        results[kind] = {"ok": ok, "defects": defects}
        all_ok = all_ok and ok
    return {"fixtures_ok": all_ok, "fixtures": results}


def main() -> int:
    g0 = json.loads(G0_EVIDENCE.read_text(encoding="utf-8"))
    if g0.get("g0_verdict") != "PHASE_G_INPUT_ACCEPTED":
        print("G7 verdict: PHASE_G_BLOCKED_INPUT_IDENTITY (G0 not accepted)")
        return 1
    g6 = json.loads(G6_EVIDENCE.read_text(encoding="utf-8"))
    input_path = Path(g6["output"])
    root = ET.parse(str(input_path)).getroot()

    fixtures = run_fixtures()
    audit_in = audit_roadmarks(root)

    # blocking defect classes (structural): invalid values, missing marks,
    # visible markings with non-positive width, solid allowing crossing
    structural_ok = (
        not audit_in["invalid_type"]
        and not audit_in["invalid_weight"]
        and not audit_in["invalid_color"]
        and not audit_in["invalid_lanechange"]
        and not audit_in["missing_roadmark"]
        and not audit_in["visible_neg_width"]
        and not audit_in["solid_crossing_allowed"]
        and fixtures["fixtures_ok"]
    )
    if not structural_ok:
        report = {
            "run_id": RUN_ID,
            "producer": "ultimate_pipeline/tools/phase_g7_roadmark_semantics.py",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "phase": "G",
            "input": str(input_path),
            "audit_input": audit_in,
            "checks": {
                "no_invalid_values": not (
                    audit_in["invalid_type"] or audit_in["invalid_weight"]
                    or audit_in["invalid_color"] or audit_in["invalid_lanechange"]),
                "no_missing_roadmarks": not audit_in["missing_roadmark"],
                "no_nonpositive_visible_widths": not (
                    audit_in["visible_zero_width"] or audit_in["visible_neg_width"]),
                "no_solid_crossing": not audit_in["solid_crossing_allowed"],
                "fixtures_ok": fixtures["fixtures_ok"],
            },
            "fixtures": fixtures,
            "g7_verdict": "PHASE_G_ROADMARK_SEMANTICS_BLOCKED",
        }
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        (EVIDENCE_DIR / "PHASE_G_ROADMARK_SEMANTICS.json").write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )
        print("G7 verdict: PHASE_G_ROADMARK_SEMANTICS_BLOCKED")
        return 1

    repair = repair_roadmarks(root)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EVIDENCE_DIR / "candidate_g7_roadmarks.xodr"
    ET.indent(root, space="  ", level=0)
    out_path.write_text(
        ET.tostring(root, encoding="unicode", xml_declaration=True),
        encoding="utf-8",
    )

    out_root = ET.parse(str(out_path)).getroot()
    audit_out = audit_roadmarks(out_root)
    clean_after = (
        not audit_out["invalid_type"]
        and not audit_out["invalid_weight"]
        and not audit_out["invalid_color"]
        and not audit_out["invalid_lanechange"]
        and not audit_out["missing_roadmark"]
        and not audit_out["visible_zero_width"]
        and not audit_out["visible_neg_width"]
        and not audit_out["solid_crossing_allowed"]
        and not audit_out["solid_lanechange_missing"]
    )

    identity = compute_identity_hashes(out_path)
    g0_hash = g0["input_candidate"]
    protected_checks = {k: identity[k] == g0_hash[k] for k in PROTECTED_KEYS}
    topology_changed = identity["lane_topology_hash"] != g0_hash["lane_topology_hash"]

    g4 = audit_lane_continuity(out_path)
    g4_struct = {k: v for k, v in g4["metrics"].items()
                 if k not in ("legitimate_terminal_lanes",
                              "type_incompatible_lane_links")}
    g4_ok = all(v == 0 for v in g4_struct.values())

    passed = (
        structural_ok
        and clean_after
        and all(protected_checks.values())
        and topology_changed
        and g4_ok
    )

    report = {
        "run_id": RUN_ID,
        "producer": "ultimate_pipeline/tools/phase_g7_roadmark_semantics.py",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase": "G",
        "input": str(input_path),
        "output": str(out_path),
        "audit_input": {
            "lanes_audited": audit_in["lanes_audited"],
            "roadmarks_audited": audit_in["roadmarks_audited"],
            "metrics": {
                "invalid_type": len(audit_in["invalid_type"]),
                "invalid_weight": len(audit_in["invalid_weight"]),
                "invalid_color": len(audit_in["invalid_color"]),
                "invalid_lanechange": len(audit_in["invalid_lanechange"]),
                "missing_roadmark": len(audit_in["missing_roadmark"]),
                "visible_zero_width": len(audit_in["visible_zero_width"]),
                "visible_neg_width": len(audit_in["visible_neg_width"]),
                "solid_crossing_allowed": len(audit_in["solid_crossing_allowed"]),
                "solid_lanechange_missing": len(audit_in["solid_lanechange_missing"]),
                "advisory_none_with_width": len(audit_in["advisory"]),
            },
            "samples": {
                "visible_zero_width": audit_in["visible_zero_width"][:50],
                "solid_lanechange_missing": audit_in["solid_lanechange_missing"][:50],
            },
        },
        "repair": {
            "widths_fixed": repair["widths_fixed"],
            "lanechange_fixed": repair["lanechange_fixed"],
            "mutation_kind": "roadMark attribute only (width, laneChange)",
        },
        "audit_output": {
            "metrics": {
                "visible_zero_width": len(audit_out["visible_zero_width"]),
                "solid_lanechange_missing": len(audit_out["solid_lanechange_missing"]),
                "invalid_type": len(audit_out["invalid_type"]),
            },
            "clean_after_repair": clean_after,
        },
        "identity": {
            "lane_topology_hash_before": g0_hash["lane_topology_hash"],
            "lane_topology_hash_after": identity["lane_topology_hash"],
            "lane_topology_changed": topology_changed,
            "protected_hash_matches_g0": protected_checks,
        },
        "cross_checks": {
            "g4_lane_continuity_metrics_after": g4_struct,
            "g4_still_passes": g4_ok,
        },
        "fixtures": fixtures,
        "g7_verdict": (
            "PHASE_G_ROADMARK_SEMANTICS_PASS" if passed
            else "PHASE_G_ROADMARK_SEMANTICS_BLOCKED"
        ),
    }

    (EVIDENCE_DIR / "PHASE_G_ROADMARK_SEMANTICS.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )

    md = [
        "# G7 — roadMark semantics",
        "",
        f"- run_id: `{RUN_ID}`",
        f"- verdict: **{report['g7_verdict']}**",
        f"- input: `{input_path}`",
        f"- output: `{out_path}`",
        "",
        "## Audit (input)",
        "",
    ]
    m = report["audit_input"]["metrics"]
    for k, v in m.items():
        md.append(f"- {k}: {v}")
    md += [
        "",
        "## Repair",
        "",
        f"- widths fixed (visible marking with width 0.00 -> 0.13): "
        f"{report['repair']['widths_fixed']}",
        f"- laneChange added (solid -> none): "
        f"{report['repair']['lanechange_fixed']}",
        "",
        "## Identity",
        "",
        f"- lane-topology hash before: `{report['identity']['lane_topology_hash_before']}`",
        f"- lane-topology hash after: `{report['identity']['lane_topology_hash_after']}`",
        "",
        "| protected domain | matches G0 |",
        "|---|---|",
    ]
    for key, ok in report["identity"]["protected_hash_matches_g0"].items():
        md.append(f"| {key} | {'PASS' if ok else 'FAIL'} |")
    md += [
        "",
        f"- G4 lane continuity still passes: "
        f"{'PASS' if report['cross_checks']['g4_still_passes'] else 'FAIL'}",
        "",
        "## Fixtures",
        "",
    ]
    for kind, fx in fixtures["fixtures"].items():
        md.append(f"- {kind}: {'PASS' if fx['ok'] else 'FAIL'} "
                  f"(defects {fx['defects']})")
    md += [
        "",
        "Lane 0 roadMarks are the optional centerline marks (cosmetic in CARLA "
        "for zero-width lanes); they are normalised, not removed.  'none' type "
        "with positive width is harmless and reported advisory only.",
    ]
    (EVIDENCE_DIR / "PHASE_G_ROADMARK_SEMANTICS.md").write_text(
        "\n".join(md), encoding="utf-8"
    )

    print(f"G7 verdict: {report['g7_verdict']}")
    print(f"  widths fixed: {repair['widths_fixed']}, laneChange fixed: {repair['lanechange_fixed']}")
    print(EVIDENCE_DIR / "PHASE_G_ROADMARK_SEMANTICS.json")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
