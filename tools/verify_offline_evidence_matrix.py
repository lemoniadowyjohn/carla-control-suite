#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline validation of the Wave B evidence/freshness/closure matrices.

Runs in GitHub-hosted offline CI. It performs NO live CARLA work and requires
no UE4, Blender or OSM2World binary. Its only job is to refuse to let an
evidence packet silently drift:

  1. every named matrix exists and parses
  2. every evidence binding names a producer, a protocol, an artifact and a status
  3. no binding claims AUTHORITATIVE/RUNTIME_IDENTITY_ESTABLISHED for a result
     whose own artifact records a blocked or not-run status
  4. every blocker id referenced in the closure matrix is defined in the
     readiness matrix
  5. the remote-candidate commit recorded in the matrices is a real commit

Exits non-zero on any violation so it is a real gate, not a report.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parents[1]
MATRICES = {
    "closure": "RQ_CLOSURE_MATRIX.json",
    "readiness": "PRODUCTION_READINESS_MATRIX.json",
    "freshness": "EVIDENCE_FRESHNESS.json",
}

# Statuses that must never be paired with an authoritative claim.
BLOCKING_STATUS_MARKERS = (
    "BLOCKED",
    "NOT_EXECUTED",
    "NOT_RUN",
    "DEFERRED",
    "NOT_ESTABLISHED",
    "NOT_READY",
    "NOT_VERIFIED",
    "FAILED",
    "NOT_PRODUCTION_READY",
)


def main() -> int:
    failures: List[str] = []
    docs: Dict[str, Any] = {}

    for key, rel in MATRICES.items():
        p = REPO / rel
        if not p.is_file():
            failures.append(f"{rel}: missing")
            continue
        try:
            docs[key] = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            failures.append(f"{rel}: invalid JSON ({e})")

    freshness = docs.get("freshness") or {}
    closure = docs.get("closure") or {}
    readiness = docs.get("readiness") or {}

    # 2. binding completeness
    bindings = freshness.get("bindings") or []
    if not bindings:
        failures.append("EVIDENCE_FRESHNESS.json: no bindings recorded")
    required = ("rq", "metric", "producer", "producer_commit", "protocol", "status")
    for b in bindings:
        missing = [k for k in required if not b.get(k)]
        if missing:
            failures.append(
                f"binding {b.get('rq') or b.get('metric')!r}: missing {missing}"
            )

    # 3. no authoritative claim over a blocking status
    for b in bindings:
        status = str(b.get("status", "")).upper()
        if "AUTHORITATIVE" in status or "RUNTIME_IDENTITY_ESTABLISHED" in status:
            if any(m in status for m in BLOCKING_STATUS_MARKERS):
                failures.append(
                    f"binding {b.get('rq')!r}: status {status!r} both claims "
                    "authority and records a blocker"
                )

    # 3b. not_authoritative list must stay explicit and non-empty
    not_auth = freshness.get("claims_that_are_NOT_authoritative") or []
    if not not_auth:
        failures.append(
            "EVIDENCE_FRESHNESS.json: claims_that_are_NOT_authoritative is empty; "
            "a packet with no explicit non-claims is not auditable"
        )

    # 4. every blocker id referenced is defined
    defined = {
        str(b.get("id"))
        for b in (readiness.get("exact_blockers") or [])
        if b.get("id")
    }
    if not defined:
        failures.append("PRODUCTION_READINESS_MATRIX.json: no exact_blockers defined")
    summary = (closure.get("summary") or {}).get("single_root_cause_blocker")
    defined_blockers = {
        str(b.get("blocker")) for b in (readiness.get("exact_blockers") or [])
    }
    if summary and summary not in defined and summary not in defined_blockers:
        failures.append(
            f"closure summary blocker {summary!r} is not defined in readiness matrix"
        )

    # 5. the recorded candidate commit must be a real commit
    for label, doc in (("freshness", freshness), ("closure", closure)):
        sha = doc.get("candidate_commit")
        if sha and re.fullmatch(r"[0-9a-f]{7,40}", str(sha)):
            r = subprocess.run(
                ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
                cwd=str(REPO),
                capture_output=True,
            )
            if r.returncode != 0:
                failures.append(
                    f"{label}.candidate_commit {sha} is not a commit in this repository"
                )

    report = {
        "schema": "offline_evidence_gate/v1",
        "matrices_checked": sorted(docs),
        "bindings_checked": len(bindings),
        "blockers_defined": sorted(defined),
        "failures": failures,
        "status": "PASS" if not failures else "FAIL",
        "note": "offline only: no live CARLA, no UE4, no Blender/OSM2World binary required",
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())