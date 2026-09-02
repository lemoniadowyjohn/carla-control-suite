# ultimate_pipeline/tools/preflight_xodr_loadability.py -- zero prior test
# coverage. Live: run_preflight() is imported and called directly from
# stage_08_integrity.py (the final XODR integrity gate), phase_g8_acceptance.py,
# and smoke_load_xodr.py. (stage_08_final_integrity.py also calls it but is
# itself dead code -- deleted 2026-09-02, WS5 repo-hygiene pass -- confirmed
# zero references from anywhere outside its own file.)
#
# Real bug found: main() (the CLI entrypoint) duplicated the ENTIRE ~115
# line body of run_preflight() (the programmatic entrypoint the live
# pipeline stages call) verbatim instead of calling it -- a maintenance
# drift risk on a live gate: a future fix to run_preflight()'s report
# assembly would silently NOT apply to CLI invocations (and vice versa)
# unless both copies were remembered and kept in sync by hand. Fixed by
# making main() call run_preflight() and derive its exit code from the
# returned summary, matching the exact behavior the duplicate previously
# reimplemented.
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

from ultimate_pipeline.tools import preflight_xodr_loadability as pxl


VALID_MINIMAL_XODR = """<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
  <header revMajor="1" revMinor="4" name="" version="1.00" north="0" south="0" east="0" west="0"/>
  <road name="R1" length="10.0" id="1" junction="-1">
    <planView>
      <geometry s="0" x="0" y="0" hdg="0" length="10.0"><line/></geometry>
    </planView>
    <lanes>
      <laneSection s="0">
        <center><lane id="0" type="none" level="false"/></center>
      </laneSection>
    </lanes>
  </road>
</OpenDRIVE>
"""


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "in.xodr"
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# run_preflight() orchestration -- isolate report assembly from the three
# validator sub-modules by monkeypatching their _run_* wrappers, matching
# the level at which the CLI/programmatic duplication actually occurred.
# ---------------------------------------------------------------------------

def test_run_preflight_ok_when_all_modules_clean(tmp_path: Path, monkeypatch):
    xodr = _write(tmp_path, VALID_MINIMAL_XODR)
    monkeypatch.setattr(pxl, "_run_strict_validator", lambda root: {"available": True, "report": {"issues": []}})
    monkeypatch.setattr(pxl, "_run_carla_gate", lambda root: {"available": True, "issues": [], "stats": {}})
    monkeypatch.setattr(pxl, "_run_successor_scan", lambda path: {"available": True, "report": {"failures": []}})

    report = pxl.run_preflight(xodr, tmp_path / "out")

    assert report["summary"]["status"] == "ok"
    assert report["summary"]["error_count"] == 0
    assert (tmp_path / "out" / "preflight_report.json").is_file()


def test_run_preflight_fails_on_parse_error(tmp_path: Path):
    xodr = _write(tmp_path, "not valid xml <<<")

    report = pxl.run_preflight(xodr, tmp_path / "out")

    assert report["summary"]["status"] == "fail"
    assert report["parse_error"] is not None
    assert any(e["module"] == "xml_parse" for e in report["errors"])


def test_run_preflight_fails_on_strict_validator_error_issue(tmp_path: Path, monkeypatch):
    xodr = _write(tmp_path, VALID_MINIMAL_XODR)
    monkeypatch.setattr(
        pxl,
        "_run_strict_validator",
        lambda root: {"available": True, "report": {"issues": [{"severity": "error", "code": "bad"}]}},
    )
    monkeypatch.setattr(pxl, "_run_carla_gate", lambda root: {"available": True, "issues": [], "stats": {}})
    monkeypatch.setattr(pxl, "_run_successor_scan", lambda path: {"available": True, "report": {"failures": []}})

    report = pxl.run_preflight(xodr, tmp_path / "out")

    assert report["summary"]["status"] == "fail"
    assert report["summary"]["error_count"] == 1


def test_run_preflight_warns_but_does_not_fail_on_warn_issue(tmp_path: Path, monkeypatch):
    xodr = _write(tmp_path, VALID_MINIMAL_XODR)
    monkeypatch.setattr(
        pxl,
        "_run_strict_validator",
        lambda root: {"available": True, "report": {"issues": [{"severity": "warn", "code": "minor"}]}},
    )
    monkeypatch.setattr(pxl, "_run_carla_gate", lambda root: {"available": True, "issues": [], "stats": {}})
    monkeypatch.setattr(pxl, "_run_successor_scan", lambda path: {"available": True, "report": {"failures": []}})

    report = pxl.run_preflight(xodr, tmp_path / "out")

    assert report["summary"]["status"] == "ok"
    assert report["summary"]["warning_count"] == 1


def test_run_preflight_fails_on_successor_scan_failures(tmp_path: Path, monkeypatch):
    xodr = _write(tmp_path, VALID_MINIMAL_XODR)
    monkeypatch.setattr(pxl, "_run_strict_validator", lambda root: {"available": True, "report": {"issues": []}})
    monkeypatch.setattr(pxl, "_run_carla_gate", lambda root: {"available": True, "issues": [], "stats": {}})
    monkeypatch.setattr(
        pxl,
        "_run_successor_scan",
        lambda path: {
            "available": True,
            "report": {"failures": [{"reason": "dangling_successor", "road_id": "7"}]},
        },
    )

    report = pxl.run_preflight(xodr, tmp_path / "out")

    assert report["summary"]["status"] == "fail"
    matching = [e for e in report["errors"] if e["module"] == "lane_section_successor_scan"]
    assert len(matching) == 1
    assert matching[0]["code"] == "dangling_successor"


def test_run_preflight_module_exception_becomes_error_not_crash(tmp_path: Path, monkeypatch):
    xodr = _write(tmp_path, VALID_MINIMAL_XODR)
    monkeypatch.setattr(pxl, "_run_strict_validator", lambda root: {"available": True, "error": "boom"})
    monkeypatch.setattr(pxl, "_run_carla_gate", lambda root: {"available": True, "issues": [], "stats": {}})
    monkeypatch.setattr(pxl, "_run_successor_scan", lambda path: {"available": True, "report": {"failures": []}})

    report = pxl.run_preflight(xodr, tmp_path / "out")

    assert report["summary"]["status"] == "fail"
    assert any(e["code"] == "validator_exception" for e in report["errors"])


# ---------------------------------------------------------------------------
# main() CLI entrypoint must delegate to run_preflight(), not reimplement it.
# ---------------------------------------------------------------------------

def test_main_delegates_to_run_preflight_and_derives_exit_code_ok(tmp_path: Path, monkeypatch):
    xodr = _write(tmp_path, VALID_MINIMAL_XODR)
    out_dir = tmp_path / "out"
    calls = []

    def fake_run_preflight(xodr_path: Path, out_path: Path) -> Dict[str, Any]:
        calls.append((xodr_path, out_path))
        return {"summary": {"status": "ok"}}

    monkeypatch.setattr(pxl, "run_preflight", fake_run_preflight)
    monkeypatch.setattr(
        sys, "argv", ["preflight_xodr_loadability.py", "--xodr", str(xodr), "--out", str(out_dir)]
    )

    rc = pxl.main()

    assert rc == 0
    assert len(calls) == 1
    assert Path(calls[0][0]) == xodr
    assert Path(calls[0][1]) == out_dir


def test_main_delegates_to_run_preflight_and_derives_exit_code_fail(tmp_path: Path, monkeypatch):
    xodr = _write(tmp_path, VALID_MINIMAL_XODR)
    out_dir = tmp_path / "out"

    monkeypatch.setattr(pxl, "run_preflight", lambda x, o: {"summary": {"status": "fail"}})
    monkeypatch.setattr(
        sys, "argv", ["preflight_xodr_loadability.py", "--xodr", str(xodr), "--out", str(out_dir)]
    )

    rc = pxl.main()

    assert rc == 2


def test_main_real_end_to_end_matches_run_preflight_report(tmp_path: Path):
    # No mocking: prove main()'s CLI path and calling run_preflight()
    # directly produce the exact same report content and file -- the
    # concrete regression check for the duplication bug.
    xodr = _write(tmp_path, VALID_MINIMAL_XODR)
    out_via_main = tmp_path / "out_main"
    out_via_direct = tmp_path / "out_direct"

    direct_report = pxl.run_preflight(xodr, out_via_direct)

    import sys as _sys
    old_argv = _sys.argv
    try:
        _sys.argv = ["preflight_xodr_loadability.py", "--xodr", str(xodr), "--out", str(out_via_main)]
        rc = pxl.main()
    finally:
        _sys.argv = old_argv

    main_report = json.loads((out_via_main / "preflight_report.json").read_text(encoding="utf-8"))

    assert rc == (0 if direct_report["summary"]["status"] == "ok" else 2)
    assert main_report["summary"]["status"] == direct_report["summary"]["status"]
    assert main_report["summary"]["error_count"] == direct_report["summary"]["error_count"]
