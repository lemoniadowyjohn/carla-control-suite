# ultimate_pipeline/quality/topology_certification.py
# -*- coding: utf-8 -*-
from __future__ import annotations

"""
Topology component certification (OC-2, AREA-008).

Production certification must use the LITERAL spec graph
(component_reachability_summary(literal=True)). The lenient
recovered-diagnostic graph (which tolerates flipped contactPoints and
alternate-boundary laneLink resolution) may keep a candidate healthy that is
NOT literal-spec-conformant -- its only legitimate role is diagnostic.

`certify_topology` compares the two and emits the status vocabulary:

- SPEC_TOPOLOGY: status of the literal-spec reachability gate
  (largest_component_fraction >= threshold). REQUIRED for production.
- RECOVERY_DIAGNOSTIC: status of the lenient graph. Diagnostic band only;
  a PASS here with a SPEC_TOPOLOGY FAIL means the candidate depends on
  recovery heuristics and is not certifiable as topology-spec-conformant.
- production_evidence is always "LITERAL_SPEC".

The statuses are `QualityStatus` values (see stage_contracts) so a FAIL can
never be mistaken for a PASS, and an unmeasured/absent summary surfaces as
INCOMPLETE -- never a silent pass (fail-closed).

All outputs include SHA256 bindings for input summaries and the certification
result, plus a provenance block with tool version, git SHA, and Python version.
Schema versioning enables forward/backward compatibility.
"""

import hashlib
import json
import os
import sys
from typing import Any, Dict, Optional

from ultimate_pipeline.contracts.stage_contracts import QualityStatus, from_legacy_bool

DEFAULT_REACHABILITY_THRESHOLD = 0.95

SPEC_TOPOLOGY_EVIDENCE = "LITERAL_SPEC"
RECOVERY_DIAGNOSTIC_EVIDENCE = "RECOVERED_DIAGNOSTIC"


def _evidence_field(summary: Optional[Dict[str, Any]], name: str) -> Any:
    """Read optional topology evidence without letting diagnostics authorize a pass."""
    return summary.get(name) if isinstance(summary, dict) else None


def _status_for_fraction(
    summary: Optional[Dict[str, Any]],
    *,
    expected_graph_source: str,
    fraction_threshold: float,
) -> QualityStatus:
    """Return a fail-closed status for one explicitly identified graph."""
    if not isinstance(summary, dict) or summary.get("graph_source") != expected_graph_source:
        return QualityStatus.INCOMPLETE
    try:
        fraction = float(summary["largest_component_fraction"])
    except (KeyError, TypeError, ValueError):
        return QualityStatus.INCOMPLETE
    return from_legacy_bool(fraction >= fraction_threshold)


def _sha256_dict(obj: Any) -> str:
    """Deterministic SHA256 of a JSON-serializable object."""
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()


def _get_git_sha() -> str:
    """Get current git commit SHA if available."""
    try:
        import subprocess
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        return ""


def certify_topology(
    literal_summary: Optional[Dict[str, Any]],
    recovered_summary: Optional[Dict[str, Any]],
    *,
    fraction_threshold: float = DEFAULT_REACHABILITY_THRESHOLD,
) -> Dict[str, Any]:
    """Compare the literal-spec and recovered-diagnostic reachability graphs.

    Args:
        literal_summary: component_reachability_summary(literal=True) result
            (or a precomputed evidence dict with the same schema).
        recovered_summary: component_reachability_summary() default result.
        fraction_threshold: largest_component_fraction must be >= this value
            for the corresponding status to pass.

    Returns a dict with SPEC_TOPOLOGY / RECOVERY_DIAGNOSTIC QualityStatus
    values plus the supporting evidence numbers. Missing summaries map to
    INCOMPLETE (fail-closed), never PASS.

    The returned dict includes SHA256 bindings for both input summaries and the
    certification result itself, plus a provenance block with tool version,
    git SHA, and Python version. Schema versioning enables forward/backward
    compatibility.
    """
    literal_sha = _sha256_dict(literal_summary) if isinstance(literal_summary, dict) else ""
    recovered_sha = _sha256_dict(recovered_summary) if isinstance(recovered_summary, dict) else ""

    # The source marker is mandatory for production evidence. Accepting an
    # unlabelled precomputed dict here would make it possible to pass a
    # recovered graph through the literal production slot.
    literal_status = _status_for_fraction(
        literal_summary,
        expected_graph_source=SPEC_TOPOLOGY_EVIDENCE,
        fraction_threshold=fraction_threshold,
    )
    recovered_status = _status_for_fraction(
        recovered_summary,
        expected_graph_source=RECOVERY_DIAGNOSTIC_EVIDENCE,
        fraction_threshold=fraction_threshold,
    )

    result = {
        "schema": "topology_certification_v1",
        "SPEC_TOPOLOGY": literal_status.value,
        "RECOVERY_DIAGNOSTIC": recovered_status.value,
        "production_evidence": SPEC_TOPOLOGY_EVIDENCE,
        "fraction_threshold": fraction_threshold,
        "literal_largest_component_fraction": _evidence_field(
            literal_summary, "largest_component_fraction"
        ),
        "literal_component_count": _evidence_field(literal_summary, "component_count"),
        "literal_isolated_lane_component_count": _evidence_field(
            literal_summary, "isolated_lane_component_count"
        ),
        "literal_isolated_components": _evidence_field(
            literal_summary, "isolated_components"
        ),
        "literal_problematic_components": _evidence_field(
            literal_summary, "problematic_components"
        ),
        "literal_unmatched_cross_links": _evidence_field(
            literal_summary, "unmatched_cross_links"
        ),
        "literal_unmatched_cross_link_details": _evidence_field(
            literal_summary, "unmatched_cross_link_details"
        ),
        "recovered_largest_component_fraction": _evidence_field(
            recovered_summary, "largest_component_fraction"
        ),
        "recovered_component_count": _evidence_field(recovered_summary, "component_count"),
        "recovered_unmatched_cross_links": _evidence_field(
            recovered_summary, "unmatched_cross_links"
        ),
        "note": (
            "Production certification uses the literal spec graph "
            f"({SPEC_TOPOLOGY_EVIDENCE}); the recovered graph "
            f"({RECOVERY_DIAGNOSTIC_EVIDENCE}) is diagnostic only. A "
            "RECOVERY_DIAGNOSTIC pass with a SPEC_TOPOLOGY fail means the "
            "candidate depends on recovery heuristics and is not "
            "topology-spec-conformant."
        ),
"input_bindings": {
            "literal_summary_sha256": literal_sha,
            "recovered_summary_sha256": recovered_sha,
        },
        "certification_sha256": "",
        "provenance": {
            "tool": "topology_certification",
            "git_sha": _get_git_sha(),
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        },
    }
    # Compute certification SHA256 excluding itself
    cert_sha = _sha256_dict({k: v for k, v in result.items() if k != "certification_sha256"})
    result["certification_sha256"] = cert_sha

    return result
