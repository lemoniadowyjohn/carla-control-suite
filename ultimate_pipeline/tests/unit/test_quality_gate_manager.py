# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/quality/quality_gate_manager.py.

Live: QualityGateManager (self.qgate in main_pipeline.py:813) is the sole
dispatch point for every quality/safety gate in the pipeline. Zero prior
test coverage. Focused on the bookkeeping/dispatch logic unique to this
file, plus gate_junction_integrity specifically -- it was missing a
`return rep` (see test_gate_runner.py's non-dict-return test and
[[project_junction_integrity_gate_silent_pass_fix]]), meaning a real
junction-integrity violation was silently tallied as a PASS by the strict
CumulativeGateRunner used in main_pipeline.py._stage_gate.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.core.validation_report import ValidationReport
from ultimate_pipeline.quality.quality_gate_manager import QualityGateManager


def _bad_junction_xodr(tmp_path: Path) -> Path:
    xodr = tmp_path / "bad_junction.xodr"
    xodr.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<OpenDRIVE>"
        '<road name="r1" length="10" id="1" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10">'
        "<line/></geometry></planView>"
        "</road>"
        '<junction id="5">'
        '<connection id="0" incomingRoad="999" connectingRoad="1" contactPoint="start"/>'
        "</junction>"
        "</OpenDRIVE>\n",
        encoding="utf-8",
    )
    return xodr


def _good_junction_xodr(tmp_path: Path) -> Path:
    xodr = tmp_path / "good_junction.xodr"
    xodr.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<OpenDRIVE>"
        '<road name="r1" length="10" id="1" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10">'
        "<line/></geometry></planView>"
        "</road>"
        '<junction id="5">'
        '<connection id="0" incomingRoad="1" connectingRoad="1" contactPoint="start"/>'
        "</junction>"
        "</OpenDRIVE>\n",
        encoding="utf-8",
    )
    return xodr


# ---------------------------------------------------------------------------
# bookkeeping: fail / passed / get_failures
# ---------------------------------------------------------------------------


def test_fail_records_failure_and_adds_to_vreport():
    vreport = ValidationReport()
    qgate = QualityGateManager(vreport)
    qgate.fail("my_gate", {"issue": "bad"})
    assert qgate.get_failures() == {"my_gate": {"issue": "bad"}}


def test_passed_clears_a_prior_failure_for_same_gate_name():
    vreport = ValidationReport()
    qgate = QualityGateManager(vreport)
    qgate.fail("my_gate", {"issue": "bad"})
    qgate.passed("my_gate")
    assert qgate.get_failures() == {}


def test_get_failures_returns_a_copy_not_the_live_dict():
    vreport = ValidationReport()
    qgate = QualityGateManager(vreport)
    qgate.fail("my_gate", {"issue": "bad"})
    failures = qgate.get_failures()
    failures["injected"] = "should not leak back"
    assert "injected" not in qgate.get_failures()


def test_failures_are_instance_scoped_not_shared_across_managers():
    vreport1 = ValidationReport()
    qgate1 = QualityGateManager(vreport1)
    qgate1.fail("my_gate", {"issue": "bad"})

    vreport2 = ValidationReport()
    qgate2 = QualityGateManager(vreport2)
    assert qgate2.get_failures() == {}


# ---------------------------------------------------------------------------
# _finalize_gate / _require_path
# ---------------------------------------------------------------------------


def test_finalize_gate_fails_on_ok_false():
    qgate = QualityGateManager(ValidationReport())
    qgate._finalize_gate("g", {"ok": False, "detail": "x"})
    assert "g" in qgate.get_failures()


def test_finalize_gate_passes_on_ok_true():
    qgate = QualityGateManager(ValidationReport())
    qgate._finalize_gate("g", {"ok": True})
    assert qgate.get_failures() == {}


def test_finalize_gate_fails_closed_on_non_dict_report():
    qgate = QualityGateManager(ValidationReport())
    qgate._finalize_gate("g", None)  # type: ignore[arg-type]
    assert "g" in qgate.get_failures()


def test_require_path_rejects_non_string():
    qgate = QualityGateManager(ValidationReport())
    try:
        qgate._require_path(123, "gate_x")
        assert False, "expected TypeError"
    except TypeError as e:
        assert "gate_x" in str(e)


def test_require_path_rejects_empty_string():
    qgate = QualityGateManager(ValidationReport())
    try:
        qgate._require_path("   ", "gate_x")
        assert False, "expected TypeError"
    except TypeError:
        pass


def test_require_path_accepts_nonempty_string():
    qgate = QualityGateManager(ValidationReport())
    assert qgate._require_path("a.xodr", "gate_x") == "a.xodr"


# ---------------------------------------------------------------------------
# gate_junction_integrity -- the confirmed bug: was missing `return rep`,
# meaning main_pipeline.py's _stage_gate(lambda: self.qgate.gate_junction_
# integrity(...)) always fed None into CumulativeGateRunner, which (before
# its own fix in gate_runner.py) silently treated that as an unconditional
# pass, regardless of real junction-integrity violations.
# ---------------------------------------------------------------------------


def test_gate_junction_integrity_returns_the_report_dict(tmp_path):
    xodr = _bad_junction_xodr(tmp_path)
    qgate = QualityGateManager(ValidationReport())
    rep = qgate.gate_junction_integrity(str(xodr), stage="03_topology_repair")
    assert isinstance(rep, dict)
    assert rep["ok"] is False
    assert rep["issue_count"] == 1


def test_gate_junction_integrity_records_failure_for_broken_reference(tmp_path):
    xodr = _bad_junction_xodr(tmp_path)
    qgate = QualityGateManager(ValidationReport())
    qgate.gate_junction_integrity(str(xodr))
    assert "junction_integrity" in qgate.get_failures()


def test_gate_junction_integrity_passes_for_valid_references(tmp_path):
    xodr = _good_junction_xodr(tmp_path)
    qgate = QualityGateManager(ValidationReport())
    rep = qgate.gate_junction_integrity(str(xodr))
    assert rep["ok"] is True
    assert qgate.get_failures() == {}


def test_gate_junction_integrity_accepts_an_element_root_directly(tmp_path):
    xodr = _good_junction_xodr(tmp_path)
    root = ET.parse(str(xodr)).getroot()
    qgate = QualityGateManager(ValidationReport())
    rep = qgate.gate_junction_integrity(root)
    assert rep["ok"] is True
