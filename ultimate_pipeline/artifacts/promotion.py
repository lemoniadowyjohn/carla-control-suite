from __future__ import annotations

from ultimate_pipeline.artifacts.errors import PromotionError
from ultimate_pipeline.artifacts.model import (
    ArtifactRef,
    CandidateResult,
    GateResult,
    MutationDeclaration,
)


class PromotionEngine:
    """Fail-closed promotion coordinator for accepted artifacts."""

    def promote(
        self,
        store,
        candidate_id: str,
        parent: ArtifactRef,
        candidate: ArtifactRef,
        mutation: MutationDeclaration,
        gate_results: tuple[GateResult, ...],
    ) -> ArtifactRef | None:
        if candidate.parent_sha256 != parent.sha256:
            raise PromotionError(candidate_id, "candidate parent hash does not match accepted parent")

        failed = tuple(gate for gate in gate_results if not gate.passed)
        if failed:
            detail = ", ".join(gate.gate_name for gate in failed)
            raise PromotionError(candidate_id, f"candidate has failing gates: {detail}")

        result = CandidateResult(
            status="PASS",
            parent=parent,
            candidate=candidate,
            mutation_declaration=mutation,
            gate_results=gate_results,
            blockers=(),
        )
        promoted = store.promote_candidate(candidate_id, result)
        if promoted is None:
            raise PromotionError(candidate_id, "store refused candidate promotion")
        return promoted


__all__ = ["PromotionEngine"]
