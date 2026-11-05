from __future__ import annotations

from pathlib import Path

from research.evidence.claim_adjudicator import adjudicate_rq1
from research.evidence.canonical import sha256_file
from research.evidence.schemas import (
    RESEARCH_CONTRACT_SHA256,
    build_experiment_receipt,
)


def _receipt(tmp_path: Path) -> dict:
    protocol = Path("research/thesis_rq_contract.yaml").resolve()
    source = tmp_path / "input.xodr"
    output = tmp_path / "output.json"
    source.write_text("input", encoding="utf-8")
    output.write_text("output", encoding="utf-8")
    return build_experiment_receipt(
        rq_id="RQ1",
        metric_ids=[
            "raw_hash_repeatability",
            "normalized_hash_repeatability",
            "structural_signature_repeatability",
            "byte_nondeterminism_source",
        ],
        git_sha="a" * 40,
        source_dirty=False,
        dirty_reason=None,
        protocol_path=str(protocol),
        protocol_sha256=sha256_file(protocol),
        input_paths=[{"path": str(source), "sha256": sha256_file(source)}],
        map_identities={"frozen_reproduction": True},
        settings_digest="b" * 64,
        runtime={"python": "test"},
        seeds=[0],
        output_paths=[{"path": str(output), "sha256": sha256_file(output)}],
        raw_metric_payload={},
        statistics_method="test",
        execution_status="COMPLETED",
        claim_boundary="test",
    )


def test_adjudication_refuses_missing_bound_input_even_if_frozen(tmp_path: Path):
    receipt = _receipt(tmp_path)
    Path(receipt["inputs"][0]["path"]).unlink()
    matrix = {
        "valid_run_count": 5,
        "all_raw_equal": True,
        "all_normalized_equal": True,
        "all_structural_equal": True,
        "divergence_classification": "NO_DIFFERENCE",
    }

    claim = adjudicate_rq1(
        [receipt] * 5,
        matrix,
        current_contract_sha256=RESEARCH_CONTRACT_SHA256,
    )

    assert claim["claim_status"] == "NOT_RUN"
    assert any("missing" in problem for problem in claim["adjudication"]["problems"])


def test_rq1_assembler_refuses_missing_or_mismatched_declared_final_xodr(tmp_path: Path):
    from tools.rq1_evidence_assembler import validated_final_xodr

    declared = tmp_path / "declared.xodr"
    decoy = tmp_path / "newer-decoy.xodr"
    decoy.write_text("decoy", encoding="utf-8")
    child = {
        "out_dir": str(tmp_path),
        "map_acceptance": {"final_xodr_path": str(declared)},
        "xodr_sha256": sha256_file(decoy),
    }

    path, reason = validated_final_xodr(child)
    assert path is None
    assert reason == "declared_final_xodr_missing"

    declared.write_text("different bytes", encoding="utf-8")
    path, reason = validated_final_xodr(child)
    assert path is None
    assert reason == "declared_final_xodr_sha256_mismatch"
