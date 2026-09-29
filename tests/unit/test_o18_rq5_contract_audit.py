"""Tests for O18 RQ5 contract audit."""
from tools.rq5_contract_audit import REQUIRED, audit


def test_all_required_decisions_are_classified():
    rows = audit(__import__("pathlib").Path.cwd())["rows"]
    assert {row["decision"] for row in rows} == set(REQUIRED)
    assert all(row["status"] in {"DEFINED", "AMBIGUOUS", "MISSING"} for row in rows)


def test_audit_does_not_fill_choices():
    report = audit(__import__("pathlib").Path.cwd())
    assert report["scientific_choices_filled"] is False
    assert "no architecture" in report["claim_boundary"]
