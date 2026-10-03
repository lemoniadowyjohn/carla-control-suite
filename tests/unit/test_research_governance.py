"""Tests for the central research governance layer.

These prove the governance layer actually rejects bad records. A test that
passes because the check is absent is worse than no test, so each control here
mirrors a negative control in
``tools/build_governance_gates.py::negative_controls``.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKTREE))

from ultimate_pipeline.research.evidence_freshness import (
    Binding, assess, FRESH, STALE_PRODUCER, STALE_INPUT, STALE_PROTOCOL,
    MISSING_PROVENANCE, HASH_MISMATCH, STATUSES,
)
from ultimate_pipeline.research.evidence_graph import (
    EvidenceGraph, EvidenceNode, verify, sha256_file,
)
from ultimate_pipeline.research.rq_closure_orchestrator import (
    Component, assess_component, rollup, PASS, INCOMPLETE, NOT_RUN,
    BLOCKED_EXTERNAL, build as build_closure,
)

sys.path.insert(0, str(WORKTREE / "tools"))


@pytest.fixture(scope="module")
def head():
    return subprocess.run(["git", "-C", str(WORKTREE), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture(scope="module")
def readme_sha():
    return sha256_file(WORKTREE / "README.md")


# --------------------------------------------------------------------------
# freshness
# --------------------------------------------------------------------------

def test_freshness_status_vocabulary_is_governed():
    assert set(STATUSES) == {FRESH, STALE_PRODUCER, STALE_INPUT, STALE_PROTOCOL,
                             "STALE_SCHEMA", MISSING_PROVENANCE, HASH_MISMATCH}


def test_fresh_binding_is_fresh(head, readme_sha):
    # A protocol pin is required before freshness can be confirmed: an
    # unpinned protocol is STALE_PROTOCOL, not FRESH (asserted below).
    r = assess(Binding(artifact="README.md", schema="S/v1",
                       producer_commit=head, declared_sha256=readme_sha,
                       protocol_sha256=readme_sha,
                       protocol_source="README.md"), WORKTREE, head)
    assert r["status"] == FRESH


def test_unpinned_protocol_is_not_fresh(head, readme_sha):
    r = assess(Binding(artifact="README.md", schema="S/v1",
                       producer_commit=head, declared_sha256=readme_sha),
               WORKTREE, head)
    assert r["status"] == STALE_PROTOCOL


def test_stale_producer_is_detected(head, readme_sha):
    r = assess(Binding(artifact="README.md", schema="S/v1",
                       producer_commit="f" * 40, declared_sha256=readme_sha),
               WORKTREE, head)
    assert r["status"] == STALE_PRODUCER


def test_hash_mismatch_is_detected(head, readme_sha):
    r = assess(Binding(artifact="README.md", schema="S/v1",
                       producer_commit=head, declared_sha256="0" * 64),
               WORKTREE, head)
    assert r["status"] == HASH_MISMATCH


def test_stale_input_is_detected(head, readme_sha):
    r = assess(Binding(artifact="README.md", schema="S/v1",
                       producer_commit=head, declared_sha256=readme_sha,
                       source_sha256={"README.md": "0" * 64}), WORKTREE, head)
    assert r["status"] == STALE_INPUT


def test_bad_protocol_sha_is_detected(head, readme_sha):
    r = assess(Binding(artifact="README.md", schema="S/v1",
                       producer_commit=head, declared_sha256=readme_sha,
                       protocol_sha256="a" * 64,
                       protocol_source="README.md"), WORKTREE, head)
    assert r["status"] == STALE_PROTOCOL


def test_missing_provenance_is_detected():
    r = assess(Binding(artifact="README.md", schema="UNKNOWN",
                       producer_commit="UNKNOWN"), WORKTREE)
    assert r["status"] == MISSING_PROVENANCE


# --------------------------------------------------------------------------
# evidence graph rules
# --------------------------------------------------------------------------

def _node(**kw):
    d = dict(node_id="N", rq="RQX", claim="c", metric="m", producer="p",
             producer_commit="0" * 40, output_artifact="README.md",
             output_sha256="", schema="S/v1", status="CURRENT", required=False)
    d.update(kw)
    return EvidenceNode(**d)


def test_duplicate_current_authority_is_blocking():
    g = EvidenceGraph([_node(node_id="A", claim="same"),
                       _node(node_id="B", claim="same")])
    v = verify(g, WORKTREE)
    assert v["status"] == "FAIL"
    assert any(f["rule"] == "DUPLICATE_CURRENT_AUTHORITY" for f in v["findings"])
    assert v["every_current_claim_resolves_to_one_producer"] is False


def test_single_current_authority_verifies():
    g = EvidenceGraph([_node(node_id="A", claim="only")])
    v = verify(g, WORKTREE)
    assert v["status"] != "FAIL"
    assert v["blocking_count"] == 0


def test_superseded_used_as_current_is_blocking():
    newer = _node(node_id="NEW", claim="c2", supersedes=["OLD"])
    older = _node(node_id="OLD", claim="c1", status="CURRENT")
    g = EvidenceGraph([newer, older])
    v = verify(g, WORKTREE)
    assert any(f["rule"] == "SUPERSEDED_USED_AS_CURRENT" for f in v["findings"])


def test_deferred_with_authoritative_note_is_blocking():
    g = EvidenceGraph([_node(node_id="RQ5", status="DEFERRED",
                             notes="AUTHORITATIVE, infrastructure is ready")])
    v = verify(g, WORKTREE)
    assert any(f["rule"] == "NON_PASSING_STATUS_WITH_AUTHORITATIVE_NOTE"
               for f in v["findings"])


def test_unreachable_producer_commit_is_blocking():
    g = EvidenceGraph([_node(node_id="X", producer_commit="f" * 40,
                             required=True)])
    v = verify(g, WORKTREE)
    assert any(f["rule"] == "PRODUCER_COMMIT_UNREACHABLE" for f in v["findings"])


def test_absent_required_artifact_is_blocking():
    g = EvidenceGraph([_node(node_id="X", output_artifact="nope/missing.json",
                             required=True)])
    v = verify(g, WORKTREE)
    assert any(f["rule"] == "REQUIRED_ARTIFACT_ABSENT" for f in v["findings"])


def test_non_governed_claim_status_is_rejected_at_construction():
    with pytest.raises(ValueError):
        EvidenceGraph([_node(node_id="X", status="PROBABLY_FINE")])


def test_duplicate_node_id_is_rejected():
    g = EvidenceGraph([_node(node_id="X")])
    with pytest.raises(ValueError):
        g.add(_node(node_id="X"))


# --------------------------------------------------------------------------
# closure orchestrator: statuses derived, never asserted
# --------------------------------------------------------------------------

def test_component_with_no_evidence_is_not_pass():
    r = assess_component(Component("C", "no evidence", []), WORKTREE)
    assert r["status"] == NOT_RUN
    assert r["status"] != PASS


def test_blocked_component_reports_block_reason():
    r = assess_component(Component("C", "external", [], blocked_by=BLOCKED_EXTERNAL),
                         WORKTREE)
    assert r["status"] == BLOCKED_EXTERNAL


def test_component_with_absent_evidence_is_incomplete():
    r = assess_component(Component("C", "x", ["definitely/absent.json"]), WORKTREE)
    assert r["status"] == INCOMPLETE
    assert r["evidence_absent"] == ["definitely/absent.json"]


def test_component_with_present_evidence_passes():
    r = assess_component(Component("C", "x", ["README.md"]), WORKTREE)
    assert r["status"] == PASS
    assert len(r["evidence_present"]) == 1


def test_rollup_is_worst_required_not_average():
    rows = [{"required": True, "status": PASS},
            {"required": True, "status": INCOMPLETE}]
    assert rollup("RQ", rows) == INCOMPLETE


def test_rollup_ignores_non_required_for_the_verdict_but_not_the_list():
    rows = [{"required": True, "status": PASS},
            {"required": False, "status": BLOCKED_EXTERNAL}]
    assert rollup("RQ", rows) == PASS


def test_closure_matrix_separates_offline_from_live():
    doc = build_closure(WORKTREE)
    assert doc["schema"] == "RQ_CLOSURE_MATRIX/v1"
    assert doc["live_runtime"]["status"] == "NOT_RUN"
    assert doc["readiness_semantics"]["live_runtime_not_run"] is True
    assert doc["readiness_semantics"]["full_production_ready"] is False


def test_closure_matrix_has_the_required_rq_structure():
    doc = build_closure(WORKTREE)
    expected = {"RQ1", "RQ2", "RQ3", "RQ4", "RQ5A", "RQ5B"}
    assert expected <= set(doc["rqs"])
    ids = {c["component_id"] for r in doc["rqs"].values() for c in r["components"]}
    for required in ("RQ1.generator_determinism", "RQ1.post_generation_determinism",
                     "RQ2.map_authority", "RQ2.metric_authority",
                     "RQ3.pair_contract", "RQ4.leak_free_training",
                     "RQ4.reproducibility", "RQ5A.split", "RQ5B.external_dataset"):
        assert required in ids, required


def test_rq5b_is_blocked_external_not_authoritative():
    doc = build_closure(WORKTREE)
    assert doc["rqs"]["RQ5B"]["status"] == BLOCKED_EXTERNAL
    assert doc["rqs"]["RQ5B"]["status"] != PASS


def test_rq1_is_not_claimed_pass_without_evidence():
    doc = build_closure(WORKTREE)
    assert doc["rqs"]["RQ1"]["status"] != PASS


# --------------------------------------------------------------------------
# verifier CLI
# --------------------------------------------------------------------------

def test_verify_claim_graph_cli_exits_zero():
    r = subprocess.run([sys.executable, "tools/verify_research_claim_graph.py"],
                       cwd=str(WORKTREE), capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert "RESEARCH_CLAIM_GRAPH_OK" in r.stdout


# --------------------------------------------------------------------------
# generated governance artifacts
# --------------------------------------------------------------------------

GOV = WORKTREE / "reports/integration_wave/20261002_batch13"


@pytest.mark.parametrize("name", [
    "FULL_REGRESSION_CLASSIFICATION.json",
    "RESEARCH_EVIDENCE_GRAPH.json",
    "RESEARCH_EVIDENCE_GRAPH_VERIFICATION.json",
    "RQ_CLOSURE_MATRIX.json",
    "EVIDENCE_FRESHNESS.json",
    "INTEGRATION_GOVERNANCE_NEGATIVE_CONTROLS.json",
    "PRODUCTION_READINESS_MATRIX.json",
    "SCHEMA_VALIDATION.json",
    "SIGNAL_RECONCILIATION.json",
])
def test_governance_artifact_is_self_describing(name):
    p = GOV / name
    assert p.is_file(), f"missing governance artifact {name}"
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert "schema" in doc


def test_readiness_matrix_is_not_reduced_to_one_bool():
    doc = json.loads((GOV / "PRODUCTION_READINESS_MATRIX.json").read_text(
        encoding="utf-8"))
    dims = doc["dimensions"]
    assert len(dims) >= 15
    assert doc["readiness"]["full_production_ready"] is False
    assert doc["readiness"]["live_runtime_not_run"] is True
    assert "live_runtime" in dims


def test_regression_classification_has_no_new_regressions():
    doc = json.loads((GOV / "FULL_REGRESSION_CLASSIFICATION.json").read_text(
        encoding="utf-8"))
    assert doc["NEW_REGRESSION_COUNT"] == 0
    assert doc["UNCLASSIFIED_COUNT"] == 0
    assert doc["status"] == "PASS"


def test_governance_negative_controls_all_reject():
    doc = json.loads(
        (GOV / "INTEGRATION_GOVERNANCE_NEGATIVE_CONTROLS.json").read_text(
            encoding="utf-8"))
    assert doc["n_broken"] == 0
    assert doc["status"] == "ALL_CONTROLS_REJECT"
    names = {c["control"] for c in doc["controls"]}
    for required in ("stale_producer_sha", "wrong_input_sha", "bad_protocol_sha",
                     "missing_evidence_schema", "duplicate_current_authorities",
                     "superseded_treated_as_current",
                     "rq5_implementation_only_promoted",
                     "signal_without_production_writer", "fake_success_marker",
                     "closure_unsupported_status",
                     "lane_commit_based_on_wrong_base"):
        assert required in names, required