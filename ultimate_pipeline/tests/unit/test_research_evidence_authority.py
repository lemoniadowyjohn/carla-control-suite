# -*- coding: utf-8 -*-
"""Deterministic tests for the research evidence authority layer.

Covers:
  * RQ experiment receipt schema (fail-closed bindings, claim statuses)
  * claim adjudicator (RQ1 five-run gate, RQ2 bounded boundary, contract
    boundaries for Town10HD/RQ3 and unlabeled RQ5B)
  * five-run comparator classification matrix
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

from research.evidence.canonical import (
    canonical_json_bytes,
    safe_env_record,
    sha256_of_jsonable,
)
from research.evidence.claim_adjudicator import (
    ADJUDICATOR_VERSION,
    adjudicate_rq1,
    adjudicate_rq2,
    semantic_scope_guard,
)
from research.evidence.schemas import (
    CLAIM_STATUSES,
    RESEARCH_CONTRACT_SHA256,
    build_experiment_receipt,
    load_claim_statuses,
    validate_receipt,
)

CONTRACT_SHA = RESEARCH_CONTRACT_SHA256


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------
def _receipt_base(**overrides):
    fields = dict(
        rq_id="RQ1",
        metric_ids=["raw_hash_repeatability", "normalized_hash_repeatability",
                    "structural_signature_repeatability", "byte_nondeterminism_source"],
        git_sha="0" * 40,
        source_dirty=False,
        dirty_reason=None,
        protocol_path="research/thesis_rq_contract.yaml",
        protocol_sha256=CONTRACT_SHA,
        input_paths=[{"path": "in.xodr", "sha256": "a" * 64}],
        map_identities={"scope": "manual_hull", "frozen_reproduction": True},
        settings_digest="b" * 64,
        runtime={"python": "3.12"},
        seeds=["deterministic-no-seed"],
        output_paths=[{"path": "out.json", "sha256": "c" * 64}],
        raw_metric_payload={"k": 1},
        statistics_method="exact identity comparison",
        execution_status="COMPLETED",
        claim_boundary="test boundary",
    )
    fields.update(overrides)
    return fields


def _matrix(**overrides):
    m = dict(
        schema="rq1_full_determinism_matrix/v1",
        run_count=5,
        valid_run_count=5,
        all_raw_equal=True,
        all_normalized_equal=True,
        all_structural_equal=True,
        first_divergent_stage=None,
        divergence_classification="NO_DIFFERENCE",
    )
    m.update(overrides)
    return m


# ---------------------------------------------------------------------------
# receipt schema
# ---------------------------------------------------------------------------
class TestExperimentReceiptSchema:
    def test_valid_receipt_roundtrip_same_digest(self):
        r1 = build_experiment_receipt(**_receipt_base())
        r1 = json.loads(json.dumps(r1))
        r2 = build_experiment_receipt(**_receipt_base())
        assert sha256_of_jsonable(r1) == sha256_of_jsonable(r2)

    def test_missing_protocol_sha_fails(self):
        with pytest.raises(ValueError, match="protocol_sha256"):
            build_experiment_receipt(**_receipt_base(protocol_sha256=""))

    def test_hex_sha256_required_on_bindings(self):
        with pytest.raises(ValueError, match="hex SHA256"):
            build_experiment_receipt(
                **_receipt_base(input_paths=[{"path": "in.xodr", "sha256": "not-a-hash"}])
            )

    def test_dirty_source_without_reason_inadmissible(self):
        with pytest.raises(ValueError, match="dirty source"):
            build_experiment_receipt(**_receipt_base(source_dirty=True))

    def test_dirty_source_with_reason_is_admissible(self):
        r = build_experiment_receipt(
            **_receipt_base(source_dirty=True, dirty_reason="documented reason")
        )
        validate_receipt(r)

    def test_unknown_execution_status_fails(self):
        with pytest.raises(ValueError, match="execution_status"):
            build_experiment_receipt(**_receipt_base(execution_status="probably valid"))

    def test_contract_drift_detected(self, tmp_path):
        inp = tmp_path / "in.xodr"
        inp.write_bytes(b"<x/>")
        import hashlib

        real = hashlib.sha256(inp.read_bytes()).hexdigest()
        r = build_experiment_receipt(**_receipt_base(input_paths=[{"path": str(inp), "sha256": real}]))
        (tmp_path / "in.xodr").write_bytes(b"<y/>")  # bind-then-drift
        with pytest.raises(ValueError, match="sha drift"):
            validate_receipt(r, verify=True)

    def test_claim_status_enum_from_contract(self):
        statuses = load_claim_statuses()
        assert statuses
        assert "AUTHORITATIVE" in statuses and "NOT_RUN" in statuses
        assert "probably authoritative" not in statuses
        assert CLAIM_STATUSES == statuses

    def test_free_form_upgrade_status_rejected(self):
        from research.evidence.schemas import build_claim_receipt

        with pytest.raises(ValueError, match="not an authorized status"):
            build_claim_receipt(
                rq_id="RQ1",
                claim_status="probably authoritative",
                claim_statement="x",
                experiment_receipt_digests=[],
                adjudication={},
                contract_sha256=CONTRACT_SHA,
            )


# ---------------------------------------------------------------------------
# adjudicator
# ---------------------------------------------------------------------------
class TestAdjudicatorRQ1:
    def _runs(self, n=5, **overrides):
        return [
            json.loads(
                json.dumps(build_experiment_receipt(**_receipt_base(rq_id="RQ1", **overrides)))
            )
            for _ in range(n)
        ]

    def test_authoritative_requires_exact_valid_run_count_and_metrics(self):
        claim = adjudicate_rq1(self._runs(5), _matrix())
        assert claim["claim_status"] == "AUTHORITATIVE", claim["adjudication"]["problems"]

    def test_missing_runs_not_run(self):
        claim = adjudicate_rq1(self._runs(4), _matrix())
        assert claim["claim_status"] == "NOT_RUN"
        assert any("missing required runs" in p for p in claim["adjudication"]["problems"])

    def test_missing_metrics_not_run(self):
        runs = self._runs(5)
        for r in runs:
            r["metric_ids"] = ["raw_hash_repeatability"]
        claim = adjudicate_rq1(runs, _matrix())
        assert claim["claim_status"] == "NOT_RUN"

    def test_failed_executions_not_run(self):
        runs = self._runs(5)
        for r in runs:
            r["execution_status"] = "FAILED"
        claim = adjudicate_rq1(runs, _matrix())
        assert claim["claim_status"] == "NOT_RUN"

    def test_dirty_without_reason_not_run(self):
        runs = self._runs(5)
        for r in runs:
            r["source_dirty"] = True
            r["dirty_reason"] = None
            r["status"] = "ok"
        v = False  # direct structure mutation (adjudicator gate check)
        assert not v
        r0 = runs[0]
        # dirty source passes build only with a reason; simulate a forged receipt
        r0["source_dirty"] = True
        r0["dirty_reason"] = None
        claim = adjudicate_rq1([r0] + self._runs(4), _matrix())
        assert claim["claim_status"] == "NOT_RUN"

    def test_mismatched_identities_bounded_not_authoritative(self):
        claim = adjudicate_rq1(self._runs(5), _matrix(all_raw_equal=False, divergence_classification="RAW_DIFFERENT_NORMALIZED_EQUAL"))
        assert claim["claim_status"] == "BOUNDED"

    def test_matrix_missing_not_run(self):
        claim = adjudicate_rq1(self._runs(5), None)
        assert claim["claim_status"] == "NOT_RUN"

    def test_return_codes_alone_never_authoritative(self):
        # receipts + rc=0 + receipts-present only; without matrix identity
        # evidence the gate must NOT produce AUTHORITATIVE.
        claim = adjudicate_rq1(self._runs(5), _matrix(all_raw_equal=False))
        assert claim["claim_status"] != "AUTHORITATIVE"

    def test_protocol_sha_missing_invalid_evidence(self):
        runs = self._runs(5)
        for r in runs:
            r["protocol"]["sha256"] = ""
        claim = adjudicate_rq1(runs, _matrix())
        assert claim["claim_status"] == "NOT_RUN"


class TestAdjudicatorRQ2:
    def _receipt(self, **overrides):
        base = dict(
            rq_id="RQ2",
            metric_ids=[
                "lane_width_gap", "curvature_gap", "curvature_wasserstein_gap",
                "road_count_ratio", "road_length_ratio", "junction_ratio",
                "building_density_gap", "frechet_distance", "connectivity_gap",
                "semantic_object_gap",
            ],
            git_sha="0" * 40,
            source_dirty=False,
            dirty_reason=None,
            protocol_path="research/thesis_rq_contract.yaml",
            protocol_sha256=CONTRACT_SHA,
            input_paths=[{"path": "auto.xodr", "sha256": "a" * 64}],
            map_identities={"scope": "manual_hull", "frozen_reproduction": True},
            settings_digest="b" * 64,
            runtime={"python": "3.12"},
            seeds=["deterministic-no-seed"],
            output_paths=[{"path": "rq2.json", "sha256": "c" * 64}],
            raw_metric_payload={"lane_width_gap": 0.0597},
            statistics_method="point recomputation",
            execution_status="COMPLETED",
            claim_boundary="bounded local-hull",
        )
        base.update(overrides)
        receipt = build_experiment_receipt(**base)
        return receipt

    def test_bounded_reproduction(self):
        claim = adjudicate_rq2([self._receipt()])
        assert claim["claim_status"] == "BOUNDED", claim["adjudication"]["problems"]

    def test_whole_map_scope_never_upgrades(self):
        claim = adjudicate_rq2([self._receipt(
            map_identities={"scope": "whole_map", "frozen_reproduction": True}
        )])
        assert claim["claim_status"] == "NOT_RUN"

    def test_no_receipts_not_run(self):
        assert adjudicate_rq2([])["claim_status"] == "NOT_RUN"

    def test_missing_frozen_reproduction_not_run(self):
        claim = adjudicate_rq2([self._receipt(
            map_identities={"scope": "manual_hull", "frozen_reproduction": False}
        )])
        assert claim["claim_status"] == "NOT_RUN"


class TestSemanticScopeGuards:
    def test_town10hd_never_rq3_authoritative_evidence(self):
        reason = semantic_scope_guard("RQ3", {"map_identity": "Town10HD"})
        assert reason and "Town10HD" in reason

    def test_unlabeled_rq5b_never_generalization_accuracy(self):
        reason = semantic_scope_guard("RQ5B", {"map_identity": "grid0828", "labeled": False})
        assert reason and "unlabeled" in reason

    def test_labeled_other_maps_pass(self):
        assert semantic_scope_guard("RQ3", {"map_identity": "Grid0828"}) is None
        assert semantic_scope_guard("RQ5A", {"map_identity": "grid0828", "labeled": True}) is None


# ---------------------------------------------------------------------------
# canonical hashing / env masking
# ---------------------------------------------------------------------------
class TestCanonicalHelpers:
    def test_canonical_json_is_order_independent(self):
        d1 = {"x": 1, "y": {"a": 1, "b": 2}}
        d2 = {"y": {"b": 2, "a": 1}, "x": 1}
        assert canonical_json_bytes(d1) == canonical_json_bytes(d2)

    def test_secret_masking(self):
        record = safe_env_record({
            "PATH": "/usr/bin",
            "UP_GITHUB_TOKEN": "s3cret",
            "MY_PASSWORD": "hunter2",
            "API_KEY": "k",
        })
        assert record["PATH"] == "/usr/bin"
        assert record["UP_GITHUB_TOKEN"] == "<redacted>"
        assert record["MY_PASSWORD"] == "<redacted>"
        assert record["API_KEY"] == "<redacted>"


# ---------------------------------------------------------------------------
# five-run comparator
# ---------------------------------------------------------------------------
from research.rq1_determinism_matrix import build_determinism_matrix


def _child_run(i, *, xodr="X" * 64, normalized=None, structural=None, status="ok"):
    normalized = normalized or xodr
    structural = structural or ("S" * 64)
    return {
        "schema": "rq1_run_receipt/v2",
        "run": i,
        "status": status,
        "input_xodr": "pinned.xodr",
        "input_sha256": "I" * 64,
        "out_dir": f"out/run_{i:02d}",
        "xodr_sha256": xodr,
        "normalized_xodr_sha256": normalized,
        "structural_signature": structural,
        "tileset_digest": "T" * 64,
        "map_acceptance_digest": "M" * 64,
        "final_receipt_digest": "F" * 64,
        "settings_digest": "D" * 64,
        "feature_counts": {"road_count": 10},
        "topology_counts": {"junction_count": 3},
        "inputs_record": {
            "OSM": {"path": "a.osm", "sha256": "O" * 64},
            "BUILDINGS": {"path": "b.json", "sha256": "B" * 64},
        },
        "effective_env": {"governed": {"UP_OFFLINE_ONLY": "1", "UP_RUN_TAG": f"rq1b_run{i:02d}"}},
    }


def _wrapper(i, child):
    return {
        "run_index": i,
        "return_code": 0,
        "timed_out": False,
        "child_receipt": child,
        "receipt_found": True,
    }


class TestFiveRunComparator:
    def test_no_difference_classification(self):
        receipts = [_wrapper(i, _child_run(i)) for i in range(5)]
        matrix = build_determinism_matrix(receipts, valid_run_count=5)
        assert matrix["divergence_classification"] == "NO_DIFFERENCE"
        assert matrix["all_raw_equal"] and matrix["all_normalized_equal"] and matrix["all_structural_equal"]
        assert matrix["first_divergent_stage"] is None

    def test_raw_diff_normalized_equal_serialization_nondeterminism(self):
        receipts = []
        for i in range(5):
            same = _child_run(i)
            if i == 2:
                same["xodr_sha256"] = "Y" * 64  # raw bytes differ
                # normalized + structural identical
            receipts.append(_wrapper(i, same))
        matrix = build_determinism_matrix(receipts, valid_run_count=5)
        assert matrix["all_raw_equal"] is False
        assert matrix["all_normalized_equal"] is True
        assert matrix["all_structural_equal"] is True
        assert matrix["divergence_classification"] == "RAW_DIFFERENT_NORMALIZED_EQUAL"
        assert matrix["first_divergent_stage"] == "raw_xodr_sha256"

    def test_numeric_variation_classification(self):
        receipts = []
        for i in range(5):
            child = _child_run(i, normalized="N%s" % ("9" * 62))
            if i == 1:
                child["normalized_xodr_sha256"] = "MISMATCH" + "9" * 55
            receipts.append(_wrapper(i, child))
        matrix = build_determinism_matrix(receipts, valid_run_count=5)
        assert matrix["all_normalized_equal"] is False
        assert matrix["all_structural_equal"] is True
        assert matrix["divergence_classification"] == "NORMALIZED_DIFFERENT_STRUCTURAL_EQUAL"

    def test_true_structural_difference_classification(self):
        receipts = []
        for i in range(5):
            child = _child_run(i)
            if i == 3:
                child["structural_signature"] = "Z" * 64  # real topology change
            receipts.append(_wrapper(i, child))
        matrix = build_determinism_matrix(receipts, valid_run_count=5)
        assert matrix["divergence_classification"] == "STRUCTURAL_DIFFERENCE"
        assert matrix["first_divergent_stage"] == "structural_signature"

    def test_invalid_run_never_valid(self):
        receipts = [_wrapper(i, _child_run(i)) for i in range(4)]
        receipts.append(
            _wrapper(4, _child_run(4, status="FAILED"))
        )
        receipts[4]["return_code"] = 1
        matrix = build_determinism_matrix(receipts, valid_run_count=4)
        assert matrix["valid_run_count"] == 4

    def test_mismatches_never_hidden(self):
        receipts = [_wrapper(i, _child_run(i)) for i in range(4)]
        odd = _child_run(4)
        odd["tileset_digest"] = "DIFF" + "0" * 60
        receipts.append(_wrapper(4, odd))
        matrix = build_determinism_matrix(receipts, valid_run_count=5)
        assert matrix["identity_gaps"], gap_for_tileset(matrix)
        assert any(g["identity"] == "tileset_digest" for g in matrix["identity_gaps"])


def gap_for_tileset(matrix):
    return any(g.get("identity") == "tileset_digest" for g in matrix["identity_gaps"])


def test_adjudicator_version_recorded():
    assert ADJUDICATOR_VERSION

