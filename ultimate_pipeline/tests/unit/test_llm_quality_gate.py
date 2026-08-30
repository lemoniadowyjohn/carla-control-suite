# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/llm/llm_quality_gate.py.

Live: main_pipeline.py's _final_summary_and_llm calls
LLMQualityGate().review(...) and .review_gate_failures(...). Zero prior
test coverage. Purely advisory -- produces a markdown report, never
raises/gates the pipeline based on the LLM's verdict (confirmed earlier
this session: the LLM review runs AFTER "Pipeline completed successfully"
is already printed). No bugs found; LLMClient is mocked so these tests
never make a real API call.
"""
from __future__ import annotations

import json
from unittest import mock

from ultimate_pipeline.llm.llm_quality_gate import LLMQualityGate


def _mock_client(response: str = "mock LLM response"):
    client = mock.Mock()
    client.ask.return_value = response
    return client


def test_review_gate_failures_formats_each_failure_as_markdown():
    failures = {
        "junction_integrity": {"ok": False, "issue_count": 1},
        "xml_integrity": {"ok": False, "error": "parse failed"},
    }
    md = LLMQualityGate.review_gate_failures(failures)
    assert "## ❌ Gate Failed: junction_integrity" in md
    assert "## ❌ Gate Failed: xml_integrity" in md
    assert "issue_count" in md
    assert "parse failed" in md


def test_review_gate_failures_empty_dict_returns_empty_string():
    assert LLMQualityGate.review_gate_failures({}) == ""


def test_review_raises_for_missing_xodr(tmp_path):
    gate = LLMQualityGate(client=_mock_client())
    try:
        gate.review(
            xodr_path=str(tmp_path / "missing.xodr"),
            validation_report_path=str(tmp_path / "report.json"),
        )
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_review_raises_for_missing_validation_report(tmp_path):
    xodr = tmp_path / "final.xodr"
    xodr.write_text("<OpenDRIVE></OpenDRIVE>", encoding="utf-8")
    gate = LLMQualityGate(client=_mock_client())
    try:
        gate.review(
            xodr_path=str(xodr),
            validation_report_path=str(tmp_path / "missing_report.json"),
        )
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_review_returns_the_llm_answer_and_writes_markdown_file(tmp_path):
    xodr = tmp_path / "final.xodr"
    xodr.write_text("<OpenDRIVE></OpenDRIVE>", encoding="utf-8")
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps({"ok": True}), encoding="utf-8")

    client = _mock_client("# Map Quality Summary\n- looks fine")
    gate = LLMQualityGate(client=client)
    out_md = tmp_path / "out" / "review.md"

    answer = gate.review(
        xodr_path=str(xodr),
        validation_report_path=str(report_path),
        out_md_path=str(out_md),
    )

    assert answer == "# Map Quality Summary\n- looks fine"
    assert out_md.read_text(encoding="utf-8") == answer
    client.ask.assert_called_once()


def test_review_does_not_write_file_when_out_md_path_omitted(tmp_path):
    xodr = tmp_path / "final.xodr"
    xodr.write_text("<OpenDRIVE></OpenDRIVE>", encoding="utf-8")
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps({"ok": True}), encoding="utf-8")

    gate = LLMQualityGate(client=_mock_client())
    answer = gate.review(xodr_path=str(xodr), validation_report_path=str(report_path))
    assert answer == "mock LLM response"


def test_review_truncates_oversized_validation_report(tmp_path):
    xodr = tmp_path / "final.xodr"
    xodr.write_text("<OpenDRIVE></OpenDRIVE>", encoding="utf-8")
    report_path = tmp_path / "report.json"
    big_report = {"issues": ["x" * 100] * 200}  # comfortably over 6000 chars
    report_path.write_text(json.dumps(big_report), encoding="utf-8")

    client = _mock_client()
    gate = LLMQualityGate(client=client)
    gate.review(xodr_path=str(xodr), validation_report_path=str(report_path))

    prompt_sent = client.ask.call_args[0][0]
    assert "[...VALIDATION REPORT TRUNCATED...]" in prompt_sent


def test_review_includes_report_content_when_under_size_limit(tmp_path):
    xodr = tmp_path / "final.xodr"
    xodr.write_text("<OpenDRIVE></OpenDRIVE>", encoding="utf-8")
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps({"ok": True, "marker": "UNIQUE_MARKER_XYZ"}), encoding="utf-8")

    client = _mock_client()
    gate = LLMQualityGate(client=client)
    gate.review(xodr_path=str(xodr), validation_report_path=str(report_path))

    prompt_sent = client.ask.call_args[0][0]
    assert "UNIQUE_MARKER_XYZ" in prompt_sent
    assert "[...VALIDATION REPORT TRUNCATED...]" not in prompt_sent
