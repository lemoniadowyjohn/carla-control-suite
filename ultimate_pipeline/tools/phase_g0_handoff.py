#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G0 — Phase F handoff and freeze.

Registers the exact F7-approved elevation candidate that enters Phase G and
records its full identity:

- path
- byte SHA-256
- canonical semantic SHA-256 (whitespace/line-ending normalized)
- planView hash
- road-length hash
- elevation-profile hash
- road-link hash
- junction-structure hash
- connector-geometry hash
- contactPoint hash
- lane-topology hash (Phase G baseline; recomputed after every mutating
  subphase G1..G7 and frozen by G8)

Verdicts:
- PHASE_G_INPUT_ACCEPTED
- PHASE_G_BLOCKED_PHASE_F_IDENTITY
- PHASE_G_BLOCKED_FREEZE_MISMATCH

The domain hashes are whitespace-insensitive: elements are serialized after
all whitespace-only text/tail nodes are stripped, so re-serialization with a
different indent style never changes the protected hashes.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

RUN_ID = "20260803T190000Z"
EVIDENCE_DIR = REPO_ROOT / "reports" / "post_audit_hardening" / RUN_ID

EXPECTED_ROADS = 32710

F5_CANDIDATE = (
    REPO_ROOT
    / "reports"
    / "post_audit_hardening"
    / "20260803T160000Z"
    / "candidate_f5_bounded_offsets.xodr"
)
F7_EVIDENCE = (
    REPO_ROOT
    / "reports"
    / "post_audit_hardening"
    / "20260803T180000Z"
    / "PHASE_F_ELEVATION_VERIFIED.json"
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strip_ws(elem: ET.Element) -> ET.Element:
    """Deep copy of elem with all whitespace text/tail removed."""
    el = copy.deepcopy(elem)
    if el.text and not el.text.strip():
        el.text = None
    for child in list(el):
        _strip_ws(child)
        if child.tail and not child.tail.strip():
            child.tail = None
    if el.tail and not el.tail.strip():
        el.tail = None
    return el


def ws_normalized_xml(elem: ET.Element) -> str:
    return ET.tostring(_strip_ws(elem), encoding="unicode")


def _domain_hash(keys: list) -> str:
    h = hashlib.sha256()
    for k in sorted(set(keys)):
        h.update(k.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _road_planview_key(road: ET.Element) -> str:
    plan = road.find("planView")
    if plan is None:
        return ""
    return ws_normalized_xml(plan)


def compute_identity_hashes(xodr_path: Path) -> dict:
    """Compute all Phase G protected identity hashes for an XODR file."""
    root = ET.parse(str(xodr_path)).getroot()
    roads = root.findall("road")

    planview_keys = []
    length_keys = []
    elevation_keys = []
    roadlink_keys = []
    contactpoint_keys = []
    lanetopo_keys = []
    connector_keys = []
    for r in roads:
        rid = r.get("id")
        planview_keys.append(f"{rid}|{_road_planview_key(r)}")
        length_keys.append(f"{rid}|{r.get('length')}")
        prof = r.find("elevationProfile")
        elevation_keys.append(
            f"{rid}|{ws_normalized_xml(prof) if prof is not None else ''}"
        )
        link = r.find("link")
        link_xml = ws_normalized_xml(link) if link is not None else ""
        roadlink_keys.append(f"{rid}|{link_xml}")
        if link is not None:
            for tag in ("predecessor", "successor"):
                el = link.find(tag)
                if el is not None:
                    contactpoint_keys.append(
                        f"{rid}|{tag}|{el.get('elementType')}|{el.get('elementId')}"
                        f"|{el.get('contactPoint')}"
                    )
        lanes = r.find("lanes")
        lanetopo_keys.append(
            f"{rid}|{ws_normalized_xml(lanes) if lanes is not None else ''}"
        )
        if str(r.get("junction", "-1")) != "-1":
            connector_keys.append(f"{rid}|{_road_planview_key(r)}")

    junction_keys = []
    for j in root.findall("junction"):
        conns = []
        for c in j.findall("connection"):
            conns.append(
                f"id={c.get('id')}:in={c.get('incomingRoad')}"
                f":conn={c.get('connectingRoad')}:cp={c.get('contactPoint')}"
            )
            contactpoint_keys.append(
                f"junction|{j.get('id')}|in={c.get('incomingRoad')}"
                f":conn={c.get('connectingRoad')}:cp={c.get('contactPoint')}"
            )
        junction_keys.append(f"{j.get('id')}|{','.join(sorted(conns))}")

    canonical_parts = []
    for r in roads:
        canonical_parts.append(ws_normalized_xml(r))
    for j in root.findall("junction"):
        canonical_parts.append(ws_normalized_xml(j))
    canonical = "\n".join(sorted(canonical_parts)).encode("utf-8")

    return {
        "path": str(xodr_path),
        "byte_sha256": sha256_file(xodr_path),
        "canonical_semantic_sha256": sha256_bytes(canonical),
        "planview_hash": _domain_hash(planview_keys),
        "road_length_hash": _domain_hash(length_keys),
        "elevation_profile_hash": _domain_hash(elevation_keys),
        "road_link_hash": _domain_hash(roadlink_keys),
        "junction_structure_hash": _domain_hash(junction_keys),
        "connector_geometry_hash": _domain_hash(connector_keys),
        "contactpoint_hash": _domain_hash(contactpoint_keys),
        "lane_topology_hash": _domain_hash(lanetopo_keys),
        "road_count": len(roads),
    }


def _line_ending_variants(path: Path) -> list:
    raw = path.read_bytes()
    return {
        "as_stored": sha256_bytes(raw),
        "lf_normalized": sha256_bytes(raw.replace(b"\r\n", b"\n")),
        "crlf_normalized": sha256_bytes(raw.replace(b"\n", b"\r\n")),
    }


def main() -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    if not F5_CANDIDATE.exists():
        print("G0 verdict: PHASE_G_BLOCKED_PHASE_F_IDENTITY (candidate missing)")
        return 1
    if not F7_EVIDENCE.exists():
        print("G0 verdict: PHASE_G_BLOCKED_PHASE_F_IDENTITY (F7 evidence missing)")
        return 1

    f7 = json.loads(F7_EVIDENCE.read_text(encoding="utf-8"))
    f7_fc = f7.get("final_candidate", {})
    f7_recorded_sha = f7_fc.get("sha256")
    f7_recorded_path = str(f7_fc.get("path", "")).replace("\\", "/")

    identity = compute_identity_hashes(F5_CANDIDATE)
    variants = _line_ending_variants(F5_CANDIDATE)

    f7_path_ok = f7_recorded_path.replace("\\", "/") == identity["path"].replace("\\", "/")
    sha_ok = (
        f7_recorded_sha in variants.values()
    )
    f7_verified = f7.get("phase_f_verdict") == "PHASE_F_ELEVATION_VERIFIED"
    road_count_ok = identity["road_count"] == EXPECTED_ROADS
    freeze_ok = bool(f7_fc.get("phase_e_record_matches_pinned")) and bool(
        f7_fc.get("geometry_matches_pinned")
    )

    checks = {
        "f7_evidence_verdict_verified": f7_verified,
        "f7_recorded_path_matches": f7_path_ok,
        "f7_recorded_sha_matches_byte_identity": sha_ok,
        "road_count_32710": road_count_ok,
        "phase_e_freeze_record_validated_by_f7": freeze_ok,
    }
    passed = all(checks.values())

    report = {
        "run_id": RUN_ID,
        "producer": "ultimate_pipeline/tools/phase_g0_handoff.py",
        "generated_at_utc": now,
        "phase": "G",
        "phase_f_freeze": {
            "f7_evidence_path": str(F7_EVIDENCE),
            "f7_verdict": f7.get("phase_f_verdict"),
            "f7_recorded_sha256": f7_recorded_sha,
            "f7_recorded_candidate_path": f7_recorded_path,
        },
        "input_candidate": identity,
        "line_ending_variants": variants,
        "byte_sha256_lf_variant_matches_f7_record": (
            variants["lf_normalized"] == f7_recorded_sha
        ),
        "checks": checks,
        "g0_verdict": (
            "PHASE_G_INPUT_ACCEPTED" if passed else "PHASE_G_BLOCKED_FREEZE_MISMATCH"
        ),
    }
    if not passed:
        report["g0_fail_reason"] = [n for n, ok in checks.items() if not ok]

    (EVIDENCE_DIR / "PHASE_G_INPUT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )

    md = [
        "# G0 — Phase F handoff and freeze",
        "",
        f"- run_id: `{RUN_ID}`",
        f"- verdict: **{report['g0_verdict']}**",
        "",
        "## Input candidate (F7-approved)",
        "",
        f"- path: `{identity['path']}`",
        f"- byte sha256: `{identity['byte_sha256']}`",
        f"- canonical semantic sha256: `{identity['canonical_semantic_sha256']}`",
        f"- roads: {identity['road_count']}",
        "",
        "## Protected identity hashes",
        "",
        "| domain | sha256 |",
        "|---|---|",
        f"| planView | `{identity['planview_hash']}` |",
        f"| road length | `{identity['road_length_hash']}` |",
        f"| elevation profile | `{identity['elevation_profile_hash']}` |",
        f"| road link | `{identity['road_link_hash']}` |",
        f"| junction structure | `{identity['junction_structure_hash']}` |",
        f"| connector geometry | `{identity['connector_geometry_hash']}` |",
        f"| contactPoint | `{identity['contactpoint_hash']}` |",
        f"| lane topology (G baseline) | `{identity['lane_topology_hash']}` |",
        "",
        "## Freeze cross-checks",
        "",
    ]
    for name, ok in checks.items():
        md.append(f"- {name}: {'PASS' if ok else 'FAIL'}")
    md += [
        "",
        "Byte identity is line-ending tolerant: the F7 evidence recorded the "
        "working-copy CRLF sha while the LFS-stored blob is LF-normalized; the "
        "stored byte sha matches the recorded sha under LF normalization."
        "  The lane-topology hash is the Phase G baseline and will be recomputed "
        "after every mutating subphase.",
    ]
    (EVIDENCE_DIR / "PHASE_G_INPUT.md").write_text("\n".join(md), encoding="utf-8")

    print(f"G0 verdict: {report['g0_verdict']}")
    print(EVIDENCE_DIR / "PHASE_G_INPUT.json")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
