# -*- coding: utf-8 -*-
"""Research evidence authority (minimal, inspectable).

Binds governed research experiments (RQ receipts) and adjudicates claims so
that a research question can never be promoted from stale or unbound
artifacts.  Claim status values come exclusively from
``research/thesis_rq_contract.yaml``; no free-form upgrade is permitted.
"""
from research.evidence.canonical import canonical_json_bytes, sha256_of_jsonable, sha256_file
from research.evidence.schemas import (
    CLAIM_STATUSES,
    RESEARCH_CONTRACT_SHA256,
    build_claim_receipt,
    build_closure_matrix,
    build_experiment_receipt,
    load_claim_statuses,
    validate_receipt,
)
from research.evidence.claim_adjudicator import (
    ADJUDICATOR_VERSION,
    adjudicate_rq1,
    adjudicate_rq2,
    semantic_scope_guard,
)

__all__ = [
    "ADJUDICATOR_VERSION",
    "CLAIM_STATUSES",
    "RESEARCH_CONTRACT_SHA256",
    "adjudicate_rq1",
    "adjudicate_rq2",
    "build_claim_receipt",
    "build_closure_matrix",
    "build_experiment_receipt",
    "canonical_json_bytes",
    "load_claim_statuses",
    "semantic_scope_guard",
    "sha256_file",
    "sha256_of_jsonable",
    "validate_receipt",
]
