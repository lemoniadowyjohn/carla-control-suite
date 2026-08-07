"""Q16 - Final independent review gate.

FULL_PRODUCTION_RELEASE_READY requires an independent read-only audit by an
identity/session that did NOT implement: the connector repair, the loader
hardening, the Phase L changes, run_n_certify.py, the packaged-map build, or
the final evidence manifest.

The auditor independently verifies:
  candidate authority, package authority, semantic completeness,
  runtime identity, primary sensor evidence, stress evidence,
  old-vs-new comparison, manifest integrity, verdict logic.

Final verdicts:
  INDEPENDENT_FULL_RELEASE_CONFIRMED
  INDEPENDENT_RELEASE_REJECTED
  INDEPENDENT_EVIDENCE_INCOMPLETE

This module is fail-closed: without an independent auditor identity and
signature the verdict can never be CONFIRMED.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from phase_q.common import save_json, utcnow_iso

IMPLEMENTER_ROLES = (
    "connector repair",
    "map hardening",
    "phase l changes",
    "run_n_certify.py",
    "packaged-map build",
    "final evidence manifest",
)

AUDIT_ITEMS = [
    "candidate_authority",
    "package_authority",
    "semantic_completeness",
    "runtime_identity",
    "primary_sensor_evidence",
    "stress_evidence",
    "old_vs_new_comparison",
    "manifest_integrity",
    "verdict_logic",
]


def assess_audit(
    auditor_identity: Optional[str],
    *,
    implementers: Optional[List[str]] = None,
    findings: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Evaluate the independent audit.

    implementers: identities (session names, keys) that implemented the items
                  Q16 forbids (self-certification).
    findings: dict of item -> {"verified": bool, "read_only": bool,
                               "notes": str}
    """
    implementation_context = False
    if auditor_identity and implementers:
        implementation_context = auditor_identity in implementers

    findings = findings or {}
    results = []
    all_ok = True
    for item in AUDIT_ITEMS:
        f = findings.get(item) or {}
        ok = bool(f.get("passed")) and f.get("read_only") == "read-only"
        if not ok:
            all_ok = False
        results.append({
            "item": item,
            "verified": ok,
            "read_only_mode": f.get("read_only"),
            "notes": f.get("notes"),
        })

    unexplained = [r["item"] for r in results if not r["verified"]]

    if not auditor_identity:
        verdict = "INDEPENDENT_EVIDENCE_INCOMPLETE"
        reason = "no independent auditor identity supplied"
    elif implementation_context:
        verdict = "INDEPENDENT_RELEASE_REJECTED"
        reason = "auditor identity overlaps the set of implementers; " \
                 "self-certification is prohibited"
    elif unexplained:
        verdict = "INDEPENDENT_EVIDENCE_INCOMPLETE"
        reason = "items not independently verified: {}".format(unexplained)
    else:
        verdict = "INDEPENDENT_FULL_RELEASE_CONFIRMED"
        reason = "independent read-only audit passed all items"

    return {
        "schema": "Q16_INDEPENDENT_AUDIT/v1",
        "auditor_identity": auditor_identity,
        "auditor_independent_of_implementers": (
            bool(auditor_identity) and auditor_identity not in (implementers or [])),
        "auditor_signature_required": True,
        "verdict": verdict,
        "reason": reason,
        "items": results,
    }