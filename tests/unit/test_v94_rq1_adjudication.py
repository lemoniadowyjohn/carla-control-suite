"""V94: measured RQ1 evidence, not a summary flag, determines claim authority.

Offline tests use real receipt constructors and the real production
adjudicator. Each receipt has its own output and UTC acquisition time.
"""
from __future__ import annotations

from copy import deepcopy

import pytest

from research.evidence.claim_adjudicator import (
    RQ1_REQUIRED_METRIC_IDS,
    adjudicate_rq1,
)
from research.evidence.schemas import (
    RESEARCH_CONTRACT_SHA256,
    build_experiment_receipt,
)

SOURCE = "a" * 40
MAP = "b" * 64
RAW = "c" * 64
NORMALIZED = "d" * 64
STRUCTURAL = "e" * 64
SETTINGS = "f" * 64


def _receipts():
    out = []
    for idx in range(5):
        r = build_experiment_receipt(
            rq_id="RQ1",
            metric_ids=sorted(RQ1_REQUIRED_METRIC_IDS),
            git_sha=SOURCE,
            source_dirty=False,
            dirty_reason=None,
            protocol_path="research/thesis_rq_contract.yaml",
            protocol_sha256=RESEARCH_CONTRACT_SHA256,
            input_paths=[{"path": "source/auto.xodr", "sha256": MAP}],
            map_identities={
                "auto_map_of_record_sha256": MAP,
                "final_xodr_sha256": RAW,
                "normalized_xodr_sha256": NORMALIZED,
                "structural_signature_sha256": STRUCTURAL,
            },
            settings_digest=SETTINGS,
            runtime={"python": "test"},
            seeds=[0],
            output_paths=[
                {"path": f"reports/run_{idx:02d}/rq1.json", "sha256": RAW}
            ],
            raw_metric_payload={"synthetic_run": idx},
            statistics_method="five_cold_independent_runs",
            execution_status="COMPLETED",
            claim_boundary="pinned input and config",
        )
        r["generated_at_utc"] = f"2026-11-11T00:{idx:02d}:00+00:00"
        out.append(r)
    return out


def _matrix():
    return {
        "schema": "rq1_full_determinism_matrix/v1",
        "valid_run_count": 5,
        "all_raw_equal": True,
        "all_normalized_equal": True,
        "all_structural_equal": True,
        "divergence_classification": "NO_DIFFERENCE",
        "identity_gaps": [],
        "per_run": [
            {
                "run_id": f"run_{idx:02d}",
                "valid": True,
                "identities": {
                    "input_identity": {"input_xodr_sha256": MAP},
                    "raw_xodr_sha256": RAW,
                    "normalized_xodr_sha256": NORMALIZED,
                    "structural_signature": STRUCTURAL,
                    "settings_digest": SETTINGS,
                },
            }
            for idx in range(5)
        ],
    }


def _adjudicate(receipts, matrix, **kwargs):
    return adjudicate_rq1(
        receipts,
        matrix,
        current_contract_sha256=RESEARCH_CONTRACT_SHA256,
        current_source_sha=SOURCE,
        **kwargs,
    )


def test_five_coherent_source_bound_receipts_can_pass():
    result = _adjudicate(_receipts(), _matrix())
    assert result["claim_status"] == "AUTHORITATIVE"
    assert result["adjudication"]["problems"] == []


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda rs: rs[2].update(git_sha="9" * 40), "source SHA"),
        (lambda rs: rs[2]["map_identities"].update(auto_map_of_record_sha256="9" * 64), "input"),
        (lambda rs: rs[2].update(generated_at_utc="bad-timestamp"), "timestamp"),
        (lambda rs: rs[2].update(generated_at_utc=rs[0]["generated_at_utc"]), "timestamps"),
        (lambda rs: rs[2].update(source_dirty=True, dirty_reason="local edits"), "source_dirty"),
        (lambda rs: rs[2].update(settings_digest="another-setting"), "settings_digest"),
        (lambda rs: rs[2]["outputs"][0].update(path=rs[0]["outputs"][0]["path"]), "output paths"),
    ],
)
def test_mixed_or_falsely_comparable_runs_rejected(mutation, reason):
    receipts = _receipts()
    mutation(receipts)
    claim = _adjudicate(receipts, _matrix())
    assert claim["claim_status"] == "NOT_RUN"
    assert reason.lower() in " ".join(claim["adjudication"]["problems"]).lower()


def test_missing_current_candidate_sha_blocks_authority():
    result = adjudicate_rq1(
        _receipts(),
        _matrix(),
        current_contract_sha256=RESEARCH_CONTRACT_SHA256,
    )
    assert result["claim_status"] == "NOT_RUN"
    assert "current_source_sha" in " ".join(result["adjudication"]["problems"])


@pytest.mark.parametrize(
    "mutation",
    [
        lambda matrix: matrix.pop("per_run"),
        lambda matrix: matrix["per_run"][0]["identities"].update(raw_xodr_sha256="9"*64),
        lambda matrix: matrix["per_run"][0].update(valid=False),
        lambda matrix: matrix["per_run"][4].update(run_id="run_00"),
        lambda matrix: matrix.update(identity_gaps=[{"identity": "raw_xodr_sha256"}]),
        lambda matrix: matrix.update(valid_run_count=1),
    ],
)
def test_self_asserted_matrix_flags_cannot_replace_matching_children(mutation):
    matrix = _matrix()
    mutation(matrix)
    claim = _adjudicate(_receipts(), matrix)
    assert claim["claim_status"] == "NOT_RUN"


def test_five_is_nonnegotiable_even_with_matching_summary():
    result = _adjudicate(_receipts(), _matrix(), required_valid_runs=1)
    assert result["claim_status"] == "NOT_RUN"


def test_four_receipts_never_pass_as_five_runs():
    result = _adjudicate(_receipts()[:4], _matrix())
    assert result["claim_status"] == "NOT_RUN"
