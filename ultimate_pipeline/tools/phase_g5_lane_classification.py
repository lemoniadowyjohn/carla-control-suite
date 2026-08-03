#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G5 — side-lane classification.

Audits lane type semantics and reclassifies lanes whose declared type
contradicts their geometric and topological context.

Audit invariants:
- lane types are from the OpenDRIVE 1.7 set
- walk-side lanes (sidewalk/border/curb/median) are always outermost:
  |id| of a walk-side lane >= |id| of every driving lane in the section
- lane width plausibility per declared type
- at most one walk-side lane per side per section

Reclassification rule (evidence-driven):
a lane declared `restricted` is reclassified to `driving` when ALL of:
- its width lies in the driving band [2.5, 6.0] m
- it is the innermost side lane (|id| == 1)
- it is connected to driving traffic at the same position: an explicit
  lane link (predecessor/successor) to a driving lane, a junction
  connection that maps a driving lane of the incoming road onto it, or a
  road-level link whose contacted section carries a driving lane there

Reclassification never touches geometry: only the `type` attribute of the
affected lanes changes.  Protected identity hashes (planView, road length,
elevation, road links, junction structure, connector geometry,
contactPoint) must stay identical to the G0 baseline; the lane-topology
hash is expected to change and is recorded as the new G5 baseline.

Cross-check: G4's type-incompatible lane-link advisory (7 links) must
resolve to 0 on the reclassified candidate.
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from ultimate_pipeline.tools.phase_g0_handoff import compute_identity_hashes
from ultimate_pipeline.tools.phase_g4_lane_continuity import audit_lane_continuity

RUN_ID = "20260804T000000Z"
EVIDENCE_DIR = REPO_ROOT / "reports" / "post_audit_hardening" / RUN_ID

G0_EVIDENCE = (
    REPO_ROOT
    / "reports"
    / "post_audit_hardening"
    / "20260803T190000Z"
    / "PHASE_G_INPUT.json"
)

VALID_LANE_TYPES = {
    "driving", "none", "restricted", "shoulder", "sidewalk", "biking",
    "border", "parking", "median", "curb", "stop", "special", "tram",
    "rail", "bidirectional",
}
WALK_SIDE = {"sidewalk", "border", "curb", "median"}
DRIVING_BAND = (2.5, 6.0)
WIDTH_BANDS = {
    "driving": (2.5, 6.0),
    "sidewalk": (1.0, 8.0),
    "border": (0.1, 1.0),
    "curb": (0.1, 0.8),
    "median": (0.5, 8.0),
    "shoulder": (0.3, 6.0),
    "biking": (0.8, 4.0),
    "parking": (1.5, 4.0),
}

PROTECTED = [
    "planview_hash",
    "road_length_hash",
    "elevation_profile_hash",
    "road_link_hash",
    "junction_structure_hash",
    "connector_geometry_hash",
    "contactpoint_hash",
]


def _width_average(lane: ET.Element) -> float:
    ws = []
    for w in lane.findall("width"):
        try:
            ws.append(float(w.get("a") or 0.0))
        except Exception:
            pass
    return (sum(ws) / len(ws)) if ws else 0.0


def audit_classification(root: ET.Element) -> dict:
    bad_types = []
    outer_viol = []
    width_viol = []
    multiple_walk = []
    restricted = []
    for r in root.findall("road"):
        rid = r.get("id")
        for s in r.findall("lanes/laneSection"):
            lanes = s.findall(".//lane")
            ids = [int(l.get("id")) for l in lanes]
            for lane in lanes:
                lt = lane.get("type")
                lid = int(lane.get("id"))
                if lt not in VALID_LANE_TYPES:
                    bad_types.append({"road": rid, "lane": lid, "type": lt})
                if lt in WALK_SIDE:
                    for other in lanes:
                        if (other.get("type") == "driving"
                                and abs(int(other.get("id"))) > abs(lid)):
                            outer_viol.append({
                                "road": rid,
                                "lane_section_s": s.get("s"),
                                "walk_lane": lid,
                                "driving_lane": other.get("id"),
                            })
                w = _width_average(lane)
                band = WIDTH_BANDS.get(lt)
                if band and not (band[0] <= w <= band[1]):
                    width_viol.append({
                        "road": rid, "lane": lid, "type": lt,
                        "width": w, "band": band,
                    })
                if lt == "restricted":
                    restricted.append({
                        "road": rid, "lane": lid,
                        "width": w, "section_s": s.get("s"),
                    })
            for side in (-1, 1):
                walk = [l for l in lanes
                        if l.get("type") in WALK_SIDE
                        and int(l.get("id")) * side > 0]
                if len(walk) > 1:
                    multiple_walk.append({
                        "road": rid, "section_s": s.get("s"), "side": side,
                        "walk_lanes": [int(l.get("id")) for l in walk],
                    })
    return {
        "invalid_lane_types": bad_types,
        "walk_lane_not_outermost": outer_viol,
        "width_band_violations": width_viol,
        "multiple_walk_side_lanes": multiple_walk,
        "restricted_lanes": restricted,
    }


def _driving_connection(root: ET.Element, rid: str, lid: int) -> bool:
    """True if a restricted lane at (rid, lid) touches driving traffic."""
    roads = {r.get("id"): r for r in root.findall("road")}
    r = roads[rid]
    # 1) explicit lane links to a driving lane
    for s in r.findall("lanes/laneSection"):
        for lane in s.findall(".//lane"):
            if int(lane.get("id")) != lid:
                continue
            link_el = lane.find("link")
            if link_el is None:
                continue
            for tag in ("predecessor", "successor"):
                for l in link_el.findall(tag):
                    tgt = l.get("id")
                    for s2 in r.findall("lanes/laneSection"):
                        for l2 in s2.findall(".//lane"):
                            if (int(l2.get("id")) == int(tgt)
                                    and l2.get("type") == "driving"):
                                return True
    # 2) junction connection maps a driving lane onto it
    if str(r.get("junction", "-1")) != "-1":
        for j in root.findall("junction"):
            for c in j.findall("connection"):
                if c.get("connectingRoad") != rid:
                    continue
                inc = roads.get(c.get("incomingRoad"))
                if inc is None:
                    continue
                for s in inc.findall("lanes/laneSection"):
                    for l in s.findall(".//lane"):
                        if (int(l.get("id")) == lid
                                and l.get("type") == "driving"):
                            return True
    # 2b) the road is an incoming road of a junction connection whose
    #     connecting road carries a driving lane at the same position
    else:
        for j in root.findall("junction"):
            for c in j.findall("connection"):
                if c.get("incomingRoad") != rid:
                    continue
                conn = roads.get(c.get("connectingRoad"))
                if conn is None:
                    continue
                secs = sorted(
                    conn.findall("lanes/laneSection"),
                    key=lambda x: float(x.get("s") or 0.0),
                )
                if not secs:
                    continue
                sec = secs[0] if c.get("contactPoint") == "start" else secs[-1]
                for l in sec.findall(".//lane"):
                    if (int(l.get("id")) == lid
                            and l.get("type") == "driving"):
                        return True
    # 3) road-level link: contacted section has driving lane at |id|
    link_el = r.find("link")
    if link_el is not None:
        for tag in ("predecessor", "successor"):
            el = link_el.find(tag)
            if el is None or el.get("elementType") != "road":
                continue
            other = roads.get(el.get("elementId"))
            if other is None:
                continue
            secs = sorted(
                other.findall("lanes/laneSection"),
                key=lambda x: float(x.get("s") or 0.0),
            )
            if not secs:
                continue
            sec = secs[0] if el.get("contactPoint") == "start" else secs[-1]
            for l in sec.findall(".//lane"):
                if (int(l.get("id")) == lid
                        and l.get("type") == "driving"):
                    return True
    return False


def main() -> int:
    g0 = json.loads(G0_EVIDENCE.read_text(encoding="utf-8"))
    if g0.get("g0_verdict") != "PHASE_G_INPUT_ACCEPTED":
        print("G5 verdict: PHASE_G_BLOCKED_INPUT_IDENTITY (G0 not accepted)")
        return 1
    input_path = Path(g0["input_candidate"]["path"])
    root = ET.parse(str(input_path)).getroot()

    audit = audit_classification(root)
    structural_ok = (
        not audit["invalid_lane_types"]
        and not audit["walk_lane_not_outermost"]
        and not audit["width_band_violations"]
        and not audit["multiple_walk_side_lanes"]
    )
    restricted = audit["restricted_lanes"]
    reclass = []
    reclass_issues = []
    for item in restricted:
        rid, lid, w = item["road"], item["lane"], item["width"]
        if (DRIVING_BAND[0] <= w <= DRIVING_BAND[1]
                and abs(lid) == 1
                and _driving_connection(root, rid, lid)):
            reclass.append((rid, lid))
        else:
            reclass_issues.append(item)

    if not structural_ok or reclass_issues:
        print("G5 verdict: PHASE_G_LANE_CLASSIFICATION_BLOCKED")
        return 1

    # mutate: reclassify restricted -> driving
    n_changed = 0
    for r in root.findall("road"):
        if r.get("id") not in [x[0] for x in reclass]:
            continue
        for s in r.findall("lanes/laneSection"):
            for lane in s.findall(".//lane"):
                if lane.get("type") == "restricted":
                    lane.set("type", "driving")
                    n_changed += 1

    ET.indent(root, space="  ", level=0)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EVIDENCE_DIR / "candidate_g5_lane_types.xodr"
    out_path.write_text(
        ET.tostring(root, encoding="unicode", xml_declaration=True),
        encoding="utf-8",
    )

    # identity: protected hashes must match G0; lane topology may change
    identity = compute_identity_hashes(out_path)
    g0_hash = g0["input_candidate"]
    protected_checks = {}
    for key in PROTECTED:
        ok = identity[key] == g0_hash[key]
        protected_checks[key] = ok
    topology_changed = identity["lane_topology_hash"] != g0_hash["lane_topology_hash"]

    # re-audit the output
    out_root = ET.parse(str(out_path)).getroot()
    out_audit = audit_classification(out_root)
    clean_after = (
        not out_audit["invalid_lane_types"]
        and not out_audit["walk_lane_not_outermost"]
        and not out_audit["width_band_violations"]
        and not out_audit["multiple_walk_side_lanes"]
        and len(out_audit["restricted_lanes"]) == 0
    )

    # cross-check: G4 advisory resolved
    g4 = audit_lane_continuity(out_path)
    g4_type_incompat = g4["metrics"]["type_incompatible_lane_links"]

    passed = (
        structural_ok
        and not reclass_issues
        and n_changed == len(reclass)
        and all(protected_checks.values())
        and topology_changed
        and clean_after
        and g4_type_incompat == 0
    )

    report = {
        "run_id": RUN_ID,
        "producer": "ultimate_pipeline/tools/phase_g5_lane_classification.py",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase": "G",
        "input": str(input_path),
        "output": str(out_path),
        "audit_input": {
            "restricted_lanes": audit["restricted_lanes"],
            "invalid_lane_types": audit["invalid_lane_types"],
            "walk_lane_not_outermost": audit["walk_lane_not_outermost"],
            "width_band_violations": audit["width_band_violations"],
            "multiple_walk_side_lanes": audit["multiple_walk_side_lanes"],
        },
        "reclassified_lanes": [{"road": r, "lane": l} for r, l in reclass],
        "reclass_issues": reclass_issues,
        "mutations": {
            "lanes_reclassified": n_changed,
            "mutation_kind": "type attribute only (restricted -> driving)",
        },
        "identity": {
            "lane_topology_hash_after": identity["lane_topology_hash"],
            "lane_topology_hash_before": g0_hash["lane_topology_hash"],
            "lane_topology_changed": topology_changed,
            "protected_hash_matches_g0": protected_checks,
        },
        "audit_output": {
            "restricted_lanes_after": out_audit["restricted_lanes"],
            "clean_after_reclassification": clean_after,
        },
        "cross_checks": {
            "g4_type_incompatible_links_after": g4_type_incompat,
        },
        "g5_verdict": (
            "PHASE_G_LANE_CLASSIFICATION_PASS" if passed
            else "PHASE_G_LANE_CLASSIFICATION_BLOCKED"
        ),
    }

    (EVIDENCE_DIR / "PHASE_G_LANE_CLASSIFICATION.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )

    md = [
        "# G5 — side-lane classification",
        "",
        f"- run_id: `{RUN_ID}`",
        f"- verdict: **{report['g5_verdict']}**",
        f"- input: `{input_path}`",
        f"- output: `{out_path}`",
        "",
        "## Audit (input)",
        "",
        f"- restricted lanes: {len(audit['restricted_lanes'])}",
        f"- invalid lane types: {len(audit['invalid_lane_types'])}",
        f"- walk-lane-not-outermost: {len(audit['walk_lane_not_outermost'])}",
        f"- width-band violations: {len(audit['width_band_violations'])}",
        f"- multiple walk-side lanes: {len(audit['multiple_walk_side_lanes'])}",
        "",
        "## Reclassification",
        "",
    ]
    for item in report["reclassified_lanes"]:
        md.append(f"- road {item['road']} lane {item['lane']}: `restricted` -> `driving`")
    md += [
        "",
        "Criteria: width in driving band [2.5, 6.0] m, innermost side lane "
        "(|id| == 1), and a driving connection at the same position (explicit "
        "lane link, junction connection from a driving incoming road, or "
        "road-level link with a driving contacted lane).  Only the `type` "
        "attribute changes; geometry is untouched.",
        "",
        "## Identity",
        "",
        f"- lane-topology hash before: `{g0_hash['lane_topology_hash']}`",
        f"- lane-topology hash after: `{identity['lane_topology_hash']}`",
        "",
        "| protected domain | matches G0 |",
        "|---|---|",
    ]
    for key, ok in protected_checks.items():
        md.append(f"| {key} | {'PASS' if ok else 'FAIL'} |")
    md += [
        "",
        f"- G4 type-incompatible lane links after: "
        f"{report['cross_checks']['g4_type_incompatible_links_after']} (was 7)",
    ]
    (EVIDENCE_DIR / "PHASE_G_LANE_CLASSIFICATION.md").write_text(
        "\n".join(md), encoding="utf-8"
    )

    print(f"G5 verdict: {report['g5_verdict']}")
    print(f"  reclassified: {n_changed} lanes -> driving")
    print(EVIDENCE_DIR / "PHASE_G_LANE_CLASSIFICATION.json")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
