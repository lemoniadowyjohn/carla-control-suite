from __future__ import annotations

from pathlib import Path

import pytest

from research.evidence import schemas


@pytest.mark.parametrize(
    "content", [None, "", "statuses: [", "statuses: []\n", "__DIRECTORY__"]
)
def test_contract_authority_rejects_missing_empty_or_unparseable_file(
    tmp_path: Path, content: str | None
):
    contract_path = tmp_path / "contract.yaml"
    if content == "__DIRECTORY__":
        contract_path.mkdir()
    elif content is not None:
        contract_path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match="governing RQ contract"):
        schemas._load_contract_authority(contract_path)


def test_display_status_fallback_cannot_authorize_claim(tmp_path: Path, monkeypatch):
    missing_contract = tmp_path / "missing-contract.yaml"
    monkeypatch.setattr(schemas, "CONTRACT_PATH", missing_contract)

    # The display helper may show frozen fallback labels, but claim creation
    # must require a readable, parseable, hash-bound governing contract.
    assert "AUTHORITATIVE" in schemas.load_claim_statuses(missing_contract)
    with pytest.raises(ValueError, match="governing RQ contract"):
        schemas.build_claim_receipt(
            rq_id="RQ1",
            claim_status="AUTHORITATIVE",
            claim_statement="test",
            experiment_receipt_digests=["a" * 64],
            adjudication={},
            contract_sha256=schemas.RESEARCH_CONTRACT_SHA256,
        )


def test_claim_creation_rejects_contract_digest_mismatch():
    with pytest.raises(ValueError, match="does not match governing"):
        schemas.build_claim_receipt(
            rq_id="RQ1",
            claim_status="AUTHORITATIVE",
            claim_statement="test",
            experiment_receipt_digests=["a" * 64],
            adjudication={},
            contract_sha256="0" * 64,
        )


def test_closure_matrix_rejects_unknown_status_and_malformed_digest():
    with pytest.raises(ValueError, match="unauthorized claim status"):
        schemas.build_closure_matrix(
            [{"rq_id": "RQ1", "claim_status": "PASS", "claim_receipt_sha256": "a" * 64}]
        )
    with pytest.raises(ValueError, match="not SHA256"):
        schemas.build_closure_matrix(
            [{"rq_id": "RQ1", "claim_status": "AUTHORITATIVE", "claim_receipt_sha256": "bad"}]
        )


def test_relative_artifact_bindings_resolve_from_repo_root_outside_repo_cwd(
    tmp_path: Path, monkeypatch
):
    from research.evidence.canonical import sha256_file

    repo_root = Path(__file__).resolve().parents[2]
    contract_path = repo_root / "research" / "thesis_rq_contract.yaml"
    contract_sha = sha256_file(contract_path)
    receipt = schemas.build_experiment_receipt(
        rq_id="RQ1",
        metric_ids=["raw_hash_repeatability"],
        git_sha="a" * 40,
        source_dirty=False,
        dirty_reason=None,
        protocol_path="research/thesis_rq_contract.yaml",
        protocol_sha256=contract_sha,
        input_paths=[
            {"path": "research/thesis_rq_contract.yaml", "sha256": contract_sha}
        ],
        map_identities={"frozen_reproduction": False},
        settings_digest="b" * 64,
        runtime={"python": "3.12"},
        seeds=[0],
        output_paths=[
            {"path": "research/thesis_rq_contract.yaml", "sha256": contract_sha}
        ],
        raw_metric_payload={},
        statistics_method="test",
        execution_status="COMPLETED",
        claim_boundary="test",
    )
    monkeypatch.chdir(tmp_path)

    schemas.validate_receipt(receipt, verify=True, repo_root=repo_root)


def test_freshness_gate_recognizes_versioned_rq1_matrix_v2(tmp_path: Path):
    import json

    from tools.evidence_freshness_gate import _verify_evidence

    (tmp_path / "matrix.json").write_text(
        json.dumps({"schema": "rq1_full_determinism_matrix/v2"}), encoding="utf-8"
    )
    result = _verify_evidence(tmp_path, current_commit="test")
    schema_check = next(c for c in result["checks"] if c.get("check") == "schema_version")
    assert schema_check["status"] == "PASS"
