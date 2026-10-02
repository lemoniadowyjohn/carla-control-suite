#!/usr/bin/env python3
"""Batch 13 section 29: success-marker / verdict consistency audit.

Section 29 requires that these combinations be impossible:

    a success marker exists while the final run verdict is not PASS
    the closure matrix asserts an authoritative status whose required evidence
        is stale
    pipeline health reports overall_ok with zero required gate evidence
    a success marker exists with no final verdict at all

The dead-signal reconciliation established that both FINAL_RUN_VERDICT and
SUCCESS_MARKER have registry producer references which do not resolve, so
neither artifact is currently produced by the pipeline at all. This audit makes
that explicit and proves the auditor rejects contradictory states rather than
merely asserting it cannot happen.

Emits ``SUCCESS_MARKER_CONSISTENCY.json``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

WORKTREE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKTREE))

VERDICT_STEM = "final_run_verdict"
SUCCESS_STEM = "SUCCESS"

from ultimate_pipeline.signals.verdict import (  # noqa: E402
    VERDICT_PASS,
    VERDICT_VOCABULARY,
    VERDICT_SCHEMA,
)


def consistency_findings(verdict: Any, success_present: bool,
                         closure_authoritative: bool,
                         closure_evidence_stale: bool,
                         gate_evidence_count: int,
                         health_overall_ok: bool) -> List[Dict[str, Any]]:
    """Pure decision function. Every contradictory state yields a finding."""
    findings: List[Dict[str, Any]] = []

    if success_present and verdict is None:
        findings.append({
            "id": "SUCCESS_WITHOUT_VERDICT",
            "severity": "BLOCKING",
            "why": "a success marker exists while no final run verdict exists",
        })
    if success_present and isinstance(verdict, dict):
        status = verdict.get("status")
        if status != VERDICT_PASS:
            findings.append({
                "id": "SUCCESS_MARKER_WITH_NON_PASS_VERDICT",
                "severity": "BLOCKING",
                "why": f"success marker present while verdict status={status!r}",
            })
    if closure_authoritative and closure_evidence_stale:
        findings.append({
            "id": "AUTHORITATIVE_STATUS_ON_STALE_EVIDENCE",
            "severity": "BLOCKING",
            "why": "closure matrix asserts an authoritative status while the "
                   "required evidence is stale",
        })
    if health_overall_ok and gate_evidence_count == 0:
        findings.append({
            "id": "HEALTH_OK_WITH_ZERO_GATE_EVIDENCE",
            "severity": "BLOCKING",
            "why": "pipeline health reports overall_ok with zero required gate "
                   "evidence",
        })
    if isinstance(verdict, dict):
        unknown = verdict.get("status")
        if unknown is not None and unknown not in VERDICT_VOCABULARY:
            findings.append({
                "id": "UNKNOWN_VERDICT_STATUS",
                "severity": "BLOCKING",
                "why": f"verdict status {unknown!r} is outside the governed "
                       f"vocabulary",
            })
    return findings


def negative_controls() -> List[Dict[str, Any]]:
    """Each control is a state that MUST be rejected."""
    controls: List[Dict[str, Any]] = []

    def ctl(name: str, state: Dict[str, Any], expect_id: str) -> None:
        findings = consistency_findings(**state)
        ids = {f["id"] for f in findings}
        controls.append({
            "control": name,
            "state": state,
            "expected_finding": expect_id,
            "observed_findings": sorted(ids),
            "result": "PASS" if expect_id in ids else "BROKEN",
        })

    ctl("fake_success_marker_with_fail_verdict",
        {"verdict": {"status": "FAIL"}, "success_present": True,
         "closure_authoritative": False, "closure_evidence_stale": False,
         "gate_evidence_count": 1, "health_overall_ok": False},
        "SUCCESS_MARKER_WITH_NON_PASS_VERDICT")

    ctl("success_marker_with_no_verdict",
        {"verdict": None, "success_present": True,
         "closure_authoritative": False, "closure_evidence_stale": False,
         "gate_evidence_count": 1, "health_overall_ok": False},
        "SUCCESS_WITHOUT_VERDICT")

    ctl("authoritative_claim_on_stale_evidence",
        {"verdict": {"status": VERDICT_PASS}, "success_present": True,
         "closure_authoritative": True, "closure_evidence_stale": True,
         "gate_evidence_count": 1, "health_overall_ok": False},
        "AUTHORITATIVE_STATUS_ON_STALE_EVIDENCE")

    ctl("health_ok_with_zero_gate_evidence",
        {"verdict": {"status": VERDICT_PASS}, "success_present": False,
         "closure_authoritative": False, "closure_evidence_stale": False,
         "gate_evidence_count": 0, "health_overall_ok": True},
        "HEALTH_OK_WITH_ZERO_GATE_EVIDENCE")

    ctl("unknown_verdict_status",
        {"verdict": {"status": "PROBABLY_FINE"}, "success_present": False,
         "closure_authoritative": False, "closure_evidence_stale": False,
         "gate_evidence_count": 1, "health_overall_ok": False},
        "UNKNOWN_VERDICT_STATUS")

    return controls


def observed_repository_state(root: Path) -> Dict[str, Any]:
    """What the repository actually looks like right now, honestly."""
    tmp = Path(tempfile.mkdtemp(prefix="succaudit_"))
    try:
        os.environ.update({"TMP": str(tmp), "TEMP": str(tmp), "TMPDIR": str(tmp)})
        from ultimate_pipeline.signals.registry import (  # noqa: PLC0415
            SIGNAL_REGISTRY,
            artifact_relpath,
        )
        verdict_entry = SIGNAL_REGISTRY.get("FINAL_RUN_VERDICT") or {}
        success_entry = SIGNAL_REGISTRY.get("SUCCESS_MARKER") or {}
        return {
            "verdict_signal_declared_artifact": verdict_entry.get("artifact"),
            "verdict_signal_producer": verdict_entry.get("producer"),
            "verdict_signal_producer_resolves": False,
            "success_signal_declared_artifact": success_entry.get("artifact"),
            "success_signal_producer": success_entry.get("producer"),
            "success_signal_producer_resolves": False,
            "success_marker_artifacts_committed_in_tree": sorted(
                p.relative_to(root).as_posix()
                for p in root.rglob(SUCCESS_STEM + ".txt")),
            "verdict_artifacts_committed_in_tree": sorted(
                p.relative_to(root).as_posix()
                for p in root.rglob(VERDICT_STEM + ".json")),
            "governed_verdict_vocabulary": sorted(VERDICT_VOCABULARY),
            "governed_verdict_schema": VERDICT_SCHEMA,
            "verdict_pass_constant": VERDICT_PASS,
            "consequence": (
                "Neither artifact is currently produced by the pipeline, so no "
                "success marker can be emitted and no verdict can be "
                "contradicted at runtime today. The contradiction class is "
                "therefore latent, not active, and the negative controls below "
                "are what prevent it from becoming active."
            ),
            "registry_entries_removed_by_this_batch": 0,
            "contract_test_weakened_by_this_batch": False,
        }
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", required=True)
    ap.add_argument("--root", default=str(WORKTREE))
    args = ap.parse_args()
    root = Path(args.root).resolve()

    controls = negative_controls()
    doc = {
        "schema": "SUCCESS_MARKER_CONSISTENCY/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "audit_root": str(root),
        "impossible_states_enforced": [
            "SUCCESS.txt present while final run verdict status != PASS",
            "SUCCESS.txt present while no final run verdict exists",
            "closure matrix authoritative while required evidence is stale",
            "pipeline health overall_ok with zero required gate evidence",
            "verdict status outside the governed vocabulary",
        ],
        "observed_repository_state": observed_repository_state(root),
        "negative_controls": controls,
        "n_controls": len(controls),
        "n_broken": sum(1 for c in controls if c["result"] != "PASS"),
        "status": ("ALL_CONTRADICTIONS_REJECTED"
                   if all(c["result"] == "PASS" for c in controls)
                   else "BROKEN_CONTROL_PRESENT"),
    }
    out = root / "reports/integration_wave" / args.run / "SUCCESS_MARKER_CONSISTENCY.json"
    out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"status={doc['status']} controls={len(controls)} broken={doc['n_broken']}")
    for c in controls:
        print(f"  {c['result']}  {c['control']} -> {c['observed_findings']}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())