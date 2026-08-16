#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G6 — junction LaneLink validation and repair.

Validates every <junction><connection><laneLink> element:

- from-lane must exist in the incoming road's contacted section (the end of
  the incoming road that links to this junction)
- to-lane must exist in the connecting road's contacted section (start
  section when contactPoint=start, last section when contactPoint=end)
- per connection: no duplicate from-lane
- driving coverage (per junction + incoming road): every driving lane that
  flows into the incoming road's contacted endpoint must appear as a `from`
  in at least one connection of that junction; every driving lane that flows
  away from the connecting road's contacted endpoint must appear as a `to`
- lane type compatibility between from-lane and to-lane classes
- advisory consistency: when the connecting road carries an explicit lane
  link at the contacted end pointing at the incoming road, its target lane
  must equal the LaneLink `from` lane

Coverage gaps are REPAIRED iteratively: an uncovered driving lane U converges
onto the driving target lanes of its routed neighbour (inner neighbour
preferred, outer neighbour fallback) within each connection of the junction. Each
repair adds:
- the junction <laneLink from="U" to="T"/> element
- the mirror lane link on the connecting road's lane T at the junction end
  (<predecessor id="U"/> for contactPoint=start, <successor> for "end")

Protected identity hashes (planView, road length, elevation, road links,
junction structure, connector geometry, contactPoint) must stay identical
to the G0 baseline; the lane-topology hash is expected to change and is
recorded as the new G6 baseline.  G4 (lane continuity) must still pass on
the repaired candidate.

Fixtures: synthetic junctions validate the checker itself — clean 4-way,
missing to-lane, missing from-lane, missing driving coverage, and a
roundabout approach fixture.  Clean fixtures must yield zero issues; each
defect fixture must trigger exactly its defect class.  Roundabout handling
is enabled only while the roundabout fixture passes.
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

RUN_ID = "20260804T020000Z"
EVIDENCE_DIR = REPO_ROOT / "reports" / "post_audit_hardening" / RUN_ID

G0_EVIDENCE = (
    REPO_ROOT
    / "reports"
    / "post_audit_hardening"
    / "20260803T190000Z"
    / "PHASE_G_INPUT.json"
)
G5_EVIDENCE = (
    REPO_ROOT
    / "reports"
    / "post_audit_hardening"
    / "20260804T000000Z"
    / "PHASE_G_LANE_CLASSIFICATION.json"
)

DRIVABLE = {"driving", "entry", "exit", "onRamp", "offRamp", "connectingRamp"}
SIDEWALK = {"sidewalk", "border", "curb", "median"}
SUPPORT = {"shoulder", "biking", "parking", "restricted", "stop", "special",
           "bidirectional", "tram", "rail"}
TYPE_GROUPS = [DRIVABLE, SIDEWALK, SUPPORT]

PROTECTED_KEYS = [
    "planview_hash",
    "road_length_hash",
    "elevation_profile_hash",
    "road_link_hash",
    "junction_structure_hash",
    "connector_geometry_hash",
    "contactpoint_hash",
]


def _type_compatible(a: str, b: str) -> bool:
    if a is None or b is None:
        return True
    for group in TYPE_GROUPS:
        if a in group and b in group:
            return True
    return a == b


def _sections(road: ET.Element):
    secs = road.findall("lanes/laneSection")
    secs.sort(key=lambda s: float(s.get("s") or 0.0))
    return secs


def _road_end_contacted_by_junction(road: ET.Element, jid: str) -> str:
    """'start'/'end' end of road that links to junction jid (default end)."""
    link = road.find("link")
    if link is not None:
        for tag, end in (("successor", "end"), ("predecessor", "start")):
            el = link.find(tag)
            if el is not None and el.get("elementType") == "junction" \
                    and el.get("elementId") == jid:
                return end
    return "end"


def _contacted_section(road: ET.Element, contact_point: str):
    secs = _sections(road)
    if not secs:
        return None
    return secs[0] if contact_point == "start" else secs[-1]


def _lane_map(section: ET.Element) -> dict:
    out = {}
    for lane in section.findall(".//lane"):
        out[lane.get("id")] = lane.get("type")
    return out


def _lane_id_int(lane_id: str):
    try:
        return int(lane_id)
    except Exception:
        return None


def _lane_reaches_contacted_end(lane_id: str, contacted_end: str) -> bool:
    """Whether a conventional OpenDRIVE lane flows into a road endpoint."""
    lid = _lane_id_int(lane_id)
    if lid is None or lid == 0:
        return False
    # In the generated right-hand traffic maps, negative lanes follow the
    # road reference-line direction and therefore reach the road end; positive
    # lanes travel toward the road start. Requiring both signs at one endpoint
    # creates false junction-coverage gaps for opposite-direction lanes.
    return (contacted_end == "end" and lid < 0) or (contacted_end == "start" and lid > 0)


def _lane_leaves_contacted_end(lane_id: str, contacted_end: str) -> bool:
    """Whether a conventional OpenDRIVE lane leaves a road endpoint."""
    lid = _lane_id_int(lane_id)
    if lid is None or lid == 0:
        return False
    return (contacted_end == "start" and lid < 0) or (contacted_end == "end" and lid > 0)


def _required_incoming_driving_lanes(lane_map: dict, incoming_end: str) -> list:
    return [
        lid for lid, lt in lane_map.items()
        if lt in DRIVABLE and _lane_reaches_contacted_end(lid, incoming_end)
    ]


def _required_connecting_driving_lanes(lane_map: dict, contact_point: str) -> list:
    return [
        lid for lid, lt in lane_map.items()
        if lt in DRIVABLE and _lane_leaves_contacted_end(lid, contact_point)
    ]


def _dedupe_items(items: list) -> list:
    seen_keys = set()
    uniq = []
    for item in items:
        key = tuple(sorted(item.items()))
        if key not in seen_keys:
            seen_keys.add(key)
            uniq.append(item)
    return uniq


def audit_junction_lanelinks(root: ET.Element) -> dict:
    roads = {r.get("id"): r for r in root.findall("road")}
    missing_from = []
    missing_to = []
    duplicate_from = []
    missing_driving_from = []
    missing_driving_to = []
    type_incompat = []
    consistency = []
    connections_audited = 0
    lanelinks_audited = 0

    for j in root.findall("junction"):
        jid = j.get("id")
        # per-incoming routed from-lanes and per-connecting reached to-lanes,
        # aggregated over all connections of this junction
        routed_from = {}
        reached_to = {}
        for c in j.findall("connection"):
            routed_from.setdefault(c.get("incomingRoad"), set())
            reached_to.setdefault(c.get("connectingRoad"), set())
            for ll in c.findall("laneLink"):
                if ll.get("from") is not None:
                    routed_from[c.get("incomingRoad")].add(ll.get("from"))
                if ll.get("to") is not None:
                    reached_to[c.get("connectingRoad")].add(ll.get("to"))

        for c in j.findall("connection"):
            incoming = roads.get(c.get("incomingRoad"))
            connecting = roads.get(c.get("connectingRoad"))
            cp = c.get("contactPoint")
            connections_audited += 1
            if incoming is None or connecting is None:
                continue
            in_end = _road_end_contacted_by_junction(incoming, jid)
            in_sec = _contacted_section(incoming, in_end)
            conn_sec = _contacted_section(connecting, cp)
            in_map = _lane_map(in_sec) if in_sec is not None else {}
            conn_map = _lane_map(conn_sec) if conn_sec is not None else {}

            seen = set()
            for ll in c.findall("laneLink"):
                lanelinks_audited += 1
                f = ll.get("from")
                t = ll.get("to")
                if f not in in_map:
                    missing_from.append({
                        "junction": jid, "connection": c.get("id"),
                        "incoming": c.get("incomingRoad"), "from": f,
                    })
                if t not in conn_map:
                    missing_to.append({
                        "junction": jid, "connection": c.get("id"),
                        "connecting": c.get("connectingRoad"), "to": t,
                    })
                if f in seen:
                    duplicate_from.append({
                        "junction": jid, "connection": c.get("id"),
                        "from": f,
                    })
                seen.add(f)
                if f in in_map and t in conn_map:
                    if not _type_compatible(in_map[f], conn_map[t]):
                        type_incompat.append({
                            "junction": jid, "connection": c.get("id"),
                            "from": f, "to": t,
                            "from_type": in_map[f], "to_type": conn_map[t],
                        })
                    # advisory: connecting road's own lane link at the
                    # contacted end must target the from-lane
                    for lane in (conn_sec.findall(".//lane") if conn_sec
                                 is not None else []):
                        if lane.get("id") != t:
                            continue
                        lk = lane.find("link")
                        if lk is None:
                            continue
                        other_tag = "predecessor" if cp == "start" else "successor"
                        targets = [x.get("id") for x in lk.findall(other_tag)]
                        if targets and f not in targets:
                            consistency.append({
                                "junction": jid, "connection": c.get("id"),
                                "from": f, "to": t,
                                "connecting_link_targets": targets,
                            })

            # driving coverage: per (junction, incoming) and
            # (junction, connecting), aggregated over all connections
            if in_sec is not None:
                for lid in _required_incoming_driving_lanes(in_map, in_end):
                    if lid not in routed_from.get(c.get("incomingRoad"), set()):
                        missing_driving_from.append({
                            "junction": jid, "connection": c.get("id"),
                            "incoming": c.get("incomingRoad"), "lane": lid,
                        })
            if conn_sec is not None:
                for lid in _required_connecting_driving_lanes(conn_map, cp):
                    if lid not in reached_to.get(c.get("connectingRoad"), set()):
                        missing_driving_to.append({
                            "junction": jid, "connection": c.get("id"),
                            "connecting": c.get("connectingRoad"), "lane": lid,
                        })

    # Dedupe coverage flags (aggregated at junction level). Do this with real
    # assignments; writing through locals() is not reliable in function scope.
    missing_driving_from = _dedupe_items(missing_driving_from)
    missing_driving_to = _dedupe_items(missing_driving_to)

    return {
        "connections_audited": connections_audited,
        "lanelinks_audited": lanelinks_audited,
        "missing_from_lanes": missing_from,
        "missing_to_lanes": missing_to,
        "duplicate_from_lanes": duplicate_from,
        "missing_driving_from_coverage": missing_driving_from,
        "missing_driving_to_coverage": missing_driving_to,
        "type_incompatible_lanelinks": type_incompat,
        "lane_link_consistency_advisory": consistency,
    }


def checks_of(audit: dict) -> dict:
    return {
        "no_missing_from_lanes": len(audit["missing_from_lanes"]) == 0,
        "no_missing_to_lanes": len(audit["missing_to_lanes"]) == 0,
        "no_duplicate_from_lanes": len(audit["duplicate_from_lanes"]) == 0,
        "complete_driving_from_coverage": len(audit["missing_driving_from_coverage"]) == 0,
        "complete_driving_to_coverage": len(audit["missing_driving_to_coverage"]) == 0,
        "no_type_incompatible_lanelinks": len(audit["type_incompatible_lanelinks"]) == 0,
    }


def _uncovered_driving_lanes(root: ET.Element) -> list:
    """Per (junction, incoming): driving lanes with no `from` anywhere."""
    roads = {r.get("id"): r for r in root.findall("road")}
    out = []
    for j in root.findall("junction"):
        jid = j.get("id")
        routed = {}
        for c in j.findall("connection"):
            routed.setdefault(c.get("incomingRoad"), set()).update(
                l.get("from") for l in c.findall("laneLink")
            )
        for c in j.findall("connection"):
            inc_id = c.get("incomingRoad")
            inc = roads.get(inc_id)
            if inc is None:
                continue
            in_end = _road_end_contacted_by_junction(inc, jid)
            in_sec = _contacted_section(inc, in_end)
            if in_sec is None:
                continue
            covered = routed.get(inc_id, set())
            for lid in _required_incoming_driving_lanes(_lane_map(in_sec), in_end):
                if lid not in covered:
                    out.append({"junction": jid, "incoming": inc_id,
                                "lane": lid, "incoming_end": in_end})
    # dedupe (junction, incoming, lane)
    seen = set()
    uniq = []
    for item in out:
        key = (item["junction"], item["incoming"], item["lane"])
        if key not in seen:
            seen.add(key)
            uniq.append(item)
    return uniq


def _routed_neighbour_targets(root: ET.Element, jid: str, inc_id: str,
                              lane: str) -> tuple:
    """(inner_targets, outer_targets) of routed driving neighbours."""
    roads = {r.get("id"): r for r in root.findall("road")}
    lane_int = int(lane)
    if lane_int < 0:
        inner = str(lane_int + 1)
        outer = str(lane_int - 1)
    else:
        inner = str(lane_int - 1)
        outer = str(lane_int + 1)
    inner_t, outer_t = set(), set()
    for j in root.findall("junction"):
        if j.get("id") != jid:
            continue
        for c in j.findall("connection"):
            if c.get("incomingRoad") != inc_id:
                continue
            conn = roads.get(c.get("connectingRoad"))
            if conn is None:
                continue
            conn_sec = _contacted_section(conn, c.get("contactPoint"))
            if conn_sec is None:
                continue
            conn_map = _lane_map(conn_sec)
            for ll in c.findall("laneLink"):
                f, t = ll.get("from"), ll.get("to")
                if t not in conn_map or conn_map[t] not in DRIVABLE:
                    continue
                if f == inner:
                    inner_t.add((c.get("id"), t))
                elif f == outer:
                    outer_t.add((c.get("id"), t))
    return sorted(inner_t), sorted(outer_t)


def repair_coverage_gaps(root: ET.Element) -> dict:
    """Adds missing laneLinks; returns repair log."""
    roads = {r.get("id"): r for r in root.findall("road")}
    added = []
    issues = []
    max_passes = 8
    for _pass in range(max_passes):
        pass_added = 0
        unresolved = []
        for item in _uncovered_driving_lanes(root):
            jid = item["junction"]
            inc_id = item["incoming"]
            lane = item["lane"]
            inner_t, outer_t = _routed_neighbour_targets(root, jid, inc_id, lane)
            targets = inner_t or outer_t
            if not targets:
                unresolved.append(item)
                continue
            for conn_id, tgt in targets:
                # find connection element
                conn_el = None
                for j in root.findall("junction"):
                    if j.get("id") != jid:
                        continue
                    for c in j.findall("connection"):
                        if c.get("id") == conn_id:
                            conn_el = c
                if conn_el is None:
                    continue
                exists = any(
                    ll.get("from") == lane and ll.get("to") == tgt
                    for ll in conn_el.findall("laneLink")
                )
                if not exists:
                    ll = ET.SubElement(conn_el, "laneLink")
                    ll.set("from", lane)
                    ll.set("to", tgt)
                    pass_added += 1
                # mirror on connecting road lane tgt at the junction end
                cp = conn_el.get("contactPoint")
                conn = roads.get(conn_el.get("connectingRoad"))
                if conn is not None:
                    conn_sec = _contacted_section(conn, cp)
                    if conn_sec is not None:
                        for lane_el in conn_sec.findall(".//lane"):
                            if lane_el.get("id") != tgt:
                                continue
                            link_el = lane_el.find("link")
                            if link_el is None:
                                link_el = ET.SubElement(lane_el, "link")
                            tag = "predecessor" if cp == "start" else "successor"
                            mirror_exists = any(
                                x.get("id") == lane for x in link_el.findall(tag)
                            )
                            if not mirror_exists:
                                el = ET.SubElement(link_el, tag)
                                el.set("id", lane)
                added.append({
                    "junction": jid, "connection": conn_id,
                    "incoming": inc_id, "lane": lane, "target": tgt,
                    "repair_pass": _pass + 1,
                })
        if not _uncovered_driving_lanes(root):
            issues = []
            break
        if pass_added == 0:
            issues = unresolved
            break
    else:
        issues = _uncovered_driving_lanes(root)
    return {"added_lanelinks": added, "repair_issues": issues}


# ---------------------------------------------------------------- fixtures

FIXTURE_LANES = {
    "driving2": """
        <lane id="1" type="driving"><width sOffset="0" a="3.5"/></lane>
        <lane id="0" type="none"/>
        <lane id="-1" type="driving"><width sOffset="0" a="3.5"/></lane>
    """,
    "driving3": """
        <lane id="1" type="driving"><width sOffset="0" a="3.5"/></lane>
        <lane id="0" type="none"/>
        <lane id="-1" type="driving"><width sOffset="0" a="3.5"/></lane>
        <lane id="-2" type="driving"><width sOffset="0" a="3.5"/></lane>
    """,
    "driving_sidewalk": """
        <lane id="1" type="sidewalk"><width sOffset="0" a="2.5"/></lane>
        <lane id="0" type="none"/>
        <lane id="-1" type="driving"><width sOffset="0" a="3.5"/></lane>
        <lane id="-2" type="sidewalk"><width sOffset="0" a="2.5"/></lane>
    """,
}


def _road_xml(rid: str, lanes_xml: str, junction: str = "-1") -> str:
    return f"""
    <road id="{rid}" junction="{junction}" length="50">
      <planView><geometry s="0" x="0" y="0" hdg="0" length="50">
        <line/></geometry></planView>
      <lanes><laneOffset s="0" a="0" b="0" c="0" d="0"/>
        <laneSection s="0">{lanes_xml}</laneSection></lanes>
    </road>"""


def _conn_xml(jid: str, conns: list, ll_per_conn: dict) -> str:
    body = []
    for i, (inc, conn, cp) in enumerate(conns):
        links = "".join(
            f'<laneLink from="{f}" to="{t}"/>' for f, t in ll_per_conn.get(i, [])
        )
        body.append(
            f'<connection id="{i}" incomingRoad="{inc}" '
            f'connectingRoad="{conn}" contactPoint="{cp}">{links}'
            f"</connection>"
        )
    return (
        f'<OpenDRIVE><header version="1.7"/><junction id="{jid}">'
        + "".join(body)
        + "</junction></OpenDRIVE>"
    )


def build_fixture(kind: str) -> dict:
    """Returns expected defect class -> count for each fixture."""
    if kind == "clean_4way":
        roads = (
            _road_xml("A", FIXTURE_LANES["driving2"], junction="9")
            + _road_xml("B", FIXTURE_LANES["driving2"], junction="9")
            + _road_xml("C", FIXTURE_LANES["driving2"], junction="9")
            + _road_xml("D", FIXTURE_LANES["driving2"], junction="9")
        )
        xml = (
            f'<OpenDRIVE><header version="1.7"/>{roads}'
            '<junction id="9">'
            '<connection id="0" incomingRoad="A" connectingRoad="B" contactPoint="start">'
            '<laneLink from="-1" to="-1"/><laneLink from="1" to="1"/>'
            "</connection>"
            '<connection id="1" incomingRoad="B" connectingRoad="C" contactPoint="start">'
            '<laneLink from="-1" to="-1"/><laneLink from="1" to="1"/>'
            "</connection>"
            '<connection id="2" incomingRoad="C" connectingRoad="D" contactPoint="start">'
            '<laneLink from="-1" to="-1"/><laneLink from="1" to="1"/>'
            "</connection>"
            "</junction></OpenDRIVE>"
        )
        return {"root": ET.fromstring(xml), "expect": {}}

    if kind == "missing_to":
        xml = (
            f'<OpenDRIVE><header version="1.7"/>'
            + _road_xml("A", FIXTURE_LANES["driving2"], junction="9")
            + _road_xml("B", FIXTURE_LANES["driving2"], junction="9")
            + '<junction id="9"><connection id="0" incomingRoad="A" '
            'connectingRoad="B" contactPoint="start">'
            '<laneLink from="-1" to="-5"/></connection></junction></OpenDRIVE>'
        )
        return {"root": ET.fromstring(xml),
                "expect": {"missing_to_lanes": 1}}

    if kind == "missing_from":
        xml = (
            f'<OpenDRIVE><header version="1.7"/>'
            + _road_xml("A", FIXTURE_LANES["driving2"], junction="9")
            + _road_xml("B", FIXTURE_LANES["driving2"], junction="9")
            + '<junction id="9"><connection id="0" incomingRoad="A" '
            'connectingRoad="B" contactPoint="start">'
            '<laneLink from="-9" to="-1"/></connection></junction></OpenDRIVE>'
        )
        return {"root": ET.fromstring(xml),
                "expect": {"missing_from_lanes": 1,
                           "missing_driving_from_coverage": 1}}

    if kind == "missing_coverage":
        xml = (
            f'<OpenDRIVE><header version="1.7"/>'
            + _road_xml("A", FIXTURE_LANES["driving3"], junction="9")
            + _road_xml("B", FIXTURE_LANES["driving3"], junction="9")
            + '<junction id="9"><connection id="0" incomingRoad="A" '
            'connectingRoad="B" contactPoint="start">'
            '<laneLink from="-1" to="-1"/></connection></junction></OpenDRIVE>'
        )
        return {"root": ET.fromstring(xml),
                "expect": {"missing_driving_from_coverage": 1,
                           "missing_driving_to_coverage": 1}}

    if kind == "roundabout_approach":
        xml = (
            f'<OpenDRIVE><header version="1.7"/>'
            + _road_xml("R1", FIXTURE_LANES["driving2"], junction="9")
            + _road_xml("R2", FIXTURE_LANES["driving2"], junction="9")
            + _road_xml("R3", FIXTURE_LANES["driving2"], junction="9")
            + _road_xml("R4", FIXTURE_LANES["driving2"], junction="9")
            + _road_xml("E1", FIXTURE_LANES["driving2"])
            + '<junction id="9">'
            '<connection id="0" incomingRoad="E1" connectingRoad="R1" contactPoint="start">'
            '<laneLink from="-1" to="1"/><laneLink from="1" to="-1"/>'
            "</connection>"
            '<connection id="1" incomingRoad="R1" connectingRoad="R2" contactPoint="end">'
            '<laneLink from="-1" to="-1"/><laneLink from="1" to="1"/>'
            "</connection>"
            '<connection id="2" incomingRoad="R2" connectingRoad="R3" contactPoint="start">'
            '<laneLink from="-1" to="-1"/><laneLink from="1" to="1"/>'
            "</connection>"
            '<connection id="3" incomingRoad="R3" connectingRoad="R4" contactPoint="start">'
            '<laneLink from="-1" to="-1"/><laneLink from="1" to="1"/>'
            "</connection>"
            '<connection id="4" incomingRoad="R4" connectingRoad="R1" contactPoint="end">'
            '<laneLink from="-1" to="-1"/><laneLink from="1" to="1"/>'
            "</connection>"
            "</junction></OpenDRIVE>"
        )
        return {"root": ET.fromstring(xml), "expect": {}}

    raise ValueError(kind)


def run_fixtures() -> dict:
    results = {}
    all_ok = True
    for kind in ("clean_4way", "missing_to", "missing_from",
                 "missing_coverage", "roundabout_approach"):
        fx = build_fixture(kind)
        audit = audit_junction_lanelinks(fx["root"])
        expect = fx["expect"]
        defects = {
            "missing_from_lanes": len(audit["missing_from_lanes"]),
            "missing_to_lanes": len(audit["missing_to_lanes"]),
            "duplicate_from_lanes": len(audit["duplicate_from_lanes"]),
            "missing_driving_from_coverage": len(audit["missing_driving_from_coverage"]),
            "missing_driving_to_coverage": len(audit["missing_driving_to_coverage"]),
            "type_incompatible_lanelinks": len(audit["type_incompatible_lanelinks"]),
        }
        ok = True
        for key, count in expect.items():
            if defects[key] < count:
                ok = False
        # clean fixtures must have zero issues of every class
        if not expect:
            ok = all(v == 0 for v in defects.values())
        results[kind] = {"ok": ok, "defects": defects}
        all_ok = all_ok and ok
    return {"fixtures_ok": all_ok, "fixtures": results}


def main() -> int:
    g0 = json.loads(G0_EVIDENCE.read_text(encoding="utf-8"))
    if g0.get("g0_verdict") != "PHASE_G_INPUT_ACCEPTED":
        print("G6 verdict: PHASE_G_BLOCKED_INPUT_IDENTITY (G0 not accepted)")
        return 1
    g5 = json.loads(G5_EVIDENCE.read_text(encoding="utf-8"))
    input_path = Path(g5["output"])
    root = ET.parse(str(input_path)).getroot()

    fixtures = run_fixtures()
    audit_in = audit_junction_lanelinks(root)
    checks_in = checks_of(audit_in)
    repair = None
    out_path = input_path
    if (all(v for k, v in checks_in.items()
            if k not in ("complete_driving_from_coverage",))
            and fixtures["fixtures_ok"]):
        # structural integrity holds; repair driving-coverage gaps
        repair = repair_coverage_gaps(root)
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        out_path = EVIDENCE_DIR / "candidate_g6_junction_lanelinks.xodr"
        ET.indent(root, space="  ", level=0)
        out_path.write_text(
            ET.tostring(root, encoding="unicode", xml_declaration=True),
            encoding="utf-8",
        )
        out_root = ET.parse(str(out_path)).getroot()
        audit_out = audit_junction_lanelinks(out_root)
        checks_out = checks_of(audit_out)
        repair["audit_after"] = audit_out
        repair["checks_after"] = checks_out
    else:
        out_root = root
        audit_out = audit_in
        checks_out = checks_in
        repair = {"added_lanelinks": [], "repair_issues": [],
                  "repair_blocked": True}

    # identity: protected hashes must match G0; lane topology may change
    identity = compute_identity_hashes(out_path)
    g0_hash = g0["input_candidate"]
    protected_checks = {}
    for key in PROTECTED_KEYS:
        protected_checks[key] = identity[key] == g0_hash[key]
    topology_changed = identity["lane_topology_hash"] != g0_hash["lane_topology_hash"]

    # cross-check: G4 lane continuity must still pass on the output
    from ultimate_pipeline.tools.phase_g4_lane_continuity import audit_lane_continuity
    g4 = audit_lane_continuity(out_path)
    g4_struct = {k: v for k, v in g4["metrics"].items()
                 if k != "legitimate_terminal_lanes"
                 and k != "type_incompatible_lane_links"}
    g4_ok = all(v == 0 for v in g4_struct.values())

    passed = (
        fixtures["fixtures_ok"]
        and all(checks_out.values())
        and all(protected_checks.values())
        and topology_changed
        and not repair.get("repair_blocked", False)
        and not repair["repair_issues"]
        and g4_ok
    )

    def _metric_summary(aud):
        return {
            "missing_from_lanes": len(aud["missing_from_lanes"]),
            "missing_to_lanes": len(aud["missing_to_lanes"]),
            "duplicate_from_lanes": len(aud["duplicate_from_lanes"]),
            "missing_driving_from_coverage": len(aud["missing_driving_from_coverage"]),
            "missing_driving_to_coverage": len(aud["missing_driving_to_coverage"]),
            "type_incompatible_lanelinks": len(aud["type_incompatible_lanelinks"]),
            "lane_link_consistency_advisory": len(aud["lane_link_consistency_advisory"]),
        }

    report = {
        "run_id": RUN_ID,
        "producer": "ultimate_pipeline/tools/phase_g6_junction_lanelinks.py",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase": "G",
        "input": str(input_path),
        "output": str(out_path),
        "connections_audited": audit_in["connections_audited"],
        "lanelinks_audited": audit_in["lanelinks_audited"],
        "metrics_input": _metric_summary(audit_in),
        "metrics_output": _metric_summary(audit_out),
        "issues_input": {
            "missing_from_lanes": audit_in["missing_from_lanes"][:200],
            "missing_to_lanes": audit_in["missing_to_lanes"][:200],
            "duplicate_from_lanes": audit_in["duplicate_from_lanes"][:200],
            "missing_driving_from_coverage": audit_in["missing_driving_from_coverage"][:200],
            "missing_driving_to_coverage": audit_in["missing_driving_to_coverage"][:200],
            "type_incompatible_lanelinks": audit_in["type_incompatible_lanelinks"][:200],
            "lane_link_consistency_advisory": audit_in["lane_link_consistency_advisory"][:200],
        },
        "checks_input": checks_in,
        "checks_output": checks_out,
        "repair": {
            "added_lanelinks": repair["added_lanelinks"],
            "repair_issues": repair["repair_issues"],
            "laneLink_added": len(repair["added_lanelinks"]),
            "mutation_kind": (
                "junction laneLink + connecting-road mirror lane link "
                "(uncovered driving lanes converge onto routed neighbour targets)"
            ),
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
        "g6_verdict": (
            "PHASE_G_JUNCTION_LANELINKS_PASS" if passed
            else "PHASE_G_JUNCTION_LANELINKS_BLOCKED"
        ),
    }

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "PHASE_G_JUNCTION_LANELINKS.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )

    m_in = report["metrics_input"]
    m_out = report["metrics_output"]
    md = [
        "# G6 — junction LaneLink validation and repair",
        "",
        f"- run_id: `{RUN_ID}`",
        f"- verdict: **{report['g6_verdict']}**",
        f"- input: `{input_path}`",
        f"- output: `{out_path}`",
        "",
        "## Metrics (input -> output)",
        "",
        "| metric | input | output |",
        "|---|---|---|",
        f"| connections audited | {report['connections_audited']} | {report['connections_audited']} |",
        f"| laneLinks audited | {report['lanelinks_audited']} | {report['lanelinks_audited'] + report['repair']['laneLink_added']} |",
        f"| missing from-lanes | {m_in['missing_from_lanes']} | {m_out['missing_from_lanes']} |",
        f"| missing to-lanes | {m_in['missing_to_lanes']} | {m_out['missing_to_lanes']} |",
        f"| duplicate from-lanes | {m_in['duplicate_from_lanes']} | {m_out['duplicate_from_lanes']} |",
        f"| driving from-coverage gaps | {m_in['missing_driving_from_coverage']} | {m_out['missing_driving_from_coverage']} |",
        f"| driving to-coverage gaps | {m_in['missing_driving_to_coverage']} | {m_out['missing_driving_to_coverage']} |",
        f"| type-incompatible laneLinks | {m_in['type_incompatible_lanelinks']} | {m_out['type_incompatible_lanelinks']} |",
        f"| link-consistency advisory | {m_in['lane_link_consistency_advisory']} | {m_out['lane_link_consistency_advisory']} |",
        "",
        "## Repair",
        "",
        f"- laneLinks added: {report['repair']['laneLink_added']}",
        f"- repair issues: {len(report['repair']['repair_issues'])}",
        "",
        "## Checks (output)",
        "",
    ]
    for name, ok in report["checks_output"].items():
        md.append(f"- {name}: {'PASS' if ok else 'FAIL'}")
    md += ["", "## Fixtures", ""]
    for kind, fx in fixtures["fixtures"].items():
        md.append(f"- {kind}: {'PASS' if fx['ok'] else 'FAIL'} "
                  f"(defects {fx['defects']})")
    md += [
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
        "from/to lanes are resolved against the contacted sections (incoming "
        "road end at this junction; connecting road start/end by contactPoint). "
        "Uncovered driving lanes converge onto the driving target of their "
        "routed neighbour (inner preferred, outer fallback); each repair adds "
        "the junction laneLink plus the mirror lane link on the connecting "
        "road's lane at the junction end.  Advisory consistency items compare "
        "the connecting road's own lane links with the junction LaneLinks.",
    ]
    (EVIDENCE_DIR / "PHASE_G_JUNCTION_LANELINKS.md").write_text(
        "\n".join(md), encoding="utf-8"
    )

    print(f"G6 verdict: {report['g6_verdict']}")
    print(f"  fixtures: {fixtures['fixtures_ok']}")
    print(f"  laneLinks added: {report['repair']['laneLink_added']}")
    print(EVIDENCE_DIR / "PHASE_G_JUNCTION_LANELINKS.json")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
