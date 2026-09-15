# ultimate_pipeline/quality/topology_certification.py
# -*- coding: utf-8 -*-

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
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ultimate_pipeline.contracts.stage_contracts import QualityStatus, from_legacy_bool

DEFAULT_REACHABILITY_THRESHOLD = 0.95

SPEC_TOPOLOGY_EVIDENCE = "LITERAL_SPEC"
RECOVERY_DIAGNOSTIC_EVIDENCE = "RECOVERED_DIAGNOSTIC"


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
    """
    if not isinstance(literal_summary, dict) or literal_summary.get("graph_source") not in (
        "LITERAL_SPEC",
        None,  # tolerate precomputed evidence without the marker
    ):
        literal_status = QualityStatus.INCOMPLETE
    else:
        literal_fraction = literal_summary.get("largest_component_fraction")
        literal_status = (
            from_legacy_bool(literal_fraction is not None and float(literal_fraction) >= fraction_threshold)
            if literal_fraction is not None
            else QualityStatus.INCOMPLETE
        )

    recovered_fraction = (
        recovered_summary.get("largest_component_fraction")
        if isinstance(recovered_summary, dict)
        else None
    )
    recovered_status = (
        from_legacy_bool(float(recovered_fraction) >= fraction_threshold)
        if recovered_fraction is not None
        else QualityStatus.INCOMPLETE
    )

    return {
        "SPEC_TOPOLOGY": literal_status.value,
        "RECOVERY_DIAGNOSTIC": recovered_status.value,
        "production_evidence": SPEC_TOPOLOGY_EVIDENCE,
        "fraction_threshold": fraction_threshold,
        "literal_largest_component_fraction": (
            literal_summary.get("largest_component_fraction")
            if isinstance(literal_summary, dict)
            else None
        ),
        "recovered_largest_component_fraction": (
            float(recovered_fraction) if recovered_fraction is not None else None
        ),
        "literal_unmatched_cross_links": (
            literal_summary.get("unmatched_cross_links")
            if isinstance(literal_summary, dict)
            else None
        ),
        "recovered_unmatched_cross_links": (
            recovered_summary.get("unmatched_cross_links")
            if isinstance(recovered_summary, dict)
            else None
        ),
        "note": (
            "Production certification uses the literal spec graph "
            f"({SPEC_TOPOLOGY_EVIDENCE}); the recovered graph "
            f"({RECOVERY_DIAGNOSTIC_EVIDENCE}) is diagnostic only. A "
            "RECOVERY_DIAGNOSTIC pass with a SPEC_TOPOLOGY fail means the "
            "candidate depends on recovery heuristics and is not "
            "topology-spec-conformant."
        ),
    }