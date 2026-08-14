#!/usr/bin/env python3
"""
Phase N certification against corrected Phase L evidence.

This program now delegates ALL verdict logic to the independently validated
engine in ``phase_q.certifier_decision.assess`` (Q1).  It never hardcodes a
gate status; every gate is a predicate over evidence.  It also records Q0
provenance at the start of the run (Q00/Q01/Q02).

Read-only: consumes evidence files, writes reports under
reports/post_audit_hardening/{RUN_ID}_N_CERTIFICATION/.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from phase_q.common import PROJECT_ROOT, make_run_id, save_json, save_text, sha256_file
from phase_q.certifier_decision import assess
from phase_q.semantic_policy import (
    PROFILE_PERCEPTION_RELEASE,
    PROFILE_PACKAGED_MAP,
    PROFILE_STRUCTURAL_XODR,
)
from ultimate_pipeline.tools.cert_runtime.runtime_config import (
    assert_candidate_consistency,
    resolve_cert_runtime_config,
)

BASE = "reports/post_audit_hardening"
RUN_ID = make_run_id()
OUT_DIR = os.path.join(BASE, "{}_N_CERTIFICATION".format(RUN_ID))

PROFILES = {
    "structural": PROFILE_STRUCTURAL_XODR,
    "packaged": PROFILE_PACKAGED_MAP,
    "perception": PROFILE_PERCEPTION_RELEASE,
}


def _load_json(rel):
    with open(rel, "r", encoding="utf-8") as f:
        return json.load(f)


def _length_invariant_evidence(candidate_xodr):
    """Count roads whose planView extent exceeds the declared road length.

    CARLA's mesh builder asserts `s <= road->GetLength()`; a road trips it (and
    crashes the cook) when any geometry satisfies `s + geometry.length >
    road.length + 1e-9`.  This evidence feeds gate G19.

    Length handling (matches the crash-safe intent, fail-closed):
    - A road with a missing or unparseable ``length`` attribute is skipped
      entirely (NOT counted in ``roads_checked``) -- it cannot be evaluated.
    - A road with a parseable declared length is counted in ``roads_checked``.
      A non-positive declared length is NOT exempted: since any positive
      geometry extent then exceeds a length <= 0, such a road registers a
      violation whenever it carries geometry, because it is a genuine crash
      risk under the same assert.
    """
    import xml.etree.ElementTree as ET

    root = ET.parse(candidate_xodr).getroot()
    violations = 0
    roads_checked = 0
    for road in root.findall("road"):
        try:
            rlen = float(road.get("length"))
        except (TypeError, ValueError):
            continue
        roads_checked += 1
        for g in road.findall("planView/geometry"):
            try:
                s = float(g.get("s"))
                glen = float(g.get("length"))
            except (TypeError, ValueError):
                continue
            if s + glen - rlen > 1e-9:
                violations += 1
                break
    return {"violations": violations, "roads_checked": roads_checked}


def build_bundle(args, *, phase_l_evidence_dir, p4_evidence_dir):
    """Assemble the evidence bundle exactly as the engine consumes it."""
    l = {}
    names = (
        "L1_carla_preflight.json", "L2_map_identity.json", "L3_parser_logs.json",
        "L4_alignment.json", "L5_visual_regression.json", "L6_waypoint_topology.json",
        "L7_drivability.json", "L8_signal_validation.json", "L9_sensor_validation.json",
        "L10_performance.json", "L11_old_vs_new.json", "L12_protected_hashes.json",
        "PHASE_L_RUNTIME_VALIDATION.json",
    )
    for fn in names:
        l[fn] = _load_json(os.path.join(phase_l_evidence_dir, fn))
    p4 = _load_json(os.path.join(p4_evidence_dir, "P04_RAW_RUNTIME_EVIDENCE.json"))
    stage7 = _load_json("_stage7_acceptance_results.json")
    p1 = _load_json("P04_REPAIR_MUTATION_SUMMARY.json")

    l2 = l["L2_map_identity.json"]
    l4 = l["L4_alignment.json"]
    l7 = l["L7_drivability.json"]
    l9 = l["L9_sensor_validation.json"]
    l10 = l["L10_performance.json"]
    l11 = l["L11_old_vs_new.json"]
    l1 = l["L1_carla_preflight.json"]

    semantic_counts = {}
    semantic_counts_file = args.get("semantic_counts")
    if semantic_counts_file and os.path.exists(semantic_counts_file):
        with open(semantic_counts_file, "r", encoding="utf-8") as f:
            semantic_counts = json.load(f)

    combined = l["PHASE_L_RUNTIME_VALIDATION.json"]
    bundle = {
        "provenance": {},
        "run_manifest": {
            "run_id": combined.get("run_id"),
            "commit": combined.get("commit"),
            "branch": combined.get("branch"),
        },
        "config": {
            "expected_run_id": args.get("expected_run_id") or combined.get("run_id"),
            "profile": args.get("profile"),
        },
        "map": {"name": l2.get("map_name")},
        "l2": l2,
        "l4": l4,
        "l7": l7,
        "l9": l9,
        "l10": l10,
        "l11": l11,
        "p4": p4,
        "stage7": stage7,
        "p1": p1,
        "semantic_equiv": {"verdict": "SEMANTIC_EQUIVALENCE_PENDING"},
        "semantic_counts": semantic_counts,
        "length_invariant": _length_invariant_evidence(
            args.get("candidate_xodr")
            or os.path.join("campaigns", "ingolstadt_cooked_perception_v1",
                            "candidate", "ingolstadt_perception_final_repaired.xodr")),
        "evidence_manifest": {},
    }
    return bundle


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Phase N certification (governed)")
    parser.add_argument("--profile", choices=sorted(PROFILES.keys()),
                        default="perception")
    parser.add_argument("--semantic-counts", default=None,
                        help="JSON with per-category semantic counts/dispositions")
    parser.add_argument("--candidate-xodr", default=None,
                        help="governed repaired candidate XODR (G19 length-invariant evidence)")
    parser.add_argument("--run-id", default=None, help="certification run ID override")
    parser.add_argument("--phase-l-dir", default=None, help="Phase L evidence directory override")
    parser.add_argument("--p4-dir", default=None, help="P4 evidence directory override")
    args_p = parser.parse_args()
    profile = PROFILES[args_p.profile]
    runtime = resolve_cert_runtime_config(
        candidate_xodr=args_p.candidate_xodr,
        run_id=args_p.run_id,
        phase_l_dir=args_p.phase_l_dir,
        p4_dir=args_p.p4_dir,
    )
    bundle = build_bundle(
        {
            "profile": args_p.profile,
            "semantic_counts": args_p.semantic_counts,
            "expected_run_id": None,
            "candidate_xodr": str(runtime.candidate_xodr),
        },
        phase_l_evidence_dir=str(runtime.phase_l_dir),
        p4_evidence_dir=str(runtime.p4_dir),
    )

    assert_candidate_consistency(
        p4_rep_sha256=(bundle.get("p4") or {}).get("rep_sha256"),
        phase_l_l2_sha256=(bundle.get("l2") or {}).get("opendrive_sha256"),
        candidate_xodr=runtime.candidate_xodr,
    )

    # Q0 - provenance capture (offline, git-based)
    from phase_q import provenance as prov
    Path(OUT_DIR).mkdir(parents=True, exist_ok=True)
    prov_q = prov.write_q0_outputs(Path(OUT_DIR))
    bundle["provenance"] = prov.capture_worktree_provenance()

    result = assess(bundle, {
        "profile": profile,
        "expected_run_id": bundle["config"]["expected_run_id"],
    })

    _write("N0_PHASE_L_EVIDENCE_AUDIT.json", {
        "run_id": RUN_ID,
        "audit_timestamp": datetime.now(timezone.utc).isoformat(),
        "phase_l_verdict": bundle["run_manifest"]["commit"],
        "verdict": result["verdict"],
        "rejections": result["rejections"],
        "candidate_xodr": str(runtime.candidate_xodr),
        "phase_l_dir": str(runtime.phase_l_dir),
        "p4_dir": str(runtime.p4_dir),
    })
    _write("N18_FINAL_RELEASE_VERDICT.json", {
        "run_id": RUN_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "profile": result["profile"],
        "verdict": result["verdict"],
        "gate_summary": result["summary"],
        "gate_results": result["gates"],
        "rejections": result["rejections"],
    })
    _write("N00_GATE_MATRIX.json",
           {"run_id": RUN_ID, "profile": result["profile"], "gates": result["gates"]})
    _write("G00_GATE_MATRIX.md", md_gate_matrix(result["gates"]))
    _write("N00_EXECUTIVE_SUMMARY.md", executive_summary(result))
    _write("PHASE_N_Q1_RELATED_PROVENANCE.json", prov_q)

    _write("EVIDENCE_MANIFEST.json", build_evidence_manifest())

    print("Phase N certification written to: {}".format(OUT_DIR))
    print("Profile: {}".format(result["profile"]))
    print("Verdict: {}".format(result["verdict"]))
    print("Gate summary: {}".format(result["summary"]))


def md_gate_matrix(gates):
    lines = ["# Phase N Gate Matrix (governed)", "",
             "| Gate | Status | Evidence |", "|------|--------|----------|"]
    for k, v in gates.items():
        lines.append("| {} | {} | {} |".format(k, v["status"], v["evidence"]))
    return "\n".join(lines)


def executive_summary(result):
    lines = [
        "# Phase N Certification - Summary",
        "",
        "**Run ID:** {}".format(RUN_ID),
        "**Profile:** {}".format(result["profile"]),
        "**Engine verdict:** {}".format(result["verdict"]),
        "",
        "Gate pass: {} / {}  \nRejections: {}".format(
            result["summary"]["passed"],
            int(result["summary"]["passed"]) + int(result["summary"]["failed"]),
            len(result["rejections"])),
        "",
    ]
    for r in result["rejections"]:
        lines.append("- `{}` {}".format(r["code"], r["reason"]))
    lines.append("")
    lines.append("Evidence provenance: {}".format(BASE))
    return "\n".join(lines)


def _write(rel, payload):
    path = os.path.join(OUT_DIR, rel)
    os.makedirs(OUT_DIR, exist_ok=True)
    if isinstance(payload, (dict, list)):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
    else:
        with open(path, "w", encoding="utf-8") as f:
            f.write(payload)
    return path


def build_evidence_manifest():
    entries = []
    for root, _, files in os.walk(OUT_DIR):
        for fn in files:
            if fn.lower().endswith((".json", ".md", ".csv")):
                p = os.path.join(root, fn)
                rel = os.path.relpath(p, OUT_DIR)
                entries.append({"path": rel, "size_bytes": os.path.getsize(p),
                                "sha256": sha256_file(p)})
    entries.sort(key=lambda e: e["path"])
    return {"run_id": RUN_ID, "generated_at": datetime.now(timezone.utc).isoformat(),
            "scope": "run-local", "entries": entries}


if __name__ == "__main__":
    main()
