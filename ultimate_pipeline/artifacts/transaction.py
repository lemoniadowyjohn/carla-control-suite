from __future__ import annotations
from pathlib import Path
from typing import Sequence

from ultimate_pipeline.artifacts.errors import (
    CandidateValidationError,
    MutationDomainViolationError,
    PromotionError,
)
from ultimate_pipeline.artifacts.model import (
    ArtifactRef,
    CandidateResult,
    GateResult,
    MutationDeclaration,
    sha256_of,
    compute_semantic_sha256,
)
from ultimate_pipeline.artifacts.store import ArtifactStore
from ultimate_pipeline.artifacts.semantic_diff import SemanticDiffEngine
from ultimate_pipeline.artifacts.promotion import PromotionEngine


class ArtifactTransaction:
    def __init__(
        self,
        store: ArtifactStore,
        semantic_diff: SemanticDiffEngine,
        promotion: PromotionEngine,
    ):
        self.store = store
        self.semantic_diff = semantic_diff
        self.promotion = promotion

    def declare_mutation(
        self,
        operation: str,
        allowed_xml_domains: Sequence[str] = (),
        forbidden_xml_domains: Sequence[str] = (),
        affected_ids: Sequence[str] = (),
    ) -> MutationDeclaration:
        return MutationDeclaration(
            operation=operation,
            allowed_xml_domains=tuple(allowed_xml_domains),
            forbidden_xml_domains=tuple(forbidden_xml_domains),
            affected_ids=tuple(affected_ids),
        )

    def propose_candidate(
        self,
        candidate_id: str,
        candidate_path: Path,
        artifact_type: str,
        mutation: MutationDeclaration,
    ) -> CandidateResult:
        if not candidate_id or candidate_id in {".", ".."} or "/" in candidate_id or "\\" in candidate_id:
            raise CandidateValidationError(candidate_id, "candidate_id must be a single path-safe segment")
        parent = self.store.get_parent()
        if parent is None:
            raise CandidateValidationError(candidate_id, "No accepted parent artifact exists")

        parent_hash_before = sha256_of(parent.path)

        candidate_ref = self.store.store_candidate(
            candidate_id, candidate_path, artifact_type, parent
        )
        if candidate_ref is None:
            raise CandidateValidationError(candidate_id, "Candidate already exists or storage failed")

        if sha256_of(parent.path) != parent_hash_before:
            raise CandidateValidationError(
                candidate_id, "Parent artifact was modified during candidate creation"
            )

        gates: list[GateResult] = []

        try:
            diff_result = self.semantic_diff.compare(parent.path, candidate_ref.path)
            gates.append(diff_result)
        except Exception as e:
            gates.append(GateResult("semantic_diff", False, str(e)))
            self.store.reject_candidate(candidate_id, CandidateResult(
                status="FAIL",
                parent=parent,
                candidate=candidate_ref,
                mutation_declaration=mutation,
                gate_results=tuple(gates),
                blockers=(f"Semantic diff failed: {e}",),
            ))
            return CandidateResult(
                status="FAIL",
                parent=parent,
                candidate=None,
                mutation_declaration=mutation,
                gate_results=tuple(gates),
                blockers=(f"Semantic diff failed: {e}",),
            )

        if self.semantic_diff.detect_undeclared_mutation(candidate_ref, mutation):
            gates.append(GateResult("undeclared_mutation", False, "Undeclared mutation detected"))
            self.store.reject_candidate(candidate_id, CandidateResult(
                status="BLOCKED",
                parent=parent,
                candidate=candidate_ref,
                mutation_declaration=mutation,
                gate_results=tuple(gates),
                blockers=("Undeclared mutation detected",),
            ))
            return CandidateResult(
                status="BLOCKED",
                parent=parent,
                candidate=None,
                mutation_declaration=mutation,
                gate_results=tuple(gates),
                blockers=("Undeclared mutation detected",),
            )

        if not diff_result.passed:
            gates.append(GateResult("validation", False, "Semantic diff validation failed"))
            self.store.reject_candidate(candidate_id, CandidateResult(
                status="FAIL",
                parent=parent,
                candidate=candidate_ref,
                mutation_declaration=mutation,
                gate_results=tuple(gates),
                blockers=("Validation failed",),
            ))
            return CandidateResult(
                status="FAIL",
                parent=parent,
                candidate=candidate_ref,
                mutation_declaration=mutation,
                gate_results=tuple(gates),
                blockers=("Validation failed",),
            )

        gates.append(GateResult("validation", True, "All checks passed"))

        promoted = self.promotion.promote(self.store, candidate_id, parent, candidate_ref, mutation, tuple(gates))
        if promoted is None:
            raise PromotionError(candidate_id, "Promotion failed")

        return CandidateResult(
            status="PASS",
            parent=parent,
            candidate=candidate_ref,
            mutation_declaration=mutation,
            gate_results=tuple(gates),
            blockers=(),
        )
