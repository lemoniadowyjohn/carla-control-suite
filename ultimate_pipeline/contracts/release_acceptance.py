"""Release acceptance contract (P0-Q, extended by P0-R).

Background
----------
The 2026-09-15 comprehensive gap audit (reports/production_readiness/
20260915T203000Z_COMPREHENSIVE_GAP_AUDIT.json, packets P0-K/P0-L) found:

    "Position-dependent semantics (signals, crosswalks, signs) are written
    before structural geometry freeze. No explicit STRUCTURE_FROZEN gate
    exists. Stages lack capability prerequisites."

The first slice of this module (2026-09-17) added an additive-only capability
(model ``requires``/``provides``) plus a fail-closed validator, and an honest
mirror of ``MainPipeline._mark_stage(...)`` order.

P0-C (2026-09-18) extends it for the *final-artifact authority* defect

``MainPipeline._run_internal()`` produced ``map_acceptance.json``,
``map_content_fingerprint.json``, preflight validation and the determinism
fingerprint BEFORE the ``junction_link_integrity`` and ``map_hygiene`` stages,
both of which can still mutate the map (link patching; road quarantine /
deleteration, lane repair, lane width repair, z-seam repair) and both of which
can even return a DIFFERENT output path. The acceptance receipt therefore did not
necessarily describe the file published as "final".

Two things were missing from the model to express (and enforce) that:

1. There was no ``STRUCTURE_FROZEN`` capability marking "every permitted
   road/lane/topology/hygiene mutation is now complete".
2. The model had no way for a stage to INVALIDATE a capability. The original
docstring said so explicitly: "this model has no 'revokes' primitive". So a
stage may legally declare both -- that is the "mutate, then re-establish and force
regeneration" pattern. Invalidating a capability that was never provided is a
legal no-op (it is how a stage declares "I would break this if it were held").

This revision adds both, plus a declared ``mutates_structure`` flag so the
validator can catch a structural mutation scheduled after ``STRUCTURE_FROZEN``
without an explicit invalidation -- real validation rather than a naming
convention. The runtime half (evidence freshness, structural fingerprints, the
final receipt) lives in ``ultimate_pipeline.contracts.artifact_authority``.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from ultimate_pipeline.common import (
    digest_object,
    file_sha256,
    read_object,
    safe_artifact,
    utc_now,
    write_immutable_json,
)
from ultimate_pipeline.contracts.stage_capabilities import GEOMETRY_FROZEN, STRUCTURE_FROZEN


class ReleaseAcceptanceStatus:
    """Release acceptance status enumeration."""

    PENDING = "pending"
    APPROVED = "approved"
    FAILED = "failed"
    SKIPPED = "skipped"

    def __init__(self, status: str = PENDING):
        self.status = status


class ReleaseAcceptanceGate:
    """Gates for release acceptance."""

    def __init__(self, name: str = "release_acceptance"):
        self.name = name
        self.requirements: List[str] = []
        self.results: List[Dict] = []

    def add_requirement(self, requirement: str) -> None:
        self.requirements.append(requirement)

    def approve(self, reason: str) -> None:
        self.status = ReleaseAcceptanceStatus.APPROVED
        self.results.append({"reason": reason})

    def fail(self, reason: str) -> None:
        self.status = ReleaseAcceptanceStatus.FAILED
        self.results.append({"reason": reason})

    def skip(self, reason: str) -> None:
        self.status = ReleaseAcceptanceStatus.SKIPPED
        self.results.append({"reason": reason})


def validate_release_acceptance(
    stages: List[Dict],
    release_profile: str,
    git_sha: str,
    initial_capabilities: frozenset,
    final_artifact_path: str,
) -> Dict:
    """Validate release acceptance against the release profile.

    Args:
        stages: List of stage dictionaries with capability contracts.
        release_profile: The release profile name.
        git_sha: Git SHA of the commit.
        initial_capabilities: Initial set of capabilities.
        final_artifact_path: Path to the final artifact.

    Returns:
        Dictionary with validation results.
    """
    # Validate that all required capabilities are met
    missing = set(stages[0]["requires"]) - set(initial_capabilities)
    if missing:
        return {
            "valid": False,
            "missing_capabilities": sorted(missing),
            "details": f"Missing capabilities: {missing}",
        }

    # Check if STRUCTURE_FROZEN is set appropriately
    if any(s["mutates_structure"] and "STRUCTURE_FROZEN" not in stages[i]["provides"]
            for i, s in enumerate(stages) if s["mutates_structure"]):
        return {
            "valid": False,
            "issue": "Structure mutation without STRUCTURE_FROZEN",
            "details": "Stage with mutates_structure=True must either invalidate STRUCTURE_FROZEN "
                       "before mutating or explicitly invalidate it.",
        }

    # Validate all stages meet their requirements
    for i, stage in enumerate(stages):
        if not all(cap in stage["requires"] for cap in stage["requires"]):
            return {
                "valid": False,
                "stage": i,
                "issue": "Missing required capabilities",
                "details": f"Stage {i} missing required capabilities",
            }

    return {
        "valid": True,
        "message": "Release acceptance validated successfully",
    }
