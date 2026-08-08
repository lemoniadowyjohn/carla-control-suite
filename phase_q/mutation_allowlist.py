"""R13 - mutation allowlist + semantic parent hard gate (C0 remediation H).

Freezes the exact set of mutations the C0 semantic-write contract permits and
provides the single gate used by enrichment producers before they touch the
semantic parent.

Hard gate semantics (fail-closed):
  - input must parse as well-formed OpenDRIVE XML;
  - road/junction/signal counts and the summed traffic-control digest must
    match the frozen semantic-parent authority record;
  - the effective mutation allowlist must be non-empty (a producer with no
    permitted mutation kind may not run).

Negative control (evidence in R13N): ingolstadt_fixed_final.xodr must be
rejected (zero-signal repaired candidate, not the frozen semantic parent).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from phase_q.common import XodrTree, sha256_text

ALLOWLIST_SCHEMA = "phase_q/mutation_allowlist/r13"

# ---------------------------------------------------------------------------
# Frozen allowlist. The ONLY mutation the C0 contract permits for semantic
# enrichment is the insertion of <object type="crosswalk"> with a closed
# <outline><cornerLocal u v z> polyline under an EXISTING <road><objects>
# container (Stage I.1 writer). Every protected category is empty (forbidden).
# ---------------------------------------------------------------------------
PROTECTED_CATEGORIES: List[str] = [
    "road", "junction", "signal", "controller", "signalReference",
    "geometry", "laneSection", "roadMark", "superelevation", "crosssect",
    "header", "geoReference", "object_non_crosswalk",
]

ALLOWED_MUTATIONS: Dict[str, List[str]] = {
    "object": ["INSERT_OBJECT_CROSSWALK"],
    "road": [],
    "junction": [],
    "signal": [],
    "controller": [],
    "signalReference": [],
    "geometry": [],
    "laneSection": [],
    "roadMark": [],
    "superelevation": [],
    "crosssect": [],
    "header": [],
    "geoReference": [],
    "object_non_crosswalk": [],
    "object": ["INSERT_OBJECT_CROSSWALK"],
}


def effective_allowlist() -> List[str]:
    """Flat, deterministic freeze of the allowlist (category:kind)."""
    out: List[str] = []
    for cat in PROTECTED_CATEGORIES + ["object"]:
        for kind in ALLOWED_MUTATIONS.get(cat, []):
            out.append(f"{cat}:{kind}")
    return out


@dataclass
class GateResult:
    allowed: bool
    reasons: List[str]
    effective_allowlist: List[str]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reasons": self.reasons,
            "effective_allowlist": self.effective_allowlist,
        }


def parent_hard_gate(
    xodr_text: str,
    frozen_authority: Dict[str, Any],
    *,
    allowlist: Optional[List[str]] = None,
) -> GateResult:
    """Gate a candidate parent document against the frozen semantic-parent
    authority. Fail-closed; never raises.
    """
    reasons: List[str] = []
    try:
        root = XodrTree(xodr_text).root
    except Exception as exc:
        return GateResult(False, [f"PARSE_FAILURE: {exc}"], list(allowlist or []))

    frozen = frozen_authority or {}
    frozen_counts = frozen.get("counts") or {}
    f_roads = frozen_counts.get("roads")
    f_junctions = frozen_counts.get("junctions")
    f_signals = frozen_counts.get("signals")

    if f_roads is not None:
        n = len(root.findall("road"))
        if n != f_roads:
            reasons.append(f"ROAD_COUNT_MISMATCH expected={f_roads} got={n}")
    if f_junctions is not None:
        n = len(root.findall("junction"))
        if n != f_junctions:
            reasons.append(f"JUNCTION_COUNT_MISMATCH expected={f_junctions} got={n}")
    if f_signals is not None:
        n = len(root.findall(".//signal"))
        if n != f_signals:
            reasons.append(f"SIGNAL_COUNT_MISMATCH expected={f_signals} got={n}")

    frozen_sha = (frozen.get("semantic_parent") or {}).get("sha256_lf_text")
    if frozen_sha:
        if sha256_text(xodr_text) != frozen_sha:
            reasons.append(
                "PARENT_SHA256_MISMATCH vs frozen semantic-parent authority")

    from phase_q.signal_digest import combined_traffic_control_digest

    if f_signals is not None:
        try:
            tc = combined_traffic_control_digest(XodrTree(xodr_text))
        except Exception as exc:
            tc = {}
            reasons.append(f"TC_DIGEST_UNPARSEABLE: {exc}")
        frozen_tc = frozen.get("traffic_control") or {}
        if frozen_tc.get("combined_traffic_control_digest") and \
                tc.get("combined_traffic_control_digest") != frozen_tc["combined_traffic_control_digest"]:
            reasons.append("COMBINED_TC_DIGEST_MISMATCH_vs_frozen_authority")

    eff = list(allowlist) if allowlist is not None else effective_allowlist()
    if not eff:
        reasons.append("MUTATION_ALLOWLIST_EMPTY: no mutation kind may be applied")

    return GateResult(not reasons, reasons, eff)


def quarantine_rejected(error: Exception) -> bool:
    """Any PROVISIONAL/quarantine error response is a hard failure."""
    return True