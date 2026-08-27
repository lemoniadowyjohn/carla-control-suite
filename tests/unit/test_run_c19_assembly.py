"""C19 assembly orchestrator: the 4 steps (export_thesis_tables, audit_thesis_topic_contract,
validate_thesis_claim_provenance, pack_thesis_run) were previously only ever run by hand,
individually. That's exactly how the committed evidence bundle went stale after the C29 pin
promotion -- someone (this session) updated the registry and rq_tables.json but never
re-ran the other 3 steps, so contract_audit.json/provenance_validation.json/
thesis_run_bundle.json silently kept citing pre-promotion state until caught by chance (see
FRECHET_ROW_WIRED_AND_PROVENANCE_VALIDATOR_REGRESSION_FIXED.md). This module makes "run all
4 together, in order, fail closed on the first failure" the only supported path.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tools.run_c19_assembly import build_step_commands, run_steps


def test_build_step_commands_runs_in_dependency_order():
    """export must run first (the other 3 all read its output); provenance validation
    (the honesty gate) must run before pack (which should bundle a freshly-verified state,
    not a stale one)."""
    steps = build_step_commands(Path("/out"), Path("/repo"))
    names = [name for name, _argv in steps]
    assert names == [
        "export_thesis_tables",
        "audit_thesis_topic_contract",
        "validate_thesis_claim_provenance",
        "pack_thesis_run",
    ]


def test_build_step_commands_uses_this_interpreter_and_the_right_out_forms():
    """export_thesis_tables/pack_thesis_run take --out <dir>; audit_thesis_topic_contract/
    validate_thesis_claim_provenance take --out <file-inside-that-dir> -- mixing these up
    (as is easy to do running them by hand) silently creates a directory named like a JSON
    file instead of writing the JSON (this bit a real run during this session)."""
    out_dir = Path("/out")
    steps = build_step_commands(out_dir, Path("/repo"))
    by_name = dict(steps)

    assert sys.executable in by_name["export_thesis_tables"]
    assert str(out_dir) in by_name["export_thesis_tables"]

    assert str(out_dir / "contract_audit.json") in by_name["audit_thesis_topic_contract"]
    assert str(out_dir) not in by_name["audit_thesis_topic_contract"]  # bare dir, not the file, would be wrong

    assert str(out_dir / "provenance_validation.json") in by_name["validate_thesis_claim_provenance"]

    assert str(out_dir) in by_name["pack_thesis_run"]
    assert str(out_dir / "thesis_run_bundle.json") not in by_name["pack_thesis_run"]


def test_run_steps_all_succeed():
    steps = [("a", ["true"]), ("b", ["true"])]
    calls = []

    def fake_run(argv):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, returncode=0)

    result = run_steps(steps, fake_run)
    assert result["ok"] is True
    assert result["failed_at"] is None
    assert len(calls) == 2  # both steps actually invoked


def test_run_steps_stops_at_first_failure_fail_closed():
    """Step 2 fails -> step 3 must NOT run (a stale/broken intermediate state should never
    be silently built on top of), and the failure must be clearly attributable."""
    steps = [("a", ["x"]), ("b", ["y"]), ("c", ["z"])]
    calls = []

    def fake_run(argv):
        calls.append(argv)
        rc = 1 if argv == ["y"] else 0
        return subprocess.CompletedProcess(argv, returncode=rc)

    result = run_steps(steps, fake_run)
    assert result["ok"] is False
    assert result["failed_at"] == "b"
    assert len(calls) == 2  # step "c" never ran
    assert result["steps"][-1]["step"] == "b"
    assert result["steps"][-1]["returncode"] == 1
